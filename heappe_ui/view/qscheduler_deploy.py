"""
QScheduler page: QScheduler instances and their HEAppE assignments.

Instances
  * Deploy    - build the image from git (branch / tag) or use an image present on the Docker host, start a
                private PostgreSQL (or use an existing DB) and `qscheduler serve` (with a generated ADMIN_TOKEN for the
                admin API of QScheduler >= 0.2.1). No machine is registered here:
                machines are added per HEAppE on the Clusters page.
  * Register  - an existing QScheduler: local container, remote container over SSH to its VM, or over SSH
                directly into the container.
  * Update    - rebuild from git / switch image and recreate the container (Docker-based instances). A container
                without ADMIN_TOKEN gets one, so QScheduler >= 0.2.1 is managed over its admin API.
  * Admin token - QScheduler >= 0.2.1 is managed only over its admin API, through the admin proxy (see
                qscheduler_admin); the token is stored encrypted on the record. It can be shown (to use it in another
                HEAppE Management), set by hand, or regenerated (Docker-based instances; recreates the container).
  * Undeploy / unregister - only when no HEAppE instance is assigned.

Assignments (HEAppE instance <-> QScheduler instance)
  * network: the QScheduler container joins the HEAppE API network (local Docker instances),
  * notifications (optional, HEAppE >= 6.6.0) and the callback URL. Each cluster of that HEAppE gets its own
    notifier `<identifier>.<machine> --url <TaskCallback> --token <t>` when it is created on the Clusters page;
    the token is set as QSchedulerNotifyToken and always kept in HEAppE Vault.
"""
import json
import re
import secrets
import uuid

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from heappe_ui.models import InstanceCredentials, QSchedulerAssignment, QSchedulerInstance as Q

from . import qscheduler_core as core
from .qscheduler_core import (DockerCli, DockerTarget, ContainerShellTarget, SshSession,
                              DEFAULT_QSCHEDULER_REPO, DEFAULT_QSCHEDULER_REF, DEFAULT_QSCHEDULER_IMAGE,
                              DEFAULT_POSTGRES_IMAGE, DEFAULT_PORT, DEFAULT_RESTART_COMMAND,
                              LABEL_INSTANCE, LABEL_REPO, LABEL_BRANCH, IMAGE_BUILD_TIMEOUT,
                              NAME_RE, HOST_RE, GIT_REF_RE, IMAGE_RE)
from . import qscheduler_admin as qadmin
from . import qscheduler_shared_db as shared_db
from . import qscheduler_network as qnet
from .extra_hosts import extra_hosts_as_list, format_extra_host, qscheduler_container_extra_hosts

DOCKER_KINDS = (Q.KIND_MANAGED, Q.KIND_LOCAL, Q.KIND_SSH_HOST)
NAME_PREFIX_MAX = 54          # + "-<8 hex>" = 63, the maximum instance name
ARCHIVED_MESSAGE = "QScheduler instance '{name}' is archived: restore it or delete it with its clusters."
LOCAL_KINDS = (Q.KIND_MANAGED, Q.KIND_LOCAL)
ADMIN_TOKEN_RE = re.compile(r"^[!-~]{8,512}$")


# ---------------------------------------------------------------------------
# Request parsing (pure, unit-tested)
# ---------------------------------------------------------------------------

class _Reader:
    def __init__(self, data):
        self.data = data or {}
        self.errors = []

    def s(self, key, default=""):
        val = self.data.get(key)
        return default if val is None or str(val).strip() == "" else str(val).strip()

    def b(self, key, default=False):
        val = self.data.get(key)
        if val is None or val == "":
            return default
        return val if isinstance(val, bool) else str(val).strip().lower() in ("1", "true", "on", "yes")

    def port(self, key, default, label):
        raw = self.s(key)
        if raw == "":
            return default
        try:
            val = int(raw)
            if not 1 <= val <= 65535:
                raise ValueError
            return val
        except ValueError:
            self.errors.append(f"{label} must be a port number (1-65535).")
            return default


def _network_prefix(r):
    """Size of the database network to create (/24 ... /29); default from QSCHEDULER_NETWORK_PREFIX (29)."""
    raw = r.s('network_prefix').lstrip("/")
    default = core.network_pool()[1]
    if not raw:
        return default
    if not raw.isdigit() or int(raw) not in core.NETWORK_PREFIX_CHOICES:
        r.errors.append(f"Network size must be one of {', '.join('/' + str(p) for p in core.NETWORK_PREFIX_CHOICES)}.")
        return default
    return int(raw)


def _qs_network_options(r, opts, inst=None):
    """QScheduler network subnet (empty: proposed automatically), its size and the aliases of the instance."""
    try:
        subnet = qnet.parse_subnet(r.s('qs_subnet'))
        opts['qs_subnet'] = str(subnet) if subnet else ""
        opts['qs_prefix'] = subnet.prefixlen if subnet else qnet.parse_prefix(r.s('qs_prefix'))
    except ValueError as e:
        r.errors.append(str(e))
        opts['qs_subnet'], opts['qs_prefix'] = "", qnet.DEFAULT_PREFIX
    raw = r.data.get('aliases')
    opts['aliases'], errors = qnet.parse_aliases(raw if raw is not None else "", inst)
    r.errors += errors


def _validate_source(r, opts):
    if opts['source'] not in ('git', 'image'):
        r.errors.append("Image source must be 'git' or 'image'.")
    if opts['source'] == 'git':
        if not re.match(r"^(https?://|git@|ssh://)", opts['repo']):
            r.errors.append("Git repository must be an http(s):// or ssh git URL.")
        if not GIT_REF_RE.match(opts['ref']):
            r.errors.append("Branch / tag contains invalid characters.")
    if not IMAGE_RE.match(opts['image']):
        r.errors.append("Image name is invalid.")


def parse_deploy_options(data: dict, uid: str) -> tuple:
    r = _Reader(data)
    # The name entered is a prefix: a random suffix "-<uid>" is always appended (unique names, also of the database
    # container, network and volume derived from it). Empty -> "qscheduler-<uid>".
    base = r.s('name', 'qscheduler').rstrip("-_.")
    opts = {
        'name_prefix': base,
        'name': f"{base}-{uid}",
        'port': r.port('port', DEFAULT_PORT, "Service port"),
        'host_port': r.port('host_port', None, "Host port"),
        'source': r.s('source', 'git').lower(),
        'repo': r.s('repo', DEFAULT_QSCHEDULER_REPO),
        'ref': r.s('ref', DEFAULT_QSCHEDULER_REF),
        'image': r.s('image', DEFAULT_QSCHEDULER_IMAGE),
        'rebuild_image': r.b('rebuild_image'),
        'no_cache': r.b('no_cache'),
        'db_mode': r.s('db_mode', 'new').lower(),
        'database_url': r.s('database_url'),
        'db_network': r.s('db_network'),
        'network_prefix': _network_prefix(r),
        'assign_heappe_id': r.s('assign_heappe_id'),
        'assign_notifications': r.b('assign_notifications', True),
    }
    if not NAME_RE.match(base) or len(base) > NAME_PREFIX_MAX:
        r.errors.append(f"Name may contain only letters, digits, '_', '.', '-' and must start with a letter or digit "
                        f"(max {NAME_PREFIX_MAX} chars; '-<random id>' is appended).")
    _validate_source(r, opts)
    if opts['db_mode'] not in ('new', 'shared', 'existing'):
        r.errors.append("Database mode must be 'new' (dedicated container), 'shared' or 'existing'.")
    if opts['db_mode'] == 'existing' and not opts['database_url'].startswith(("postgres://", "postgresql://")):
        r.errors.append("Existing database requires a postgres:// DATABASE_URL.")
    if opts['db_network'] and not NAME_RE.match(opts['db_network']):
        r.errors.append("DB network name is invalid.")
    if opts['assign_heappe_id'] and not opts['assign_heappe_id'].isdigit():
        r.errors.append("Invalid HEAppE instance.")
    _qs_network_options(r, opts)
    return opts, r.errors


def parse_register_options(data: dict) -> tuple:
    r = _Reader(data)
    opts = {
        'name': r.s('name'),
        'kind': r.s('kind', Q.KIND_LOCAL),
        'container_name': r.s('container_name'),
        'service_host': r.s('service_host'),
        'port': r.port('port', None, "Service port"),
        'ssh_host': r.s('ssh_host'),
        'ssh_port': r.port('ssh_port', 22, "SSH port"),
        'ssh_user': r.s('ssh_user'),
        'ssh_private_key': (r.data.get('ssh_private_key') or "").strip(),
        'ssh_key_passphrase': r.data.get('ssh_key_passphrase') or "",
        'docker_command': r.s('docker_command', 'docker'),
        'database_url': r.s('database_url'),
        'restart_command': r.s('restart_command', DEFAULT_RESTART_COMMAND if r.data.get('restart_command') is None else ""),
        'admin_token': (r.data.get('admin_token') or "").strip(),
    }
    if opts['kind'] not in (Q.KIND_LOCAL, Q.KIND_SSH_HOST, Q.KIND_SSH_CONTAINER):
        r.errors.append("Choose how the existing QScheduler is reached.")
    if opts['kind'] in (Q.KIND_LOCAL, Q.KIND_SSH_HOST) and not NAME_RE.match(opts['container_name']):
        r.errors.append("Container name is required (letters, digits, '_', '.', '-').")
    if not opts['name']:
        opts['name'] = opts['container_name'] or (opts['ssh_host'].replace(":", "-") if opts['ssh_host'] else "")
    if not NAME_RE.match(opts['name'] or ""):
        r.errors.append("Name may contain only letters, digits, '_', '.', '-' (max 63 chars).")
    if opts['kind'] in (Q.KIND_SSH_HOST, Q.KIND_SSH_CONTAINER):
        if not HOST_RE.match(opts['ssh_host']):
            r.errors.append("SSH host is required.")
        if not opts['ssh_user'] or not re.match(r"^[A-Za-z0-9._-]{1,64}$", opts['ssh_user']):
            r.errors.append("SSH user is required.")
        if "PRIVATE KEY" not in opts['ssh_private_key']:
            r.errors.append("Paste the SSH private key (OpenSSH or PEM format).")
        if not opts['service_host']:
            opts['service_host'] = opts['ssh_host']
        if opts['kind'] == Q.KIND_SSH_HOST and not re.match(r"^(sudo( -n)? )?docker$", opts['docker_command']):
            r.errors.append("Docker command must be 'docker' or 'sudo docker'.")
        if opts['database_url'] and not opts['database_url'].startswith(("postgres://", "postgresql://")):
            r.errors.append("DATABASE_URL must start with postgres://.")
        if opts['kind'] == Q.KIND_SSH_HOST:
            opts.update({'database_url': "", 'restart_command': ""})
    else:
        opts.update({'ssh_host': "", 'ssh_user': "", 'ssh_private_key': "", 'ssh_key_passphrase': "",
                     'database_url': "", 'restart_command': ""})
        if not opts['service_host']:
            opts['service_host'] = opts['container_name']
    if opts['service_host'] and not HOST_RE.match(opts['service_host']):
        r.errors.append("Service host (as seen from HEAppE) is invalid.")
    if opts['admin_token'] and not ADMIN_TOKEN_RE.match(opts['admin_token']):
        r.errors.append("Admin token must be 8-512 printable characters without spaces.")
    return opts, r.errors


def parse_update_options(data: dict) -> tuple:
    r = _Reader(data)
    opts = {'source': r.s('source', 'git').lower(), 'repo': r.s('repo', DEFAULT_QSCHEDULER_REPO),
            'ref': r.s('ref', DEFAULT_QSCHEDULER_REF), 'image': r.s('image', DEFAULT_QSCHEDULER_IMAGE),
            'no_cache': r.b('no_cache')}
    _validate_source(r, opts)
    return opts, r.errors


def parse_assignment_options(data: dict) -> tuple:
    r = _Reader(data)
    opts = {
        'heappe_instance_id': r.s('heappe_instance_id'),
        'notifications_enabled': r.b('notifications_enabled'),
        'callback_url': r.s('callback_url'),
        'rotate_tokens': r.b('rotate_tokens'),
    }
    if not opts['heappe_instance_id'].isdigit():
        r.errors.append("Select the HEAppE instance.")
    if opts['callback_url'] and not opts['callback_url'].startswith(("http://", "https://")):
        r.errors.append("Callback URL must start with http:// or https://.")
    return opts, r.errors


# ---------------------------------------------------------------------------
# Docker helpers for deployed containers
# ---------------------------------------------------------------------------

def _network_is_internal(net, docker=None):
    return (docker or DockerCli()).network_is_internal(net)


def recreate_args_from_inspect(info, image, extra_labels=None, docker=None, extra_hosts=None, extra_env=None):
    """
    Rebuilds `docker create` arguments for a QScheduler service container from `docker inspect`
    output: env, labels, restart policy, published ports, extra hosts, command; adds the Docker healthcheck.
    extra_hosts: list of "host:ip" replacing the container's extra hosts (None keeps them).
    extra_env: {name: value} added to / replacing the container's environment.
    Returns (create_args, [(network, [aliases], static ip or "")...], port); the first network is used at create
    time. Static addresses (e.g. on the QScheduler network) and aliases are kept.
    """
    cfg = info.get("Config", {}) or {}
    host = info.get("HostConfig", {}) or {}
    name = info.get("Name", "").lstrip("/")
    cmd = cfg.get("Cmd") or ["serve", "--port", str(DEFAULT_PORT)]
    port = core.parse_serve_port(cmd)
    labels = dict(cfg.get("Labels") or {})
    labels.update(extra_labels or {})
    args = ["create", "--name", name]
    policy = (host.get("RestartPolicy") or {}).get("Name") or "unless-stopped"
    if policy != "no":
        args += ["--restart", policy]
    extra_env = extra_env or {}
    for e in cfg.get("Env") or []:
        if not e.startswith("PATH=") and e.split("=", 1)[0] not in extra_env:
            args += ["-e", e]
    for k, v in extra_env.items():
        args += ["-e", f"{k}={v}"]
    for k, v in sorted(labels.items()):
        args += ["--label", f"{k}={v}"]
    for cport, binds in sorted((host.get("PortBindings") or {}).items()):
        for bnd in binds or []:
            hip, hport = bnd.get("HostIp") or "", bnd.get("HostPort") or ""
            args += ["-p", f"{hip + ':' if hip else ''}{hport}:{cport.split('/')[0]}"]
    hosts = extra_hosts if extra_hosts is not None else host.get("ExtraHosts")
    for h, ip in extra_hosts_as_list(hosts):
        args += ["--add-host", format_extra_host(h, ip)]
    networks = []
    short_id = info.get("Id", "")[:12]
    for net, ncfg in (info.get("NetworkSettings", {}).get("Networks") or {}).items():
        aliases = [a for a in ((ncfg or {}).get("Aliases") or []) if a not in (short_id, info.get("Id"))]
        if net not in ("bridge", "host", "none") and name not in aliases:
            aliases.append(name)
        ip = ((ncfg or {}).get("IPAMConfig") or {}).get("IPv4Address") or ""
        networks.append((net, aliases if net not in ("bridge", "host", "none") else [], ip))
    # egress-capable network first (internal DB networks after), as at deploy time
    networks.sort(key=lambda n: _network_is_internal(n[0], docker) if n[0] not in ("bridge", "host", "none") else False)
    if networks:
        args += ["--network", networks[0][0]]
        for a in networks[0][1]:
            args += ["--network-alias", a]
        if networks[0][2]:
            args += ["--ip", networks[0][2]]
    args += core.qscheduler_healthcheck_args(port)
    args += [image] + list(cmd)
    return args, networks, port


def list_local_images():
    res = DockerCli().run(["images", "--format", "{{.Repository}}:{{.Tag}}"], check=False, quiet=True)
    imgs = [l.strip() for l in res.stdout.splitlines() if l.strip() and "<none>" not in l]
    imgs.sort(key=lambda i: ("qscheduler" not in i.lower(), i))
    return imgs


def list_local_qscheduler_containers():
    """Containers on the local Docker host that look like a QScheduler service (image or command)."""
    res = DockerCli().run(["ps", "-a", "--no-trunc", "--format", "{{.Names}}\t{{.Image}}\t{{.Command}}\t{{.Status}}"],
                          check=False, quiet=True)
    known = set(Q.objects.exclude(container_name="").filter(kind__in=LOCAL_KINDS).values_list("container_name", flat=True))
    out = []
    for line in res.stdout.splitlines():
        name, image, command, status = (line.split("\t") + ["", "", "", ""])[:4]
        if ("qscheduler" in image.lower() or "qscheduler" in command) and "serve" in command:
            out.append({'name': name, 'image': image, 'status': status, 'registered': name in known})
    return out


def import_legacy_instances():
    """Containers deployed by earlier versions of this page (label service=qscheduler) become managed instances."""
    docker = DockerCli()
    try:
        res = docker.run(["ps", "-a", "--filter", "label=com.docker.compose.service=qscheduler",
                          "--format", '{{.Names}}\t{{.Label "com.docker.compose.project"}}'], check=False, quiet=True,
                         timeout=20)
    except Exception:
        return
    for line in res.stdout.splitlines():
        name, project = (line.split("\t") + [""])[:2]
        if not name or Q.objects.filter(container_name=name, kind__in=LOCAL_KINDS).exists() or Q.objects.filter(name=name).exists():
            continue
        info = docker.inspect(name) or {}
        cfg = info.get("Config", {}) or {}
        labels = cfg.get("Labels") or {}
        inst = Q.objects.create(name=name, kind=Q.KIND_MANAGED, container_name=name, service_host=name,
                                port=core.parse_serve_port(cfg.get("Cmd") or []), source="git",
                                repo=labels.get(LABEL_REPO) or DEFAULT_QSCHEDULER_REPO,
                                ref=labels.get(LABEL_BRANCH) or DEFAULT_QSCHEDULER_REF,
                                image=cfg.get("Image") or DEFAULT_QSCHEDULER_IMAGE)
        # It was deployed for the HEAppE instance named in its compose project label: keep that HEAppE assigned
        # (notifications off: the old per-machine callbacks are gone in the notifier release of QScheduler).
        cred = InstanceCredentials.objects.filter(instance_name__iexact=project).first() if project else None
        if cred:
            nets = [n for n in docker.networks_of(name) if n not in ("bridge", "host", "none") and not n.endswith("_db_net")]
            QSchedulerAssignment.objects.create(qscheduler=inst, heappe_instance=cred, network=nets[0] if nets else "")


# ---------------------------------------------------------------------------
# Workers (run in the background through core.start_operation)
# ---------------------------------------------------------------------------

def build_args(image, repo, ref, no_cache=False):
    """docker build of a git ref; no_cache: clean rebuild (no layer cache, newer base images pulled)."""
    return ["build"] + (["--no-cache", "--pull"] if no_cache else []) + ["-t", image, f"{repo}#{ref}"]


def _build_or_check_image(docker, source, repo, ref, image, rebuild, log, no_cache=False):
    if source == 'git':
        if rebuild or no_cache or not docker.exists("image", image):
            log(f"Building image '{image}' from {repo}#{ref}{docker.where}"
                f"{' from scratch (no build cache, pulling base images)' if no_cache else ''} "
                f"(Rust release build, can take several minutes)...")
            docker.run(build_args(image, repo, ref, no_cache), log, timeout=IMAGE_BUILD_TIMEOUT)
            log("Image built successfully.")
        else:
            log(f"Reusing existing image '{image}' (tick 'Rebuild image' to force a fresh build).")
    elif not docker.exists("image", image):
        raise RuntimeError(f"Image '{image}' is not available on the Docker host{docker.where}.")


def deploy_service(docker, opts, log):
    """
    Build/check the image, create the database - db_mode 'new': dedicated PostgreSQL container; 'shared': role and
    schema in the shared database; 'existing': database_url + optional db_network - and start the QScheduler service
    container. On failure the created resources are listed for cleanup.
    QScheduler network "<name>_qs_net": subnet opts['qs_subnet'] or the first free one of size opts['qs_prefix']; an
    existing network of that name (left by a removed instance of the same name) is reused. QScheduler gets the static
    address .2 there and the aliases opts['aliases'].
    Returns {'database_url', 'version', 'admin_token', 'db_kind', 'db_schema', 'shared_database', 'qs_network',
    'qs_subnet', 'qs_ip'}.
    """
    name = opts['name']
    pg_name, db_net, volume = f"{name}-pgsql", f"{name}_db_net", f"{name}-pgdata"
    qs_net = qnet.network_name(name)
    created = []
    try:
        _build_or_check_image(docker, opts['source'], opts['repo'], opts['ref'], opts['image'], opts['rebuild_image'], log,
                              no_cache=opts.get('no_cache', False))

        lay = qnet.existing_layout(docker, qs_net)
        if lay:
            log(f"Reusing existing QScheduler network '{qs_net}' (subnet {lay['subnet']}, QScheduler at {lay['ip']}).")
        else:
            subnet = opts.get('qs_subnet') or qnet.propose(docker, opts.get('qs_prefix') or qnet.DEFAULT_PREFIX)['subnet']
            lay = qnet.create(docker, qs_net, subnet, name, log)
            created.append(("network", qs_net))

        if opts['db_mode'] == 'new':
            db_password = secrets.token_hex(16)
            core.create_internal_network(docker, db_net, {LABEL_INSTANCE: name}, log, prefix=opts.get('network_prefix'))
            created.append(("network", db_net))
            docker.run(["volume", "create", "--label", f"{LABEL_INSTANCE}={name}", volume], log)
            created.append(("volume", volume))
            docker.run(postgres_run_args(name, db_password), log)
            created.append(("container", pg_name))
            _wait_for_postgres(docker, pg_name, log)
            database_url = f"postgres://qscheduler:{db_password}@{pg_name}:5432/qscheduler"
            db_networks = [db_net]
            db_kind, db_schema, shared = Q.DB_DEDICATED, "", None
        elif opts['db_mode'] == 'shared':
            shared = shared_db.require_running(docker)
            core.create_internal_network(docker, db_net, {LABEL_INSTANCE: name}, log, prefix=opts.get('network_prefix'))
            created.append(("network", db_net))
            db_schema, db_password = shared_db.create_instance_schema(docker, shared, name, log)
            created.append(("schema", db_schema))
            shared_db.connect_network(docker, shared, db_net, log)
            created.append(("shared_link", db_net))
            database_url = f"postgres://{db_schema}:{db_password}@{shared.name}:5432/{shared.database}"
            db_networks = [db_net]
            db_kind = Q.DB_SHARED
        else:
            db_kind, db_schema, shared = opts.get('reuse_kind') or Q.DB_EXTERNAL, opts.get('reuse_schema') or "", None
            if db_kind == Q.DB_SHARED:
                shared = shared_db.shared_database()
            database_url = opts['database_url']
            db_networks = [opts['db_network']] if opts['db_network'] else []
            log(f"Using existing database{(' on network ' + opts['db_network']) if opts['db_network'] else ''}.")

        admin_token = core.new_admin_token()
        # Default bridge first (egress, e.g. to IQM); HEAppE networks are joined per assignment.
        run_cmd = ["create", "--name", name, "--restart", "unless-stopped",
                   "--label", f"com.docker.compose.project={name}",
                   "--label", "com.docker.compose.service=qscheduler",
                   "--label", f"{LABEL_INSTANCE}={name}",
                   "--label", f"{LABEL_REPO}={opts['repo'] if opts['source'] == 'git' else ''}",
                   "--label", f"{LABEL_BRANCH}={opts['ref'] if opts['source'] == 'git' else ''}",
                   "-e", f"DATABASE_URL={database_url}",
                   # admin API (QScheduler >= 0.2.1); older versions ignore it
                   "-e", f"ADMIN_TOKEN={admin_token}", "--network", "bridge"]
        if opts['host_port']:
            run_cmd += ["-p", f"127.0.0.1:{opts['host_port']}:{opts['port']}"]
        for h, ip in extra_hosts_as_list(opts.get('extra_hosts')):
            run_cmd += ["--add-host", format_extra_host(h, ip)]
        run_cmd += core.qscheduler_healthcheck_args(opts['port'])
        run_cmd += [opts['image'], "serve", "--port", str(opts['port'])]
        docker.run(run_cmd, log)
        created.append(("container", name))
        for net in db_networks:
            docker.run(["network", "connect", "--alias", name, net, name], log)
        aliases = [a for a in opts.get('aliases') or [] if a != name]
        qnet.connect_qscheduler(docker, qs_net, name, lay['ip'], aliases, log)
        if aliases:
            log(f"Aliases on '{qs_net}': {', '.join(aliases)}.")
        docker.run(["start", name], log)
        target = DockerTarget(docker, name, opts['port'])
        target.wait_healthy(log)
        return {'database_url': database_url, 'version': target.version(), 'admin_token': admin_token,
                'db_kind': db_kind, 'db_schema': db_schema, 'shared_database': shared,
                'qs_network': qs_net, 'qs_subnet': lay['subnet'], 'qs_ip': lay['ip']}
    except Exception:
        if created:
            order = {'container': 0, 'shared_link': 1, 'schema': 2, 'volume': 3, 'network': 4}

            def cleanup_cmd(kind, n):
                if kind == 'container':
                    return f"docker rm -f {n}"
                if kind == 'shared_link':
                    return f"docker network disconnect {n} {shared_db.SHARED_NAME}"
                if kind == 'schema':
                    return (f"docker exec {shared_db.SHARED_NAME} psql -U postgres -d {shared_db.SHARED_DATABASE} "
                            f"-c 'DROP SCHEMA {n} CASCADE; DROP OWNED BY {n}; DROP ROLE {n};'")
                return f"docker {kind} rm {n}"
            cmds = "".join(f"  {cleanup_cmd(k, n)}\n" for k, n in sorted(created, key=lambda x: order.get(x[0], 9)))
            log("Resources created before the failure (left in place for inspection). To remove them:\n" + cmds)
        raise


def postgres_run_args(name, db_password):
    """docker run arguments of the PostgreSQL container of a managed instance (volume <name>-pgdata)."""
    pg_name, db_net, volume = f"{name}-pgsql", f"{name}_db_net", f"{name}-pgdata"
    return ["run", "-d", "--name", pg_name, "--restart", "unless-stopped",
            "--network", db_net, "--network-alias", pg_name, "--shm-size", "128m",
            "--label", f"com.docker.compose.project={name}",
            "--label", "com.docker.compose.service=qscheduler-db",
            "--label", f"{LABEL_INSTANCE}={name}",
            "-e", "POSTGRES_USER=qscheduler", "-e", f"POSTGRES_PASSWORD={db_password}",
            "-e", "POSTGRES_DB=qscheduler", "-v", f"{volume}:/var/lib/postgresql/data",
            DEFAULT_POSTGRES_IMAGE]


def deploy_worker(log, result, opts):
    docker = DockerCli()
    name = opts['name']
    result.update({'name': name, 'port': opts['port']})
    log(f"=== QSCHEDULER: DEPLOY INSTANCE '{name}' ({opts['source']}: "
        f"{opts['repo'] + '#' + opts['ref'] if opts['source'] == 'git' else opts['image']}) ===")
    info = deploy_service(docker, opts, log)
    result['version'] = info['version']
    result.update({k: info.get(k) for k in ('qs_network', 'qs_subnet', 'qs_ip')})

    # database_url is kept so that a restore can reuse the database after the container was removed manually
    inst = Q.objects.create(name=name, kind=Q.KIND_MANAGED, container_name=name, service_host=name, port=opts['port'],
                            source=opts['source'], repo=opts['repo'] if opts['source'] == 'git' else "",
                            ref=opts['ref'] if opts['source'] == 'git' else "", image=opts['image'],
                            database_url=info['database_url'], db_kind=info.get('db_kind') or Q.DB_EXTERNAL,
                            db_schema=info.get('db_schema') or "", shared_database=info.get('shared_database'),
                            qs_network=info.get('qs_network') or "", qs_subnet=info.get('qs_subnet') or "",
                            qs_ip=info.get('qs_ip') or "", aliases=opts.get('aliases') or [])
    inst.admin_token = info.get('admin_token', "")
    inst.save(update_fields=["admin_token_encrypted", "updated_at"])
    result['id'] = inst.id
    log(f"SUCCESS: QScheduler instance '{name}' is running ({result.get('version') or 'version unknown'}).")
    if opts['assign_heappe_id']:
        assign_worker(log, result, inst.id, {'heappe_instance_id': opts['assign_heappe_id'],
                                             'notifications_enabled': opts['assign_notifications'],
                                             'callback_url': "", 'rotate_tokens': False})


def _wait_for_postgres(docker, container, log, timeout=60):
    import time
    log(f"Waiting for PostgreSQL in '{container}' to accept connections (timeout {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        if docker.run(["exec", container, "pg_isready", "-U", "qscheduler", "-h", "127.0.0.1"],
                      check=False, quiet=True).returncode == 0:
            log("PostgreSQL is ready.")
            return
        time.sleep(1)
    raise RuntimeError(f"PostgreSQL container '{container}' did not become ready within {timeout}s.")


def register_worker(log, result, opts):
    kind = opts['kind']
    log(f"=== QSCHEDULER: REGISTER EXISTING INSTANCE '{opts['name']}' ({dict(Q.KIND_CHOICES)[kind]}) ===")
    ssh = None
    port = opts['port']
    if kind == Q.KIND_SSH_CONTAINER:
        ssh = SshSession(opts['ssh_host'], opts['ssh_port'], opts['ssh_user'], opts['ssh_private_key'],
                         opts['ssh_key_passphrase']).connect()
        log(f"SSH connection to {opts['ssh_user']}@{opts['ssh_host']}:{opts['ssh_port']} OK (host key {ssh.host_key.split()[0]} pinned).")
        port = port or DEFAULT_PORT
        target = ContainerShellTarget(ssh, port, opts['database_url'], opts['restart_command'])
        res = ssh.run("qscheduler --version", timeout=30)
        if res.returncode != 0:
            raise RuntimeError(f"'qscheduler' is not available in the container: {res.output[-300:]}")
        log(f"Found {res.stdout.strip()}.")
    else:
        if kind == Q.KIND_SSH_HOST:
            ssh = SshSession(opts['ssh_host'], opts['ssh_port'], opts['ssh_user'], opts['ssh_private_key'],
                             opts['ssh_key_passphrase']).connect()
            log(f"SSH connection to {opts['ssh_user']}@{opts['ssh_host']}:{opts['ssh_port']} OK (host key {ssh.host_key.split()[0]} pinned).")
        docker = DockerCli(ssh, opts['docker_command'])
        info = docker.inspect(opts['container_name'])
        if not info:
            raise RuntimeError(f"Container '{opts['container_name']}' not found{docker.where}.")
        cmd = (info.get("Config", {}).get("Entrypoint") or []) + (info.get("Config", {}).get("Cmd") or [])
        if "serve" not in cmd:
            raise RuntimeError(f"Container '{opts['container_name']}' does not run 'qscheduler serve'.")
        port = port or core.parse_serve_port(info.get("Config", {}).get("Cmd") or [])
        target = DockerTarget(docker, opts['container_name'], port)
    try:
        if target.health() != 200:
            raise RuntimeError(f"QScheduler does not answer GET /health with 200 on port {port}.")
        version = target.version()
        if core.supports_admin_api(version):
            # Admin API only, through the admin proxy that is created with the first HEAppE assignment.
            log(f"QScheduler {version} healthy; machines and notifiers are managed over its admin API "
                f"(admin proxy, created when a HEAppE instance is assigned).")
        else:
            notifiers = target.list_notifiers(log)
            log(f"QScheduler {version or '(version unknown)'} healthy; {len(notifiers)} notifier(s) registered.")
    finally:
        target.close()

    image = ""
    if kind != Q.KIND_SSH_CONTAINER:
        image = (info.get("Config", {}) or {}).get("Image") or ""
    inst = Q.objects.create(
        name=opts['name'], kind=kind, container_name=opts['container_name'], service_host=opts['service_host'],
        port=port, ssh_host=opts['ssh_host'], ssh_port=opts['ssh_port'], ssh_user=opts['ssh_user'],
        ssh_private_key=opts['ssh_private_key'], ssh_key_passphrase=opts['ssh_key_passphrase'],
        ssh_host_key=ssh.host_key if ssh else "", docker_command=opts['docker_command'],
        database_url=opts['database_url'], restart_command=opts['restart_command'],
        source="external", image=image)
    token = opts['admin_token'] or (qadmin.container_admin_token(info) if kind != Q.KIND_SSH_CONTAINER else "")
    if token:
        inst.admin_token = token
        inst.save(update_fields=["admin_token_encrypted", "updated_at"])
        log("Admin token stored (" + ("entered" if opts['admin_token'] else "taken over from the container environment") + ").")
    elif core.supports_admin_api(version):
        log("WARNING: no admin token known for this QScheduler: set it with 'Admin token...' before adding machines.")
    result.update({'id': inst.id, 'name': inst.name, 'version': version})
    log(f"SUCCESS: QScheduler instance '{inst.name}' registered (HEAppE reaches it at {inst.service_host}:{inst.port}).")


def update_worker(log, result, inst_id, opts, uid):
    inst = Q.objects.get(pk=inst_id)
    if inst.kind not in DOCKER_KINDS:
        raise RuntimeError("Update is available only for Docker-based instances (local or SSH to the VM).")
    target = core.target_for(inst)
    docker = target.docker
    name = inst.container_name
    log(f"=== QSCHEDULER: UPDATE INSTANCE '{inst.name}'{docker.where} ===")
    try:
        info = docker.inspect(name)
        if not info:
            raise RuntimeError(f"Container '{name}' not found{docker.where}.")
        _build_or_check_image(docker, opts['source'], opts['repo'], opts['ref'], opts['image'], True, log,
                              no_cache=opts.get('no_cache', False))
        labels = {LABEL_INSTANCE: name}
        if opts['source'] == 'git':
            labels.update({LABEL_REPO: opts['repo'], LABEL_BRANCH: opts['ref']})
        extra_hosts = qscheduler_container_extra_hosts((info.get("HostConfig") or {}).get("ExtraHosts"), inst.extra_hosts)
        extra_env = admin_token_env(info, log)
        recreate_container(docker, target, info, opts['image'], labels, log, uid, "Update", extra_hosts, extra_env)
        token = (extra_env or {}).get("ADMIN_TOKEN") or qadmin.container_admin_token(info)
        if token and token != inst.admin_token:
            inst.admin_token = token
            log("Admin token of the container stored.")
        version = target.version()
    finally:
        target.close()
    inst.source, inst.image = opts['source'], opts['image']
    inst.repo = opts['repo'] if opts['source'] == 'git' else ""
    inst.ref = opts['ref'] if opts['source'] == 'git' else ""
    inst.restart_pending = False
    inst.save()
    result.update({'name': inst.name, 'version': version, 'image': inst.image})
    log(f"SUCCESS: '{inst.name}' updated ({version or 'version unknown'}). Machines, notifiers and projects are kept in PostgreSQL.")
    if not core.supports_admin_api(version):
        log(f"Note: QScheduler {'.'.join(map(str, core.ADMIN_API_MIN_VERSION))}+ manages machines and notifiers over "
            f"its admin API; this version uses the CLI (changes need a restart).")


def admin_token_env(info, log):
    """{'ADMIN_TOKEN': <new token>} when the container has none (enables the admin API of QScheduler >= 0.2.1)."""
    env = dict(e.split("=", 1) for e in ((info.get("Config") or {}).get("Env") or []) if "=" in e)
    if env.get("ADMIN_TOKEN"):
        return None
    log("Setting a generated ADMIN_TOKEN: QScheduler >= 0.2.1 then manages machines and notifiers over its admin API "
        "(no restarts).")
    return {"ADMIN_TOKEN": core.new_admin_token()}


def recreate_container(docker, target, info, image, labels, log, uid, what, extra_hosts=None, extra_env=None):
    """Recreate the QScheduler container from its inspect output; the previous one is restored on failure."""
    name = info.get("Name", "").lstrip("/")
    create_args, networks, _port = recreate_args_from_inspect(info, image, labels, docker, extra_hosts, extra_env)
    backup = f"{name}-old-{uid}"
    docker.run(["stop", name], log)
    docker.run(["rename", name, backup], log)
    try:
        docker.run(create_args, log)
        for net, aliases, ip in networks[1:]:
            alias_args = [arg for a in aliases for arg in ("--alias", a)] + (["--ip", ip] if ip else [])
            docker.run(["network", "connect"] + alias_args + [net, name], log)
        docker.run(["start", name], log)
        target.wait_healthy(log)
    except Exception as ex:
        log(f"{what} failed ({str(ex).splitlines()[0]}); rolling back to the previous container...")
        docker.run(["rm", "-f", name], log, check=False)
        docker.run(["rename", backup, name], log, check=False)
        docker.run(["start", name], log, check=False)
        raise RuntimeError(f"{what} failed and was rolled back: {ex}")
    docker.run(["rm", backup], log)


def extra_hosts_worker(log, result, inst_id, uid):
    """Recreate the container (same image) so that it gets the extra hosts stored on the instance record."""
    inst = Q.objects.get(pk=inst_id)
    if inst.kind not in DOCKER_KINDS:
        raise RuntimeError("Extra hosts can be applied only to Docker-based instances (local or SSH to the VM).")
    target = core.target_for(inst)
    docker = target.docker
    name = inst.container_name
    log(f"=== QSCHEDULER: APPLY EXTRA HOSTS TO '{inst.name}'{docker.where} ===")
    try:
        info = docker.inspect(name)
        if not info:
            raise RuntimeError(f"Container '{name}' not found{docker.where}.")
        current = (info.get("HostConfig") or {}).get("ExtraHosts")
        extra_hosts = qscheduler_container_extra_hosts(current, inst.extra_hosts or [])
        log(f"Extra hosts: {', '.join(extra_hosts) or '(none)'}")
        image = (info.get("Config") or {}).get("Image") or inst.image
        recreate_container(docker, target, info, image, None, log, uid, "Applying extra hosts", extra_hosts)
    finally:
        target.close()
    result.update({'name': inst.name, 'extra_hosts': extra_hosts})
    log(f"SUCCESS: extra hosts applied to '{inst.name}'.")


def regenerate_admin_token_worker(log, result, inst_id, uid):
    """New ADMIN_TOKEN: recreate the container (same image and settings) with it and store it."""
    inst = Q.objects.get(pk=inst_id)
    if inst.kind not in DOCKER_KINDS:
        raise RuntimeError("The admin token can be regenerated only for Docker-based instances; set ADMIN_TOKEN in the "
                           "service yourself and store it with 'Set token'.")
    target = core.target_for(inst)
    docker = target.docker
    name = inst.container_name
    log(f"=== QSCHEDULER: REGENERATE ADMIN TOKEN OF '{inst.name}'{docker.where} ===")
    log("Other HEAppE Management instances managing this QScheduler lose admin access until they get the new token.")
    try:
        info = docker.inspect(name)
        if not info:
            raise RuntimeError(f"Container '{name}' not found{docker.where}.")
        token = core.new_admin_token()
        image = (info.get("Config") or {}).get("Image") or inst.image
        recreate_container(docker, target, info, image, None, log, uid, "Regenerating the admin token",
                           None, {"ADMIN_TOKEN": token})
        inst.admin_token = token
        inst.save(update_fields=["admin_token_encrypted", "updated_at"])
        log("New admin token stored.")
        if qadmin.desired_networks(inst) and target.uses_admin_api(log):
            status, text = target.admin_request("GET", "/notifiers")
            if status != 200:
                raise RuntimeError(f"Admin API check failed: {core.api_error_text(status, text)}")
            log("Admin API accepts the new token.")
    finally:
        target.close()
    result['name'] = inst.name
    log(f"SUCCESS: admin token of '{inst.name}' regenerated.")


def restart_worker(log, result, inst_id):
    inst = Q.objects.get(pk=inst_id)
    target = core.target_for(inst)
    try:
        if inst.kind == Q.KIND_SSH_CONTAINER and not inst.restart_command:
            # No restart command: the operator restarted the container; confirm the service is back.
            log(f"=== QSCHEDULER: CONFIRM MANUAL RESTART OF '{inst.name}' ===")
            target.wait_healthy(log, timeout=30)
        else:
            log(f"=== QSCHEDULER: RESTART INSTANCE '{inst.name}' ===")
            target.restart(log)
    finally:
        target.close()
    inst.restart_pending = False
    inst.save(update_fields=["restart_pending", "updated_at"])
    result['name'] = inst.name
    log(f"SUCCESS: '{inst.name}' restarted.")


def undeploy_worker(log, result, inst_id, remove_data):
    inst = Q.objects.get(pk=inst_id)
    if inst.assignments.exists():
        raise RuntimeError("HEAppE instances are still assigned to this QScheduler. Unassign them first.")
    result['name'] = inst.name
    if inst.kind != Q.KIND_MANAGED:
        log(f"=== QSCHEDULER: UNREGISTER '{inst.name}' === (the QScheduler service itself is left untouched)")
        qadmin.remove_proxy(inst, log)
        if inst.kind == Q.KIND_LOCAL and inst.qs_network:
            docker = DockerCli()
            docker.run(["network", "disconnect", inst.qs_network, inst.container_name], log, check=False)
            qnet.remove(docker, inst.qs_network, log)
        inst.delete()
        log(f"SUCCESS: '{result['name']}' removed from HEAppE Management.")
        return
    docker = DockerCli()
    name = inst.container_name
    log(f"=== QSCHEDULER: UNDEPLOY INSTANCE '{name}' ===")
    pg, net, vol = f"{name}-pgsql", f"{name}_db_net", f"{name}-pgdata"
    image = ((docker.inspect(name) or {}).get("Config") or {}).get("Image")
    docker.run(["rm", "-f", name], log, check=False)
    if docker.exists("container", pg):
        docker.run(["rm", "-f", pg], log)
    if inst.db_kind == Q.DB_SHARED and inst.shared_database:
        shared_db.disconnect_network(docker, inst.shared_database, net, log)
        if remove_data:
            shared_db.drop_instance_schema(docker, inst.db_schema, log)
        else:
            log(f"Kept schema and role '{inst.db_schema}' in the shared database (drop it on the shared database card).")
    if docker.json(["network", "inspect", net]):
        res = docker.run(["network", "rm", net], log, check=False)
        if res.returncode != 0:
            log(f"WARNING: could not remove network '{net}': {res.stderr.strip()}")
    if docker.json(["volume", "inspect", vol]):
        if remove_data:
            docker.run(["volume", "rm", vol], log)
        else:
            log(f"Kept database volume '{vol}' (remove with: docker volume rm {vol}).")
    log(f"Image '{image}' kept (may be used by other instances).")
    qadmin.remove_proxy(inst, log)
    qnet.remove(docker, inst.qs_network or qnet.network_name(name), log)
    inst.delete()
    log(f"SUCCESS: QScheduler instance '{name}' undeployed.")


def assign_worker(log, result, inst_id, opts):
    """
    Create or update a HEAppE assignment: network access, notifications on/off and the callback URL.
    Notifiers belong to clusters ("<identifier>.<machine>", own token in HEAppE Vault). When the notification
    settings change, the notifiers of this HEAppE's existing clusters on the instance are recreated with new
    tokens (or removed), and the clusters are updated accordingly.
    """
    from .clusters import connect_heappe_management_api

    inst = Q.objects.get(pk=inst_id)
    cred = InstanceCredentials.objects.get(pk=int(opts['heappe_instance_id']))
    asg = QSchedulerAssignment.objects.filter(qscheduler=inst, heappe_instance=cred).first()
    log(f"=== QSCHEDULER: {'UPDATE' if asg else 'ASSIGN'} HEAppE '{cred.instance_name}' -> '{inst.name}' ===")
    version, identifier = core.heappe_identity(cred)
    log(f"HEAppE '{cred.instance_name}': version {version or 'unknown'}, instance identifier '{identifier}'.")
    if not core.supports_qscheduler(version):
        raise RuntimeError(core.unsupported_version_message(cred.instance_name, version))

    # Notifier names are "<identifier>.<machine>": identifiers must differ between HEAppEs on one QScheduler.
    same_id = QSchedulerAssignment.objects.filter(qscheduler=inst, heappe_identifier=identifier)
    if asg:
        same_id = same_id.exclude(pk=asg.pk)
    if same_id.exists():
        raise RuntimeError(f"HEAppE '{same_id.first().heappe_instance.instance_name}' with the same instance identifier "
                           f"'{identifier}' is already assigned to '{inst.name}'. Notifier names would clash; give one "
                           f"of the HEAppE instances another identifier (InstanceIdentifierPath).")

    want = bool(opts['notifications_enabled'])

    # Clusters of this HEAppE on this QScheduler (read before anything is changed)
    controller, session_code, _ = connect_heappe_management_api(cred.instance_name, log)
    clusters = core.qscheduler_clusters(controller, session_code, inst)

    target = core.target_for(inst)
    updates = []      # (cluster, notifier or None) to apply in HEAppE after QScheduler has the notifiers
    try:
        # 1. Network: the HEAppE container joins the instance's QScheduler network (local instances that have one);
        #    otherwise local instances join the HEAppE API network (instances not migrated yet)
        network = asg.network if asg else ""
        network_changed = False
        if inst.kind in LOCAL_KINDS and inst.qs_network:
            heappe_container, heappe_net = qnet.heappe_join(cred.instance_name, inst.qs_network, log), None
            network = inst.qs_network
        else:
            heappe_container, heappe_net = core.resolve_heappe_service_network(cred.instance_name, log)
        if heappe_net and inst.kind not in LOCAL_KINDS:
            network = heappe_net          # the admin proxy joins it (remote QScheduler: tunnelled into it)
        if inst.kind in LOCAL_KINDS and not inst.qs_network:
            if heappe_net:
                if heappe_net not in target.docker.networks_of(inst.container_name):
                    target.docker.run(["network", "connect", "--alias", inst.service_host, heappe_net, inst.container_name], log)
                    network_changed = True
                    log(f"'{inst.container_name}' joined HEAppE network '{heappe_net}'.")
                network = heappe_net
            else:
                log(f"WARNING: HEAppE API container of '{cred.instance_name}' not found on this Docker host; "
                    f"make sure HEAppE can reach {inst.service_host}:{inst.port}.")

        target.admin_client.extra_networks = [network] if network else []

        # 2. Callback URL (shared by all notifiers of this HEAppE)
        callback_url = opts.get('callback_url') or (asg.callback_url if asg and asg.callback_url else "")
        if want and not callback_url:
            if heappe_container and inst.kind in LOCAL_KINDS:
                callback_url = f"http://{heappe_container}:80/heappe/JobManagement/TaskCallback"
            else:
                raise RuntimeError("Enter the callback URL: the HEAppE TaskCallback endpoint as reachable from the QScheduler "
                                   "host, e.g. https://heappe.example.org/heappe/JobManagement/TaskCallback.")

        # 3. Existing clusters: recreate / remove their notifiers when the settings change
        old_on = bool(asg and asg.notifications_enabled)
        settings_changed = (want != old_on or (want and callback_url != asg.callback_url)
                            or (want and opts.get('rotate_tokens')))
        if clusters and settings_changed:
            add, remove = {}, set()
            for c in clusters:
                old_name = core.cluster_notifier(c)
                new_name = core.cluster_notifier_name(identifier, core.cluster_machine(c))
                if old_name:
                    remove.add(old_name)
                if want:
                    token = core.new_notify_token()
                    add[new_name] = (callback_url, token)
                    remove.discard(new_name)
                    updates.append((c, (new_name, token)))
                else:
                    remove.add(new_name)
                    updates.append((c, None))
            current = {n['name']: n for n in target.list_notifiers(log)}
            remove = {n for n in remove if n in current}
            if core.replace_notifiers(target, add, remove, current, log):
                core.apply_changes(inst, target, log)
        elif clusters:
            log("Notification settings unchanged; the clusters' notifiers are kept.")
        else:
            log("This HEAppE has no clusters on this QScheduler yet; notifiers are created with each cluster (Clusters page).")
    finally:
        target.close()

    if heappe_container and network_changed:
        core.restart_heappe(heappe_container, log)
    if heappe_container:
        try:
            core.check_from_heappe(heappe_container, inst.service_host, inst.port, "/health", log, attempts=5)
        except RuntimeError as e:
            log(f"WARNING: {e}")

    if asg is None:
        asg = QSchedulerAssignment(qscheduler=inst, heappe_instance=cred)
    asg.heappe_identifier = identifier
    asg.network = network
    asg.notifications_enabled = want
    asg.callback_url = callback_url
    asg.save()
    result.update({'assignment_id': asg.id, 'heappe_instance': cred.instance_name, 'notifications': want})

    # 4. Apply the new tokens / disabled callbacks to the HEAppE clusters (tokens go to Vault)
    try:
        for c, notifier in updates:
            core.update_cluster_notifications(controller, session_code, c, notifier, log)
    except Exception as e:
        raise RuntimeError(f"Assignment saved and notifiers changed, but updating the HEAppE clusters failed: {e}. "
                           f"Edit the assignment and tick 'Generate new tokens' to retry.")
    result['updated_clusters'] = [c.get('id') for c, _ in updates]
    log(f"SUCCESS: HEAppE '{cred.instance_name}' assigned to '{inst.name}' (notifications {'on' if want else 'off'}).")


def unassign_worker(log, result, asg_id, force):
    from .clusters import connect_heappe_management_api

    asg = QSchedulerAssignment.objects.select_related("qscheduler", "heappe_instance").get(pk=asg_id)
    inst, cred = asg.qscheduler, asg.heappe_instance
    log(f"=== QSCHEDULER: UNASSIGN HEAppE '{cred.instance_name}' from '{inst.name}' ===")
    try:
        controller, session_code, _ = connect_heappe_management_api(cred.instance_name, log)
        clusters = core.qscheduler_clusters(controller, session_code, inst)
    except Exception as e:
        if not force:
            raise RuntimeError(f"Cannot check the clusters of HEAppE '{cred.instance_name}' ({e}). "
                               f"Tick 'Force' to unassign anyway.")
        log(f"WARNING: could not check HEAppE clusters ({e}); continuing (force).")
        clusters = []
    if clusters:
        names = ", ".join(f"{c.get('name')} (ID {c.get('id')})" for c in clusters)
        raise RuntimeError(f"HEAppE '{cred.instance_name}' still has clusters on this QScheduler: {names}. "
                           f"Remove them first (Clusters > QScheduler > Remove quantum machine).")
    target = core.target_for(inst)
    try:
        # Leftover notifiers of this HEAppE (its clusters are gone)
        if asg.heappe_identifier:
            current = {n['name']: n for n in target.list_notifiers(log)}
            leftover = {n for n in current if n.startswith(asg.heappe_identifier + ".")}
            if leftover and core.replace_notifiers(target, {}, leftover, current, log):
                core.apply_changes(inst, target, log)
        if inst.kind in LOCAL_KINDS and inst.qs_network and asg.network == inst.qs_network:
            qnet.heappe_leave(cred.instance_name, inst.qs_network, log)
        elif inst.kind in LOCAL_KINDS and asg.network:
            shared = QSchedulerAssignment.objects.filter(qscheduler=inst, network=asg.network).exclude(pk=asg.pk).exists()
            if not shared and asg.network in target.docker.networks_of(inst.container_name):
                target.docker.run(["network", "disconnect", asg.network, inst.container_name], log, check=False)
    finally:
        target.close()
    asg.delete()
    qadmin.sync_proxy(inst, log)
    result.update({'name': inst.name, 'heappe_instance': cred.instance_name})
    log(f"SUCCESS: HEAppE '{cred.instance_name}' unassigned from '{inst.name}'.")


def managed_notifier(inst, name):
    """True when a notifier belongs to an assignment of `inst` (named "<HEAppE identifier>.<machine>")."""
    return any(name.startswith(a.heappe_identifier + ".") for a in inst.assignments.exclude(heappe_identifier=""))


def remove_notifier_worker(log, result, inst_id, name):
    """
    Remove an unmanaged notifier (e.g. a leftover of the old one-notifier-per-HEAppE scheme). Refused when it is
    managed, when a cluster of an assigned HEAppE still uses it, or when an assigned HEAppE cannot be checked.
    """
    from .clusters import connect_heappe_management_api

    inst = Q.objects.get(pk=inst_id)
    result.update({'name': inst.name, 'notifier': name})
    log(f"=== QSCHEDULER: REMOVE UNMANAGED NOTIFIER '{name}' from '{inst.name}' ===")
    if managed_notifier(inst, name):
        raise RuntimeError(f"Notifier '{name}' belongs to a cluster of an assigned HEAppE instance; it is removed with "
                           f"the cluster (Clusters > QScheduler > Remove quantum machine) or by editing the assignment.")
    # Clusters of all assigned HEAppE instances must not use it (callbacks would stop; HEAppE does not poll them)
    users = []
    for asg in inst.assignments.select_related("heappe_instance"):
        cname = asg.heappe_instance.instance_name
        try:
            controller, session_code, _ = connect_heappe_management_api(cname, log)
            clusters = core.qscheduler_clusters(controller, session_code, inst)
        except Exception as e:
            raise RuntimeError(f"Cannot check the clusters of HEAppE '{cname}' ({str(e).splitlines()[0][:200]}); the "
                               f"notifier is not removed.")
        users += [f"{cname}: {c.get('name')} (ID {c.get('id')})" for c in clusters if core.cluster_notifier(c) == name]
    if users:
        raise RuntimeError(f"Notifier '{name}' is still used by HEAppE cluster(s) {', '.join(users)}; not removed. "
                           f"Edit the assignment and tick 'Generate new tokens' to move them to their own notifiers.")
    log(f"No cluster of the {inst.assignments.count()} assigned HEAppE instance(s) uses '{name}'.")
    target = core.target_for(inst)
    try:
        current = {n['name']: n for n in target.list_notifiers(log)}
        if name not in current:
            raise RuntimeError(f"Notifier '{name}' is not registered in '{inst.name}' (already removed?).")
        core.replace_notifiers(target, {}, {name}, current, log)
        result['restarted'] = core.apply_changes(inst, target, log)
    finally:
        target.close()
    log(f"SUCCESS: notifier '{name}' removed from '{inst.name}'.")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except Exception:
        return request.POST.dict()


def _error(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


def _started(ok, message):
    return JsonResponse({'status': 'success' if ok else 'error', 'message': message}, status=200 if ok else 409)


def _post_only(view):
    def wrapper(request, *args, **kwargs):
        if request.method != "POST":
            return _error('Only POST method is allowed', 405)
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def instance_summary(inst):
    return {
        'id': inst.id, 'name': inst.name, 'kind': inst.kind, 'kind_label': inst.get_kind_display(),
        'container_name': inst.container_name, 'service_host': inst.service_host, 'port': inst.port,
        'ssh': f"{inst.ssh_user}@{inst.ssh_host}:{inst.ssh_port}" if inst.is_remote else "",
        'source': inst.source, 'repo': inst.repo, 'ref': inst.ref, 'image': inst.image,
        'restart_pending': inst.restart_pending, 'can_update': inst.kind in DOCKER_KINDS,
        'manual_restart': inst.kind == Q.KIND_SSH_CONTAINER and not inst.restart_command,
        'archived': inst.is_archived,
        'archived_at': inst.archived_at.strftime("%Y-%m-%d %H:%M UTC") if inst.archived_at else "",
        'archived_reason': inst.archived_reason,
        'admin_token_stored': bool(inst.admin_token_encrypted),
        'db_kind': inst.db_kind, 'db_kind_label': inst.get_db_kind_display(), 'db_schema': inst.db_schema,
        'can_backup': shared_db.can_backup(inst),
        'can_migrate_to_shared': inst.kind == Q.KIND_MANAGED and inst.db_kind == Q.DB_DEDICATED,
        'qs_network': inst.qs_network, 'qs_subnet': inst.qs_subnet, 'qs_ip': inst.qs_ip,
        'aliases': list(inst.aliases or []),
        'is_local': inst.kind in LOCAL_KINDS,
        'can_migrate_network': inst.kind in LOCAL_KINDS and not inst.qs_network and not inst.is_archived,
        'can_edit_aliases': not inst.is_archived and (inst.kind not in LOCAL_KINDS or bool(inst.qs_network)),
        'assignments': [{
            'id': a.id, 'heappe_instance_id': a.heappe_instance_id, 'heappe_instance': a.heappe_instance.instance_name,
            'notifications_enabled': a.notifications_enabled, 'heappe_identifier': a.heappe_identifier,
            'callback_url': a.callback_url, 'network': a.network,
            'heappe_local': qnet.heappe_override_path(a.heappe_instance.instance_name) is not None,
        } for a in inst.assignments.select_related("heappe_instance").order_by("heappe_instance__instance_name")],
    }


def _default_prefix():
    try:
        return core.network_pool()[1]
    except Exception:
        return 29


@login_required
def qscheduler_page(request: HttpRequest) -> HttpResponse:
    try:
        import_legacy_instances()
    except Exception as e:
        print(f"QScheduler legacy import skipped: {e}")
    instances = [instance_summary(i) for i in Q.objects.all()]
    return render(request, "qscheduler.html", {
        'instances': instances,
        'instances_json': json.dumps(instances),
        'heappe_instances': list(InstanceCredentials.objects.order_by("instance_name").values("id", "instance_name")),
        'defaults': {'repo': DEFAULT_QSCHEDULER_REPO, 'ref': DEFAULT_QSCHEDULER_REF, 'image': DEFAULT_QSCHEDULER_IMAGE,
                     'port': DEFAULT_PORT, 'restart_command': DEFAULT_RESTART_COMMAND,
                     'network_prefix': _default_prefix()},
        'network_prefixes': list(core.NETWORK_PREFIX_CHOICES),
        'qs_network_prefixes': list(qnet.PREFIX_CHOICES), 'qs_network_default_prefix': qnet.DEFAULT_PREFIX,
        'alias_zone': qnet.alias_zone(), 'alias_example': qnet.ALIAS_EXAMPLE,
        'chosen_instance': request.session.get("chosen_instance"),
        'shared_db_deployed': shared_db.shared_database() is not None,
        'shared_db_image': shared_db.shared_image(),
    })


@login_required
def qscheduler_local_docker_api(request: HttpRequest) -> HttpResponse:
    """Images and QScheduler-like containers on the local Docker host (for the deploy / register forms)."""
    try:
        return JsonResponse({'status': 'success', 'images': list_local_images(),
                             'containers': list_local_qscheduler_containers()})
    except Exception as e:
        return _error(f"Docker is not available on the management host: {e}", 500)


@login_required
def qscheduler_git_refs_api(request: HttpRequest) -> HttpResponse:
    """Branches and tags of a git repository (GitHub / GitLab API, else git ls-remote) for the branch / tag picker."""
    try:
        refs = core.list_git_refs(request.GET.get("repo", ""))
    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f"Branches and tags could not be loaded ({str(e)[:300]})."})
    return JsonResponse(dict(refs, status='success'))


@login_required
def qscheduler_live_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """
    Health, version, notifiers and machines of one instance (slow for SSH instances: loaded lazily), and its
    presence: 'missing' / 'unreachable' when the service is gone (e.g. removed without HEAppE Management).
    """
    try:
        inst = Q.objects.get(pk=inst_id)
    except Q.DoesNotExist:
        return _error("QScheduler instance not found.", 404)
    out = {'status': 'success', 'id': inst.id, 'health': None, 'version': None, 'notifiers': None, 'machines': None,
           'error': None, 'archived': inst.is_archived, 'presence': None, 'presence_detail': ""}
    if inst.is_archived:
        out['presence'], out['presence_detail'] = core.presence(inst)
        return JsonResponse(out)
    target = None
    try:
        target = core.target_for(inst)
        out['health'] = target.health()
        if out['health'] == 200:
            out['version'] = target.version()
        out['admin'] = {'api': core.supports_admin_api(out['version']) if out['version'] else None,
                        'token_stored': bool(inst.admin_token_encrypted), 'proxy': None}
        if out['admin']['api']:
            try:
                out['admin']['proxy'] = qadmin.proxy_status(inst)
            except Exception:
                pass
        try:
            notifiers = target.list_notifiers()
            prefixes = {a.heappe_identifier + "." for a in inst.assignments.exclude(heappe_identifier="")}
            out['notifiers'] = [dict(n, managed=any(n['name'].startswith(p) for p in prefixes)) for n in notifiers]   # see managed_notifier()
            out['machines'] = target.list_machines()
        except qadmin.AdminTokenError as e:
            out['error'] = str(e)
            out['admin_token_error'] = e.info()
        except qadmin.AdminApiUnavailable as e:
            if inst.assignments.exists():          # without an assignment there is no proxy yet: not an error
                out['error'] = str(e).splitlines()[0][:400]
        except Exception as e:
            out['error'] = str(e).splitlines()[0][:400]
    except Exception as e:
        out['error'] = str(e).splitlines()[0][:400]
    finally:
        if target:
            target.close()
    if out['health'] == 200:
        out['presence'] = core.PRESENT
    else:
        out['presence'], out['presence_detail'] = core.presence(inst)
    # The container exists but QScheduler does not answer (stopped, crashed, hanging): a restart may fix it
    # ("docker restart" also starts a stopped container; SSH into container: restart command or manual restart).
    out['restartable'] = out['health'] != 200 and out['presence'] == core.PRESENT
    return JsonResponse(out)


@login_required
@_post_only
def qscheduler_admin_token_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """
    Admin token of an instance. action 'show': return it (to use it in another HEAppE Management); 'set': store a
    token (checked against the service when the admin proxy is available); 'regenerate': new token, recreates the
    container (background operation).
    """
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    data = _json_body(request)
    action = data.get('action')
    if action == 'regenerate':
        if inst.is_archived:
            return _error(ARCHIVED_MESSAGE.format(name=inst.name))
        if inst.kind not in DOCKER_KINDS:
            return _error("The admin token can be regenerated only for Docker-based instances.")
        return _started(*core.start_operation("regenerate admin token", regenerate_admin_token_worker, inst.id,
                                              str(uuid.uuid4())[:8]))

    if action == 'show':
        target = None
        try:
            target = core.target_for(inst) if inst.kind in DOCKER_KINDS and not inst.admin_token else None
            token = qadmin.admin_token(inst, getattr(target, 'docker', None))
        except qadmin.AdminTokenError as e:
            return JsonResponse({'status': 'error', 'message': str(e), 'admin_token_error': e.info()}, status=404)
        except Exception as e:
            return _error(f"Could not read the admin token: {str(e).splitlines()[0]}", 500)
        finally:
            if target:
                target.close()
        resp = JsonResponse({'status': 'success', 'token': token})
        resp['Cache-Control'] = 'no-store'
        return resp

    if action == 'set':
        token = str(data.get('token') or "").strip()
        if not ADMIN_TOKEN_RE.match(token):
            return _error("Admin token must be 8-512 printable characters without spaces.")
        previous = inst.admin_token_encrypted
        inst.admin_token = token
        note = ""
        if inst.is_archived or not qadmin.desired_networks(inst):
            note = " Not checked: the admin proxy is created when a HEAppE instance is assigned."
        else:
            try:
                status, text = qadmin.AdminClient(inst).request("GET", "/notifiers")
                if status != 200:
                    note = f" The check returned {core.api_error_text(status, text)}."
            except qadmin.AdminTokenError as e:
                inst.admin_token_encrypted = previous
                return _error(f"Not stored: {e.MESSAGES[e.reason].format(name=inst.name)}" if e.reason != 'rejected'
                              else "Not stored: the QScheduler service rejected this token (HTTP 401).")
            except Exception as e:
                note = f" Not checked: {str(e).splitlines()[0]}"
        inst.save(update_fields=["admin_token_encrypted", "updated_at"])
        return JsonResponse({'status': 'success', 'message': f"Admin token of '{inst.name}' stored.{note}"})

    return _error(f"Invalid action: {action}")


@login_required
def qscheduler_shared_db_api(request: HttpRequest) -> HttpResponse:
    """
    GET: status of the shared database. POST action 'deploy' (image), 'update' (image, same major version),
    'remove' (remove_data), 'drop_schema' (schema not used by any instance) - background operations.
    """
    if request.method == "GET":
        try:
            return JsonResponse({'status': 'success', **shared_db.shared_status()})
        except Exception as e:
            return _error(f"Could not read the shared database status: {str(e).splitlines()[0]}", 500)
    if request.method != "POST":
        return _error('Only GET and POST are allowed', 405)
    data = _json_body(request)
    r = _Reader(data)
    action = r.s('action')
    if action in ('deploy', 'update'):
        image = r.s('image', shared_db.shared_image())
        if not IMAGE_RE.match(image):
            return _error("Image name is invalid.")
        if action == 'deploy':
            if shared_db.shared_database():
                return _error("A shared database is already deployed.")
            return _started(*core.start_operation("deploy shared database", shared_db.deploy_shared_worker,
                                                  {'image': image}))
        if not shared_db.shared_database():
            return _error("No shared database is deployed.")
        return _started(*core.start_operation("update shared database", shared_db.update_shared_worker,
                                              {'image': image}, str(uuid.uuid4())[:8]))
    if action == 'remove':
        db = shared_db.shared_database()
        if not db:
            return _error("No shared database is deployed.")
        users = list(Q.objects.filter(shared_database=db).values_list("name", flat=True))
        if users:
            return _error(f"Instances still use the shared database: {', '.join(users)}. Undeploy them first.")
        return _started(*core.start_operation("remove shared database", shared_db.remove_shared_worker,
                                              r.b('remove_data')))
    if action == 'drop_schema':
        schema = r.s('schema')
        if not shared_db.IDENT_RE.match(schema) or not schema.startswith("qs_"):
            return _error("Invalid schema name.")
        if Q.objects.filter(db_schema=schema, db_kind=Q.DB_SHARED).exists():
            return _error(f"Schema '{schema}' belongs to a registered instance; undeploy it instead.")
        return _started(*core.start_operation("drop unused schema", shared_db.drop_orphan_schema_worker, schema))
    return _error(f"Invalid action: {action}")


@login_required
@_post_only
def qscheduler_migrate_to_shared_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """Move the database of a deployed instance from its dedicated PostgreSQL into the shared database."""
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    if inst.kind != Q.KIND_MANAGED or inst.db_kind != Q.DB_DEDICATED:
        return _error("Only instances deployed by HEAppE Management with a dedicated PostgreSQL container can be "
                      "migrated to the shared database.")
    if not shared_db.shared_database():
        return _error("No shared database is deployed: deploy it first.")
    opts = {'remove_old': _Reader(_json_body(request)).b('remove_old')}
    return _started(*core.start_operation("migrate to shared database", shared_db.migrate_to_shared_worker, inst.id,
                                          opts, str(uuid.uuid4())[:8]))


@login_required
def qscheduler_network_proposal_api(request: HttpRequest) -> HttpResponse:
    """GET ?prefix=27[&subnet=...]: a free QScheduler network subnet (or the check of the entered one) and its layout."""
    try:
        prefix = qnet.parse_prefix(request.GET.get('prefix'))
        subnet = qnet.parse_subnet(request.GET.get('subnet'))
        docker = DockerCli()
        if subnet:
            qnet.check_free(docker, subnet)
            lay = qnet.layout(subnet)
        else:
            lay = qnet.propose(docker, prefix)
    except qnet.SubnetUnavailable as e:
        return JsonResponse({'status': 'error', 'message': str(e), 'proposal': e.proposal}, status=409)
    except (ValueError, RuntimeError) as e:
        return _error(str(e))
    return JsonResponse({'status': 'success', **lay})


@login_required
@_post_only
def qscheduler_migrate_network_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """Move a local instance to its own QScheduler network (static address, no downtime)."""
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    if inst.kind not in LOCAL_KINDS or inst.qs_network:
        return _error("Only local instances without a QScheduler network can be migrated.")
    r = _Reader(_json_body(request))
    opts = {}
    _qs_network_options(r, opts, inst)
    if r.errors:
        return _error(" ".join(r.errors))
    return _started(*core.start_operation("migrate to QScheduler network", qnet.migrate_network_worker, inst.id, opts))


@login_required
@_post_only
def qscheduler_aliases_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """Set the aliases of an instance (reconnects a local QScheduler to its QScheduler network)."""
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    data = _json_body(request)
    aliases, errors = qnet.parse_aliases(data.get('aliases') if isinstance(data, dict) else "", inst)
    if errors:
        return _error(" ".join(errors))
    return _started(*core.start_operation("aliases", qnet.aliases_worker, inst.id, aliases))


@login_required
def qscheduler_backups_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """GET: backups of an instance. POST action 'backup' (background operation) or 'delete' (file)."""
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if request.method == "GET":
        return JsonResponse({'status': 'success', 'can_backup': shared_db.can_backup(inst),
                             'directory': shared_db.backup_dir_of(inst), 'backups': shared_db.list_backups(inst)})
    if request.method != "POST":
        return _error('Only GET and POST are allowed', 405)
    data = _json_body(request)
    action = data.get('action')
    if action == 'backup':
        if not shared_db.can_backup(inst):
            return _error("Backups are available for instances deployed by HEAppE Management (shared or dedicated "
                          "database).")
        if inst.is_archived:
            return _error(ARCHIVED_MESSAGE.format(name=inst.name))
        return _started(*core.start_operation("backup", shared_db.backup_worker, inst.id))
    if action == 'delete':
        try:
            shared_db.delete_backup(inst, str(data.get('file') or ""))
        except ValueError as e:
            return _error(str(e))
        except FileNotFoundError:
            return _error("Backup not found.", 404)
        return JsonResponse({'status': 'success', 'message': "Backup deleted.", 'backups': shared_db.list_backups(inst)})
    return _error(f"Invalid action: {action}")


@login_required
def qscheduler_heappe_info_api(request: HttpRequest, heappe_id: int) -> HttpResponse:
    """Version / identifier / callback defaults of a HEAppE instance for the assignment form."""
    cred = InstanceCredentials.objects.filter(pk=heappe_id).first()
    if not cred:
        return _error("HEAppE instance not found.", 404)
    version, identifier = core.heappe_identity(cred)
    heappe_container = core.find_heappe_api_container(cred.instance_name, lambda *_: None)
    return JsonResponse({
        'status': 'success', 'version': version, 'identifier': identifier,
        'supported': core.supports_qscheduler(version),
        'min_version': core.MIN_HEAPPE_VERSION_TEXT,
        'heappe_container': heappe_container,
        'callback_url': f"http://{heappe_container}:80/heappe/JobManagement/TaskCallback" if heappe_container else "",
    })


def _heappe_version_error(heappe_id):
    """Error message when the HEAppE instance is missing or older than the QScheduler minimum, else None."""
    cred = InstanceCredentials.objects.filter(pk=int(heappe_id)).first()
    if not cred:
        return "HEAppE instance not found."
    version, _ = core.heappe_identity(cred)
    if not core.supports_qscheduler(version):
        return core.unsupported_version_message(cred.instance_name, version)
    return None


@login_required
@_post_only
def qscheduler_deploy_api(request: HttpRequest) -> HttpResponse:
    uid = str(uuid.uuid4())[:8]
    opts, errors = parse_deploy_options(_json_body(request), uid)
    if errors:
        return _error(" ".join(errors))
    if Q.objects.filter(name=opts['name']).exists():
        return _error(f"A QScheduler instance named '{opts['name']}' already exists.")
    if DockerCli().exists("container", opts['name']):
        return _error(f"Container '{opts['name']}' already exists on the Docker host.")
    if opts['db_mode'] == 'shared' and not shared_db.shared_database():
        return _error("No shared database is deployed: deploy it first or choose another database option.")
    if opts['assign_heappe_id']:
        err = _heappe_version_error(opts['assign_heappe_id'])
        if err:
            return _error(err)
    return _started(*core.start_operation("deploy", deploy_worker, opts))


@login_required
@_post_only
def qscheduler_register_api(request: HttpRequest) -> HttpResponse:
    opts, errors = parse_register_options(_json_body(request))
    if errors:
        return _error(" ".join(errors))
    if Q.objects.filter(name=opts['name']).exists():
        return _error(f"A QScheduler instance named '{opts['name']}' already exists.")
    if opts['kind'] == Q.KIND_SSH_CONTAINER or opts['kind'] == Q.KIND_SSH_HOST:
        try:
            core.load_private_key(opts['ssh_private_key'], opts['ssh_key_passphrase'])
        except ValueError as e:
            return _error(str(e))
    return _started(*core.start_operation("register", register_worker, opts))


def _instance_or_404(inst_id):
    return Q.objects.filter(pk=inst_id).first()


@login_required
@_post_only
def qscheduler_update_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    if inst.kind not in DOCKER_KINDS:
        return _error("Update is not available for instances reached over SSH into the container.")
    opts, errors = parse_update_options(_json_body(request))
    if errors:
        return _error(" ".join(errors))
    return _started(*core.start_operation("update", update_worker, inst.id, opts, str(uuid.uuid4())[:8]))


@login_required
@_post_only
def qscheduler_restart_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    return _started(*core.start_operation("restart", restart_worker, inst.id))


@login_required
@_post_only
def qscheduler_undeploy_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    assigned = list(inst.assignments.values_list("heappe_instance__instance_name", flat=True))
    if assigned:
        return _error(f"Unassign the HEAppE instances first: {', '.join(assigned)}.")
    data = _json_body(request)
    remove_data = _Reader(data).b('remove_data')
    return _started(*core.start_operation("undeploy" if inst.kind == Q.KIND_MANAGED else "unregister",
                                          undeploy_worker, inst.id, remove_data))


@login_required
@_post_only
def qscheduler_assign_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    opts, errors = parse_assignment_options(_json_body(request))
    if errors:
        return _error(" ".join(errors))
    if not InstanceCredentials.objects.filter(pk=int(opts['heappe_instance_id'])).exists():
        return _error("HEAppE instance not found.", 404)
    err = _heappe_version_error(opts['heappe_instance_id'])
    if err:
        return _error(err)
    return _started(*core.start_operation("assign", assign_worker, inst.id, opts))


@login_required
@_post_only
def qscheduler_unassign_api(request: HttpRequest, asg_id: int) -> HttpResponse:
    asg = QSchedulerAssignment.objects.select_related("qscheduler").filter(pk=asg_id).first()
    if not asg:
        return _error("Assignment not found.", 404)
    if asg.qscheduler.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=asg.qscheduler.name))
    force = _Reader(_json_body(request)).b('force')
    return _started(*core.start_operation("unassign", unassign_worker, asg_id, force))


@login_required
@_post_only
def qscheduler_notifier_remove_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(ARCHIVED_MESSAGE.format(name=inst.name))
    r = _Reader(_json_body(request))
    name = r.s('name')
    if not name or len(name) > 255 or any(ch.isspace() for ch in name):
        return _error("Invalid notifier name.")
    if not r.b('acknowledged'):
        return _error("Confirm that you know what this notifier is used for.")
    if managed_notifier(inst, name):
        return _error(f"Notifier '{name}' is managed by an assignment and cannot be removed here.")
    return _started(*core.start_operation("remove_notifier", remove_notifier_worker, inst.id, name))


@login_required
def qscheduler_operation_status_api(request: HttpRequest) -> HttpResponse:
    state = core.operation_status()
    return JsonResponse({'status': 'success', **state})
