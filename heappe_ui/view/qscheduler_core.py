"""
Shared QScheduler plumbing used by the QScheduler page (instances, assignments) and by the Clusters
page (adding / removing quantum machines).

Model:
  * QSchedulerInstance  - one QScheduler service (REST API + PostgreSQL). Shared by several HEAppEs.
  * QSchedulerAssignment - a HEAppE instance allowed to use a QScheduler: network access plus optional
    QScheduler notifiers (one per cluster).
  * HEAppE cluster == one QScheduler machine, per HEAppE. A machine can back clusters of several HEAppEs.

QScheduler (>= notifier release) facts this relies on:
  * >= 0.2.1: machines and notifiers are managed only over the admin API (/machines, /machine/{name}, /notifiers,
    Bearer ADMIN_TOKEN of the service), reached over HTTP through the admin proxy (qscheduler_admin), and apply at
    once. No CLI fallback: a missing or rejected token stops the operation (AdminTokenError),
  * older: they are written to the DB by the CLI and loaded at service start -> restart needed,
  * tasks/sessions choose a notifier with `notify=<name>`; HEAppE >= 6.6.0 sends cluster
    CustomConfiguration["QSchedulerNotifier"] (fallback: its InstanceIdentifierPath) when EnableCallback=true,
    and checks the callback token against QSchedulerNotifyToken.

Targets (how commands reach the service):
  * DockerTarget  - container on a Docker host: local docker CLI, or the docker CLI of a remote VM over SSH,
  * ContainerShellTarget - SSH directly into the QScheduler container.
"""
import base64
import io
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import threading
import time
from datetime import datetime
from urllib.parse import quote

from django.conf import settings

from .utils import clean_ver

DEFAULT_QSCHEDULER_REPO = "https://github.com/It4innovations/qscheduler.git"
DEFAULT_QSCHEDULER_REF = "main"
DEFAULT_QSCHEDULER_IMAGE = "qscheduler:latest"
DEFAULT_POSTGRES_IMAGE = "postgres:16"
DEFAULT_PORT = 4300
DEFAULT_RESTART_COMMAND = "kill -TERM 1"
# All QScheduler features (assignments, quantum machines, notifiers) need HEAppE 6.6.0+: the QScheduler
# adapter with named notifiers (notify=<name>, QSchedulerNotifier / QSchedulerNotifyToken) arrived in 6.6.0.
MIN_HEAPPE_VERSION = [6, 6, 0]
MIN_HEAPPE_VERSION_TEXT = "6.6.0"
MIN_HEAPPE_NOTIFIER_VERSION = MIN_HEAPPE_VERSION

SCHEDULER_TYPE_QSCHEDULER = 32
CONNECTION_PROTOCOL_HTTP = 8
FILE_TRANSFER_PROTOCOL_HTTP = 8
USAGE_TYPE_QPU_SECONDS = 4
# QScheduler task info exposes "exectime_ms"; HEAppE parses it into task parameters.
DEFAULT_ACCOUNTING_FORMULA = "exectime_ms/1000"

LABEL_INSTANCE = "qscheduler.instance"
LABEL_REPO = "qscheduler.repo"
LABEL_BRANCH = "qscheduler.branch"

DOCKER_TIMEOUT = 240          # seconds, default for every docker CLI call
HEALTH_TIMEOUT = 120          # seconds, default wait for QScheduler /health
IMAGE_BUILD_TIMEOUT = 3600    # seconds, Rust release build of the qscheduler image
SSH_TIMEOUT = 20

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
MACHINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$")  # Queue field is max 30 chars in HEAppE
DURATION_RE = re.compile(r"^\d+(ms|s|m|h|d)$")
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9_.:-]{0,253})$")
GIT_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/:@]{0,254}$")
NOTIFIER_MAX_LEN = 512
# From this version machines and notifiers are managed over the admin API (Bearer ADMIN_TOKEN) and changes apply
# at once; older versions only have the CLI, whose changes are loaded at service start (restart needed).
ADMIN_API_MIN_VERSION = (0, 2, 1)

SECRET_FLAGS = ("--token",)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def redact_args(args: list) -> list:
    """Hide secrets in logged command lines."""
    out, hide_next = [], False
    for a in args:
        a = str(a)
        if hide_next:
            out.append("********")
            hide_next = False
            continue
        if a in SECRET_FLAGS:
            hide_next = True
        if "DATABASE_URL=" in a or "postgres://" in a or "postgresql://" in a:
            a = re.sub(r"://([^:/@]+):[^@]*@", r"://\1:********@", a)
        if a.startswith("POSTGRES_PASSWORD="):
            a = "POSTGRES_PASSWORD=********"
        if a.startswith("ADMIN_TOKEN="):
            a = "ADMIN_TOKEN=********"
        out.append(a)
    return out


def parse_serve_port(cmd):
    cmd = list(cmd or [])
    for idx, part in enumerate(cmd):
        if part == "--port" and idx + 1 < len(cmd):
            return int(cmd[idx + 1])
        if part.startswith("--port="):
            return int(part.split("=", 1)[1])
    return DEFAULT_PORT


def status_of(response):
    """HTTP status code from a raw response ('HTTP/1.1 200 OK ...'), or None."""
    m = re.match(r"HTTP/\d(?:\.\d)?\s+(\d{3})", (response or "").lstrip())
    return int(m.group(1)) if m else None


def bash_http_get(host, port, path="/health"):
    """bash-only HTTP GET (the qscheduler image is debian-slim: bash, no curl). Prints the response."""
    return (f"exec 3<>/dev/tcp/{host}/{port} && "
            f"printf 'GET {path} HTTP/1.0\\r\\nHost: {host}\\r\\nConnection: close\\r\\n\\r\\n' >&3 && "
            f"timeout 3 cat <&3")


def qscheduler_healthcheck_args(port):
    """
    Docker HEALTHCHECK for the QScheduler container. The image (debian-slim) has bash but no curl,
    so /health is requested over bash /dev/tcp; healthy == HTTP 200 (503 when the DB is unreachable).
    """
    script = (f"exec 3<>/dev/tcp/127.0.0.1/{port} && "
              f"printf \"GET /health HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n\" >&3 && "
              f"timeout 3 head -n1 <&3 | grep -q \" 200\"")
    return ["--health-cmd", f"bash -c '{script}'",
            "--health-interval", "5s", "--health-timeout", "5s",
            "--health-retries", "5", "--health-start-period", "10s"]


def parse_notifier_list(output: str) -> list:
    """Parses `qscheduler notifier list` (NAME  TOKEN  URL columns)."""
    lines = [l for l in (output or "").splitlines() if l.strip()]
    if not lines or lines[0].startswith("No notifiers"):
        return []
    out = []
    for line in lines[1:] if lines[0].split()[:1] == ["NAME"] else lines:
        parts = line.split()
        if len(parts) >= 3:
            out.append({"name": parts[0], "has_token": parts[1] == "yes", "url": parts[2]})
    return out


def machine_args(opts: dict) -> list:
    """
    qscheduler CLI: machine add|update <NAME> [OPTIONS] <BACKEND> [BACKEND OPTIONS]
    (machine options must come before the backend sub-command). Notifications are not part of a machine.
    """
    args = ["machine", opts.get('action', 'add'), opts['machine_name'],
            "--queue-size", str(opts['queue_size']),
            "--limit-check-interval", opts['limit_check_interval'],
            "--max-session-time", opts['max_session_time'],
            "--default-task-time-limit", opts['default_task_time_limit'],
            "--max-clock-skew", opts['max_clock_skew']]
    if opts['backend'] == 'iqm':
        args += ["iqm",
                 "--url", opts['iqm_url'],
                 "--token", opts['iqm_token'],
                 "--machine-name", opts['iqm_device'],
                 "--poll-interval", opts['iqm_poll_interval']]
    else:
        args += ["test"]
    return args


def machine_remove_args(machine_name: str, force: bool = False) -> list:
    args = ["machine", "remove", machine_name]
    if force:
        args.append("--force")
    return args


def notifier_add_args(name, url, token=None) -> list:
    args = ["notifier", "add", name, "--url", url]
    if token:
        args += ["--token", token]
    return args


# ---------------------------------------------------------------------------
# Admin API (QScheduler >= 0.2.1): machines and notifiers over REST, applied without a restart
# ---------------------------------------------------------------------------

def parse_version(text):
    """(major, minor, patch) from a version string such as 'qscheduler v0.2.1', or None."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def supports_admin_api(version_text):
    v = parse_version(version_text)
    return v is not None and v >= ADMIN_API_MIN_VERSION


_DURATION_MS = {"ms": 1, "s": 1000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


def duration_ms(text) -> int:
    """'500ms' / '2s' / '5m' / '2h' / '1d' (the CLI duration format) -> milliseconds."""
    m = re.match(r"^(\d+)(ms|s|m|h|d)$", str(text).strip())
    if not m:
        raise ValueError(f"Invalid duration '{text}' (use e.g. 500ms, 2s, 5m, 2h, 1d).")
    return int(m.group(1)) * _DURATION_MS[m.group(2)]


def machine_request(opts: dict) -> dict:
    """Body of POST /machines: the same settings as machine_args(), durations in milliseconds."""
    body = {"name": opts['machine_name'],
            "queue_size": int(opts['queue_size']),
            "limit_check_interval_ms": duration_ms(opts['limit_check_interval']),
            "max_session_time_ms": duration_ms(opts['max_session_time']),
            "default_task_time_limit_ms": duration_ms(opts['default_task_time_limit']),
            "max_clock_skew_ms": duration_ms(opts['max_clock_skew'])}
    if opts['backend'] == 'iqm':
        body["backend"] = {"type": "iqm", "url": opts['iqm_url'], "token": opts['iqm_token'],
                           "machine_name": opts['iqm_device'],
                           "poll_interval_ms": duration_ms(opts['iqm_poll_interval'])}
    else:
        body["backend"] = {"type": "test"}
    return body


def http_body(response):
    parts = re.split(r"\r?\n\r?\n", response or "", maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def api_error_text(status, body):
    """Short error from an admin API response (JSON {"error"/"message": ...} or plain text)."""
    text = (body or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            text = str(data.get("error") or data.get("message") or text)
    except ValueError:
        pass
    return f"HTTP {status}{': ' + text[:1000] if text else ''}"


# ---------------------------------------------------------------------------
# Command runners: local shell or SSH
# ---------------------------------------------------------------------------

class CommandResult:
    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout or "", stderr or ""

    @property
    def output(self):
        return (self.stdout + "\n" + self.stderr).strip()


def load_private_key(text: str, passphrase: str = ""):
    import paramiko
    text = (text or "").strip() + "\n"
    last_error = None
    for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey):
        try:
            return cls.from_private_key(io.StringIO(text), password=passphrase or None)
        except paramiko.PasswordRequiredException:
            raise ValueError("The SSH private key is encrypted: enter its passphrase.")
        except Exception as e:     # wrong key type or malformed
            last_error = e
    raise ValueError(f"Invalid or unsupported SSH private key (Ed25519, ECDSA or RSA in OpenSSH/PEM format): {last_error}")


class SshSession:
    """paramiko connection with a pinned host key (trust on first use, stored on the instance)."""

    def __init__(self, host, port, user, private_key, passphrase="", host_key="", timeout=SSH_TIMEOUT):
        self.host, self.port, self.user = host, int(port or 22), user
        self.private_key, self.passphrase = private_key, passphrase
        self.host_key = host_key or ""
        self.timeout = timeout
        self.client = None

    def _known_name(self):
        return self.host if self.port == 22 else f"[{self.host}]:{self.port}"

    def connect(self):
        import paramiko
        pkey = load_private_key(self.private_key, self.passphrase)
        client = paramiko.SSHClient()
        if self.host_key:
            ktype, b64 = self.host_key.split(" ", 1)
            key = paramiko.PKey.from_type_string(ktype, base64.b64decode(b64))
            client.get_host_keys().add(self._known_name(), ktype, key)
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.host, port=self.port, username=self.user, pkey=pkey, timeout=self.timeout,
                           banner_timeout=self.timeout, auth_timeout=self.timeout,
                           look_for_keys=False, allow_agent=False)
        except paramiko.BadHostKeyException:
            raise RuntimeError(f"SSH host key of {self._known_name()} changed since registration. "
                               f"Re-register the QScheduler instance if the change is expected.")
        except paramiko.AuthenticationException:
            raise RuntimeError(f"SSH authentication as '{self.user}' to {self._known_name()} failed.")
        except (socket.error, paramiko.SSHException) as e:
            raise RuntimeError(f"SSH connection to {self._known_name()} failed: {e}")
        seen = client.get_transport().get_remote_server_key()
        self.host_key = f"{seen.get_name()} {seen.get_base64()}"
        self.client = client
        return self

    def run(self, command: str, timeout=DOCKER_TIMEOUT) -> CommandResult:
        if self.client is None:
            self.connect()
        try:
            _, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "replace")
            err = stderr.read().decode("utf-8", "replace")
            rc = stdout.channel.recv_exit_status()
        except socket.timeout:
            raise RuntimeError(f"Remote command timed out after {timeout}s.")
        return CommandResult(rc, out, err)

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None


class DockerCli:
    """docker CLI, either local or on a remote VM over SSH (docker_command may be e.g. 'sudo docker')."""

    def __init__(self, ssh: SshSession = None, docker_command="docker"):
        self.ssh = ssh
        self.docker_command = shlex.split(docker_command or "docker")

    @property
    def where(self):
        return f" (on {self.ssh.host})" if self.ssh else ""

    def run(self, args, log=None, check=True, timeout=DOCKER_TIMEOUT, quiet=False) -> CommandResult:
        shown = " ".join(self.docker_command + redact_args(args))
        if log and not quiet:
            log(f"$ {shown}{self.where}")
        if self.ssh:
            res = self.ssh.run(shlex.join(self.docker_command + [str(a) for a in args]), timeout=timeout)
        else:
            try:
                proc = subprocess.run(self.docker_command + [str(a) for a in args],
                                      capture_output=True, text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"Command timed out after {timeout}s: {shown}")
            except FileNotFoundError:
                raise RuntimeError("Docker CLI not found on the management host.")
            res = CommandResult(proc.returncode, proc.stdout, proc.stderr)
        if check and res.returncode != 0:
            out = res.output
            if "no space left on device" in out.lower():
                raise RuntimeError("Host is out of disk space ('No space left on device'). Free up space "
                                   "(e.g. 'docker system prune -a') and retry.")
            raise RuntimeError(f"Command failed ({res.returncode}): {shown}{self.where}\n{out[-4000:]}")
        return res

    def json(self, args):
        res = self.run(args, check=False, quiet=True)
        if res.returncode != 0:
            return None
        try:
            return json.loads(res.stdout)
        except ValueError:
            return None

    def exists(self, kind, name):
        return self.run([kind, "inspect", name], check=False, quiet=True).returncode == 0

    def inspect(self, name):
        info = self.json(["container", "inspect", name])
        return info[0] if info else None

    def networks_of(self, name):
        info = self.inspect(name)
        return list((info or {}).get("NetworkSettings", {}).get("Networks", {}) or {}) if info else []

    def network_is_internal(self, net):
        info = self.json(["network", "inspect", net])
        return bool(info and info[0].get("Internal"))


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

class QsTarget:
    """
    Machines and notifiers are managed over the admin API when the service supports it (>= 0.2.1), only through
    the admin proxy (admin_client, set by target_for); older versions use the qscheduler CLI. `reload_needed` is
    set after a CLI change: the service loads those only at start (see apply_changes).
    """
    can_update = False
    reload_needed = False
    admin_client = None      # qscheduler_admin.AdminClient
    _admin = None            # None = not checked yet
    _admin_note = ""
    _admin_note_logged = False

    def cli(self, args, log, check=True, timeout=DOCKER_TIMEOUT) -> CommandResult:
        raise NotImplementedError

    def restart(self, log):
        raise NotImplementedError

    def wait_healthy(self, log, timeout=HEALTH_TIMEOUT):
        raise NotImplementedError

    def http_get(self, path, timeout=30) -> CommandResult:
        raise NotImplementedError

    def _list_machines_db(self, log=None):
        return None

    def close(self):
        pass

    # --- admin API -----------------------------------------------------------

    def admin_request(self, method, path, body=None, timeout=60):
        """(status, body text) of an admin API call through the admin proxy. Errors never include the token."""
        from .qscheduler_admin import AdminApiUnavailable, AdminTokenError
        if self.admin_client is None:
            raise AdminApiUnavailable("The admin API is reached only through the admin proxy of a registered instance.")
        try:
            return self.admin_client.request(method, path, body, timeout)
        except (AdminApiUnavailable, AdminTokenError):
            raise
        except Exception as e:
            raise RuntimeError(f"QScheduler admin API {method} {path} could not be called "
                               f"({'timed out' if 'timed out' in str(e) else type(e).__name__}).")

    def _admin_json(self, method, path, ok=(200,)):
        status, text = self.admin_request(method, path)
        if status not in ok:
            raise RuntimeError(f"QScheduler admin API {method} {path} failed: {api_error_text(status, text)}")
        return json.loads(text) if text.strip() else None

    def uses_admin_api(self, log=None) -> bool:
        """True when this QScheduler is >= 0.2.1: then only the admin API is used (no CLI fallback)."""
        if self._admin is None:
            version = self.version()
            self._admin = supports_admin_api(version)
            if self._admin:
                self._admin_note = f"{version}: machines and notifiers are managed over the admin API (admin proxy, no restart)."
            else:
                self._admin_note = (f"QScheduler {version or '(version unknown)'} has no admin API (needs "
                                    f"{'.'.join(map(str, ADMIN_API_MIN_VERSION))}): machines and notifiers are "
                                    f"managed with the CLI and loaded after a service restart.")
        if log and not self._admin_note_logged:
            log(self._admin_note)
            self._admin_note_logged = True
        if self._admin and self.admin_client is not None and log:
            self.admin_client.log = log
        return self._admin

    def _api_result(self, status, text, ok, messages):
        """CommandResult of an admin API write (callers handle it like a CLI result)."""
        if status in ok:
            return CommandResult(0, text, "")
        prefix = messages.get(status, "")
        return CommandResult(1, "", f"{prefix + ' - ' if prefix else ''}{api_error_text(status, text)}")

    def _cli_write(self, args, log):
        res = self.cli(args, log, check=False)
        if res.returncode == 0:
            self.reload_needed = True
        return res

    # --- machines and notifiers (admin API or CLI) ---------------------------

    def list_machines(self, log=None):
        """[{'name', 'backend'}] or None when the machines cannot be listed (admin token problems are raised)."""
        from .qscheduler_admin import AdminTokenError
        try:
            if self.uses_admin_api(log):
                return [{'name': m['name'], 'backend': (m.get('backend') or {}).get('type', '')}
                        for m in self._admin_json("GET", "/machines") or []]
        except AdminTokenError:
            raise
        except Exception as e:
            if log:
                log(f"Note: could not list machines: {str(e).splitlines()[0]}")
            return None
        return self._list_machines_db(log)

    def list_notifiers(self, log=None):
        if self.uses_admin_api(log):
            return [{'name': n['name'], 'has_token': bool(n.get('has_token')), 'url': n.get('url', '')}
                    for n in self._admin_json("GET", "/notifiers") or []]
        res = self.cli(["notifier", "list"], log or (lambda *_: None), check=False)
        if res.returncode != 0:
            raise RuntimeError(f"'qscheduler notifier list' failed: {res.output[-500:] or 'no output'}. "
                               f"Is this QScheduler version older than the notifier release?")
        return parse_notifier_list(res.stdout)

    def add_machine(self, opts, log) -> CommandResult:
        """Registers machine opts['machine_name']; returncode != 0 on failure ('already exists' when it does)."""
        if not self.uses_admin_api(log):
            return self._cli_write(machine_args(dict(opts, action='add')), log)
        name = opts['machine_name']
        log(f"Admin API: POST /machines '{name}' ({opts['backend']} backend)")
        status, text = self.admin_request("POST", "/machines", machine_request(opts))
        return self._api_result(status, text, (200, 201), {409: f"Machine '{name}' already exists",
                                                           422: "Invalid machine configuration"})

    def remove_machine(self, name, force, log) -> CommandResult:
        """Removes a machine; returncode != 0 on failure ('not found' when it does not exist)."""
        if not self.uses_admin_api(log):
            return self._cli_write(machine_remove_args(name, force), log)
        path = f"/machine/{quote(name, safe='')}{'?force=true' if force else ''}"
        log(f"Admin API: DELETE {path}")
        status, text = self.admin_request("DELETE", path)
        res = self._api_result(status, text, (200, 204), {404: f"Machine '{name}' not found",
                                                          409: f"Machine '{name}' has tasks or sessions"})
        if res.returncode == 0:
            try:
                info = json.loads(text) if text.strip() else {}
                res.stdout = (f"Machine '{name}' removed ({info.get('tasks', 0)} task(s), "
                              f"{info.get('sessions', 0)} session(s) deleted).")
            except ValueError:
                res.stdout = f"Machine '{name}' removed."
        return res

    def add_notifier(self, name, url, token, log):
        if not self.uses_admin_api(log):
            self.cli(notifier_add_args(name, url, token), log)      # raises on failure (token redacted)
            self.reload_needed = True
            return
        log(f"Admin API: POST /notifiers '{name}'")
        status, text = self.admin_request("POST", "/notifiers", {"name": name, "url": url, "token": token or None})
        if status not in (200, 201):
            raise RuntimeError(f"Registering notifier '{name}' failed: {api_error_text(status, text)}")

    def remove_notifier(self, name, log, check=True) -> bool:
        """True when removed."""
        if not self.uses_admin_api(log):
            res = self._cli_write(["notifier", "remove", name], log)
            if check and res.returncode != 0:
                raise RuntimeError(f"qscheduler notifier remove {name} failed: {res.output[-3000:] or 'no output'}")
            return res.returncode == 0
        log(f"Admin API: DELETE /notifiers/{name}")
        status, text = self.admin_request("DELETE", f"/notifiers/{quote(name, safe='')}")
        if status not in (200, 204) and check:
            raise RuntimeError(f"Removing notifier '{name}' failed: {api_error_text(status, text)}")
        return status in (200, 204)

    def version(self):
        res = self.http_get("/version")
        if status_of(res.stdout) != 200:
            return None
        return re.split(r"\r?\n\r?\n", res.stdout, maxsplit=1)[-1].strip() or None

    def health(self):
        res = self.http_get("/health")
        return status_of(res.stdout)


def _psql_machines_sql():
    return "SELECT name || '|' || type FROM machines ORDER BY name"


class DockerTarget(QsTarget):
    """QScheduler container reachable with a docker CLI (local or over SSH to its VM)."""
    can_update = True

    def __init__(self, docker: DockerCli, container: str, port: int):
        self.docker, self.container, self.port = docker, container, port

    def _require_running(self):
        info = self.docker.inspect(self.container)
        if not info:
            raise RuntimeError(f"QScheduler container '{self.container}' not found{self.docker.where}.")
        if (info.get("State") or {}).get("Status") != "running":
            raise RuntimeError(f"QScheduler container '{self.container}' is not running{self.docker.where}.")
        return info

    def cli(self, args, log, check=True, timeout=DOCKER_TIMEOUT):
        self._require_running()
        res = self.docker.run(["exec", self.container, "qscheduler"] + list(args), log, check=False, timeout=timeout)
        if check and res.returncode != 0:
            raise RuntimeError(f"qscheduler {' '.join(redact_args(args))} failed: {res.output[-3000:] or 'no output'}")
        return res

    def restart(self, log):
        log(f"Restarting '{self.container}'{self.docker.where} so it reloads machines and notifiers "
            f"(running work is persisted and re-attached)...")
        self.docker.run(["restart", self.container], log)
        self.wait_healthy(log)

    def http_get(self, path, timeout=30):
        return self.docker.run(["exec", self.container, "bash", "-c", bash_http_get("127.0.0.1", self.port, path)],
                               check=False, timeout=timeout, quiet=True)

    def wait_healthy(self, log, timeout=HEALTH_TIMEOUT):
        """Docker health status when the container has a HEALTHCHECK, otherwise an in-container GET /health."""
        name = self.container
        log(f"Waiting for '{name}' to become healthy (timeout {timeout}s)...")
        start = time.time()
        status, detail = "", ""
        while time.time() - start < timeout:
            state = (self.docker.inspect(name) or {}).get("State", {}) or {}
            health = state.get("Health")
            if state.get("Status") in ("exited", "dead"):
                status = state.get("Status")
                break
            if health:
                status = health.get("Status", "")
                logs = health.get("Log") or []
                detail = (logs[-1].get("Output") or "").strip()[:300] if logs else ""
                if status in ("healthy", "unhealthy"):
                    break
            elif state.get("Status") == "running":
                res = self.http_get("/health")
                status = "healthy" if status_of(res.stdout) == 200 else "starting"
                detail = (res.stdout[:200] + res.stderr).strip()
                if status == "healthy":
                    break
            time.sleep(3)
        if status != "healthy":
            logs = self.docker.run(["logs", "--tail", "60", name], check=False, quiet=True)
            raise RuntimeError(f"QScheduler '{name}' is not healthy (status: {status or 'unknown'}"
                               f"{', last check: ' + detail if detail else ''}).\n--- {name} logs ---\n{logs.output}")
        log(f"'{name}' is healthy.")

    def database_url(self):
        info = self._require_running()
        env = dict(e.split("=", 1) for e in (info.get("Config", {}).get("Env") or []) if "=" in e)
        return env.get("DATABASE_URL")

    def _list_machines_db(self, log=None):
        """Before the admin API there is no `machine list` command: read the machines table with a one-off psql container."""
        try:
            db_url = self.database_url()
            if not db_url or not self.docker.exists("image", DEFAULT_POSTGRES_IMAGE):
                return None     # never pull an image just to list machines
            res = self.docker.run(["run", "--rm", "--network", f"container:{self.container}", DEFAULT_POSTGRES_IMAGE,
                                   "psql", db_url, "-tAc", _psql_machines_sql()],
                                  check=False, timeout=120, quiet=True)
            if res.returncode != 0:
                if log:
                    log(f"Note: could not list machines: {res.output[-300:]}")
                return None
            return [dict(zip(("name", "backend"), l.split("|", 1))) for l in res.stdout.splitlines() if l.strip()]
        except Exception as e:
            if log:
                log(f"Note: could not list machines: {e}")
            return None

    def close(self):
        if self.docker.ssh:
            self.docker.ssh.close()


class ContainerShellTarget(QsTarget):
    """SSH directly into the QScheduler container (its sshd). qscheduler CLI and the DB URL are used there."""

    def __init__(self, ssh: SshSession, port: int, database_url="", restart_command=""):
        self.ssh, self.port = ssh, port
        self.database_url = database_url
        self.restart_command = restart_command

    def _env_prefix(self):
        if self.database_url:
            return f"export DATABASE_URL={shlex.quote(self.database_url)}; "
        # the service's own environment (PID 1); readable for root / the service user
        return "export DATABASE_URL=\"${DATABASE_URL:-$(tr '\\0' '\\n' < /proc/1/environ 2>/dev/null | sed -n 's/^DATABASE_URL=//p')}\"; "

    def cli(self, args, log, check=True, timeout=DOCKER_TIMEOUT):
        log(f"$ qscheduler {' '.join(redact_args(args))} (in container via {self.ssh.host}:{self.ssh.port})")
        res = self.ssh.run(self._env_prefix() + shlex.join(["qscheduler"] + [str(a) for a in args]), timeout=timeout)
        if check and res.returncode != 0:
            raise RuntimeError(f"qscheduler {' '.join(redact_args(args))} failed: {res.output[-3000:] or 'no output'}")
        return res

    def http_get(self, path, timeout=30):
        url = f"http://127.0.0.1:{self.port}{path}"
        cmd = (f"if command -v curl >/dev/null 2>&1; then curl -sS -i --max-time 3 {shlex.quote(url)}; "
               f"else bash -c {shlex.quote(bash_http_get('127.0.0.1', self.port, path))}; fi")
        try:
            return self.ssh.run(cmd, timeout=timeout)
        except RuntimeError as e:
            return CommandResult(255, "", str(e))

    def restart(self, log):
        if not self.restart_command:
            raise RuntimeError("No restart command is configured for this instance; restart the QScheduler "
                               "container manually to apply the change.")
        log(f"Restarting QScheduler with '{self.restart_command}' (the container's restart policy must bring it back)...")
        try:
            self.ssh.run(self.restart_command, timeout=30)
        except RuntimeError:
            pass   # the connection usually drops with the container
        self.ssh.close()
        time.sleep(3)
        self.wait_healthy(log)

    def wait_healthy(self, log, timeout=HEALTH_TIMEOUT):
        log(f"Waiting for QScheduler on {self.ssh.host}:{self.ssh.port} to become healthy (timeout {timeout}s)...")
        start, last = time.time(), ""
        while time.time() - start < timeout:
            try:
                if self.ssh.client is None:
                    self.ssh.connect()
                res = self.http_get("/health")
                if status_of(res.stdout) == 200:
                    log("QScheduler is healthy.")
                    return
                last = res.output[:300]
            except Exception as e:
                last = str(e)
                self.ssh.close()
            time.sleep(3)
        raise RuntimeError(f"QScheduler did not become healthy within {timeout}s (last: {last or 'no response'}).")

    def _list_machines_db(self, log=None):
        try:
            res = self.ssh.run(self._env_prefix() + "psql \"$DATABASE_URL\" -tAc " + shlex.quote(_psql_machines_sql()),
                               timeout=60)
        except Exception:
            return None
        if res.returncode != 0:
            return None
        return [dict(zip(("name", "backend"), l.split("|", 1))) for l in res.stdout.splitlines() if l.strip()]

    def close(self):
        self.ssh.close()


def ssh_session_for(inst) -> SshSession:
    return SshSession(inst.ssh_host, inst.ssh_port, inst.ssh_user, inst.ssh_private_key,
                      inst.ssh_key_passphrase, inst.ssh_host_key)


def target_for(inst) -> QsTarget:
    from heappe_ui.models import QSchedulerInstance as Q
    from .qscheduler_admin import AdminClient
    if inst.kind in (Q.KIND_MANAGED, Q.KIND_LOCAL):
        target = DockerTarget(DockerCli(), inst.container_name, inst.port)
    elif inst.kind == Q.KIND_SSH_HOST:
        target = DockerTarget(DockerCli(ssh_session_for(inst), inst.docker_command), inst.container_name, inst.port)
    elif inst.kind == Q.KIND_SSH_CONTAINER:
        target = ContainerShellTarget(ssh_session_for(inst), inst.port, inst.database_url, inst.restart_command)
    else:
        raise RuntimeError(f"Unknown QScheduler instance kind '{inst.kind}'.")
    target.admin_client = AdminClient(inst, getattr(target, "docker", None))
    return target


def apply_changes(inst, target, log):
    """
    After machine / notifier changes: nothing to do when they went through the admin API (applied at once). CLI
    changes are loaded at service start: restart (or flag the instance when that is impossible). True when applied.
    """
    if not target.reload_needed:
        log("Changes applied through the QScheduler admin API (no restart needed).")
        return True
    try:
        target.restart(log)
        target.reload_needed = False
        if inst.restart_pending:
            inst.restart_pending = False
            inst.save(update_fields=["restart_pending", "updated_at"])
        return True
    except RuntimeError as e:
        if inst.kind == "ssh_container" and not inst.restart_command:
            log(f"WARNING: {e}")
            inst.restart_pending = True
            inst.save(update_fields=["restart_pending", "updated_at"])
            return False
        raise


# ---------------------------------------------------------------------------
# Local Docker: HEAppE API container, networks
# ---------------------------------------------------------------------------

def find_heappe_api_container(instance_name, log=print):
    """Returns the HEAppE REST API container name of the instance (compose service 'heappe'), or None."""
    candidates = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format",
             '{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}'],
            capture_output=True, text=True, timeout=30)
        for line in proc.stdout.strip().splitlines():
            name, project, service = (line.split("\t") + ["", "", ""])[:3]
            if instance_name and project.lower() != instance_name.lower() and not name.lower().startswith(f"{instance_name.lower()}_"):
                continue
            if service == "heappe":
                return name
            if name.lower().endswith("_heappe"):
                candidates.append(name)
    except Exception as e:
        log(f"Note: could not list containers: {e}")
    return candidates[0] if candidates else None


def resolve_heappe_service_network(instance_name, log):
    """
    The Docker network QScheduler must share with the HEAppE API container so HEAppE can reach it by
    container name. Prefers a non-internal network, ideally '*external*'. Returns (heappe_container, network).
    """
    docker = DockerCli()
    heappe = find_heappe_api_container(instance_name, log)
    if not heappe:
        return None, None
    nets = [n for n in docker.networks_of(heappe) if n not in ("host", "none")]
    public = [n for n in nets if not docker.network_is_internal(n)]
    for candidates in ([n for n in public if "external" in n.lower()], public, nets):
        if candidates:
            return heappe, candidates[0]
    return heappe, None


def restart_heappe(heappe_container, log, timeout=DOCKER_TIMEOUT):
    """Restarts the HEAppE API container after a network change and waits until it is healthy again."""
    docker = DockerCli()
    log(f"Restarting HEAppE API container '{heappe_container}' to apply the network change "
        f"(HEAppE API is unavailable for a short time)...")
    docker.run(["restart", heappe_container], log)
    start, status = time.time(), ""
    while time.time() - start < timeout:
        state = (docker.inspect(heappe_container) or {}).get("State", {}) or {}
        health = (state.get("Health") or {}).get("Status")
        status = health or state.get("Status", "")
        if status == "healthy" or (health is None and status == "running"):
            log(f"HEAppE API container '{heappe_container}' is {status}.")
            return
        if state.get("Status") in ("exited", "dead"):
            break
        time.sleep(3)
    raise RuntimeError(f"HEAppE API container '{heappe_container}' did not become healthy after restart "
                       f"(last status: {status or 'unknown'}). Check: docker logs {heappe_container}")


def check_from_heappe(heappe_container, host, port, path, log, attempts=10, expect=200):
    """`docker exec <heappe> curl http://<host>:<port><path>`: the request exactly as HEAppE makes it."""
    url = f"http://{host}:{port}{path}"
    cmd = ["docker", "exec", heappe_container, "curl", "-sS", "--max-time", "5", "-o", "/dev/null",
           "-w", "%{http_code}", url]
    out = ""
    for _ in range(attempts):
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode in (126, 127) or "executable file not found" in proc.stderr:
            raise RuntimeError(f"curl is not available in '{heappe_container}'; cannot verify {url}.")
        if proc.stdout.strip() == str(expect):
            log(f"Reachable from HEAppE: {url} -> HTTP {expect}")
            return True
        time.sleep(2)
    raise RuntimeError(f"{url} is not reachable from HEAppE container '{heappe_container}' (got: {out or 'no response'}).")


# ---------------------------------------------------------------------------
# HEAppE instance info and clusters
# ---------------------------------------------------------------------------

def heappe_identity(cred, timeout=5):
    """(version, instance_identifier) of a HEAppE instance: Health API, fallback appsettings.json on disk."""
    import py4heappe.heappe_v6.core as hp
    version, identifier = "", ""
    full_host = f"{cred.heappe_host}:{cred.heappe_port}" if cred.heappe_port and cred.heappe_port not in ('80', '443', '') else cred.heappe_host
    host_url = full_host if full_host.startswith("http") else "http://" + full_host
    try:
        config = hp.Configuration()
        config.host = host_url
        info = hp.HealthApi(hp.ApiClient(config)).heappe_health_get(_request_timeout=timeout)
        version = str(getattr(info, "version", "") or "").lstrip("vV")
        identifier = getattr(info, "instance_identifier", "") or ""
    except Exception:
        pass
    if not identifier:
        try:
            path = os.path.join("/opt/heappe-deployment/", cred.instance_name, "app", "confs", "appsettings.json")
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            identifier = cfg.get("HPCConnectionFrameworkSettings", {}).get("ScriptsSettings", {}).get("InstanceIdentifierPath") or ""
        except Exception:
            pass
    return version, identifier or cred.instance_name


def supports_qscheduler(version):
    """True when a HEAppE version (e.g. "v6.6.0") supports QScheduler; an unknown version does not."""
    return bool(version) and clean_ver(version) >= MIN_HEAPPE_VERSION


supports_notifiers = supports_qscheduler


def unsupported_version_message(instance_name, version):
    return (f"HEAppE '{instance_name}' runs version {version or 'unknown'}; QScheduler features require HEAppE "
            f"{MIN_HEAPPE_VERSION_TEXT} or newer.")


def as_dict(obj):
    return obj.to_dict() if hasattr(obj, "to_dict") else (obj or {})


def id_of(resp):
    d = as_dict(resp)
    if isinstance(d, dict):
        return d.get('id') or d.get('Id')
    return d


def qscheduler_clusters(controller, session_code, inst):
    """HEAppE QScheduler clusters (of one HEAppE instance) that point to this QScheduler instance."""
    out = []
    for c in controller.heappe_management_clusters_get(SessionCode=session_code) or []:
        d = as_dict(c)
        if d.get('scheduler_type') != SCHEDULER_TYPE_QSCHEDULER:
            continue
        cfg = d.get('custom_configuration') or {}
        host = cfg.get("QSchedulerHost") or d.get('master_node_name')
        port = str(cfg.get("QSchedulerPort") or d.get('port') or "")
        if host == inst.service_host and port == str(inst.port):
            out.append(d)
    return out


def cluster_machine(cluster: dict):
    """QScheduler machine of a HEAppE cluster: the queue of its node type (fallback: cluster name)."""
    for nt in cluster.get('node_types') or []:
        if nt.get('queue'):
            return nt['queue']
    return cluster.get('name')


NOTIFY_TOKEN_KEY = "QSchedulerNotifyToken"
NOTIFIER_KEY = "QSchedulerNotifier"


def cluster_notifier_name(heappe_identifier, machine):
    """
    Notifier of one HEAppE cluster: "<HEAppE identifier>.<machine>". A HEAppE has at most one cluster per machine
    on a QScheduler instance, and identifiers are unique among the HEAppEs assigned to it, so the name is unique.
    """
    return f"{heappe_identifier}.{machine}"[:NOTIFIER_MAX_LEN]


def new_admin_token():
    """ADMIN_TOKEN of a QScheduler service (bearer token of its admin API). Kept only in the container environment."""
    return secrets.token_urlsafe(32)


def new_notify_token():
    return secrets.token_urlsafe(32)


def notification_config(notifier=None):
    """
    (CustomConfiguration updates, keys to remove, vault toggle updates) for a cluster.
    notifier: (name, token) to enable callbacks, None to disable them. The token is always kept in HEAppE Vault
    (toggle on): HEAppE moves it there and blanks it in its database; an empty value removes it from Vault.
    """
    if notifier:
        name, token = notifier
        return ({"EnableCallback": "true", NOTIFIER_KEY: name, NOTIFY_TOKEN_KEY: token}, [], {NOTIFY_TOKEN_KEY: True})
    return {"EnableCallback": "false", NOTIFY_TOKEN_KEY: ""}, [NOTIFIER_KEY], {NOTIFY_TOKEN_KEY: True}


def build_cluster_custom_configuration(inst, notifier=None, use_sessions=True):
    """CustomConfiguration + vault toggles for a new QScheduler cluster on `inst` (notifier: (name, token) or None)."""
    config = {
        "QSchedulerHost": inst.service_host,
        "QSchedulerPort": str(inst.port),
        "QSchedulerUseSessions": "true" if use_sessions else "false",
    }
    if not notifier:
        config["EnableCallback"] = "false"
        return config, {}
    updates, _, toggles = notification_config(notifier)
    config.update(updates)
    return config, toggles


def update_cluster_notifications(controller, session_code, cluster: dict, notifier, log, location=None):
    """
    PUT the cluster back with callbacks via `notifier` ((name, token)) or disabled (None); other settings unchanged.
    location: (host, port) to point the cluster to another QScheduler endpoint (restore), or None to keep it.
    """
    cfg = dict(cluster.get('custom_configuration') or {})
    master, port = cluster.get('master_node_name'), cluster.get('port')
    if location:
        master, port = location[0], int(location[1])
        cfg["QSchedulerHost"] = master
        cfg["QSchedulerPort"] = str(port)
    toggles = {k: bool(v) for k, v in (cluster.get('custom_configuration_vault_toggles') or {}).items()}
    updates, remove, toggle_updates = notification_config(notifier)
    cfg.update(updates)
    for k in remove:
        cfg.pop(k, None)
        toggles.pop(k, None)
    toggles.update(toggle_updates)
    proxy = cluster.get('proxy_connection') or {}
    body = {
        "Id": cluster.get('id'),
        "Name": cluster.get('name'),
        "Description": cluster.get('description'),
        "MasterNodeName": master,
        "SchedulerType": cluster.get('scheduler_type'),
        "ConnectionProtocol": cluster.get('connection_protocol'),
        "TimeZone": cluster.get('time_zone'),
        "Port": port,
        "UpdateJobStateByServiceAccount": bool(cluster.get('update_job_state_by_service_account')),
        "DomainName": cluster.get('domain_name') or "",
        "ProxyConnectionId": proxy.get('id') if isinstance(proxy, dict) else None,
        "CustomConfiguration": cfg,
        "CustomConfigurationVaultToggles": toggles,
        "SessionCode": session_code,
    }
    controller.heappe_management_cluster_put(body=body)
    log(f"Cluster '{cluster.get('name')}' (ID {cluster.get('id')}): callbacks "
        f"{'enabled via notifier ' + repr(notifier[0]) + ' (token in Vault)' if notifier else 'disabled'}"
        f"{f', now on {master}:{port}' if location else ''}.")


def repoint_file_transfer_methods(controller, session_code, cluster: dict, host, port, log):
    """Point the cluster's file transfer methods (HTTP to QScheduler) to a new host / port."""
    ids = set(cluster.get('file_transfer_method_ids') or [])
    if not ids:
        return
    for ftm in controller.heappe_management_file_transfer_methods_get(SessionCode=session_code) or []:
        d = as_dict(ftm)
        if d.get('id') not in ids:
            continue
        controller.heappe_management_file_transfer_method_put(body={
            "Id": d.get('id'), "ServerHostname": host, "Protocol": d.get('protocol'),
            "ClusterId": cluster.get('id'), "Port": int(port), "SessionCode": session_code})
        log(f"File transfer method {d.get('id')} of cluster '{cluster.get('name')}' -> {host}:{port}.")


def cluster_notifier(cluster: dict):
    """Notifier name configured on a HEAppE cluster, or None."""
    cfg = cluster.get('custom_configuration') or {}
    if str(cfg.get("EnableCallback", "")).lower() != "true":
        return None
    return cfg.get(NOTIFIER_KEY) or None


def replace_notifiers(target, add: dict, remove, current: dict, log):
    """
    Removes notifiers `remove` and (re)creates `add` ({name: (url, token)}) in QScheduler. A notifier cannot be
    updated in place, so an existing one is removed first. Returns True when anything changed (then call apply_changes).
    """
    changed = False
    for name in list(remove) + [n for n in add if n in current]:
        if name in current:
            target.remove_notifier(name, log)
            current.pop(name)
            changed = True
    for name, (url, token) in add.items():
        target.add_notifier(name, url, token, log)
        log(f"Notifier '{name}' -> {url}")
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Internal Docker networks with small subnets
# ---------------------------------------------------------------------------
# Docker's default address pools hand out /16 or /20 subnets and run out ("all predefined address pools have been
# fully subnetted"). QScheduler's database networks hold two containers, so they get a /29 (default) from a dedicated range.

NETWORK_PREFIX_CHOICES = (24, 25, 26, 27, 28, 29)     # /29 = 6 usable addresses, enough for QScheduler + PostgreSQL


def network_pool():
    """(pool, default prefix) from QSCHEDULER_NETWORK_POOL / QSCHEDULER_NETWORK_PREFIX (settings or environment)."""
    import ipaddress
    pool = getattr(settings, "QSCHEDULER_NETWORK_POOL", None) or os.getenv("QSCHEDULER_NETWORK_POOL", "10.213.0.0/16")
    prefix = int(getattr(settings, "QSCHEDULER_NETWORK_PREFIX", None) or os.getenv("QSCHEDULER_NETWORK_PREFIX", "29"))
    net = ipaddress.ip_network(pool, strict=False)
    check_network_prefix(net, prefix)
    return net, prefix


def check_network_prefix(pool, prefix):
    if not pool.prefixlen <= prefix <= 29:
        raise RuntimeError(f"A /{prefix} subnet does not fit QSCHEDULER_NETWORK_POOL {pool} (between /{pool.prefixlen} and /29).")


def used_subnets(docker):
    """Subnets of all existing Docker networks (IPv4 and IPv6)."""
    import ipaddress
    ids = [i for i in docker.run(["network", "ls", "-q"], check=False, quiet=True).stdout.split() if i]
    used = []
    for info in (docker.json(["network", "inspect", *ids]) or []) if ids else []:
        for cfg in ((info.get("IPAM") or {}).get("Config") or []):
            try:
                used.append(ipaddress.ip_network(cfg.get("Subnet"), strict=False))
            except (TypeError, ValueError):
                pass
    return used


def free_subnets(docker, prefix=None):
    """Free subnets of the QScheduler network pool (size /prefix, default from the settings), in order."""
    pool, default = network_pool()
    prefix = prefix or default
    check_network_prefix(pool, prefix)
    used = [u for u in used_subnets(docker) if u.version == pool.version]
    for candidate in pool.subnets(new_prefix=prefix):
        if not any(candidate.overlaps(u) for u in used):
            yield candidate


def create_internal_network(docker, name, labels, log, attempts=5, prefix=None):
    """
    `docker network create --internal` with an explicit small subnet: /prefix (chosen when deploying; default /29,
    QSCHEDULER_NETWORK_PREFIX) from QSCHEDULER_NETWORK_POOL (default 10.213.0.0/16). Retries the next subnet when
    Docker reports an overlap (e.g. a network created meanwhile).
    """
    pool, default = network_pool()
    prefix = prefix or default
    label_args = [arg for k, v in labels.items() for arg in ("--label", f"{k}={v}")]
    last = ""
    for i, subnet in enumerate(free_subnets(docker, prefix)):
        if i >= attempts:
            break
        res = docker.run(["network", "create", "--driver", "bridge", "--internal", "--subnet", str(subnet),
                          *label_args, name], log, check=False)
        if res.returncode == 0:
            log(f"Network '{name}' created with subnet {subnet}.")
            return str(subnet)
        last = res.output.strip()
        if not re.search(r"overlap", last, re.I):
            break
    raise RuntimeError(f"Could not create network '{name}' with a /{prefix} subnet from {pool}: {last or 'pool exhausted'}. "
                       f"Set QSCHEDULER_NETWORK_POOL to a free private range.")


# ---------------------------------------------------------------------------
# Presence of an instance (manually removed QScheduler) and machine definitions (restore)
# ---------------------------------------------------------------------------

PRESENT, MISSING, UNREACHABLE = "present", "missing", "unreachable"


def presence(inst):
    """
    (state, detail) of the QScheduler container (not of the service: PRESENT does not mean healthy):
      PRESENT     - the container exists (detail: its state, e.g. "exited"), or for "SSH into container" the SSH
                    login into it works
      MISSING     - the container is gone
      UNREACHABLE - cannot tell: Docker or SSH unavailable (an "SSH into container" instance that cannot be
                    logged into looks the same as a removed one)
    """
    from heappe_ui.models import QSchedulerInstance as Q
    try:
        if inst.kind in (Q.KIND_MANAGED, Q.KIND_LOCAL, Q.KIND_SSH_HOST):
            ssh = ssh_session_for(inst) if inst.kind == Q.KIND_SSH_HOST else None
            try:
                docker = DockerCli(ssh, inst.docker_command if ssh else "docker")
                info = docker.inspect(inst.container_name)
                if info:
                    status = (info.get("State") or {}).get("Status") or "unknown"
                    return PRESENT, f"container '{inst.container_name}' is {status}{docker.where}"
                return MISSING, f"container '{inst.container_name}' not found{docker.where}"
            finally:
                if ssh:
                    ssh.close()
        session = ssh_session_for(inst)
        try:
            session.connect()
        finally:
            session.close()
        return PRESENT, f"SSH login into the container on {inst.ssh_host} works"
    except Exception as e:
        return UNREACHABLE, str(e).splitlines()[0][:300]


MACHINE_OPTION_KEYS = ("queue_size", "limit_check_interval", "max_session_time", "default_task_time_limit",
                       "max_clock_skew", "iqm_url", "iqm_device", "iqm_poll_interval")
MACHINE_DEFAULTS = {"queue_size": 4, "limit_check_interval": "2s", "max_session_time": "2h",
                    "default_task_time_limit": "1h", "max_clock_skew": "4s", "iqm_url": "", "iqm_device": "",
                    "iqm_poll_interval": "500ms"}


def machine_definition(opts):
    """(backend, options) of a machine to store in QSchedulerMachine: everything but the IQM token."""
    return opts['backend'], {k: opts.get(k, MACHINE_DEFAULTS[k]) for k in MACHINE_OPTION_KEYS}


# ---------------------------------------------------------------------------
# Background operations: one QScheduler operation at a time, progress streamed through a log file
# ---------------------------------------------------------------------------

_op_lock = threading.Lock()
_op_state = {'is_running': False, 'success': False, 'error': None, 'result': None, 'kind': None}


def log_file_path():
    return os.path.join(settings.BASE_DIR, "qscheduler_setup.log")


def make_logger():
    path = log_file_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass

    def log(message):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        print(message)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            pass
    return log


def start_operation(kind, fn, *args):
    """
    Runs fn(log, result, *args) in a background thread. fn fills `result` (dict) and raises on failure.
    Returns (started, message).
    """
    with _op_lock:
        if _op_state['is_running']:
            return False, f"Another QScheduler operation ({_op_state.get('kind')}) is running. Wait until it finishes."
        _op_state.update({'is_running': True, 'success': False, 'error': None, 'result': None, 'kind': kind})

    def runner():
        from django.db import close_old_connections
        log = make_logger()
        result = {'action': kind}
        try:
            fn(log, result, *args)
            with _op_lock:
                _op_state.update({'is_running': False, 'success': True, 'result': result})
        except Exception as ex:
            from .qscheduler_admin import find_admin_token_error
            err = str(ex) or ex.__class__.__name__
            log(f"EXCEPTION: {kind} failed: {err}")
            token_error = find_admin_token_error(ex)
            if token_error:       # the UI offers to set or regenerate the admin token
                result['admin_token_error'] = token_error.info()
            with _op_lock:
                _op_state.update({'is_running': False, 'success': False, 'result': result,
                                  'error': err.splitlines()[0][:500]})
        finally:
            close_old_connections()

    threading.Thread(target=runner, daemon=True).start()
    return True, f"{kind} started."


def operation_status():
    logs = ""
    path = log_file_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                logs = f.read()
        except Exception as e:
            logs = f"Error reading logs: {e}"
    with _op_lock:
        state = dict(_op_state)
    state['logs'] = logs
    return state


# ---------------------------------------------------------------------------
# Branches and tags of a git repository (deploy / update forms)
# ---------------------------------------------------------------------------

GIT_REFS_CACHE_SECONDS = 300
GIT_REFS_LIMIT = 200
_git_refs_cache = {}   # repo -> (time, result)


def _version_key(ref):
    nums = re.findall(r"\d+", ref)
    return [int(n) for n in nums] if nums else [-1]


def _sorted_refs(branches, tags, default_branch=""):
    branches = sorted(set(branches))
    if default_branch in branches:
        branches.remove(default_branch)
        branches.insert(0, default_branch)
    tags = sorted(set(tags), key=_version_key, reverse=True)
    return branches[:GIT_REFS_LIMIT], tags[:GIT_REFS_LIMIT]


def _http_json_pages(url, timeout, headers=None, pages=2):
    import requests
    out = []
    for page in range(1, pages + 1):
        resp = requests.get(url, params={"per_page": 100, "page": page}, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("unexpected response")
        out += data
        if len(data) < 100:
            break
    return out


def _github_refs(owner, name, timeout):
    import requests
    base = f"https://api.github.com/repos/{owner}/{name}"
    headers = {"Accept": "application/vnd.github+json"}
    info = requests.get(base, headers=headers, timeout=timeout)
    info.raise_for_status()
    default_branch = info.json().get("default_branch", "")
    branches = [b["name"] for b in _http_json_pages(base + "/branches", timeout, headers)]
    tags = [t["name"] for t in _http_json_pages(base + "/tags", timeout, headers)]
    return branches, tags, default_branch


def _gitlab_refs(scheme, host, path, timeout):
    import requests
    from urllib.parse import quote
    base = f"{scheme}://{host}/api/v4/projects/{quote(path, safe='')}"
    info = requests.get(base, timeout=timeout)
    info.raise_for_status()
    default_branch = info.json().get("default_branch", "")
    branches = [b["name"] for b in _http_json_pages(base + "/repository/branches", timeout)]
    tags = [t["name"] for t in _http_json_pages(base + "/repository/tags", timeout)]
    return branches, tags, default_branch


def _ls_remote_refs(repo, timeout):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0",
               GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=5")
    proc = subprocess.run(["git", "ls-remote", "--symref", repo], capture_output=True, text=True,
                          timeout=timeout, env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "git ls-remote failed").strip().splitlines()[-1][:200])
    branches, tags, default_branch = [], [], ""
    for line in proc.stdout.splitlines():
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            default_branch = line[len("ref: refs/heads/"):].split("\t")[0]
            continue
        ref = line.split("\t")[-1]
        if ref.startswith("refs/heads/"):
            branches.append(ref[len("refs/heads/"):])
        elif ref.startswith("refs/tags/") and not ref.endswith("^{}"):
            tags.append(ref[len("refs/tags/"):])
    return branches, tags, default_branch


def list_git_refs(repo, timeout=6):
    """
    Branches and tags of a git repository, for the branch / tag pickers.
    github.com -> GitHub API; other http(s) hosts -> GitLab API; otherwise (or when the API fails) git ls-remote.
    Returns {'branches', 'tags', 'default_branch', 'source'}; raises ValueError / RuntimeError when nothing works.
    Results are cached for a few minutes (the GitHub API allows 60 anonymous requests per hour).
    """
    from urllib.parse import urlparse
    repo = (repo or "").strip()
    if not re.match(r"^(https?://|git@|ssh://)", repo) or any(c.isspace() for c in repo) or repo.startswith("-"):
        raise ValueError("Enter an http(s):// or ssh git URL.")
    cached = _git_refs_cache.get(repo)
    if cached and time.time() - cached[0] < GIT_REFS_CACHE_SECONDS:
        return cached[1]

    errors = []
    found = None
    if repo.startswith(("http://", "https://")):
        u = urlparse(repo)
        path = u.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        host = (u.hostname or "").lower()
        if host and path and not u.username:
            try:
                if host in ("github.com", "www.github.com"):
                    parts = path.split("/")
                    if len(parts) == 2:
                        found = _github_refs(parts[0], parts[1], timeout) + ("github",)
                else:
                    found = _gitlab_refs(u.scheme, u.netloc, path, timeout) + ("gitlab",)
            except Exception as e:
                errors.append(f"API: {str(e).splitlines()[0][:200]}")
    if found is None:
        try:
            found = _ls_remote_refs(repo, timeout + 4) + ("git",)
        except FileNotFoundError:
            errors.append("git is not installed on the management host")
        except subprocess.TimeoutExpired:
            errors.append("git ls-remote timed out")
        except Exception as e:
            errors.append(f"git: {e}")
    if found is None:
        raise RuntimeError("; ".join(errors) or "Repository not reachable.")

    branches, tags, default_branch, source = found
    branches, tags = _sorted_refs(branches, tags, default_branch)
    result = {'branches': branches, 'tags': tags, 'default_branch': default_branch, 'source': source}
    _git_refs_cache[repo] = (time.time(), result)
    return result
