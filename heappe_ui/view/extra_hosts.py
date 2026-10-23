"""
Extra hosts (static /etc/hosts entries) of the containers of a HEAppE instance.

Targets
  * compose:<service>  - `heappe` and `datastagingapi` of the instance's docker compose project. Custom entries are
                         kept in docker-compose.override.yml (untracked): the tracked docker-compose.yml is reset by
                         `git checkout -- .` on branch switch. Compose appends them to the base extra_hosts.
                         Apply = `docker compose up -d --no-deps --force-recreate <service>`.
  * qscheduler:<id>    - a Docker-based QScheduler instance assigned to this HEAppE instance. Custom entries are kept
                         on its record (QSchedulerInstance.extra_hosts). Apply = recreate the container with
                         `--add-host` (same as an update, rolled back on failure), in the QScheduler operation queue.

Entries for host.docker.internal (usually `host.docker.internal:host-gateway`) cannot be added, changed or removed
here; existing ones are always kept.
"""
import ipaddress
import os
import re
import threading

from django.http import JsonResponse

from .utils import login_required

COMPOSE_SERVICES = [
    ("heappe", "HEAppE API"),
    ("datastagingapi", "Data Staging API"),
]
PROTECTED_EXTRA_HOSTNAMES = {"host.docker.internal"}
OVERRIDE_FILE = "docker-compose.override.yml"
DEPLOYMENT_BASE_PATH = "/opt/heappe-deployment/"
_LOCK = threading.Lock()

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)[A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9])?"
    r"(\.[A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9])?)*$"
)


# ---------------------------------------------------------------------------
# Pure helpers (also used by qscheduler_deploy)
# ---------------------------------------------------------------------------

def split_extra_host(entry):
    """Split an extra host entry ("host:ip" or "host=ip") into (host, ip)."""
    entry = str(entry).strip()
    sep = "=" if "=" in entry else ":"
    host, _, ip = entry.partition(sep)
    ip = ip.strip()
    if ip.startswith("[") and ip.endswith("]"):
        ip = ip[1:-1]
    return host.strip(), ip


def format_extra_host(host, ip):
    return f"{host}:{ip}"


def extra_hosts_as_list(value):
    """extra_hosts in list or mapping form -> list of (host, ip)."""
    if not value:
        return []
    if isinstance(value, dict):
        result = []
        for host, ips in value.items():
            for ip in (ips if isinstance(ips, list) else [ips]):
                result.append((str(host).strip(), str(ip).strip()))
        return result
    return [split_extra_host(e) for e in value]


def is_protected_extra_host(hostname):
    return str(hostname).strip().lower() in PROTECTED_EXTRA_HOSTNAMES


def validate_extra_host(hostname, ip):
    """Validate user input; returns the normalized (hostname, ip) or raises ValueError."""
    hostname = (hostname or "").strip()
    ip = (ip or "").strip()
    if ip.startswith("[") and ip.endswith("]"):
        ip = ip[1:-1]
    if not hostname or not _HOSTNAME_RE.match(hostname):
        raise ValueError(f"Invalid hostname: '{hostname}'.")
    if ip != "host-gateway":
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            raise ValueError(f"Invalid IP address: '{ip}'. Use an IPv4/IPv6 address or 'host-gateway'.")
    return hostname, ip


def qscheduler_container_extra_hosts(container_hosts, custom):
    """
    --add-host entries for a recreated QScheduler container: protected entries the container already has, then
    the custom ones. custom None (never managed here) -> None: keep whatever the container has.
    """
    if custom is None:
        return None
    protected = [h for h in extra_hosts_as_list(container_hosts) if is_protected_extra_host(h[0])]
    custom = [h for h in extra_hosts_as_list(custom) if not is_protected_extra_host(h[0])]
    return [format_extra_host(h, ip) for h, ip in protected + custom]


# ---------------------------------------------------------------------------
# docker compose (heappe, datastagingapi)
# ---------------------------------------------------------------------------

def _load_yaml_file(path):
    import yaml
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{os.path.basename(path)} does not contain a YAML mapping.")
    return data


def _service_extra_hosts(compose_data, service):
    svc = (compose_data.get("services") or {}).get(service) or {}
    return extra_hosts_as_list(svc.get("extra_hosts"))


def write_override_extra_hosts(override_path, service, hosts):
    """Store custom extra_hosts of `service`, keeping the rest of the override file intact."""
    import yaml
    data = _load_yaml_file(override_path)
    services = data.get("services") if isinstance(data.get("services"), dict) else {}
    svc = services.get(service) if isinstance(services.get(service), dict) else {}

    if hosts:
        svc["extra_hosts"] = [format_extra_host(h, ip) for h, ip in hosts]
        services[service] = svc
    else:
        svc.pop("extra_hosts", None)
        if svc:
            services[service] = svc
        else:
            services.pop(service, None)

    if services:
        data["services"] = services
    else:
        data.pop("services", None)

    if not data:
        if os.path.exists(override_path):
            os.remove(override_path)
        return

    tmp_path = override_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write("# Managed by HEAppE Management UI (Containers & Services > Extra Hosts).\n")
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    os.replace(tmp_path, override_path)


def _compose_running_hosts(instance_name, service):
    """Extra hosts of the running compose service container, or None if unknown."""
    try:
        import docker
        for c in docker.from_env().containers.list(all=True):
            labels = c.labels or {}
            if labels.get('com.docker.compose.project') == instance_name and \
                    labels.get('com.docker.compose.service') == service:
                return extra_hosts_as_list(c.attrs.get('HostConfig', {}).get('ExtraHosts') or [])
    except Exception:
        pass
    return None


class ComposeTarget:
    kind = "compose"

    def __init__(self, instance_name, service, title):
        self.instance_name, self.service, self.title = instance_name, service, title
        self.key = f"compose:{service}"
        self.compose_dir = os.path.join(DEPLOYMENT_BASE_PATH, instance_name, "heappe-core")
        self.override_path = os.path.join(self.compose_dir, OVERRIDE_FILE)

    def state(self):
        """(fixed, custom): fixed = from docker-compose.yml (read-only), custom = from the override file."""
        base = _service_extra_hosts(_load_yaml_file(os.path.join(self.compose_dir, "docker-compose.yml")), self.service)
        custom = _service_extra_hosts(_load_yaml_file(self.override_path), self.service)
        return base, custom

    def save(self, custom):
        write_override_extra_hosts(self.override_path, self.service, custom)

    def describe(self):
        base, custom = self.state()
        running = _compose_running_hosts(self.instance_name, self.service)
        return {
            'key': self.key, 'kind': self.kind, 'title': self.title, 'name': self.service,
            'storage': f"{OVERRIDE_FILE} (service {self.service})",
            'hosts': _rows(base, "default", custom),
            'pending_apply': None if running is None else sorted(set(running)) != sorted(set(base + custom)),
            'apply_note': f"Recreates the {self.service} container (short downtime).",
        }

    def apply(self):
        from .deploy import execute_docker_compose
        cmd = ["docker", "compose",
               "--profile", "db", "--profile", "heappe", "--profile", "initVault",
               "--profile", "vault", "--profile", "vaultagent", "--profile", "sshagent",
               "--profile", "staging",
               "-p", self.instance_name,
               "up", "-d", "--no-deps", "--force-recreate", self.service]
        result = execute_docker_compose(cmd, self.compose_dir)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to recreate {self.service}: {result.stderr}")
        return f"Extra hosts applied. The {self.service} container was recreated."


# ---------------------------------------------------------------------------
# QScheduler instances assigned to the HEAppE instance
# ---------------------------------------------------------------------------

class QSchedulerTarget:
    kind = "qscheduler"

    def __init__(self, inst):
        self.inst = inst
        self.key = f"qscheduler:{inst.pk}"
        self.title = f"QScheduler {inst.name}"
        self._container_hosts = None
        self._container_error = None

    def _load_container_hosts(self):
        if self._container_hosts is None and self._container_error is None:
            from . import qscheduler_core as core
            target = None
            try:
                target = core.target_for(self.inst)
                info = target.docker.inspect(self.inst.container_name)
                if not info:
                    raise RuntimeError(f"container '{self.inst.container_name}' not found{target.docker.where}")
                self._container_hosts = extra_hosts_as_list((info.get("HostConfig") or {}).get("ExtraHosts") or [])
            except Exception as e:
                self._container_error = str(e).splitlines()[0] if str(e) else e.__class__.__name__
            finally:
                if target:
                    target.close()
        return self._container_hosts

    def state(self):
        """(fixed, custom): fixed = protected entries of the container, custom = stored on the record."""
        container = self._load_container_hosts()
        fixed = [h for h in (container or []) if is_protected_extra_host(h[0])]
        if self.inst.extra_hosts is None:
            if container is None:
                raise RuntimeError(f"Cannot read the extra hosts of the QScheduler container: {self._container_error}")
            custom = [h for h in container if not is_protected_extra_host(h[0])]
        else:
            custom = [h for h in extra_hosts_as_list(self.inst.extra_hosts) if not is_protected_extra_host(h[0])]
        return fixed, custom

    def save(self, custom):
        self.inst.extra_hosts = [format_extra_host(h, ip) for h, ip in custom]
        self.inst.save(update_fields=["extra_hosts", "updated_at"])

    def describe(self):
        section = {
            'key': self.key, 'kind': self.kind, 'title': self.title, 'name': self.inst.container_name,
            'storage': "QScheduler instance record",
            'apply_note': (f"Recreates the QScheduler container '{self.inst.container_name}' (short downtime). "
                           f"It is shared by all HEAppE instances assigned to it."),
        }
        try:
            fixed, custom = self.state()
        except RuntimeError as e:
            section.update({'hosts': [], 'pending_apply': None, 'error': str(e)})
            return section
        container = self._container_hosts
        section['hosts'] = _rows(fixed, "container", custom)
        section['pending_apply'] = None if container is None else sorted(set(container)) != sorted(set(fixed + custom))
        if self._container_error:
            section['warning'] = f"Container state unknown: {self._container_error}"
        return section

    def apply(self):
        import uuid
        from . import qscheduler_core as core
        from .qscheduler_deploy import extra_hosts_worker
        ok, message = core.start_operation("extra hosts", extra_hosts_worker, self.inst.pk, str(uuid.uuid4())[:8])
        if not ok:
            raise RuntimeError(message)
        return None


def _rows(fixed, fixed_source, custom):
    rows = [{'hostname': h, 'ip': ip, 'entry': format_extra_host(h, ip), 'source': fixed_source, 'editable': False}
            for h, ip in fixed]
    rows += [{'hostname': h, 'ip': ip, 'entry': format_extra_host(h, ip), 'source': "custom",
              'editable': not is_protected_extra_host(h)} for h, ip in custom]
    return rows


def _qscheduler_instances(instance_name):
    from heappe_ui.models import QSchedulerInstance as Q
    return list(Q.objects.filter(assignments__heappe_instance__instance_name=instance_name,
                                 kind__in=(Q.KIND_MANAGED, Q.KIND_LOCAL, Q.KIND_SSH_HOST),
                                 archived_at__isnull=True).exclude(container_name="").distinct().order_by("name"))


def targets_for(instance_name):
    compose_dir = os.path.join(DEPLOYMENT_BASE_PATH, instance_name, "heappe-core")
    targets = []
    if os.path.exists(os.path.join(compose_dir, "docker-compose.yml")):
        targets += [ComposeTarget(instance_name, svc, title) for svc, title in COMPOSE_SERVICES]
    targets += [QSchedulerTarget(inst) for inst in _qscheduler_instances(instance_name)]
    return targets


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

def _err(message, status):
    return JsonResponse({'status': 'danger', 'message': message}, status=status)


def _describe(target):
    try:
        return target.describe()
    except Exception as e:
        return {'key': target.key, 'kind': target.kind, 'title': target.title, 'hosts': [], 'pending_apply': None,
                'error': f"Failed to read extra hosts: {e}"}


def _sections(targets, message=None, extra=None):
    payload = {'status': 'success', 'sections': [_describe(t) for t in targets]}
    if message:
        payload['message'] = message
    payload.update(extra or {})
    return JsonResponse(payload)


def _desired_hosts(target, raw):
    """
    Validate the full list of custom entries sent by the tab (JSON [{"hostname", "ip"}, ...]; rows with both
    fields empty are ignored). Returns [(host, ip)] or raises _Refused.
    """
    import json
    try:
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError
    except (TypeError, ValueError):
        raise _Refused("Invalid list of extra hosts.", 400)
    fixed, _custom = target.state()
    seen = {h.lower() for h, _ in fixed}
    hosts = []
    for i, row in enumerate(rows, 1):
        row = row if isinstance(row, dict) else {}
        hostname, ip = str(row.get('hostname') or "").strip(), str(row.get('ip') or "").strip()
        if not hostname and not ip:
            continue
        try:
            hostname, ip = validate_extra_host(hostname, ip)
        except ValueError as e:
            raise _Refused(f"Row {i}: {e}", 400)
        if is_protected_extra_host(hostname):
            raise _Refused(f"Row {i}: '{hostname}' is a default entry and cannot be added or changed.", 403)
        if hostname.lower() in seen:
            raise _Refused(f"Row {i}: hostname '{hostname}' is listed more than once.", 409)
        seen.add(hostname.lower())
        hosts.append((hostname, ip))
    return hosts


class _Refused(Exception):
    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


@login_required
def instance_extra_hosts_view(request, instance_name):
    """
    GET: extra hosts of all targets.
    POST action=apply, target=<key>, hosts=<JSON list>: save the custom entries of that target and recreate its
    container. Default entries (docker-compose.yml, host.docker.internal) are never changed.
    """
    targets = targets_for(instance_name)
    if not targets:
        return _err(f"No docker compose project or QScheduler found for instance: {instance_name}", 404)

    if request.method == "GET":
        return _sections(targets)
    if request.method != "POST":
        return _err("Method not allowed.", 405)

    if request.POST.get('action') != 'apply':
        return _err(f"Invalid action: {request.POST.get('action')}", 400)
    target = next((t for t in targets if t.key == request.POST.get('target')), None)
    if not target:
        return _err("Unknown target. Reload the page and try again.", 404)

    with _LOCK:
        try:
            if 'hosts' in request.POST:
                target.save(_desired_hosts(target, request.POST.get('hosts')))
        except _Refused as e:
            return _err(str(e), e.status)
        except Exception as e:
            return _err(f"Failed to save extra hosts: {e}", 500)

    try:
        message = target.apply()
    except RuntimeError as e:
        return _err(f"Extra hosts were saved but not applied: {e}", 409 if target.kind == "qscheduler" else 500)
    if message is None:
        return JsonResponse({'status': 'started', 'target': target.key,
                             'message': f"Applying extra hosts to {target.title}..."})
    return _sections(targets_for(instance_name), message)
