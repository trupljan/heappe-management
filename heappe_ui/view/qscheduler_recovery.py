"""
QScheduler instances whose service disappeared without HEAppE Management (e.g. the container was removed by hand).

The QScheduler page flags such instances as *missing* (the container is gone) or *unreachable* (cannot tell) and
offers:

  * Archive   - keep the record, its assignments and the HEAppE clusters unchanged; the instance is no longer
                managed (no machines can be added, removing a cluster skips QScheduler).
  * Delete    - cascade: per assigned HEAppE delete its clusters on the instance and, selectable, the projects and
                queue groups used only by them; remove leftover Docker resources; forget the instance.
  * Restore   - deploy QScheduler again on this Docker host (same or another branch / tag / image, new or reused
                database), register the machines the clusters use, recreate one notifier per cluster with a new
                token and point the clusters (and their file transfer methods) to the new endpoint.
"""
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from heappe_ui.models import QSchedulerInstance as Q, QSchedulerMachine

from . import qscheduler_core as core
from . import qscheduler_shared_db as shared_db
from .qscheduler_core import DockerCli, DockerTarget, LABEL_INSTANCE, NAME_RE
from . import qscheduler_network as qnet
from .qscheduler_deploy import (_Reader, _validate_source, _network_prefix, _qs_network_options, _error, _json_body, _post_only, _started, _instance_or_404,
                                _wait_for_postgres, deploy_service, postgres_run_args, LOCAL_KINDS)

ARCHIVE_REASON_MAX = 255


def _connect(cred, log):
    from .clusters import connect_heappe_management_api
    controller, session_code, _ = connect_heappe_management_api(cred.instance_name, log)
    return controller, session_code


def _leftovers(docker, name, inst=None):
    """
    Docker resources of a managed instance named `name` that still exist: {kind: name}; with `inst` using the shared
    database also its schema ('db_schema').
    """
    pg, net, vol = f"{name}-pgsql", f"{name}_db_net", f"{name}-pgdata"
    out = {}
    if inst is not None and inst.db_kind == Q.DB_SHARED and inst.db_schema:
        try:
            if shared_db.shared_database() and shared_db.schema_exists(docker, inst.db_schema):
                out['db_schema'] = inst.db_schema
        except Exception:
            pass
    if docker.exists("container", name):
        out['service'] = name
    if docker.exists("container", pg):
        out['db_container'] = pg
    if docker.json(["network", "inspect", net]):
        out['db_network'] = net
    if docker.json(["volume", "inspect", vol]):
        out['db_volume'] = vol
    qs_net = (inst.qs_network if inst is not None and inst.qs_network else "") or qnet.network_name(name)
    if docker.json(["network", "inspect", qs_net]):
        out['qs_network'] = qs_net
    return out


def _ensure_not_running(inst):
    """Archive / delete / restore are for instances whose service is gone; refuse a running one."""
    if inst.is_archived:
        return None
    state, detail = core.presence(inst)
    if state == core.PRESENT:
        raise RuntimeError(f"QScheduler instance '{inst.name}' is running. Use Undeploy / Unregister instead.")
    return state, detail


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def archive_instance(inst, reason):
    state = _ensure_not_running(inst)
    detail = state[1] if state else ""
    inst.archived_at = datetime.now(timezone.utc)
    inst.archived_reason = (reason or detail or "QScheduler service not found")[:ARCHIVE_REASON_MAX]
    inst.save(update_fields=["archived_at", "archived_reason", "updated_at"])


def unarchive_instance(inst):
    state, detail = core.presence(inst)
    if state != core.PRESENT:
        raise RuntimeError(f"The QScheduler service of '{inst.name}' is still not available ({detail}). "
                           f"Restore it instead.")
    inst.archived_at = None
    inst.archived_reason = ""
    inst.save(update_fields=["archived_at", "archived_reason", "updated_at"])


# ---------------------------------------------------------------------------
# Cascade deletion
# ---------------------------------------------------------------------------

def parse_cascade_options(data: dict) -> tuple:
    r = _Reader(data)
    opts = {
        'delete_clusters': r.b('delete_clusters', True),
        'delete_projects': r.b('delete_projects', False),
        'delete_queue_groups': r.b('delete_queue_groups', False),
        'remove_db_container': r.b('remove_db_container', True),
        'remove_db_volume': r.b('remove_db_volume', False),
        'skip_unreachable': r.b('skip_unreachable', False),
        'confirm_name': r.s('confirm_name'),
    }
    if not opts['delete_clusters']:
        opts['delete_projects'] = opts['delete_queue_groups'] = False   # "of these clusters" needs the clusters
    if not opts['remove_db_container']:
        opts['remove_db_volume'] = False
    return opts, r.errors


def cluster_dependents(clusters, all_clusters):
    """
    Projects and queue groups used only by `clusters` (not by any other cluster of the HEAppE instance):
    ({project id: name}, {queue group id: name}).
    """
    ids = {c.get('id') for c in clusters}

    def collect(cs):
        projects, groups = {}, {}
        for c in cs:
            for nt in c.get('node_types') or []:
                for p in nt.get('projects') or []:
                    if isinstance(p, dict) and p.get('id') is not None:
                        projects[p['id']] = p.get('name') or str(p['id'])
                g = nt.get('cluster_node_type_aggregation')
                if isinstance(g, dict) and g.get('id') is not None:
                    groups[g['id']] = g.get('name') or str(g['id'])
        return projects, groups

    own_p, own_g = collect(clusters)
    other_p, other_g = collect([c for c in all_clusters if c.get('id') not in ids])
    return ({k: v for k, v in own_p.items() if k not in other_p},
            {k: v for k, v in own_g.items() if k not in other_g})


def _heappe_plan(inst, log, skip_unreachable, need_heappe=True):
    """Per assignment: HEAppE connection and its clusters on `inst`. Unreachable HEAppEs abort unless skipped."""
    plan, skipped = [], []
    for asg in inst.assignments.select_related("heappe_instance").order_by("heappe_instance__instance_name"):
        cred = asg.heappe_instance
        if not need_heappe:
            plan.append({'asg': asg, 'cred': cred, 'clusters': [], 'all': []})
            continue
        try:
            controller, session_code = _connect(cred, log)
            all_clusters = [core.as_dict(c) for c in controller.heappe_management_clusters_get(SessionCode=session_code) or []]
            clusters = core.qscheduler_clusters(controller, session_code, inst)
        except Exception as e:
            msg = f"HEAppE '{cred.instance_name}' is not reachable ({str(e).splitlines()[0][:200]})"
            if not skip_unreachable:
                raise RuntimeError(f"{msg}. Nothing was changed. Tick 'Skip unreachable HEAppE instances' to continue "
                                   f"without it (its clusters stay as they are).")
            log(f"WARNING: {msg}; skipped, its clusters stay as they are.")
            skipped.append(cred.instance_name)
            continue
        plan.append({'asg': asg, 'cred': cred, 'controller': controller, 'session_code': session_code,
                     'clusters': clusters, 'all': all_clusters})
    return plan, skipped


def _delete_queue_group(controller, session_code, group_id, log):
    for a in controller.heappe_management_project_cluster_node_type_aggregations_get(SessionCode=session_code) or []:
        d = core.as_dict(a)
        if d.get('cluster_node_type_aggregation_id') == group_id:
            controller.heappe_management_project_cluster_node_type_aggregation_delete(body={
                "ProjectId": d.get('project_id'), "ClusterNodeTypeAggregationId": group_id, "SessionCode": session_code})
    mappings = [core.as_dict(m) for m in
                controller.heappe_management_cluster_node_type_aggregation_accountings_get(SessionCode=session_code) or []]
    for m in [m for m in mappings if m.get('cluster_node_type_aggregation_id') == group_id]:
        controller.heappe_management_cluster_node_type_aggregation_accounting_delete(body={
            "ClusterNodeTypeAggregationId": group_id, "AccountingId": m.get('accounting_id'), "SessionCode": session_code})
        if not any(o.get('accounting_id') == m.get('accounting_id') and o.get('cluster_node_type_aggregation_id') != group_id
                   for o in mappings):
            controller.heappe_management_accounting_delete(body={"Id": m.get('accounting_id'), "SessionCode": session_code})
    controller.heappe_management_cluster_node_type_aggregation_delete(body={"Id": group_id, "SessionCode": session_code})


def cascade_delete_worker(log, result, inst_id, opts):
    inst = Q.objects.get(pk=inst_id)
    _ensure_not_running(inst)
    log(f"=== QSCHEDULER: DELETE '{inst.name}' WITH ITS ENTITIES ===")
    result.update({'name': inst.name, 'deleted_clusters': [], 'deleted_projects': [], 'deleted_queue_groups': [],
                   'skipped_heappe': [], 'kept_clusters': []})

    # 1. Read everything first: an unreachable HEAppE aborts before anything is deleted
    plan, skipped = _heappe_plan(inst, log, opts['skip_unreachable'], need_heappe=opts['delete_clusters'])
    result['skipped_heappe'] = skipped
    failures = []

    # 2. HEAppE entities
    for p in plan:
        name = p['cred'].instance_name
        if not opts['delete_clusters']:
            log(f"HEAppE '{name}': clusters kept (not selected).")
            continue
        controller, sc = p['controller'], p['session_code']
        projects, groups = cluster_dependents(p['clusters'], p['all'])
        log(f"HEAppE '{name}': {len(p['clusters'])} cluster(s) on '{inst.name}'.")
        for c in p['clusters']:
            label = f"'{c.get('name')}' (ID {c.get('id')})"
            try:
                cfg = c.get('custom_configuration') or {}
                if core.NOTIFY_TOKEN_KEY in cfg or core.NOTIFY_TOKEN_KEY in (c.get('custom_configuration_vault_toggles') or {}):
                    core.update_cluster_notifications(controller, sc, c, None, log)   # removes the token from Vault
                controller.heappe_management_cluster_delete(body={"Id": c.get('id'), "SessionCode": sc})
                log(f"Deleted cluster {label}.")
                result['deleted_clusters'].append(f"{name}: {c.get('name')}")
            except Exception as e:
                failures.append(f"cluster {label} of HEAppE '{name}': {str(e).splitlines()[0][:200]}")
                log(f"ERROR: deleting cluster {label} failed: {e}")
        if opts['delete_projects']:
            for pid, pname in sorted(projects.items()):
                try:
                    controller.heappe_management_project_delete(body={"Id": pid, "SessionCode": sc})
                    log(f"Deleted project '{pname}' (ID {pid}).")
                    result['deleted_projects'].append(f"{name}: {pname}")
                except Exception as e:
                    failures.append(f"project '{pname}' of HEAppE '{name}': {str(e).splitlines()[0][:200]}")
                    log(f"ERROR: deleting project '{pname}' failed: {e}")
        if opts['delete_queue_groups']:
            for gid, gname in sorted(groups.items()):
                try:
                    _delete_queue_group(controller, sc, gid, log)
                    log(f"Deleted queue group '{gname}' (ID {gid}) with its accounting and allocations.")
                    result['deleted_queue_groups'].append(f"{name}: {gname}")
                except Exception as e:
                    failures.append(f"queue group '{gname}' of HEAppE '{name}': {str(e).splitlines()[0][:200]}")
                    log(f"ERROR: deleting queue group '{gname}' failed: {e}")

    if failures:
        raise RuntimeError("Some HEAppE entities could not be deleted; the instance is kept so that you can retry:\n  "
                           + "\n  ".join(failures))

    # 3. Leftover Docker resources of a managed instance
    if inst.kind == Q.KIND_MANAGED and opts['remove_db_container']:
        docker = DockerCli()
        left = _leftovers(docker, inst.container_name, inst)
        if 'db_container' in left:
            docker.run(["rm", "-f", left['db_container']], log)
        if inst.db_kind == Q.DB_SHARED and inst.shared_database and 'db_network' in left:
            shared_db.disconnect_network(docker, inst.shared_database, left['db_network'], log)
        if 'db_schema' in left:
            if opts['remove_db_volume']:
                shared_db.drop_instance_schema(docker, left['db_schema'], log)
            else:
                log(f"Kept schema '{left['db_schema']}' in the shared database (drop it on the shared database card).")
        if 'db_network' in left:
            res = docker.run(["network", "rm", left['db_network']], log, check=False)
            if res.returncode != 0:
                log(f"WARNING: could not remove network '{left['db_network']}': {res.stderr.strip()}")
        if 'db_volume' in left:
            if opts['remove_db_volume']:
                docker.run(["volume", "rm", left['db_volume']], log)
            else:
                log(f"Kept database volume '{left['db_volume']}' (remove with: docker volume rm {left['db_volume']}).")

    # 4. Forget the instance (assignments and machine definitions go with it). The HEAppE containers leave its
    #    QScheduler network (live and in their override files), then the network is removed.
    from . import qscheduler_admin
    qscheduler_admin.remove_proxy(inst, log)
    if inst.qs_network:
        for a in inst.assignments.select_related("heappe_instance"):
            qnet.heappe_leave(a.heappe_instance.instance_name, inst.qs_network, log)
        docker = DockerCli()
        if inst.kind == Q.KIND_LOCAL and inst.container_name:
            docker.run(["network", "disconnect", inst.qs_network, inst.container_name], log, check=False)
        qnet.remove(docker, inst.qs_network, log)
    inst.delete()
    if skipped:
        log(f"NOTE: clusters of {', '.join(skipped)} were not checked and still point to the deleted instance.")
    log(f"SUCCESS: '{result['name']}' deleted ({len(result['deleted_clusters'])} cluster(s), "
        f"{len(result['deleted_projects'])} project(s), {len(result['deleted_queue_groups'])} queue group(s)).")


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def parse_restore_options(data: dict, inst) -> tuple:
    from .qscheduler_machines import parse_machine_options
    r = _Reader(data)
    defaults_git = inst.source == 'git' and inst.repo
    opts = {
        'name': r.s('name', inst.name),
        'port': r.port('port', inst.port, "Service port"),
        'host_port': r.port('host_port', None, "Host port"),
        'source': r.s('source', 'git' if defaults_git or not inst.image else 'image').lower(),
        'repo': r.s('repo', inst.repo or core.DEFAULT_QSCHEDULER_REPO),
        'ref': r.s('ref', inst.ref or core.DEFAULT_QSCHEDULER_REF),
        'image': r.s('image', inst.image or core.DEFAULT_QSCHEDULER_IMAGE),
        'rebuild_image': r.b('rebuild_image'),
        'no_cache': r.b('no_cache'),
        'db_mode': r.s('db_mode', 'new').lower(),
        'database_url': r.s('database_url'),
        'db_network': r.s('db_network'),
        'network_prefix': _network_prefix(r),
        'skip_unreachable': r.b('skip_unreachable', False),
        'machines': {},
    }
    if not NAME_RE.match(opts['name']):
        r.errors.append("Name may contain only letters, digits, '_', '.', '-' (max 63 chars).")
    _validate_source(r, opts)
    if opts['db_mode'] not in ('new', 'shared', 'reuse', 'existing'):
        r.errors.append("Database mode must be 'new', 'shared', 'reuse' or 'existing'.")
    if opts['db_mode'] == 'reuse' and (inst.kind != Q.KIND_MANAGED or opts['name'] != inst.name):
        r.errors.append("The database can be reused only for an instance deployed by HEAppE Management, under its "
                        "original name.")
    if opts['db_mode'] == 'existing' and not opts['database_url'].startswith(("postgres://", "postgresql://")):
        r.errors.append("Existing database requires a postgres:// DATABASE_URL.")
    if opts['db_network'] and not NAME_RE.match(opts['db_network']):
        r.errors.append("DB network name is invalid.")
    if r.data.get('aliases') is None:
        r.data = dict(r.data, aliases=list(inst.aliases or []))     # keep the aliases of the instance
    _qs_network_options(r, opts, inst)

    machines = data.get('machines') if isinstance(data, dict) else None
    for m in machines if isinstance(machines, list) else []:
        if not isinstance(m, dict):
            continue
        name = str(m.get('name') or "").strip()
        if not core.MACHINE_RE.match(name):
            r.errors.append(f"Invalid machine name '{name}'.")
            continue
        if str(m.get('mode') or 'register').lower() == 'skip':
            continue                       # expected to exist in the reused database
        mopts, errors = parse_machine_options(dict(m, qscheduler_id="0", machine_name=name, machine_mode="new",
                                                   create_project=False), "restore")
        r.errors += [f"Machine '{name}': {e}" for e in errors]
        opts['machines'][name] = mopts
    return opts, r.errors


def reusable_database(docker, inst):
    """Description of the database a restore can reuse, or None (managed instances only)."""
    if inst.kind != Q.KIND_MANAGED:
        return None
    left = _leftovers(docker, inst.container_name, inst)
    if 'db_schema' in left and inst.database_url:
        return f"schema '{left['db_schema']}' in the shared database (kept)"
    if 'db_container' in left:
        return f"PostgreSQL container '{left['db_container']}' (still exists)"
    if 'db_volume' in left and inst.database_url:
        return f"volume '{left['db_volume']}' (PostgreSQL container is recreated with the stored password)"
    return None


def _prepare_reused_database(docker, inst, log, prefix=None):
    """Start / recreate the old PostgreSQL of a managed instance (or rejoin its shared schema). Returns (database_url,
    db_network)."""
    name = inst.container_name
    pg, net, vol = f"{name}-pgsql", f"{name}_db_net", f"{name}-pgdata"
    if inst.db_kind == Q.DB_SHARED:
        db = shared_db.require_running(docker)
        if not inst.database_url or not shared_db.schema_exists(docker, inst.db_schema):
            raise RuntimeError(f"Schema '{inst.db_schema}' is no longer in the shared database; deploy a new database.")
        if not docker.json(["network", "inspect", net]):
            core.create_internal_network(docker, net, {LABEL_INSTANCE: name}, log, prefix=prefix)
        shared_db.connect_network(docker, db, net, log)
        log(f"Reusing schema '{inst.db_schema}' in the shared database.")
        return inst.database_url, net
    info = docker.inspect(pg)
    if info:
        env = dict(e.split("=", 1) for e in (info.get("Config") or {}).get("Env") or [] if "=" in e)
        password = env.get("POSTGRES_PASSWORD")
        if not password:
            raise RuntimeError(f"Cannot read the password of '{pg}'; use 'Use existing database' with its DATABASE_URL.")
        if not docker.json(["network", "inspect", net]):
            raise RuntimeError(f"Network '{net}' of '{pg}' is missing.")
        if not (info.get("State") or {}).get("Running"):
            docker.run(["start", pg], log)
        log(f"Reusing PostgreSQL container '{pg}'.")
    elif docker.json(["volume", "inspect", vol]) and inst.database_url:
        password = urlparse(inst.database_url).password
        if not docker.json(["network", "inspect", net]):
            core.create_internal_network(docker, net, {LABEL_INSTANCE: name}, log, prefix=prefix)
        docker.run(postgres_run_args(name, password), log)
        log(f"Recreated PostgreSQL container '{pg}' on the kept volume '{vol}'.")
    else:
        raise RuntimeError("There is no database left to reuse; deploy a new one.")
    _wait_for_postgres(docker, pg, log)
    return f"postgres://qscheduler:{password}@{pg}:5432/qscheduler", net


def _remove_leftovers(docker, name, log, inst=None):
    left = _leftovers(docker, name, inst if inst is not None and inst.container_name == name else None)
    if 'service' in left:
        raise RuntimeError(f"Container '{name}' exists on this Docker host. Choose another name.")
    for kind in ('db_container',):
        if kind in left:
            docker.run(["rm", "-f", left[kind]], log)
    if 'db_network' in left:
        docker.run(["network", "rm", left['db_network']], log)
    if 'db_volume' in left:
        docker.run(["volume", "rm", left['db_volume']], log)
        log(f"Removed the old database volume '{left['db_volume']}' (new database requested).")
    if 'db_schema' in left:
        shared_db.drop_instance_schema(docker, left['db_schema'], log)


def restore_worker(log, result, inst_id, opts):
    inst = Q.objects.get(pk=inst_id)
    _ensure_not_running(inst)
    old_name, old_host, old_port = inst.name, inst.service_host, inst.port
    name, port = opts['name'], opts['port']
    docker = DockerCli()
    log(f"=== QSCHEDULER: RESTORE '{old_name}' as '{name}' ({opts['source']}: "
        f"{opts['repo'] + '#' + opts['ref'] if opts['source'] == 'git' else opts['image']}) ===")
    if name != old_name and Q.objects.filter(name=name).exclude(pk=inst.pk).exists():
        raise RuntimeError(f"A QScheduler instance named '{name}' already exists.")
    if docker.exists("container", name):
        raise RuntimeError(f"Container '{name}' already exists on this Docker host. Choose another name.")

    # 1. Plan (nothing is changed yet): HEAppE clusters on the old endpoint and the machines they use
    plan, skipped = _heappe_plan(inst, log, opts['skip_unreachable'])
    needed = {}
    for p in plan:
        version, identifier = core.heappe_identity(p['cred'])
        if not core.supports_qscheduler(version):
            raise RuntimeError(core.unsupported_version_message(p['cred'].instance_name, version) + " Nothing was changed.")
        p['identifier'] = p['asg'].heappe_identifier or identifier
        for c in p['clusters']:
            needed.setdefault(core.cluster_machine(c), []).append(f"{p['cred'].instance_name}: {c.get('name')}")
    undefined = sorted(m for m in needed if m not in opts['machines'])
    if undefined and opts['db_mode'] != 'reuse':
        raise RuntimeError(f"Define the backend of machine(s) {', '.join(undefined)}: a new database has no machines. "
                           f"Nothing was changed.")
    result.update({'name': name, 'machines': sorted(needed), 'skipped_heappe': skipped, 'updated_clusters': [],
                   'problems': []})

    # 2. Database and service
    deploy_opts = dict(opts)
    deploy_opts['extra_hosts'] = inst.extra_hosts or []
    deploy_opts['log_level'] = inst.log_level or ""       # the restored service logs as before
    if opts['db_mode'] == 'reuse':
        url, net = _prepare_reused_database(docker, inst, log, prefix=opts.get('network_prefix'))
        deploy_opts.update(db_mode='existing', database_url=url, db_network=net,
                           reuse_kind=inst.db_kind if inst.db_kind in (Q.DB_SHARED, Q.DB_DEDICATED) else Q.DB_DEDICATED,
                           reuse_schema=inst.db_schema)
    elif opts['db_mode'] in ('new', 'shared'):
        _remove_leftovers(docker, name, log, inst)
        if inst.db_kind == Q.DB_SHARED and inst.db_schema and name != inst.container_name:
            log(f"NOTE: schema '{inst.db_schema}' of the old instance is kept in the shared database; drop it on the "
                f"shared database card when it is no longer needed.")
    elif opts['db_mode'] == 'existing':
        deploy_opts.update(reuse_kind=Q.DB_EXTERNAL)
    info = deploy_service(docker, deploy_opts, log)

    # 3. The record now describes the new deployment (assignments are kept)
    inst.name, inst.kind, inst.container_name, inst.service_host, inst.port = name, Q.KIND_MANAGED, name, name, port
    inst.source = opts['source']
    inst.repo = opts['repo'] if opts['source'] == 'git' else ""
    inst.ref = opts['ref'] if opts['source'] == 'git' else ""
    inst.image = opts['image']
    inst.database_url = info['database_url']
    inst.admin_token = info.get('admin_token', "")   # new container, new ADMIN_TOKEN
    inst.db_kind = info.get('db_kind') or Q.DB_EXTERNAL
    inst.db_schema = info.get('db_schema') or ""
    inst.shared_database = info.get('shared_database')
    old_qs_network = inst.qs_network
    inst.qs_network, inst.qs_subnet, inst.qs_ip = info.get('qs_network') or "", info.get('qs_subnet') or "", info.get('qs_ip') or ""
    inst.aliases = opts.get('aliases') or []
    inst.ssh_host = inst.ssh_user = inst.ssh_private_key = inst.ssh_key_passphrase = inst.ssh_host_key = ""
    inst.ssh_port, inst.docker_command, inst.restart_command = 22, "docker", ""
    inst.restart_pending = False
    inst.archived_at, inst.archived_reason = None, ""
    inst.save()
    log(f"Instance record updated: endpoint {name}:{port} (was {old_host}:{old_port}).")
    target = DockerTarget(docker, name, port)

    # 4. Machines used by the clusters
    changed = False
    existing = {m['name'] for m in (target.list_machines(log) or [])}
    broken = set()
    for machine in sorted(needed):
        if machine in existing:
            log(f"Machine '{machine}' exists in the database.")
            continue
        mopts = opts['machines'].get(machine)
        if not mopts:
            broken.add(machine)
            result['problems'].append(f"machine '{machine}' is not in the reused database and has no definition")
            continue
        res = target.add_machine(mopts, log)
        if res.returncode != 0:
            broken.add(machine)
            result['problems'].append(f"registering machine '{machine}' failed: {res.output.strip().splitlines()[-1] if res.output.strip() else 'no output'}")
            continue
        backend, options = core.machine_definition(mopts)
        QSchedulerMachine.objects.update_or_create(qscheduler=inst, name=machine,
                                                   defaults={'backend': backend, 'options': options})
        log(f"Machine '{machine}' registered ({backend}).")
        changed = True

    # 5. Networks and one new notifier (with a new token) per cluster
    add, updates, heappe_restarts = {}, [], set()
    for p in plan:
        asg, cname = p['asg'], p['cred'].instance_name
        # HEAppE joins the QScheduler network of the restored instance (and leaves the old one if it was renamed);
        # without one (not expected after a deploy) QScheduler joins the HEAppE network as before
        if old_qs_network and old_qs_network != inst.qs_network:
            qnet.heappe_leave(cname, old_qs_network, log)
        if inst.qs_network:
            heappe_container = qnet.heappe_join(cname, inst.qs_network, log)
            asg.network = inst.qs_network
        else:
            heappe_container, heappe_net = core.resolve_heappe_service_network(cname, log)
            if heappe_net:
                if heappe_net not in docker.networks_of(name):
                    docker.run(["network", "connect", "--alias", name, heappe_net, name], log)
                    heappe_restarts.add(heappe_container)
                asg.network = heappe_net
        callback_url = asg.callback_url or (f"http://{heappe_container}:80/heappe/JobManagement/TaskCallback"
                                            if heappe_container else "")
        notify = asg.notifications_enabled and bool(callback_url)
        if asg.notifications_enabled and not callback_url:
            result['problems'].append(f"HEAppE '{cname}' has notifications on but no callback URL; its clusters "
                                      f"were restored without callbacks")
        for c in p['clusters']:
            machine = core.cluster_machine(c)
            if machine in broken:
                result['problems'].append(f"cluster '{c.get('name')}' of HEAppE '{cname}' not restored (machine '{machine}')")
                continue
            notifier = None
            if notify:
                notifier = (core.cluster_notifier_name(p['identifier'], machine), core.new_notify_token())
                add[notifier[0]] = (callback_url, notifier[1])
            updates.append((p, c, notifier))
        asg.heappe_identifier, asg.callback_url = p['identifier'], callback_url
        asg.save()
    if add:
        current = {n['name']: n for n in target.list_notifiers(log)}
        changed |= core.replace_notifiers(target, add, set(), current, log)
    if changed:
        core.apply_changes(inst, target, log)      # one restart for machines + notifiers

    # 6. HEAppE clusters: new endpoint (clusters using an alias keep it), new notifier and token (Vault)
    for p, c, notifier in updates:
        host = core.cluster_host(c)
        new_host = host if host in inst.aliases else name
        location = (new_host, port) if (new_host, port) != (host, old_port) else None
        try:
            core.update_cluster_notifications(p['controller'], p['session_code'], c, notifier, log, location=location)
            if location:
                core.repoint_file_transfer_methods(p['controller'], p['session_code'], c, new_host, port, log)
            result['updated_clusters'].append(f"{p['cred'].instance_name}: {c.get('name')}")
        except Exception as e:
            result['problems'].append(f"updating cluster '{c.get('name')}' of HEAppE '{p['cred'].instance_name}' "
                                      f"failed: {str(e).splitlines()[0][:200]}")
    if old_qs_network and old_qs_network != inst.qs_network:
        qnet.remove(docker, old_qs_network, log)
    for container in heappe_restarts:
        if container:
            core.restart_heappe(container, log)
    for p in plan:
        container = core.find_heappe_api_container(p['cred'].instance_name, log)
        if container:
            try:
                core.check_from_heappe(container, name, port, "/health", log, attempts=5)
            except RuntimeError as e:
                result['problems'].append(f"HEAppE '{p['cred'].instance_name}' cannot reach '{name}': {e}")

    if skipped:
        result['problems'].append(f"HEAppE instance(s) {', '.join(skipped)} were unreachable; their clusters still point "
                                  f"to {old_host}:{old_port}. Edit their assignment ('Generate new tokens') once reachable")
    if result['problems']:
        raise RuntimeError(f"'{name}' is running again, but:\n  " + "\n  ".join(result['problems']))
    log(f"SUCCESS: '{name}' restored ({info.get('version') or 'version unknown'}); {len(result['updated_clusters'])} "
        f"cluster(s) reassigned with new notifier tokens.")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
@_post_only
def qscheduler_archive_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    if inst.is_archived:
        return _error(f"'{inst.name}' is already archived.")
    try:
        archive_instance(inst, _Reader(_json_body(request)).s('reason'))
    except RuntimeError as e:
        return _error(str(e))
    return JsonResponse({'status': 'success', 'message': f"'{inst.name}' archived; its HEAppE clusters are kept."})


@login_required
@_post_only
def qscheduler_unarchive_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    try:
        unarchive_instance(inst)
    except RuntimeError as e:
        return _error(str(e))
    return JsonResponse({'status': 'success', 'message': f"'{inst.name}' is managed again."})


@login_required
def qscheduler_cascade_preview_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """What a cascade deletion would remove, per assigned HEAppE (read-only)."""
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    heappes = []
    for p in _heappe_plan(inst, lambda *_: None, skip_unreachable=True)[0]:
        projects, groups = cluster_dependents(p['clusters'], p['all'])
        heappes.append({'heappe_instance': p['cred'].instance_name, 'reachable': True,
                        'clusters': [{'id': c.get('id'), 'name': c.get('name'), 'machine': core.cluster_machine(c)}
                                     for c in p['clusters']],
                        'projects': [{'id': k, 'name': v} for k, v in sorted(projects.items())],
                        'queue_groups': [{'id': k, 'name': v} for k, v in sorted(groups.items())]})
    reached = {h['heappe_instance'] for h in heappes}
    for asg in inst.assignments.select_related("heappe_instance"):
        if asg.heappe_instance.instance_name not in reached:
            heappes.append({'heappe_instance': asg.heappe_instance.instance_name, 'reachable': False,
                            'clusters': [], 'projects': [], 'queue_groups': []})
    leftovers = {}
    if inst.kind == Q.KIND_MANAGED:
        try:
            leftovers = _leftovers(DockerCli(), inst.container_name)
        except Exception:
            leftovers = {}
    return JsonResponse({'status': 'success', 'name': inst.name, 'kind': inst.kind, 'heappes': heappes,
                         'leftovers': leftovers})


@login_required
@_post_only
def qscheduler_cascade_delete_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    opts, errors = parse_cascade_options(_json_body(request))
    if errors:
        return _error(" ".join(errors))
    if opts['confirm_name'] != inst.name:
        return _error(f"Type the instance name '{inst.name}' to confirm.")
    try:
        _ensure_not_running(inst)
    except RuntimeError as e:
        return _error(str(e))
    return _started(*core.start_operation("delete", cascade_delete_worker, inst.id, opts))


@login_required
def qscheduler_restore_info_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """Defaults of the restore form: source, database options, clusters and the machines they use."""
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    stored = {m.name: {'backend': m.backend, 'options': m.options} for m in inst.machines.all()}
    machines, heappes = {}, []
    for p in _heappe_plan(inst, lambda *_: None, skip_unreachable=True)[0]:
        clusters = []
        for c in p['clusters']:
            machine = core.cluster_machine(c)
            machines.setdefault(machine, {'name': machine, 'clusters': [], 'stored': stored.get(machine)})
            machines[machine]['clusters'].append(f"{p['cred'].instance_name}: {c.get('name')}")
            clusters.append({'id': c.get('id'), 'name': c.get('name'), 'machine': machine,
                             'notifier': core.cluster_notifier(c)})
        heappes.append({'heappe_instance': p['cred'].instance_name, 'reachable': True, 'clusters': clusters,
                        'notifications_enabled': p['asg'].notifications_enabled})
    reached = {h['heappe_instance'] for h in heappes}
    for asg in inst.assignments.select_related("heappe_instance"):
        if asg.heappe_instance.instance_name not in reached:
            heappes.append({'heappe_instance': asg.heappe_instance.instance_name, 'reachable': False, 'clusters': [],
                            'notifications_enabled': asg.notifications_enabled})
    try:
        docker = DockerCli()
        reuse = reusable_database(docker, inst)
        leftovers = _leftovers(docker, inst.container_name, inst) if inst.kind == Q.KIND_MANAGED else {}
    except Exception as e:
        reuse, leftovers = None, {}
    git = inst.source == 'git' and bool(inst.repo)
    return JsonResponse({
        'status': 'success', 'name': inst.name, 'kind': inst.kind, 'old_endpoint': f"{inst.service_host}:{inst.port}",
        'defaults': {'name': inst.name, 'port': inst.port, 'source': 'git' if git or not inst.image else 'image',
                     'repo': inst.repo or core.DEFAULT_QSCHEDULER_REPO, 'ref': inst.ref or core.DEFAULT_QSCHEDULER_REF,
                     'image': inst.image or core.DEFAULT_QSCHEDULER_IMAGE},
        'reusable_database': reuse, 'leftovers': leftovers,
        'shared_db_deployed': shared_db.shared_database() is not None, 'db_kind': inst.db_kind,
        'machines': [machines[k] for k in sorted(machines)], 'machine_defaults': core.MACHINE_DEFAULTS,
        'network_prefix': core.network_pool()[1], 'network_prefixes': list(core.NETWORK_PREFIX_CHOICES),
        'qs_subnet': inst.qs_subnet, 'qs_network_kept': leftovers.get('qs_network', ""), 'aliases': inst.aliases or [],
        'heappes': heappes,
    })


@login_required
@_post_only
def qscheduler_restore_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    inst = _instance_or_404(inst_id)
    if not inst:
        return _error("QScheduler instance not found.", 404)
    opts, errors = parse_restore_options(_json_body(request), inst)
    if errors:
        return _error(" ".join(errors))
    try:
        _ensure_not_running(inst)
    except RuntimeError as e:
        return _error(str(e))
    if opts['db_mode'] == 'shared' and not shared_db.shared_database():
        return _error("No shared database is deployed: deploy it first or choose another database option.")
    return _started(*core.start_operation("restore", restore_worker, inst.id, opts))
