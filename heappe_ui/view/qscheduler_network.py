"""
QScheduler network and aliases of local QScheduler instances (deployed or existing local container).

QScheduler network
  * One per instance: "<name>_qs_net", bridge, --internal (QScheduler's egress, e.g. to IQM, stays on the default
    bridge), with its own subnet from QSCHEDULER_NETWORK_POOL (default /27, proposed automatically; the admin can
    enter another one).
  * Address layout of the subnet: .1 gateway, .2 QScheduler (static), the lower half reserved for static addresses,
    the upper half (--ip-range) for Docker's dynamic addresses (HEAppE containers, admin proxy). So a container that
    joins while QScheduler is being recreated never takes QScheduler's address.
  * The heappe container of every assigned HEAppE instance joins it: live (docker network connect, no restart) and
    persisted in that instance's docker-compose.override.yml, so a compose recreate keeps it. QScheduler does not
    join the HEAppE networks; datastagingapi does not need it (it rejects QScheduler jobs).

Aliases
  * Any valid DNS host name, e.g. vlq.machine.qscheduler.it4i.cz, unique on this host. Optionally restricted to a
    zone with QSCHEDULER_ALIAS_ZONE (unset by default: sites of different providers use their own domains). A HEAppE cluster can use one instead of the container name (MasterNodeName).
  * Local instances: Docker network aliases of the QScheduler container on its QScheduler network - Docker's DNS
    answers them with QScheduler's address, so they keep working after updates. Docker cannot change the aliases of
    a connected container: changing them reconnects QScheduler to the network (well under a second).
  * Remote instances: the admin enters the IP as an extra host of the HEAppE instance (to be automated with the
    tunnel to the remote site).
"""
import ipaddress
import os
import re

from django.conf import settings

from . import qscheduler_core as core
from .qscheduler_core import DockerCli, LABEL_INSTANCE

NETWORK_SUFFIX = "_qs_net"
DEFAULT_PREFIX = 27            # 30 addresses: 13 static (QScheduler, later proxies) + 15 dynamic (HEAppE, admin proxy)
PREFIX_CHOICES = (24, 25, 26, 27, 28)
QSCHEDULER_HOST_OFFSET = 2     # .1 is the gateway

_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class SubnetUnavailable(RuntimeError):
    """The subnet cannot be used; `proposal` is a free one of the same size (or None)."""

    def __init__(self, message, proposal=None):
        self.proposal = proposal
        super().__init__(message + (f" Free subnet of the same size: {proposal}." if proposal else ""))


def network_name(instance_name):
    return f"{instance_name}{NETWORK_SUFFIX}"


# ---------------------------------------------------------------------------
# Subnets (pure, unit-tested)
# ---------------------------------------------------------------------------

def layout(subnet):
    """{'subnet', 'gateway', 'ip' (QScheduler), 'ip_range' (dynamic addresses)} of a QScheduler network subnet."""
    net = ipaddress.ip_network(str(subnet), strict=True)
    upper = list(net.subnets(prefixlen_diff=1))[1]
    return {'subnet': str(net), 'gateway': str(net.network_address + 1),
            'ip': str(net.network_address + QSCHEDULER_HOST_OFFSET), 'ip_range': str(upper)}


def parse_subnet(text):
    """Validated subnet entered by the admin ('' -> None). Raises ValueError with a message for the form."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        net = ipaddress.ip_network(text, strict=True)
    except ValueError:
        raise ValueError(f"'{text}' is not a subnet in CIDR notation with host bits zero (e.g. 10.213.4.0/27).")
    if net.version != 4 or not net.is_private:
        raise ValueError(f"QScheduler network subnet must be a private IPv4 subnet (got {net}).")
    if net.prefixlen not in PREFIX_CHOICES:
        raise ValueError(f"QScheduler network size must be one of {', '.join('/' + str(p) for p in PREFIX_CHOICES)}.")
    return net


def parse_prefix(text):
    text = str(text or "").strip().lstrip("/")
    if not text:
        return DEFAULT_PREFIX
    if not text.isdigit() or int(text) not in PREFIX_CHOICES:
        raise ValueError(f"QScheduler network size must be one of {', '.join('/' + str(p) for p in PREFIX_CHOICES)}.")
    return int(text)


def propose(docker=None, prefix=DEFAULT_PREFIX, exclude=()):
    """First free subnet of QSCHEDULER_NETWORK_POOL of size /prefix (not used by any Docker network), as layout()."""
    docker = docker or DockerCli()
    for subnet in core.free_subnets(docker, prefix):
        if str(subnet) not in exclude:
            return layout(subnet)
    pool, _ = core.network_pool()
    raise SubnetUnavailable(f"No free /{prefix} subnet left in {pool}. Set QSCHEDULER_NETWORK_POOL to a larger private "
                            f"range or enter a subnet.")


def check_free(docker, subnet):
    """Raises SubnetUnavailable when `subnet` overlaps an existing Docker network."""
    net = ipaddress.ip_network(str(subnet))
    for used in core.used_subnets(docker):
        if used.version == net.version and used.overlaps(net):
            proposal = None
            try:
                proposal = propose(docker, net.prefixlen)['subnet']
            except Exception:
                pass
            raise SubnetUnavailable(f"Subnet {net} overlaps the existing Docker network subnet {used}.", proposal)


# ---------------------------------------------------------------------------
# Aliases (pure, unit-tested except the uniqueness query)
# ---------------------------------------------------------------------------

ALIAS_EXAMPLE = "vlq.machine.qscheduler.it4i.cz"


def alias_zone():
    """Zone the aliases must be in (QSCHEDULER_ALIAS_ZONE), or "" = any host name."""
    zone = getattr(settings, "QSCHEDULER_ALIAS_ZONE", None) or os.getenv("QSCHEDULER_ALIAS_ZONE", "")
    return zone.strip().strip(".").lower()


def validate_alias(alias, zone=None):
    """Normalized alias or ValueError: valid DNS name, at most 253 characters; inside the zone when one is set."""
    zone = zone if zone is not None else alias_zone()
    alias = (alias or "").strip().rstrip(".").lower()
    if not alias:
        raise ValueError("Alias is empty.")
    if len(alias) > 253 or not all(_LABEL_RE.match(label) for label in alias.split(".")):
        raise ValueError(f"'{alias}' is not a valid DNS name (letters, digits and '-' per label).")
    if zone and not alias.endswith("." + zone):
        raise ValueError(f"'{alias}' is not inside the alias zone {zone} (QSCHEDULER_ALIAS_ZONE), e.g. vlq.{zone}.")
    return alias


def parse_aliases(raw, inst=None, zone=None):
    """
    Aliases from a list or text (comma, space or newline separated). Returns (aliases, errors). Each alias must be
    unique on this host: not an alias, service host or container name of another QScheduler instance.
    """
    from heappe_ui.models import QSchedulerInstance as Q
    items = raw if isinstance(raw, list) else re.split(r"[\s,;]+", str(raw or ""))
    aliases, errors = [], []
    for item in items:
        if not str(item).strip():
            continue
        try:
            alias = validate_alias(str(item), zone)
        except ValueError as e:
            errors.append(str(e))
            continue
        if alias not in aliases:
            aliases.append(alias)
    others = Q.objects.exclude(pk=inst.pk) if inst is not None and inst.pk else Q.objects.all()
    taken = {}
    for other in others:
        for host in list(other.aliases or []) + [other.service_host, other.container_name]:
            if host:
                taken[host.lower()] = other.name
    for alias in aliases:
        if alias in taken:
            errors.append(f"Alias '{alias}' is already used by QScheduler instance '{taken[alias]}'.")
    return aliases, errors


def network_aliases(inst, aliases=None):
    """Aliases of the QScheduler container on its QScheduler network: service host (if not the name) + aliases."""
    out = []
    for host in [inst.service_host] + list(inst.aliases if aliases is None else aliases):
        if host and host != inst.container_name and host not in out:
            out.append(host)
    return out


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

def create(docker, name, subnet, instance_name, log):
    """`docker network create --internal` with the QScheduler layout; returns layout(subnet)."""
    lay = layout(subnet)
    check_free(docker, lay['subnet'])
    res = docker.run(["network", "create", "--driver", "bridge", "--internal",
                      "--subnet", lay['subnet'], "--gateway", lay['gateway'], "--ip-range", lay['ip_range'],
                      "--label", f"{LABEL_INSTANCE}={instance_name}", "--label", "qscheduler.network=qscheduler",
                      name], log, check=False)
    if res.returncode != 0:
        out = res.output.strip()
        if re.search(r"overlap|pool", out, re.I):
            proposal = None
            try:
                proposal = propose(docker, ipaddress.ip_network(lay['subnet']).prefixlen)['subnet']
            except Exception:
                pass
            raise SubnetUnavailable(f"Docker refused subnet {lay['subnet']} for '{name}': {out.splitlines()[-1]}",
                                    proposal)
        raise RuntimeError(f"Could not create network '{name}': {out}")
    log(f"QScheduler network '{name}' created: subnet {lay['subnet']}, QScheduler at {lay['ip']}, "
        f"dynamic addresses {lay['ip_range']}.")
    return lay


def existing_layout(docker, name):
    """layout() of an existing network `name`, or None."""
    info = docker.json(["network", "inspect", name])
    if not info:
        return None
    for cfg in (info[0].get("IPAM") or {}).get("Config") or []:
        if cfg.get("Subnet"):
            try:
                return layout(cfg["Subnet"])
            except ValueError:
                return None
    return None


def connect_qscheduler(docker, net, container, ip, aliases, log):
    args = ["network", "connect", "--ip", ip]
    for a in aliases:
        args += ["--alias", a]
    docker.run(args + [net, container], log)


def reconnect_qscheduler(docker, net, container, ip, aliases, log):
    """Apply changed aliases: Docker cannot change them on a connected container (short interruption)."""
    docker.run(["network", "disconnect", net, container], log, check=False)
    connect_qscheduler(docker, net, container, ip, aliases, log)


def remove(docker, net, log):
    if not docker.json(["network", "inspect", net]):
        return
    res = docker.run(["network", "rm", net], log, check=False)
    if res.returncode != 0:
        log(f"WARNING: could not remove network '{net}': {res.output.strip()}")


# ---------------------------------------------------------------------------
# HEAppE side
# ---------------------------------------------------------------------------

def heappe_override_path(heappe_instance_name):
    """docker-compose.override.yml of a HEAppE instance deployed on this host, or None."""
    from . import extra_hosts
    compose_dir = os.path.join(extra_hosts.DEPLOYMENT_BASE_PATH, heappe_instance_name, "heappe-core")
    if not os.path.exists(os.path.join(compose_dir, "docker-compose.yml")):
        return None
    return os.path.join(compose_dir, extra_hosts.OVERRIDE_FILE)


def heappe_join(heappe_instance_name, net, log):
    """
    The heappe container of the HEAppE instance joins `net`: live and in its override file. Returns the container
    name, or None when the HEAppE API container is not on this Docker host.
    """
    from . import extra_hosts
    docker = DockerCli()
    container = core.find_heappe_api_container(heappe_instance_name, log)
    override = heappe_override_path(heappe_instance_name)
    if override:
        extra_hosts.set_override_network(override, "heappe", net, True)
        log(f"'{net}' added to the heappe service in {override} (kept when compose recreates the container).")
    if not container:
        log(f"WARNING: HEAppE API container of '{heappe_instance_name}' not found on this Docker host.")
        return None
    if net not in docker.networks_of(container):
        docker.run(["network", "connect", net, container], log)
        log(f"HEAppE container '{container}' joined '{net}' (no restart needed).")
    if not override:
        log(f"NOTE: '{container}' is not part of a HEAppE compose project deployed by HEAppE Management; connect it "
            f"to '{net}' again if the container is recreated.")
    return container


def heappe_leave(heappe_instance_name, net, log):
    from . import extra_hosts
    docker = DockerCli()
    override = heappe_override_path(heappe_instance_name)
    if override and os.path.exists(override):
        extra_hosts.set_override_network(override, "heappe", net, False)
        log(f"'{net}' removed from the heappe service in {override}.")
    container = core.find_heappe_api_container(heappe_instance_name, lambda *_: None)
    if container and net in docker.networks_of(container):
        docker.run(["network", "disconnect", net, container], log, check=False)
        log(f"HEAppE container '{container}' left '{net}'.")


# ---------------------------------------------------------------------------
# Workers (core.start_operation)
# ---------------------------------------------------------------------------

LOCAL_KINDS = ("managed", "local")


def migrate_network_worker(log, result, inst_id, opts):
    """
    Move an existing local instance to its own QScheduler network without downtime:
      1. create "<name>_qs_net" (subnet entered or proposed) and connect QScheduler with the static address and its
         aliases,
      2. every assigned HEAppE container joins it (live + override file) and must reach QScheduler there,
      3. only then QScheduler leaves the HEAppE networks it joined for the assignments.
    Any failure in 1-2 is rolled back (nothing else changed); the clusters keep MasterNodeName (the container name
    resolves on the new network too).
    """
    from heappe_ui.models import QSchedulerInstance as Q
    from . import qscheduler_admin as qadmin
    inst = Q.objects.get(pk=inst_id)
    result['name'] = inst.name
    if inst.kind not in LOCAL_KINDS:
        raise RuntimeError("Only instances on this Docker host get a QScheduler network; remote instances are reached "
                           "through the tunnel to their site (to be automated).")
    if inst.is_archived:
        raise RuntimeError(f"'{inst.name}' is archived.")
    if inst.qs_network:
        raise RuntimeError(f"'{inst.name}' already uses the QScheduler network '{inst.qs_network}'.")
    docker = DockerCli()
    container = inst.container_name
    if not docker.inspect(container):
        raise RuntimeError(f"Container '{container}' not found on this Docker host.")
    net = network_name(inst.name)
    log(f"=== QSCHEDULER: MIGRATE '{inst.name}' TO ITS QSCHEDULER NETWORK '{net}' ===")

    lay = existing_layout(docker, net)
    created = False
    if lay:
        log(f"Network '{net}' exists (subnet {lay['subnet']}); using it.")
    else:
        subnet = opts.get('qs_subnet') or propose(docker, opts.get('qs_prefix') or DEFAULT_PREFIX)['subnet']
        lay = create(docker, net, subnet, inst.name, log)
        created = True
    aliases = network_aliases(inst)
    joined = []
    try:
        if net not in docker.networks_of(container):
            connect_qscheduler(docker, net, container, lay['ip'], aliases, log)
            log(f"'{container}' joined '{net}' at {lay['ip']}" + (f" (aliases {', '.join(aliases)})." if aliases else "."))
        for asg in inst.assignments.select_related("heappe_instance"):
            cname = asg.heappe_instance.instance_name
            heappe_container = heappe_join(cname, net, log)
            joined.append(cname)
            if heappe_container:
                core.check_from_heappe(heappe_container, inst.service_host, inst.port, "/health", log, attempts=5)
            else:
                log(f"WARNING: HEAppE '{cname}' is not on this Docker host; it cannot use the QScheduler network.")
    except Exception as ex:
        log(f"Migration failed ({str(ex).splitlines()[0]}); rolling back (the old networks were not touched)...")
        for cname in joined:
            heappe_leave(cname, net, log)
        docker.run(["network", "disconnect", net, container], log, check=False)
        if created:
            docker.run(["network", "rm", net], log, check=False)
        raise RuntimeError(f"Migration to the QScheduler network failed and was rolled back: {ex}")

    # Switch: QScheduler leaves the HEAppE networks it joined for the assignments
    old_nets = set()
    for asg in inst.assignments.all():
        if asg.network and asg.network != net:
            old_nets.add(asg.network)
        asg.network = net
        asg.save(update_fields=["network", "updated_at"])
    current = docker.networks_of(container)
    for old in sorted(old_nets):
        if old in current:
            docker.run(["network", "disconnect", old, container], log, check=False)
            log(f"'{container}' left the HEAppE network '{old}'.")
    inst.qs_network, inst.qs_subnet, inst.qs_ip = net, lay['subnet'], lay['ip']
    inst.save(update_fields=["qs_network", "qs_subnet", "qs_ip", "updated_at"])
    try:
        qadmin.remove_proxy(inst, log)                 # recreated on the QScheduler network on first use
        qadmin.ensure_proxy(inst, log)
    except Exception as e:
        log(f"WARNING: admin proxy not recreated yet ({str(e).splitlines()[0]}); it is created on the next admin call.")
    result.update({'qs_network': net, 'qs_subnet': lay['subnet'], 'qs_ip': lay['ip']})
    log(f"SUCCESS: '{inst.name}' uses the QScheduler network '{net}' (QScheduler at {lay['ip']}).")


def aliases_worker(log, result, inst_id, aliases):
    """
    Set the aliases of an instance. Local instances: reconnect QScheduler to its QScheduler network with them
    (interrupts it for well under a second) and check them from every assigned HEAppE container. An alias still used
    by a HEAppE cluster cannot be removed.
    """
    from heappe_ui.models import QSchedulerInstance as Q
    from .clusters import connect_heappe_management_api
    inst = Q.objects.get(pk=inst_id)
    result['name'] = inst.name
    old = list(inst.aliases or [])
    log(f"=== QSCHEDULER: ALIASES OF '{inst.name}': {', '.join(aliases) or '(none)'} ===")
    if inst.kind in LOCAL_KINDS and not inst.qs_network:
        raise RuntimeError(f"'{inst.name}' has no QScheduler network yet: aliases are Docker network aliases there. "
                           f"Use 'Migrate to QScheduler network' first.")
    removed = [a for a in old if a not in aliases]
    if removed:
        for asg in inst.assignments.select_related("heappe_instance"):
            cname = asg.heappe_instance.instance_name
            try:
                controller, session_code, _ = connect_heappe_management_api(cname, log)
                users = [c for c in core.qscheduler_clusters(controller, session_code, inst)
                         if core.cluster_host(c) in removed]
            except Exception as e:
                raise RuntimeError(f"Cannot check the clusters of HEAppE '{cname}' ({str(e).splitlines()[0][:200]}); "
                                   f"aliases not changed.")
            if users:
                raise RuntimeError(f"Alias(es) still used by HEAppE '{cname}' cluster(s) "
                                   f"{', '.join(c.get('name') + ' (' + core.cluster_host(c) + ')' for c in users)}; "
                                   f"aliases not changed.")
    if inst.kind in LOCAL_KINDS:
        docker = DockerCli()
        reconnect_qscheduler(docker, inst.qs_network, inst.container_name, inst.qs_ip,
                             network_aliases(inst, aliases), log)
        for asg in inst.assignments.select_related("heappe_instance"):
            container = core.find_heappe_api_container(asg.heappe_instance.instance_name, lambda *_: None)
            for alias in aliases:
                if container:
                    core.check_from_heappe(container, alias, inst.port, "/health", log, attempts=5)
    else:
        log("Remote instance: add each alias with the QScheduler's IP as an extra host of the HEAppE instance "
            "(Containers & Services > Extra Hosts; to be automated).")
    inst.aliases = aliases
    inst.save(update_fields=["aliases", "updated_at"])
    result['aliases'] = aliases
    log(f"SUCCESS: aliases of '{inst.name}' set.")
