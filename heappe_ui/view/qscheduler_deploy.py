"""
Automated QScheduler deployment for HEAppE (Clusters -> "Deploy QScheduler").

Mapping: one HEAppE Cluster == one QScheduler machine. A single QScheduler instance (service
container + PostgreSQL) hosts many machines, so the action has two targets:
  * new instance      - deploy the service and register its first machine/cluster,
  * existing instance - register one more machine on a running instance (service restart,
                        machines are loaded at startup) and create its HEAppE cluster.

Flow for a new instance (runs in a background thread, progress is streamed through a log file):
  1. Build (or reuse) the qscheduler Docker image from its git repository.
  2. Start a private PostgreSQL container on an internal network, or use an existing database.
  3. Register the quantum machine (`qscheduler machine add`) BEFORE the service starts,
     because machines are only loaded at service startup.
  4. Start `qscheduler serve` attached to the HEAppE instance network(s) + the DB network.
  5. Wait for GET /health.
  6. Register everything in HEAppE: Cluster (SchedulerType=QScheduler, ConnectionProtocol=Http),
     File Transfer Method, Queue Group + accounting formula, Queue (Queue = machine name),
     Project (UsageType=QPUSeconds, AccountingString = QScheduler project name), allocations
     and a placeholder cluster credential.

HEAppE itself registers the project in QScheduler (POST /projects) on the first job submission,
using AccountingString as the name and the summed QPU allocation as the limit.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

from .utils import clean_ver, login_required

DEFAULT_QSCHEDULER_REPO = "https://github.com/It4innovations/qscheduler.git"
DEFAULT_QSCHEDULER_BRANCH = "main"
DEFAULT_QSCHEDULER_IMAGE = "qscheduler:latest"
DEFAULT_POSTGRES_IMAGE = "postgres:16"
MIN_HEAPPE_VERSION = [6, 5, 0]

SCHEDULER_TYPE_QSCHEDULER = 32
CONNECTION_PROTOCOL_HTTP = 8
FILE_TRANSFER_PROTOCOL_HTTP = 8
USAGE_TYPE_QPU_SECONDS = 4
# QScheduler task info exposes "exectime_ms"; HEAppE parses it into task parameters.
DEFAULT_ACCOUNTING_FORMULA = "exectime_ms/1000"

LABEL_INSTANCE = "qscheduler.instance"
LABEL_REPO = "qscheduler.repo"
LABEL_BRANCH = "qscheduler.branch"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_MACHINE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,29}$")  # Queue field is max 30 chars in HEAppE
_DURATION_RE = re.compile(r"^\d+(ms|s|m|h|d)?$")

_qs_setup_lock = threading.Lock()
_qs_setup_state = {
    'is_running': False,
    'success': False,
    'error': None,
    'result': None,
}


def _log_file_path():
    return os.path.join(settings.BASE_DIR, "qscheduler_setup.log")


# ---------------------------------------------------------------------------
# Option parsing / validation (pure, unit-tested)
# ---------------------------------------------------------------------------

def parse_qscheduler_options(data: dict, uid: str) -> tuple:
    """Normalise and validate the options posted from the deploy modal. Returns (opts, errors)."""
    data = data or {}
    errors = []

    def s(key, default=""):
        val = data.get(key, default)
        if val is None or val == "":
            return default
        return str(val).strip()

    def b(key, default=False):
        val = data.get(key, default)
        if val is None or val == "":
            return default
        return str(val).strip().lower() in ("1", "true", "on", "yes")

    def i(key, default, lo, hi, label):
        """Optional integer: empty / missing -> default (may be None)."""
        raw = s(key, "")
        if raw == "":
            return default
        try:
            val = int(float(raw)) if re.fullmatch(r"\d+(\.0+)?", raw) else int(raw)
        except ValueError:
            errors.append(f"{label} must be an integer.")
            return default
        if not (lo <= val <= hi):
            errors.append(f"{label} must be between {lo} and {hi}.")
        return val

    opts = {
        'target': s('target', 'new').lower(),
        'existing_container': s('existing_container'),
        'container_name': s('container_name', default=f"qscheduler-{uid}"),
        'port': i('port', default=4300, lo=1, hi=65535, label="Service port"),
        'host_port': s('host_port'),
        'image': s('image', default=DEFAULT_QSCHEDULER_IMAGE),
        'repo': s('repo', default=DEFAULT_QSCHEDULER_REPO),
        'branch': s('branch', default=DEFAULT_QSCHEDULER_BRANCH),
        'rebuild_image': b('rebuild_image', default=False),
        'db_mode': s('db_mode', default='new'),
        'database_url': s('database_url'),
        'db_network': s('db_network'),
        'backend': s('backend', default='test').lower(),
        'machine_name': s('machine_name', default="SimulatorMachine"),
        'queue_size': i('queue_size', default=4, lo=1, hi=100000, label="Queue size"),
        'max_session_time': s('max_session_time', default="2h"),
        'iqm_url': s('iqm_url'),
        'iqm_token': s('iqm_token'),
        'iqm_device': s('iqm_device'),
        'iqm_check_interval': s('iqm_check_interval', default="500ms"),
        'create_project': b('create_project', default=True),
        'custom_name': b('custom_name', default=False),
        'project_name': s('project_name', default=f"qs-{uid}"),
        'qpu_allocation_seconds': i('qpu_allocation_seconds', default=None, lo=1, hi=10 ** 9, label="QPU allocation"),
        'accounting_formula': s('accounting_formula', default=DEFAULT_ACCOUNTING_FORMULA),
        'use_sessions': b('use_sessions', default=True),
        'enable_callback': b('enable_callback', default=True),
        'store_token_in_vault': b('store_token_in_vault', default=False),
        'callback_url': s('callback_url'),
    }

    if opts['target'] not in ('new', 'existing'):
        errors.append("Target must be 'new' or 'existing'.")
    if opts['target'] == 'existing':
        if not _NAME_RE.match(opts['existing_container']):
            errors.append("Select the QScheduler instance to add the machine to.")
        opts['container_name'] = opts['existing_container']
    if not _NAME_RE.match(opts['container_name']):
        errors.append("Container name may contain only letters, digits, '_', '.', '-' (max 63 chars).")
    if opts['host_port']:
        try:
            hp_ = int(opts['host_port'])
            if not (1 <= hp_ <= 65535):
                raise ValueError
            opts['host_port'] = hp_
        except ValueError:
            errors.append("Host port must be a valid port number or empty.")
    else:
        opts['host_port'] = None
    if not _MACHINE_RE.match(opts['machine_name']):
        errors.append("Machine name may contain only letters, digits, '_', '.', '-' (max 30 chars).")
    if not opts['create_project']:
        # No project: nothing to name and nothing to allocate QPU time to.
        opts['custom_name'] = False
        opts['project_name'] = None
        opts['qpu_allocation_seconds'] = None
    else:
        if not opts['custom_name']:
            opts['project_name'] = f"qs-{uid}"
        if not _NAME_RE.match(opts['project_name']):
            errors.append("QScheduler project name may contain only letters, digits, '_', '.', '-'.")
    if not _DURATION_RE.match(opts['max_session_time']):
        errors.append("Max session time must be a duration like 30m, 2h.")
    if opts['db_mode'] not in ('new', 'existing'):
        errors.append("Database mode must be 'new' or 'existing'.")
    if opts['target'] == 'new' and opts['db_mode'] == 'existing':
        if not opts['database_url'].startswith(("postgres://", "postgresql://")):
            errors.append("Existing database requires a postgres:// DATABASE_URL.")
    if opts['backend'] not in ('test', 'iqm'):
        errors.append("Backend must be 'test' or 'iqm'.")
    if opts['backend'] == 'iqm':
        if not opts['iqm_url'].startswith(("http://", "https://")):
            errors.append("IQM server URL is required (http/https).")
        if not opts['iqm_device']:
            errors.append("IQM device name (e.g. star24) is required.")
        if not _DURATION_RE.match(opts['iqm_check_interval']) or opts['iqm_check_interval'].isdigit():
            errors.append("IQM check interval needs a unit suffix, e.g. 500ms or 1s.")
    if opts['callback_url'] and not opts['callback_url'].startswith(("http://", "https://")):
        errors.append("Callback URL must start with http:// or https://.")
    return opts, errors


def build_machine_add_args(opts: dict, notify_url: str = None, notify_token: str = None, action: str = "add") -> list:
    """
    qscheduler CLI: machine add <NAME> [OPTIONS] <BACKEND> [BACKEND OPTIONS]
    (global options must come before the backend sub-command).
    """
    args = ["machine", action, opts['machine_name'],
            "--queue-size", str(opts['queue_size']),
            "--max-session-time", opts['max_session_time']]
    if notify_url:
        args += ["--notify-url", notify_url]
        if notify_token:
            args += ["--notify-token", notify_token]
    if opts['backend'] == 'iqm':
        args += ["iqm",
                 "--url", opts['iqm_url'],
                 "--machine-name", opts['iqm_device'],
                 "--check-interval", opts['iqm_check_interval']]
        if opts.get('iqm_token'):
            args += ["--token", opts['iqm_token']]
    else:
        args += ["test"]
    return args


def build_cluster_custom_configuration(opts: dict, notify_token: str, version: str) -> tuple:
    """Returns (CustomConfiguration, CustomConfigurationVaultToggles) for the HEAppE cluster."""
    config = {
        "QSchedulerPort": str(opts['port']),
        "QSchedulerHost": opts['container_name'],
        "QSchedulerUseSessions": "true" if opts['use_sessions'] else "false",
        "EnableCallback": "true" if opts['enable_callback'] else "false",
    }
    toggles = {}
    if opts['enable_callback'] and notify_token:
        # Same token as `machine add --notify-token`. Stored as the cluster's callback token
        # (UI: Cluster Callback Notify Token). HEAppE's QScheduler callback handler falls back to
        # ClusterCallbackNotifyToken when QSchedulerNotifyToken is not set, and compares it raw.
        # Setting it also stops HEAppE from auto-generating a different token on first job submit.
        config["ClusterCallbackNotifyToken"] = notify_token
        if clean_ver(version) >= MIN_HEAPPE_VERSION:
            toggles["ClusterCallbackNotifyToken"] = bool(opts['store_token_in_vault'])
    return config, toggles


def redact_args(args: list) -> list:
    """Hide secrets in logged command lines."""
    out, hide_next = [], False
    for a in args:
        if hide_next:
            out.append("********")
            hide_next = False
            continue
        if a in ("--token", "--notify-token"):
            hide_next = True
        if a.startswith("DATABASE_URL="):
            a = re.sub(r"://([^:/@]+):[^@]*@", r"://\1:********@", a)
        if a.startswith("POSTGRES_PASSWORD="):
            a = "POSTGRES_PASSWORD=********"
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------

DOCKER_TIMEOUT = 240          # seconds, default for every docker CLI call
HEALTH_TIMEOUT = 120          # seconds, default wait for QScheduler /health
IMAGE_BUILD_TIMEOUT = 3600    # seconds, Rust release build of the qscheduler image


def _docker(args, log, check=True, timeout=DOCKER_TIMEOUT):
    shown = "docker " + " ".join(redact_args(args))
    log(f"$ {shown}")
    try:
        proc = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out after {timeout}s: {shown}")
    if check and proc.returncode != 0:
        out = (proc.stdout + "\n" + proc.stderr).strip()
        if "no space left on device" in out.lower():
            raise RuntimeError("Host is out of disk space ('No space left on device'). Free up space (e.g. 'docker system prune -a') and retry.")
        raise RuntimeError(f"Command failed ({proc.returncode}): {shown}\n{out[-4000:]}")
    return proc


def _container_exists(name):
    return subprocess.run(["docker", "container", "inspect", name], capture_output=True, text=True).returncode == 0


def _image_exists(image):
    return subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True).returncode == 0


def _parse_serve_port(cmd):
    cmd = list(cmd or [])
    for idx, part in enumerate(cmd):
        if part == "--port" and idx + 1 < len(cmd):
            return int(cmd[idx + 1])
        if part.startswith("--port="):
            return int(part.split("=", 1)[1])
    return 4300


def inspect_qscheduler_instance(name):
    """Reads image, DATABASE_URL, port and networks of a deployed QScheduler service container."""
    proc = subprocess.run(["docker", "container", "inspect", name], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"QScheduler container '{name}' not found.")
    info = json.loads(proc.stdout)[0]
    env = dict(e.split("=", 1) for e in (info.get("Config", {}).get("Env") or []) if "=" in e)
    cmd = info.get("Config", {}).get("Cmd") or []
    if "serve" not in cmd:
        raise RuntimeError(f"Container '{name}' does not run 'qscheduler serve'.")
    if not env.get("DATABASE_URL"):
        raise RuntimeError(f"Container '{name}' has no DATABASE_URL.")
    return {
        'name': name,
        'image': info.get("Config", {}).get("Image"),
        'database_url': env["DATABASE_URL"],
        'port': _parse_serve_port(cmd),
        'running': info.get("State", {}).get("Status") == "running",
        'networks': list((info.get("NetworkSettings", {}).get("Networks") or {}).keys()),
    }


def list_qscheduler_instances(instance_name=None):
    """QScheduler service containers created by this tool (label service=qscheduler)."""
    proc = subprocess.run(["docker", "ps", "-a", "--filter", "label=com.docker.compose.service=qscheduler",
                           "--format", '{{.Names}}\t{{.Status}}\t{{.Label "com.docker.compose.project"}}'],
                          capture_output=True, text=True)
    out = []
    for line in proc.stdout.strip().splitlines():
        name, status, project = (line.split("\t") + ["", "", ""])[:3]
        info = _docker_json(["container", "inspect", name]) or [{}]
        cfg = info[0].get("Config", {}) or {}
        labels = cfg.get("Labels") or {}
        out.append({'name': name, 'status': status, 'port': _parse_serve_port(cfg.get("Cmd") or []),
                    'image': cfg.get("Image"),
                    'repo': labels.get(LABEL_REPO) or DEFAULT_QSCHEDULER_REPO,
                    'branch': labels.get(LABEL_BRANCH) or DEFAULT_QSCHEDULER_BRANCH,
                    'same_instance': bool(instance_name and project.lower() == instance_name.lower())})
    out.sort(key=lambda x: not x['same_instance'])
    return out


def find_heappe_api_container(instance_name, log=print):
    """Returns the HEAppE REST API container name of the instance (compose service 'heappe'), or None."""
    candidates = []
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format",
             '{{.Names}}\t{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.service"}}'],
            capture_output=True, text=True)
        for line in proc.stdout.strip().splitlines():
            parts = (line.split("\t") + ["", "", ""])[:3]
            name, project, service = parts
            if instance_name and project.lower() != instance_name.lower() and not name.lower().startswith(f"{instance_name.lower()}_"):
                continue
            if service == "heappe":
                return name
            if name.lower().endswith("_heappe"):
                candidates.append(name)
    except Exception as e:
        log(f"Note: could not list containers: {e}")
    return candidates[0] if candidates else None


def _docker_json(args):
    proc = subprocess.run(["docker"] + args, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return None


def _container_networks(name):
    info = _docker_json(["container", "inspect", name])
    if not info:
        return []
    return list((info[0].get("NetworkSettings", {}).get("Networks") or {}).keys())


def _network_is_internal(net):
    info = _docker_json(["network", "inspect", net])
    return bool(info and info[0].get("Internal"))


def resolve_heappe_service_network(instance_name, log):
    """
    The Docker network QScheduler must share with the HEAppE API container so HEAppE can reach it by
    container name (HEAppE probes TCP MasterNodeName:QSchedulerPort and calls the REST API there).
    Prefers a non-internal network (also gives QScheduler egress to e.g. IQM), ideally '*external*'.
    Joining only one network keeps QScheduler off HEAppE's vault / ssh-agent / db networks.
    Returns (heappe_container, network) - either may be None.
    """
    heappe = find_heappe_api_container(instance_name, log)
    if not heappe:
        return None, None
    nets = [n for n in _container_networks(heappe) if n not in ("host", "none")]
    if not nets:
        return heappe, None
    public = [n for n in nets if not _network_is_internal(n)]
    for candidates in ([n for n in public if "external" in n.lower()], public, nets):
        if candidates:
            return heappe, candidates[0]
    return heappe, None


def ensure_connected(container, network, alias, log):
    """Connects container to network if needed. Returns True when a new connection was made."""
    if network and network not in _container_networks(container):
        _docker(["network", "connect", "--alias", alias, network, container], log)
        log(f"Connected '{container}' to network '{network}'.")
        return True
    return False


def restart_heappe(heappe_container, log, timeout=DOCKER_TIMEOUT):
    """
    Restarts the HEAppE API container after a network change so it starts with fresh DNS and
    connections, then waits until it is healthy again (compose healthcheck on /heappe/Health)
    or, if the container has no healthcheck, until it is running.
    """
    log(f"Restarting HEAppE API container '{heappe_container}' to apply the network change "
        f"(HEAppE API is unavailable for a short time)...")
    _docker(["restart", heappe_container], log)
    start = time.time()
    status = ""
    while time.time() - start < timeout:
        info = _docker_json(["container", "inspect", heappe_container])
        state = (info[0].get("State", {}) if info else {})
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


def _bash_http_get(host, port, path="/health"):
    """bash-only HTTP GET (the qscheduler image is debian-slim: bash, no curl). Prints the response."""
    return (f"exec 3<>/dev/tcp/{host}/{port} && "
            f"printf 'GET {path} HTTP/1.0\\r\\nHost: {host}\\r\\nConnection: close\\r\\n\\r\\n' >&3 && "
            f"timeout 3 cat <&3")


def _status_of(response):
    """HTTP status code from a raw response ('HTTP/1.1 200 OK ...'), or None."""
    m = re.match(r"HTTP/\d(?:\.\d)?\s+(\d{3})", (response or "").lstrip())
    return int(m.group(1)) if m else None


def qscheduler_healthcheck_args(port):
    """
    Docker HEALTHCHECK for the QScheduler container. The image (debian-slim) has bash but no curl,
    so /health is requested over bash /dev/tcp; healthy == HTTP 200 (QScheduler returns 503 when
    its database is unreachable).
    """
    script = (f"exec 3<>/dev/tcp/127.0.0.1/{port} && "
              f"printf \"GET /health HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n\" >&3 && "
              f"timeout 3 head -n1 <&3 | grep -q \" 200\"")
    return ["--health-cmd", f"bash -c '{script}'",
            "--health-interval", "5s", "--health-timeout", "5s",
            "--health-retries", "5", "--health-start-period", "10s"]


def check_reachable_from_heappe(heappe_container, host, port, log, attempts=10):
    """
    Availability as HEAppE sees it: `docker exec <heappe> curl http://<host>:<port>/health`, i.e. from
    inside the HEAppE API container (its networks + Docker DNS). The HEAppE image ships curl
    (its compose healthcheck uses it).
    """
    shared = sorted(set(_container_networks(heappe_container)) & set(_container_networks(host)))
    log(f"Networks shared by '{heappe_container}' and '{host}': {', '.join(shared) or 'NONE'}")
    if not shared:
        raise RuntimeError(f"'{heappe_container}' and '{host}' share no Docker network, HEAppE cannot resolve '{host}'. "
                           f"Fix: docker network connect --alias {host} <heappe network> {host}")
    url = f"http://{host}:{port}/health"
    cmd = ["exec", heappe_container, "curl", "-sS", "--max-time", "3", "-w", "\\nHTTP %{http_code}", url]
    out = ""
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(["docker"] + cmd, capture_output=True, text=True, timeout=30)
        out = (proc.stdout + proc.stderr).strip()
        if proc.returncode in (126, 127) or "executable file not found" in proc.stderr:
            raise RuntimeError(f"curl is not available in '{heappe_container}'; cannot verify {url}.")
        if proc.returncode == 0 and out.endswith("HTTP 200"):
            log(f"Available from HEAppE: docker exec {heappe_container} curl {url} -> {out.splitlines()[0]} (HTTP 200)")
            return True
        time.sleep(2)
    raise RuntimeError(f"QScheduler is not available from HEAppE: docker exec {heappe_container} curl {url} -> {out or 'no response'}")


def _wait_for_postgres(container, user, log, timeout=60):
    log(f"Waiting for PostgreSQL in '{container}' to accept connections (timeout {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        p = subprocess.run(["docker", "exec", container, "pg_isready", "-U", user, "-h", "127.0.0.1"],
                           capture_output=True, text=True)
        if p.returncode == 0:
            log("PostgreSQL is ready.")
            return
        time.sleep(1)
    raise RuntimeError(f"PostgreSQL container '{container}' did not become ready within {timeout}s.")


def _wait_for_health(opts, log, heappe_container=None, timeout=HEALTH_TIMEOUT):
    """
    The management app runs on the host, where QScheduler (only on internal Docker networks) is not
    reachable, so nothing here calls it over HTTP from the host:
      1. wait until Docker reports the container healthy (HEALTHCHECK from qscheduler_healthcheck_args);
         containers created before the healthcheck existed fall back to an in-container /health probe,
      2. then check availability with `docker exec <heappe> curl http://<qscheduler>:<port>/health`.
    """
    name, port = opts['container_name'], opts['port']
    log(f"Waiting for Docker to report '{name}' healthy (timeout {timeout}s)...")
    start = time.time()
    status, detail = "", ""
    while time.time() - start < timeout:
        info = _docker_json(["container", "inspect", name])
        state = info[0].get("State", {}) if info else {}
        health = state.get("Health")
        if state.get("Status") in ("exited", "dead"):
            status = state.get("Status")
            break
        if health:
            status = health.get("Status", "")
            logs = health.get("Log") or []
            detail = (logs[-1].get("Output") or "").strip()[:300] if logs else ""
            if status == "healthy":
                log(f"Docker reports '{name}' healthy.")
                break
            if status == "unhealthy":
                break
        elif state.get("Status") == "running":
            # no HEALTHCHECK on this container (created by an older version): probe inside it
            proc = subprocess.run(["docker", "exec", name, "bash", "-c", _bash_http_get("127.0.0.1", port)],
                                  capture_output=True, text=True, timeout=30)
            status = "healthy" if _status_of(proc.stdout) == 200 else "starting"
            detail = (proc.stdout[:200] + proc.stderr).strip()
            if status == "healthy":
                log(f"'{name}' has no Docker healthcheck; in-container GET /health returned 200.")
                break
        time.sleep(3)
    if status != "healthy":
        logs = subprocess.run(["docker", "logs", "--tail", "60", name], capture_output=True, text=True)
        container_logs = (logs.stdout + logs.stderr).strip()
        raise RuntimeError(f"QScheduler '{name}' is not healthy (status: {status or 'unknown'}"
                           f"{', last check: ' + detail if detail else ''}).\n--- {name} logs ---\n{container_logs}")

    if heappe_container:
        check_reachable_from_heappe(heappe_container, name, port, log)
    else:
        log("WARNING: HEAppE API container not found; cannot verify that HEAppE can reach QScheduler.")
    return True


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def setup_qscheduler_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)

    try:
        data = json.loads(request.body or b"{}")
    except Exception:
        data = request.POST.dict()

    version = request.session.get("middleware_deployed_version", "") or ""
    if version and clean_ver(version) < MIN_HEAPPE_VERSION:
        return JsonResponse({'status': 'error', 'message': f"QScheduler deployment requires HEAppE 6.5.0 or newer (instance runs {version})."}, status=400)

    uid = str(uuid.uuid4())[:8]
    opts, errors = parse_qscheduler_options(data, uid)
    if errors:
        return JsonResponse({'status': 'error', 'message': " ".join(errors)}, status=400)

    with _qs_setup_lock:
        if _qs_setup_state['is_running']:
            return JsonResponse({'status': 'error', 'message': 'QScheduler deployment is already running.'}, status=400)
        if opts['target'] == 'new' and _container_exists(opts['container_name']):
            return JsonResponse({'status': 'error', 'message': f"Container '{opts['container_name']}' already exists. Choose another name or remove it in Deployments."}, status=400)
        _qs_setup_state.update({'is_running': True, 'success': False, 'error': None, 'result': None})

    instance_name = request.session.get("chosen_instance")
    thread = threading.Thread(target=_run_qscheduler_setup_thread,
                              args=(instance_name, uid, opts, version), daemon=True)
    thread.start()
    return JsonResponse({'status': 'success', 'message': 'QScheduler setup initiated.',
                         'container_name': opts['container_name']})


@login_required
def setup_qscheduler_status_view(request: HttpRequest) -> HttpResponse:
    logs = ""
    path = _log_file_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                logs = f.read()
        except Exception as e:
            logs = f"Error reading logs: {e}"
    with _qs_setup_lock:
        state = dict(_qs_setup_state)
    return JsonResponse({'status': 'success', 'is_running': state['is_running'], 'success': state['success'],
                         'error': state['error'], 'result': state['result'], 'logs': logs})


@login_required
def setup_qscheduler_defaults_view(request: HttpRequest) -> HttpResponse:
    """Values used to pre-fill the deploy form (detected HEAppE container/network and callback URL)."""
    from .clusters import find_docker_networks_for_instance
    instance_name = request.session.get("chosen_instance")
    quiet = lambda *_: None
    heappe_container = find_heappe_api_container(instance_name, quiet)
    networks = find_docker_networks_for_instance(instance_name, log_fn=quiet)
    version = request.session.get("middleware_deployed_version", "") or ""
    return JsonResponse({
        'status': 'success',
        'heappe_container': heappe_container,
        'networks': networks,
        'callback_url': f"http://{heappe_container}:80/heappe/JobManagement/TaskCallback" if heappe_container else "",
        'instances': list_qscheduler_instances(instance_name),
        'version': version,
        'version_supported': (not version) or clean_ver(version) >= MIN_HEAPPE_VERSION,
        'defaults': {'repo': DEFAULT_QSCHEDULER_REPO, 'branch': DEFAULT_QSCHEDULER_BRANCH,
                     'image': DEFAULT_QSCHEDULER_IMAGE, 'port': 4300},
    })


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Manage deployed instances: update from git / undeploy
# ---------------------------------------------------------------------------

def parse_manage_options(data: dict) -> tuple:
    """Validates the update / undeploy request. Returns (opts, errors)."""
    data = data or {}
    errors = []

    def s(key, default=""):
        val = data.get(key)
        return default if val is None or str(val).strip() == "" else str(val).strip()

    def b(key, default=False):
        val = data.get(key)
        if val is None or val == "":
            return default
        return val if isinstance(val, bool) else str(val).strip().lower() in ("1", "true", "on", "yes")

    opts = {
        'action': s('action').lower(),
        'container_name': s('instance') or s('existing_container'),
        'repo': s('repo'),
        'branch': s('branch'),
        'image': s('image'),
        'remove_clusters': b('remove_clusters', True),
        'remove_data': b('remove_data', False),
    }
    if opts['action'] not in ('update', 'undeploy'):
        errors.append("Action must be 'update' or 'undeploy'.")
    if not _NAME_RE.match(opts['container_name']):
        errors.append("Select the QScheduler instance.")
    if opts['action'] == 'update' and opts['repo'] and not re.match(r"^(https?://|git@|ssh://)", opts['repo']):
        errors.append("Git repository must be an http(s):// or ssh git URL.")
    if opts['branch'] and not re.match(r"^[A-Za-z0-9._/-]{1,100}$", opts['branch']):
        errors.append("Branch / tag contains invalid characters.")
    return opts, errors


def instance_resources(name):
    """Docker resources belonging to a QScheduler instance deployed by this tool."""
    info = _docker_json(["container", "inspect", name])
    if not info:
        raise RuntimeError(f"QScheduler container '{name}' not found.")
    labels = info[0].get("Config", {}).get("Labels") or {}
    if labels.get("com.docker.compose.service") != "qscheduler":
        raise RuntimeError(f"Container '{name}' was not deployed by HEAppE Management (missing qscheduler label).")
    pg = f"{name}-pgsql"
    net = f"{name}_db_net"
    vol = f"{name}-pgdata"
    return {
        'service': name,
        'postgres': pg if _container_exists(pg) else None,
        'db_network': net if _docker_json(["network", "inspect", net]) else None,
        'volume': vol if _docker_json(["volume", "inspect", vol]) else None,
        'labels': labels,
        'inspect': info[0],
    }


def recreate_args_from_inspect(info, image, extra_labels=None):
    """
    Rebuilds `docker create` arguments for a QScheduler service container from `docker inspect`
    output: env, labels, restart policy, published ports, command; adds the Docker healthcheck.
    Returns (create_args, [(network, [aliases])...]); the first network is used at create time.
    """
    cfg = info.get("Config", {}) or {}
    host = info.get("HostConfig", {}) or {}
    name = info.get("Name", "").lstrip("/")
    cmd = cfg.get("Cmd") or ["serve", "--port", "4300"]
    port = _parse_serve_port(cmd)
    labels = dict(cfg.get("Labels") or {})
    labels.update(extra_labels or {})
    args = ["create", "--name", name]
    policy = (host.get("RestartPolicy") or {}).get("Name") or "unless-stopped"
    if policy != "no":
        args += ["--restart", policy]
    for e in cfg.get("Env") or []:
        if not e.startswith("PATH="):
            args += ["-e", e]
    for k, v in sorted(labels.items()):
        args += ["--label", f"{k}={v}"]
    for cport, binds in sorted((host.get("PortBindings") or {}).items()):
        for bnd in binds or []:
            hip, hport = bnd.get("HostIp") or "", bnd.get("HostPort") or ""
            args += ["-p", f"{hip + ':' if hip else ''}{hport}:{cport.split('/')[0]}"]
    networks = []
    short_id = info.get("Id", "")[:12]
    for net, ncfg in (info.get("NetworkSettings", {}).get("Networks") or {}).items():
        aliases = [a for a in ((ncfg or {}).get("Aliases") or []) if a not in (short_id, info.get("Id"))]
        if net not in ("bridge", "host", "none") and name not in aliases:
            aliases.append(name)
        networks.append((net, aliases if net not in ("bridge", "host", "none") else []))
    # egress-capable network first (internal DB networks after), as at deploy time
    networks.sort(key=lambda n: _network_is_internal(n[0]))
    if networks:
        args += ["--network", networks[0][0]]
        for a in networks[0][1]:
            args += ["--network-alias", a]
    args += qscheduler_healthcheck_args(port)
    args += [image] + list(cmd)
    return args, networks, port


def _run_qscheduler_manage_thread(instance_name, uid, opts):
    from .clusters import connect_heappe_management_api

    log_path = _log_file_path()
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass

    def log(message):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        print(message)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)

    name = opts['container_name']
    result = {'action': opts['action'], 'container_name': name}
    log(f"=== QSCHEDULER: {opts['action'].upper()} INSTANCE '{name}' === (HEAppE instance: {instance_name})")
    try:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker CLI not found on the management host.")
        res = instance_resources(name)
        if opts['action'] == 'undeploy':
            _undeploy_instance(instance_name, res, opts, result, log, connect_heappe_management_api)
        else:
            _update_instance(instance_name, uid, res, opts, result, log)
        with _qs_setup_lock:
            _qs_setup_state.update({'is_running': False, 'success': True, 'result': result})
    except Exception as ex:
        err = str(ex)
        log(f"EXCEPTION: {opts['action']} failed: {err}")
        with _qs_setup_lock:
            _qs_setup_state.update({'is_running': False, 'success': False,
                                    'error': err.splitlines()[0][:500] if err else "Unknown error"})


def _undeploy_instance(instance_name, res, opts, result, log, connect_heappe_management_api):
    name = res['service']
    # 1. HEAppE clusters served by this instance (cluster MasterNodeName == QScheduler container name)
    removed = []
    if opts['remove_clusters']:
        controller, session_code, _ = connect_heappe_management_api(instance_name, log)
        clusters = controller.heappe_management_clusters_get(SessionCode=session_code)
        for c in clusters or []:
            d = c.to_dict() if hasattr(c, 'to_dict') else c
            if d.get('scheduler_type') == SCHEDULER_TYPE_QSCHEDULER and d.get('master_node_name') == name:
                controller.heappe_management_cluster_delete(body={"Id": d.get('id'), "SessionCode": session_code})
                removed.append(d.get('id'))
                log(f"Deleted HEAppE cluster '{d.get('name')}' (ID: {d.get('id')}).")
        if not removed:
            log("No HEAppE cluster uses this instance.")
    else:
        log("Keeping HEAppE clusters (they will be unreachable until pointed to another QScheduler).")
    result['removed_clusters'] = removed

    # 2. Docker resources: containers first, then network, then (optionally) the data volume
    _docker(["rm", "-f", name], log)
    if res['postgres']:
        _docker(["rm", "-f", res['postgres']], log)
    if res['db_network']:
        proc = _docker(["network", "rm", res['db_network']], log, check=False)
        if proc.returncode != 0:
            log(f"WARNING: could not remove network '{res['db_network']}': {proc.stderr.strip()}")
    if res['volume']:
        if opts['remove_data']:
            _docker(["volume", "rm", res['volume']], log)
        else:
            log(f"Kept database volume '{res['volume']}' (remove with: docker volume rm {res['volume']}).")
    log(f"Image '{res['inspect'].get('Config', {}).get('Image')}' kept (may be used by other instances).")
    log(f"SUCCESS: QScheduler instance '{name}' undeployed.")


def _update_instance(instance_name, uid, res, opts, result, log):
    name = res['service']
    info = res['inspect']
    labels = res['labels']
    image = opts['image'] or info.get("Config", {}).get("Image") or DEFAULT_QSCHEDULER_IMAGE
    repo = opts['repo'] or labels.get(LABEL_REPO) or DEFAULT_QSCHEDULER_REPO
    branch = opts['branch'] or labels.get(LABEL_BRANCH) or DEFAULT_QSCHEDULER_BRANCH
    result.update({'image': image, 'repo': repo, 'branch': branch})

    # 1. Build the new image (old container keeps running meanwhile)
    log(f"Building image '{image}' from {repo}#{branch} (Rust release build, can take several minutes)...")
    _docker(["build", "-t", image, f"{repo}#{branch}"], log, timeout=IMAGE_BUILD_TIMEOUT)
    log("Image built successfully.")

    # 2. Recreate with the same configuration; keep the old container for rollback
    create_args, networks, port = recreate_args_from_inspect(
        info, image, {LABEL_INSTANCE: name, LABEL_REPO: repo, LABEL_BRANCH: branch})
    backup = f"{name}-old-{uid}"
    heappe_container = find_heappe_api_container(instance_name, log)
    _docker(["stop", name], log)
    _docker(["rename", name, backup], log)
    try:
        _docker(create_args, log)
        for net, aliases in networks[1:]:
            alias_args = sum((["--alias", a] for a in aliases), [])
            _docker(["network", "connect"] + alias_args + [net, name], log)
        _docker(["start", name], log)
        _wait_for_health({'container_name': name, 'port': port}, log, heappe_container)
    except Exception as ex:
        log(f"Update failed ({str(ex).splitlines()[0]}); rolling back to the previous container...")
        _docker(["rm", "-f", name], log, check=False)
        _docker(["rename", backup, name], log, check=False)
        _docker(["start", name], log, check=False)
        raise RuntimeError(f"Update failed and was rolled back: {ex}")
    _docker(["rm", backup], log)

    proc = subprocess.run(["docker", "exec", name, "bash", "-c", _bash_http_get("127.0.0.1", port, "/version")],
                          capture_output=True, text=True, timeout=30)
    version = re.split(r"\r?\n\r?\n", proc.stdout, maxsplit=1)[-1].strip()
    result['version'] = version
    log(f"SUCCESS: '{name}' updated ({version or 'version unknown'}). Machines and projects are kept in PostgreSQL.")


@login_required
def qscheduler_manage_view(request: HttpRequest) -> HttpResponse:
    """POST {action: update|undeploy, instance, repo?, branch?, image?, remove_clusters?, remove_data?}"""
    if request.method != "POST":
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)
    try:
        data = json.loads(request.body or b"{}")
    except Exception:
        data = request.POST.dict()
    opts, errors = parse_manage_options(data)
    if errors:
        return JsonResponse({'status': 'error', 'message': " ".join(errors)}, status=400)
    with _qs_setup_lock:
        if _qs_setup_state['is_running']:
            return JsonResponse({'status': 'error', 'message': 'Another QScheduler operation is running.'}, status=400)
        _qs_setup_state.update({'is_running': True, 'success': False, 'error': None, 'result': None})
    uid = str(uuid.uuid4())[:8]
    threading.Thread(target=_run_qscheduler_manage_thread,
                     args=(request.session.get("chosen_instance"), uid, opts), daemon=True).start()
    return JsonResponse({'status': 'success', 'message': f"QScheduler {opts['action']} initiated."})


def _id_of(resp):
    d = resp.to_dict() if hasattr(resp, 'to_dict') else resp
    if isinstance(d, dict):
        return d.get('id') or d.get('Id')
    return d


def _run_qscheduler_setup_thread(instance_name, uid, opts, version):
    from .clusters import find_docker_networks_for_instance, connect_heappe_management_api

    log_path = _log_file_path()
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass

    def log(message):
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        print(message)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)

    name = opts['container_name']
    pg_name = f"{name}-pgsql"
    db_net = f"{name}_db_net"
    project_label = instance_name or "test"
    created = []  # (kind, name) for cleanup hints
    notify_token = secrets.token_urlsafe(32) if opts['enable_callback'] else None
    result = {'container_name': name, 'port': opts['port'], 'machine_name': opts['machine_name'],
              'backend': opts['backend'], 'project_name': opts['project_name']}

    log(f"=== QSCHEDULER: {'NEW INSTANCE' if opts['target'] == 'new' else 'ADD MACHINE TO EXISTING INSTANCE'} ===")
    log(f"Identifier: {uid} | instance container: {name} | machine: {opts['machine_name']} ({opts['backend']}) | HEAppE instance: {instance_name}")

    def resolve_callback():
        notify_url = None
        if opts['enable_callback']:
            notify_url = opts['callback_url']
            if not notify_url:
                heappe_container = find_heappe_api_container(instance_name, log)
                if heappe_container:
                    notify_url = f"http://{heappe_container}:80/heappe/JobManagement/TaskCallback"
                else:
                    log("WARNING: HEAppE API container not found; callbacks disabled, HEAppE will poll task state instead.")
                    opts['enable_callback'] = False
            if notify_url:
                log(f"Task/session callbacks -> {notify_url}")
        return notify_url

    def register_machine(run_prefix, image, notify_url, notify_token):
        # 'add' only: never 'update' an existing machine, it may already back another HEAppE cluster.
        log(f"Registering machine '{opts['machine_name']}'...")
        proc = _docker(run_prefix + [image] + build_machine_add_args(opts, notify_url, notify_token), log,
                       check=False)
        if proc.returncode != 0:
            out = (proc.stdout + proc.stderr).strip()
            if re.search(r"exist|duplicate|unique", out, re.I):
                raise RuntimeError(f"Machine '{opts['machine_name']}' already exists in this QScheduler instance "
                                   f"(it already backs a cluster). Choose another machine name.")
            raise RuntimeError(f"Machine registration failed:\n{out[-3000:]}")
        log("Machine registered.")

    try:
        if shutil.which("docker") is None:
            raise RuntimeError("Docker CLI not found on the management host.")

        if opts['target'] == 'existing':
            # ---- Add a machine (= HEAppE cluster) to a running instance ----
            inst = inspect_qscheduler_instance(name)
            if not inst['running']:
                raise RuntimeError(f"QScheduler container '{name}' is not running. Start it in Deployments first.")
            opts['port'] = inst['port']
            result['port'] = inst['port']
            log(f"Instance '{name}': image {inst['image']}, port {inst['port']}, networks {', '.join(inst['networks'])}.")
            heappe_container, heappe_net = resolve_heappe_service_network(instance_name, log)
            network_changed = bool(heappe_net) and ensure_connected(name, heappe_net, name, log)
            notify_url = resolve_callback()
            if not opts['enable_callback']:
                notify_token = None
            # Share the service's network namespace so the DB is reachable exactly as for the service.
            register_machine(["run", "--rm", "--network", f"container:{name}",
                              "-e", f"DATABASE_URL={inst['database_url']}"], inst['image'], notify_url, notify_token)
            log(f"Restarting '{name}' so it loads the new machine (running tasks on other machines are interrupted briefly)...")
            _docker(["restart", name], log)
            if heappe_container and network_changed:
                restart_heappe(heappe_container, log)
            _wait_for_health(opts, log, heappe_container)
        else:
            # ---- New instance ----
            # 1. Image
            if opts['rebuild_image'] or not _image_exists(opts['image']):
                src = f"{opts['repo']}#{opts['branch']}"
                log(f"Building image '{opts['image']}' from {src} (Rust release build, can take several minutes)...")
                _docker(["build", "-t", opts['image'], src], log, timeout=IMAGE_BUILD_TIMEOUT)
                log("Image built successfully.")
            else:
                log(f"Reusing existing image '{opts['image']}' (tick 'Rebuild image' to force a fresh build).")

            # 2. Networks: share the HEAppE API container's network (name resolution needs a user-defined network)
            heappe_container, heappe_net = resolve_heappe_service_network(instance_name, log)
            if heappe_net:
                heappe_networks = [heappe_net]
                log(f"HEAppE API container '{heappe_container}' found; QScheduler will join its network '{heappe_net}'.")
            else:
                heappe_networks = [n for n in find_docker_networks_for_instance(instance_name, log_fn=log)
                                   if not _network_is_internal(n)][:1]
                if not heappe_networks:
                    raise RuntimeError(f"No Docker network of HEAppE instance '{instance_name}' found. QScheduler would start "
                                       f"on the default bridge, where HEAppE cannot resolve it by name. Is the instance running?")
                log(f"WARNING: HEAppE API container not identified; using detected network '{heappe_networks[0]}'.")

            # 3. Database
            if opts['db_mode'] == 'new':
                db_password = secrets.token_hex(16)
                _docker(["network", "create", "--driver", "bridge", "--internal",
                         "--label", f"com.docker.compose.project={project_label}",
                         "--label", f"{LABEL_INSTANCE}={name}", db_net], log)
                created.append(("network", db_net))
                _docker(["volume", "create", "--label", f"{LABEL_INSTANCE}={name}", f"{name}-pgdata"], log)
                created.append(("volume", f"{name}-pgdata"))
                _docker(["run", "-d", "--name", pg_name, "--restart", "unless-stopped",
                         "--network", db_net, "--network-alias", pg_name, "--shm-size", "128m",
                         "--label", f"com.docker.compose.project={project_label}",
                         "--label", "com.docker.compose.service=qscheduler-db",
                         "--label", f"{LABEL_INSTANCE}={name}",
                         "-e", "POSTGRES_USER=qscheduler", "-e", f"POSTGRES_PASSWORD={db_password}",
                         "-e", "POSTGRES_DB=qscheduler",
                         "-v", f"{name}-pgdata:/var/lib/postgresql/data",
                         DEFAULT_POSTGRES_IMAGE], log)
                created.append(("container", pg_name))
                _wait_for_postgres(pg_name, "qscheduler", log)
                database_url = f"postgres://qscheduler:{db_password}@{pg_name}:5432/qscheduler"
                db_networks = [db_net]
            else:
                database_url = opts['database_url']
                db_networks = [opts['db_network']] if opts['db_network'] else []
                log(f"Using existing database{(' on network ' + opts['db_network']) if opts['db_network'] else ''}.")
            result['db_container'] = pg_name if opts['db_mode'] == 'new' else None

            # 4. Machine registration (before 'serve': machines are loaded at startup)
            notify_url = resolve_callback()
            if not opts['enable_callback']:
                notify_token = None
            run_net = db_networks[0] if db_networks else (heappe_networks[0] if heappe_networks else None)
            prefix = ["run", "--rm", "-e", f"DATABASE_URL={database_url}"] + (["--network", run_net] if run_net else [])
            register_machine(prefix, opts['image'], notify_url, notify_token)

            # 5. Service container: create, attach every network, then start (avoids racing the DB connect).
            # The first network must allow egress (IQM backend); internal DB networks come after.
            attach = list(dict.fromkeys((heappe_networks or ["bridge"]) + db_networks))
            run_cmd = ["create", "--name", name, "--restart", "unless-stopped",
                       "--label", f"com.docker.compose.project={project_label}",
                       "--label", "com.docker.compose.service=qscheduler",
                       "--label", f"{LABEL_INSTANCE}={name}",
                       "--label", f"{LABEL_REPO}={opts['repo']}",
                       "--label", f"{LABEL_BRANCH}={opts['branch']}",
                       "-e", f"DATABASE_URL={database_url}", "--network", attach[0]]
            if attach[0] != "bridge":
                run_cmd += ["--network-alias", name]
            if opts['host_port']:
                run_cmd += ["-p", f"127.0.0.1:{opts['host_port']}:{opts['port']}"]
            run_cmd += qscheduler_healthcheck_args(opts['port'])
            run_cmd += [opts['image'], "serve", "--port", str(opts['port'])]
            _docker(run_cmd, log)
            created.append(("container", name))
            for net in attach[1:]:
                _docker(["network", "connect", "--alias", name, net, name], log)
            _docker(["start", name], log)
            if heappe_container:
                restart_heappe(heappe_container, log)
            _wait_for_health(opts, log, heappe_container)
        result['notify_url'] = notify_url

        # 7. HEAppE registration
        controller, session_code, _ = connect_heappe_management_api(instance_name, log)
        now = datetime.utcnow() - timedelta(minutes=5)
        valid_to = now + timedelta(days=365)
        fmt = "%Y-%m-%dT%H:%M:%SZ"

        custom_config, vault_toggles = build_cluster_custom_configuration(opts, notify_token, version)
        cluster_payload = {
            "Name": opts['machine_name'],
            "Description": f"QScheduler ({opts['backend']} backend) deployed from HEAppE Management",
            "MasterNodeName": name,
            "SchedulerType": SCHEDULER_TYPE_QSCHEDULER,
            "ConnectionProtocol": CONNECTION_PROTOCOL_HTTP,
            "TimeZone": "UTC",
            "Port": opts['port'],
            "UpdateJobStateByServiceAccount": False,
            "DomainName": "",
            "ProxyConnectionId": None,
            "CustomConfiguration": custom_config,
            "CustomConfigurationVaultToggles": vault_toggles,
            "SessionCode": session_code,
        }
        log("Creating QScheduler Cluster in HEAppE (protocol HTTP, direct REST calls)...")
        cluster_id = _id_of(controller.heappe_management_cluster_post(body=cluster_payload))
        log(f"Cluster created (ID: {cluster_id}).")

        ftm_id = _id_of(controller.heappe_management_file_transfer_method_post(body={
            "ClusterId": cluster_id, "ServerHostname": name, "Protocol": FILE_TRANSFER_PROTOCOL_HTTP,
            "Port": opts['port'], "SessionCode": session_code}))
        log(f"File Transfer Method created (ID: {ftm_id}).")

        group_id = _id_of(controller.heappe_management_cluster_node_type_aggregation_post(body={
            "Name": f"QPU Group {uid}", "Description": f"QPU time on {opts['machine_name']}",
            "AllocationType": "QPU", "ValidityFrom": now.strftime(fmt), "ValidityTo": valid_to.strftime(fmt),
            "SessionCode": session_code}))
        log(f"Queue Group created (ID: {group_id}).")

        accounting_id = _id_of(controller.heappe_management_accounting_post(body={
            "Formula": opts['accounting_formula'], "ValidityFrom": now.strftime(fmt),
            "ValidityTo": valid_to.strftime(fmt), "SessionCode": session_code}))
        controller.heappe_management_cluster_node_type_aggregation_accounting_post(body={
            "ClusterNodeTypeAggregationId": group_id, "AccountingId": accounting_id, "SessionCode": session_code})
        log(f"Accounting formula '{opts['accounting_formula']}' created (ID: {accounting_id}) and mapped.")

        queue_id = _id_of(controller.heappe_management_cluster_node_type_post(body={
            "Name": opts['machine_name'][:50], "Description": f"QScheduler machine {opts['machine_name']}",
            "NumberOfNodes": 1, "CoresPerNode": 1, "Queue": opts['machine_name'], "QualityOfService": None,
            "MaxWalltime": 86400, "ClusterAllocationName": None, "ClusterId": cluster_id,
            "FileTransferMethodId": ftm_id, "ClusterNodeTypeAggregationId": group_id,
            "SessionCode": session_code}))
        log(f"Queue '{opts['machine_name']}' created (ID: {queue_id}).")

        project_id = None
        if opts['create_project']:
            project_id = _id_of(controller.heappe_management_project_post(body={
                "Name": opts['project_name'], "Description": f"Quantum project on {opts['machine_name']}",
                "AccountingString": opts['project_name'], "StartDate": now.strftime(fmt),
                "EndDate": valid_to.strftime(fmt), "UsageType": USAGE_TYPE_QPU_SECONDS,
                "UseAccountingStringForScheduler": True, "IsOneToOneMapping": False, "PIEmail": "",
                "SessionCode": session_code}))
            log(f"Project created (ID: {project_id}, QScheduler project name '{opts['project_name']}').")

            controller.heappe_management_project_assignment_to_cluster_post(body={
                "ProjectId": project_id, "ClusterId": cluster_id, "ScratchStoragePath": "/tmp",
                "PermanentStoragePath": "/tmp", "ProjectStoragePath": "/tmp", "SessionCode": session_code})
        
            # Optional: QPU allocation
            if opts.get('qpu_allocation_seconds') is not None:
                controller.heappe_management_project_cluster_node_type_aggregation_post(body={
                    "ProjectId": project_id, "ClusterNodeTypeAggregationId": group_id,
                    "AllocationAmount": opts['qpu_allocation_seconds'], "SessionCode": session_code})
                log(f"Project assigned to cluster with {opts['qpu_allocation_seconds']} QPU seconds.")
            else:
                log("No QPU allocation given: project is not assigned to the QPU queue group. HEAppE rejects QScheduler "
                    "jobs for this project until an allocation is added (Projects > Queue Groups).")

            # HTTP clusters ignore the credential content, but HEAppE needs one per project/cluster to submit.
            try:
                controller.heappe_management_generate_secure_shell_key_post(body={
                    "Credentials": [{"Username": "qscheduler", "Password": secrets.token_urlsafe(16)}],
                    "ProjectId": project_id, "SessionCode": session_code})
                log("Service credential for the project created.")
            except Exception as e_cred:
                log(f"WARNING: could not create project credential ({e_cred}). Add one in Projects > Credentials before submitting jobs.")

        else:
            log("Project creation skipped (not requested). The cluster and queue exist without a project, QPU allocation "
                "or credential; add them in HEAppE (Projects) before submitting QScheduler jobs.")

        result.update({'cluster_id': cluster_id, 'project_id': project_id, 'queue_id': queue_id})
        log("SUCCESS: QScheduler deployed and registered in HEAppE.")
        with _qs_setup_lock:
            _qs_setup_state.update({'is_running': False, 'success': True, 'result': result})

    except Exception as ex:
        err = str(ex)
        log(f"EXCEPTION: Deployment failed: {err}")
        if opts['target'] == 'existing' and "Machine registered." in open(log_path, encoding="utf-8").read():
            log(f"NOTE: machine '{opts['machine_name']}' is registered in '{name}' but has no HEAppE cluster. "
                f"Create the cluster manually (SchedulerType QScheduler, Queue = '{opts['machine_name']}') or remove the machine.")
        if created:
            # containers first (they hold volumes/networks), then volumes, then networks
            order = {'container': 0, 'volume': 1, 'network': 2}
            commands_tbd = ""
            for kind, n in sorted(created, key=lambda x: order.get(x[0], 9)):
                commands_tbd += f"  docker {'rm -f' if kind == 'container' else kind + ' rm'} {n}\n"
            log("Resources created before the failure (left in place for inspection). To remove them:\n" + commands_tbd)
        with _qs_setup_lock:
            _qs_setup_state.update({'is_running': False, 'success': False, 'error': err.splitlines()[0][:500] if err else "Unknown error"})