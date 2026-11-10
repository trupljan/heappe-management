"""
QScheduler panel of a HEAppE QScheduler cluster (cluster detail, Cluster Configuration):

  * which QScheduler instance the cluster is attached to (by QSchedulerHost / MasterNodeName + port) and whether the
    current HEAppE instance is assigned to it,
  * whether the cluster's notification settings match the assignment: QSchedulerNotifier = "<identifier>.<machine>",
    callbacks on, a QSchedulerNotifyToken set (Vault), the notifier registered in QScheduler with the callback URL;
    otherwise "Recreate notifier" (new notifier + token, or callbacks disabled when notifications are off),
  * whether the cluster's machine (the queue of its node type) exists in QScheduler; otherwise "Recover machine":
    register a new machine with that name, or switch the cluster to an existing machine,
  * whether the cluster has the project prefix of its HEAppE (QSchedulerProjectPrefix; HEAppE 6.7.0+ refuses to
    submit without it when callbacks are on). It is set by the prefix migration on the QScheduler page,
  * QScheduler 0.3.0+: whether the walltime of the cluster's queues fits the machine's max task time limit (HEAppE
    sends the walltime as the task time limit; more is rejected). "Fix time limits" lowers the queues' MaxWalltime
    or raises the machine's limit,
  * when its QScheduler instance is not registered, archived or cannot be reached: "Move to another QScheduler" -
    the cluster (with its queues, projects and job history) is kept and pointed to another healthy instance assigned
    to this HEAppE, with a new or existing machine there and a new notifier and token.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from heappe_ui.models import QSchedulerAssignment, QSchedulerMachine

from . import qscheduler_core as core
from .qscheduler_core import SCHEDULER_TYPE_QSCHEDULER
from .qscheduler_machines import _assignment_for, _instance_of_cluster, _json_body, _error, parse_machine_options


def _connect(instance_name, log):
    from .clusters import connect_heappe_management_api
    controller, session_code, _ = connect_heappe_management_api(instance_name, log)
    return controller, session_code


def _qs_cluster(controller, session_code, cluster_id):
    cluster = core.as_dict(controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=session_code))
    if cluster.get('scheduler_type') != SCHEDULER_TYPE_QSCHEDULER:
        raise RuntimeError(f"Cluster {cluster_id} is not a QScheduler cluster.")
    return cluster


def _identifier(asg):
    if asg.heappe_identifier:
        return asg.heappe_identifier
    return core.heappe_identity(asg.heappe_instance)[1]


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def queue_walltime_problems(cluster, machine, max_ms):
    """Queues of `cluster` on `machine` whose MaxWalltime (seconds) is above the machine max task time limit (ms)."""
    out = []
    for nt in cluster.get('node_types') or []:
        walltime = nt.get('max_walltime')
        if nt.get('queue') == machine and max_ms and (walltime is None or int(walltime) * 1000 > int(max_ms)):
            out.append({'id': nt.get('id'), 'name': nt.get('name'), 'max_walltime': walltime})
    return out


def _time_limit_status(cluster, machine, state):
    """{'max_ms', 'max', 'queues', 'problems'} of a cluster for the machine state of QScheduler >= 0.3.0."""
    max_ms = (state or {}).get('max_task_time_limit_ms')
    if not max_ms:
        return None
    queues = queue_walltime_problems(cluster, machine, max_ms)
    return {'max_ms': max_ms, 'max': core.format_duration(max_ms), 'max_walltime': max_ms // 1000,
            'default': core.format_duration((state or {}).get('default_task_time_limit_ms') or 0),
            'decay': core.format_duration((state or {}).get('decay_half_time_ms') or 0)
            if (state or {}).get('decay_half_time_ms') else None,
            'queues': queues,
            'problems': [f"queue '{q['name']}' allows {q['max_walltime'] or 'unlimited'} s, the machine accepts tasks "
                         f"of at most {core.format_duration(max_ms)} ({max_ms // 1000} s): longer jobs are rejected"
                         for q in queues]}


def time_limit_report(inst, log):
    """Logs and returns the queues of all assigned HEAppEs whose walltime is above their machine's max task time limit."""
    target = core.target_for(inst)
    try:
        states = target.machine_states(log)
    finally:
        target.close()
    problems = []
    for a in inst.assignments.select_related("heappe_instance"):
        name = a.heappe_instance.instance_name
        try:
            controller, session_code = _connect(name, lambda *_: None)
            clusters = core.qscheduler_clusters(controller, session_code, inst)
        except Exception as e:
            log(f"WARNING: clusters of HEAppE '{name}' cannot be read: {str(e).splitlines()[0][:200]}")
            continue
        for c in clusters:
            machine = core.cluster_machine(c)
            status = _time_limit_status(c, machine, states.get(machine))
            for text in (status or {}).get('problems', []):
                log(f"WARNING: HEAppE '{name}', cluster '{c.get('name')}': {text}. Fix it in the cluster's "
                    f"QScheduler panel (Fix time limits).")
                problems.append({'heappe_instance': name, 'cluster_id': c.get('id'), 'problem': text})
    if not problems:
        log("Queue walltimes fit the machines' max task time limits.")
    return problems


def cluster_status(instance_name, cluster, heappe_version=None):
    """Status of one QScheduler cluster of HEAppE `instance_name` (dict for the cluster detail panel)."""
    cfg = cluster.get('custom_configuration') or {}
    machine = core.cluster_machine(cluster)
    endpoint = f"{cfg.get('QSchedulerHost') or cluster.get('master_node_name')}:{cfg.get('QSchedulerPort') or cluster.get('port')}"
    out = {'cluster_id': cluster.get('id'), 'cluster_name': cluster.get('name'),
           'name_matches': core.cluster_name_matches(cluster), 'machine': machine, 'endpoint': endpoint, 'instance': None,
           'assigned': False, 'notifications': None, 'machine_status': None, 'error': None,
           'move_candidates': [], 'can_move': False, 'prefix': None, 'time_limit': None}
    inst = _instance_of_cluster(cluster)
    out['move_candidates'] = [{'id': a.qscheduler.id, 'name': a.qscheduler.name,
                               'endpoint': f"{a.qscheduler.service_host}:{a.qscheduler.port}"}
                              for a in QSchedulerAssignment.objects.select_related("qscheduler")
                              .filter(heappe_instance__instance_name=instance_name, qscheduler__archived_at__isnull=True)
                              .order_by("qscheduler__name") if not inst or a.qscheduler.id != inst.id]
    if not inst:
        out['can_move'] = True          # its QScheduler is not (or no longer) registered here
        return out
    out['instance'] = {'id': inst.id, 'name': inst.name, 'kind': inst.get_kind_display(), 'archived': inst.is_archived}
    asg = _assignment_for(instance_name, inst.id)
    out['assigned'] = bool(asg)
    if inst.is_archived:
        out['can_move'] = True
    if not asg or inst.is_archived:
        return out

    configured = cfg.get(core.NOTIFIER_KEY) or ""
    callbacks = str(cfg.get("EnableCallback", "")).lower() == "true"
    token_set = bool(cfg.get(core.NOTIFY_TOKEN_KEY))
    expected = core.cluster_notifier_name(_identifier(asg), machine) if asg.notifications_enabled else ""
    n = {'enabled': asg.notifications_enabled, 'expected': expected, 'configured': configured, 'callbacks': callbacks,
         'token_set': token_set, 'registered': None, 'url': None, 'callback_url': asg.callback_url, 'problems': []}
    out['notifications'] = n

    configured_prefix = core.cluster_project_prefix(cluster)
    pr = {'expected': asg.project_prefix, 'configured': configured_prefix, 'assignment_id': asg.id,
          'heappe_uses_prefix': core.uses_project_prefix(heappe_version) if heappe_version else None, 'problems': []}
    if not configured_prefix:
        pr['problems'].append(
            f"{core.PREFIX_KEY} is not set: HEAppE 6.7.0+ "
            + ("refuses to submit (it falls back to the notifier name, which contains '.')" if callbacks
               else "falls back to its InstanceIdentifierPath")
            + ". Run 'Project prefix...' on this HEAppE's assignment (QScheduler page).")
    elif asg.project_prefix and configured_prefix != asg.project_prefix:
        pr['problems'].append(f"{core.PREFIX_KEY} is '{configured_prefix}', the other clusters of this HEAppE use "
                              f"'{asg.project_prefix}' (kept: a prefix must never change)")
    pr['ok'] = not pr['problems']
    out['prefix'] = pr

    target = None
    names = None
    try:
        target = core.target_for(inst)
        notifiers = {x['name']: x for x in target.list_notifiers()}
        if expected:
            n['registered'] = expected in notifiers
            n['url'] = (notifiers.get(expected) or {}).get('url')
        names = target.list_machines()
        if names is not None and core.supports_030(target.version()):
            out['time_limit'] = _time_limit_status(cluster, machine, target.machine_states().get(machine))
    except Exception as e:
        out['error'] = f"QScheduler '{inst.name}' cannot be checked: {str(e).splitlines()[0][:300]}"
        out['can_move'] = True          # unreachable or gone: the cluster can be moved to a healthy instance
    finally:
        if target:
            target.close()

    p = n['problems']
    if asg.notifications_enabled:
        if not callbacks:
            p.append("callbacks are disabled on the cluster (HEAppE polls task state)")
        if configured != expected:
            p.append(f"QSchedulerNotifier is '{configured or 'empty'}', expected '{expected}'")
        if not token_set:
            p.append("no QSchedulerNotifyToken is set")
        if n['registered'] is False:
            p.append(f"notifier '{expected}' is not registered in QScheduler")
        elif n['registered'] and asg.callback_url and n['url'] != asg.callback_url:
            p.append(f"notifier '{expected}' calls {n['url']}, the assignment's callback URL is {asg.callback_url}")
    elif callbacks:
        p.append("callbacks are enabled on the cluster, but notifications are off for this HEAppE on this QScheduler")
    n['ok'] = not p and (n['registered'] is not None or not asg.notifications_enabled)

    if names is not None:
        registered = {m['name'] for m in names}
        out['machine_status'] = {'registered': machine in registered, 'machines': sorted(registered)}
    else:
        out['machine_status'] = {'registered': None, 'machines': []}
    return out


# ---------------------------------------------------------------------------
# Recreate the notifier of a cluster
# ---------------------------------------------------------------------------

def _other_users(controller, session_code, inst, cluster_id, notifier):
    return [c for c in core.qscheduler_clusters(controller, session_code, inst)
            if c.get('id') != cluster_id and core.cluster_notifier(c) == notifier]


def _notifier_change(controller, session_code, inst, asg, cluster, machine, log):
    """
    (add, remove, notifier) bringing the cluster's notifier in line with the assignment: a new notifier
    "<identifier>.<machine>" with a new token, or none when notifications are off. The old notifier of this cluster is
    removed when it belongs to this HEAppE and no other cluster uses it.
    """
    identifier = _identifier(asg)
    old = (cluster.get('custom_configuration') or {}).get(core.NOTIFIER_KEY) or ""
    remove = set()
    if old and old.startswith(identifier + ".") and not _other_users(controller, session_code, inst, cluster.get('id'), old):
        remove.add(old)
    if not asg.notifications_enabled:
        return {}, remove | {core.cluster_notifier_name(identifier, machine)}, None
    if not asg.callback_url:
        raise RuntimeError("The assignment has notifications on but no callback URL. Edit the assignment on the "
                           "QScheduler page first.")
    if not asg.heappe_identifier:
        asg.heappe_identifier = identifier
        asg.save(update_fields=["heappe_identifier", "updated_at"])
    notifier = (core.cluster_notifier_name(identifier, machine), core.new_notify_token())
    remove.discard(notifier[0])
    return {notifier[0]: (asg.callback_url, notifier[1])}, remove, notifier


def _context(instance_name, cluster_id, log):
    controller, session_code = _connect(instance_name, log)
    cluster = _qs_cluster(controller, session_code, cluster_id)
    inst = _instance_of_cluster(cluster)
    if not inst:
        raise RuntimeError(f"The QScheduler instance of cluster '{cluster.get('name')}' is not registered in HEAppE "
                           f"Management.")
    if inst.is_archived:
        raise RuntimeError(f"QScheduler instance '{inst.name}' is archived; restore it on the QScheduler page.")
    asg = _assignment_for(instance_name, inst.id)
    if not asg:
        raise RuntimeError(f"HEAppE '{instance_name}' is not assigned to '{inst.name}'. Assign it on the QScheduler page.")
    return controller, session_code, cluster, inst, asg


def recreate_notifier_worker(log, result, instance_name, cluster_id):
    controller, session_code, cluster, inst, asg = _context(instance_name, cluster_id, log)
    machine = core.cluster_machine(cluster)
    log(f"=== QSCHEDULER: RECREATE NOTIFIER OF CLUSTER '{cluster.get('name')}' (machine '{machine}', '{inst.name}') ===")
    add, remove, notifier = _notifier_change(controller, session_code, inst, asg, cluster, machine, log)
    target = core.target_for(inst)
    try:
        current = {n['name']: n for n in target.list_notifiers(log)}
        remove = {r for r in remove if r in current}
        if core.replace_notifiers(target, add, remove, current, log):
            core.apply_changes(inst, target, log)
    finally:
        target.close()
    core.update_cluster_notifications(controller, session_code, cluster, notifier, log)
    result.update({'cluster': cluster.get('name'), 'notifier': notifier[0] if notifier else None,
                   'removed': sorted(remove)})
    log(f"SUCCESS: cluster '{cluster.get('name')}' "
        f"{'uses notifier ' + repr(notifier[0]) + ' with a new token (Vault)' if notifier else 'has callbacks disabled'}.")


# ---------------------------------------------------------------------------
# Recover the machine of a cluster
# ---------------------------------------------------------------------------

def parse_recover_options(data, machine):
    data = data or {}
    mode = str(data.get('mode') or 'new').strip().lower()
    if mode not in ('new', 'existing'):
        return None, ["Mode must be 'new' or 'existing'."]
    if mode == 'existing':
        name = str(data.get('machine_name') or "").strip()
        if not core.MACHINE_RE.match(name):
            return None, ["Select an existing machine."]
        return {'mode': 'existing', 'machine_name': name}, []
    opts, errors = parse_machine_options(dict(data, qscheduler_id="0", machine_name=machine, machine_mode="new",
                                              create_project=False), "recover")
    return dict(opts, mode='new'), errors


def _set_queue(controller, session_code, cluster, old_machine, new_machine, log):
    """Point the cluster's node types from machine `old_machine` to `new_machine` (Queue, and Name if it was the machine)."""
    for nt in cluster.get('node_types') or []:
        if nt.get('queue') != old_machine:
            continue
        group = nt.get('cluster_node_type_aggregation') or {}
        controller.heappe_management_cluster_node_type_put(body={
            "Id": nt.get('id'), "Name": new_machine[:50] if nt.get('name') == old_machine[:50] else nt.get('name'),
            "Description": nt.get('description'), "NumberOfNodes": nt.get('number_of_nodes'),
            "CoresPerNode": nt.get('cores_per_node'), "Queue": new_machine, "QualityOfService": nt.get('quality_of_service'),
            "MaxWalltime": nt.get('max_walltime'), "ClusterAllocationName": nt.get('cluster_allocation_name'),
            "ClusterId": cluster.get('id'), "FileTransferMethodId": nt.get('file_transfer_method_id'),
            "ClusterNodeTypeAggregationId": group.get('id') if isinstance(group, dict) else None,
            "SessionCode": session_code})
        log(f"Queue '{nt.get('name')}' (ID {nt.get('id')}) now uses machine '{new_machine}'.")
        nt['queue'] = new_machine


def _name_after_machine(cluster, machine, log):
    """The cluster is PUT back named after its machine (see core.cluster_name_matches)."""
    if cluster.get('name') != machine:
        log(f"Cluster '{cluster.get('name')}' is renamed to '{machine}': a QScheduler cluster is named after its machine.")
        cluster['name'] = machine


def recover_machine_worker(log, result, instance_name, cluster_id, opts):
    controller, session_code, cluster, inst, asg = _context(instance_name, cluster_id, log)
    old_machine = core.cluster_machine(cluster)
    new_machine = opts['machine_name'] if opts['mode'] == 'existing' else old_machine
    log(f"=== QSCHEDULER: RECOVER MACHINE OF CLUSTER '{cluster.get('name')}' ('{old_machine}' -> "
        f"{'existing' if opts['mode'] == 'existing' else 'new'} machine '{new_machine}' on '{inst.name}') ===")
    if opts['mode'] == 'existing' and new_machine != old_machine:
        for c in core.qscheduler_clusters(controller, session_code, inst):
            if c.get('id') != cluster.get('id') and core.cluster_machine(c) == new_machine:
                raise RuntimeError(f"HEAppE cluster '{c.get('name')}' (ID {c.get('id')}) already uses machine "
                                   f"'{new_machine}' on '{inst.name}'.")
    if cluster.get('name') != new_machine:
        core.check_cluster_name_free(controller, session_code, new_machine, cluster.get('id'))

    target = core.target_for(inst)
    changed = False
    try:
        machines = target.list_machines(log)
        if machines is None:
            raise RuntimeError(f"Machines of '{inst.name}' cannot be listed; the machine cannot be verified.")
        names = {m['name'] for m in machines}
        if opts['mode'] == 'new':
            if old_machine in names:
                raise RuntimeError(f"Machine '{old_machine}' already exists in '{inst.name}'; nothing to recover.")
            res = target.add_machine(dict(opts, machine_name=old_machine), log)
            if res.returncode != 0:
                raise RuntimeError(f"Machine registration failed:\n{res.output[-3000:]}")
            backend, options = core.machine_definition(opts)
            QSchedulerMachine.objects.update_or_create(qscheduler=inst, name=old_machine,
                                                       defaults={'backend': backend, 'options': options})
            log(f"Machine '{old_machine}' registered ({backend}).")
            changed = True
        elif new_machine not in names:
            raise RuntimeError(f"Machine '{new_machine}' does not exist in '{inst.name}' (known: {', '.join(sorted(names)) or 'none'}).")

        # The notifier name contains the machine: recreate it (new token) for the machine the cluster uses now
        add, remove, notifier = _notifier_change(controller, session_code, inst, asg, cluster, new_machine, log)
        current = {n['name']: n for n in target.list_notifiers(log)}
        remove = {r for r in remove if r in current}
        changed |= core.replace_notifiers(target, add, remove, current, log)
        if changed:
            core.apply_changes(inst, target, log)
    finally:
        target.close()

    if new_machine != old_machine:
        _set_queue(controller, session_code, cluster, old_machine, new_machine, log)
    _name_after_machine(cluster, new_machine, log)
    core.update_cluster_notifications(controller, session_code, cluster, notifier, log)
    result.update({'cluster': cluster.get('name'), 'machine': new_machine, 'mode': opts['mode'],
                   'notifier': notifier[0] if notifier else None})
    log(f"SUCCESS: cluster '{cluster.get('name')}' uses machine '{new_machine}'"
        f"{' and notifier ' + repr(notifier[0]) + ' with a new token' if notifier else ''}.")


# ---------------------------------------------------------------------------
# Move a cluster to another QScheduler instance (its own one is gone)
# ---------------------------------------------------------------------------

def parse_move_options(data, machine):
    data = data or {}
    raw = str(data.get('qscheduler_id') or "").strip()
    opts, errors = parse_recover_options(data, machine)
    if not raw.isdigit():
        errors = ["Select the QScheduler instance to move the cluster to."] + errors
    return (dict(opts or {}, qscheduler_id=int(raw) if raw.isdigit() else None), errors)


def _remove_old_notifier(controller, session_code, old_inst, cluster, log):
    """Best effort: drop the cluster's notifier from its old instance when that one is still reachable."""
    old = (cluster.get('custom_configuration') or {}).get(core.NOTIFIER_KEY)
    if not old or not old_inst or old_inst.is_archived:
        return
    if _other_users(controller, session_code, old_inst, cluster.get('id'), old):
        log(f"Notifier '{old}' on '{old_inst.name}' is used by other clusters; kept.")
        return
    target = None
    try:
        target = core.target_for(old_inst)
        current = {n['name']: n for n in target.list_notifiers(log)}
        if old in current and core.replace_notifiers(target, {}, {old}, current, log):
            core.apply_changes(old_inst, target, log)
    except Exception as e:
        log(f"WARNING: could not remove notifier '{old}' from '{old_inst.name}' ({str(e).splitlines()[0][:200]}); "
            f"remove it there once it is reachable.")
    finally:
        if target:
            target.close()


def move_cluster_worker(log, result, instance_name, cluster_id, opts):
    controller, session_code = _connect(instance_name, log)
    cluster = _qs_cluster(controller, session_code, cluster_id)
    old_inst = _instance_of_cluster(cluster)
    asg = _assignment_for(instance_name, opts['qscheduler_id'])
    if not asg:
        raise RuntimeError(f"HEAppE '{instance_name}' is not assigned to the selected QScheduler instance.")
    inst = asg.qscheduler
    if inst.is_archived:
        raise RuntimeError(f"QScheduler instance '{inst.name}' is archived.")
    if old_inst and old_inst.id == inst.id:
        raise RuntimeError(f"The cluster already belongs to '{inst.name}'.")
    old_machine = core.cluster_machine(cluster)
    new_machine = opts['machine_name'] if opts['mode'] == 'existing' else old_machine
    log(f"=== QSCHEDULER: MOVE CLUSTER '{cluster.get('name')}' from "
        f"{old_inst.name if old_inst else (cluster.get('master_node_name') or '?')} to '{inst.name}' "
        f"({'existing' if opts['mode'] == 'existing' else 'new'} machine '{new_machine}') ===")
    for c in core.qscheduler_clusters(controller, session_code, inst):
        if core.cluster_machine(c) == new_machine:
            raise RuntimeError(f"HEAppE cluster '{c.get('name')}' (ID {c.get('id')}) already uses machine "
                               f"'{new_machine}' on '{inst.name}'.")
    if cluster.get('name') != new_machine:
        core.check_cluster_name_free(controller, session_code, new_machine, cluster.get('id'))

    target = core.target_for(inst)
    changed = False
    try:
        if target.health() != 200:
            raise RuntimeError(f"QScheduler '{inst.name}' is not healthy; choose a healthy instance.")
        machines = target.list_machines(log)
        if machines is None:
            raise RuntimeError(f"Machines of '{inst.name}' cannot be listed; the machine cannot be verified.")
        names = {m['name'] for m in machines}
        if opts['mode'] == 'new':
            if old_machine in names:
                raise RuntimeError(f"Machine '{old_machine}' already exists in '{inst.name}'. Choose 'Use an existing "
                                   f"machine' to share it.")
            res = target.add_machine(dict(opts, machine_name=old_machine), log)
            if res.returncode != 0:
                raise RuntimeError(f"Machine registration failed:\n{res.output[-3000:]}")
            backend, options = core.machine_definition(opts)
            QSchedulerMachine.objects.update_or_create(qscheduler=inst, name=old_machine,
                                                       defaults={'backend': backend, 'options': options})
            log(f"Machine '{old_machine}' registered in '{inst.name}' ({backend}).")
            changed = True
        elif new_machine not in names:
            raise RuntimeError(f"Machine '{new_machine}' does not exist in '{inst.name}' (known: {', '.join(sorted(names)) or 'none'}).")

        # New notifier on the new instance; the old one belongs to the old instance (handled below)
        moved = dict(cluster, custom_configuration={k: v for k, v in (cluster.get('custom_configuration') or {}).items()
                                                    if k != core.NOTIFIER_KEY})
        add, remove, notifier = _notifier_change(controller, session_code, inst, asg, moved, new_machine, log)
        current = {n['name']: n for n in target.list_notifiers(log)}
        remove = {r for r in remove if r in current}
        changed |= core.replace_notifiers(target, add, remove, current, log)
        if changed:
            core.apply_changes(inst, target, log)
    finally:
        target.close()

    # Network: a local instance joins the HEAppE network if the assignment did not do it yet
    if inst.kind in ("managed", "local") and asg.network:
        try:
            docker = core.DockerCli()
            if asg.network not in docker.networks_of(inst.container_name):
                docker.run(["network", "connect", "--alias", inst.service_host, asg.network, inst.container_name], log)
        except Exception as e:
            log(f"WARNING: could not connect '{inst.container_name}' to '{asg.network}': {e}")

    _remove_old_notifier(controller, session_code, old_inst, cluster, log)
    if new_machine != old_machine:
        _set_queue(controller, session_code, cluster, old_machine, new_machine, log)
    _name_after_machine(cluster, new_machine, log)
    location = (inst.service_host, inst.port)
    # On another QScheduler the cluster's projects start anew: it takes the prefix of its HEAppE there.
    from .qscheduler_prefix import ensure_assignment_prefix
    prefix = ensure_assignment_prefix(asg, None, core.qscheduler_clusters(controller, session_code, inst))
    core.update_cluster_notifications(controller, session_code, cluster, notifier, log, location=location,
                                      prefix=prefix)
    core.repoint_file_transfer_methods(controller, session_code, cluster, inst.service_host, inst.port, log)
    result.update({'cluster': cluster.get('name'), 'machine': new_machine, 'mode': opts['mode'],
                   'notifier': notifier[0] if notifier else None, 'qscheduler': inst.name,
                   'from': old_inst.name if old_inst else cluster.get('master_node_name')})
    log(f"SUCCESS: cluster '{cluster.get('name')}' moved to '{inst.name}' (machine '{new_machine}'"
        f"{', notifier ' + repr(notifier[0]) + ' with a new token' if notifier else ''}); its queues, projects and "
        f"job history are kept.")


# ---------------------------------------------------------------------------
# Fix queue walltimes vs. the machine max task time limit (QScheduler >= 0.3.0)
# ---------------------------------------------------------------------------

LIMIT_FIELDS = (('max_task_time_limit', 'max_task_time_limit_ms', "Max task time limit"),
                ('default_task_time_limit', 'default_task_time_limit_ms', "Default task time limit"),
                ('decay_half_time', 'decay_half_time_ms', "Fair share decay half-time"))


def parse_time_limit_options(data):
    """
    mode 'queues' (lower the queue walltime), 'machine' (raise the max task time limit) or 'edit' (set any of the
    machine's time limits; fit_queues also lowers queue walltimes above the new max).
    """
    data = data or {}
    flag = lambda v: v if isinstance(v, bool) else str(v or "").strip().lower() in ("1", "true", "on", "yes")
    mode = str(data.get('mode') or 'queues').strip().lower()
    if mode not in ('queues', 'machine', 'edit'):
        return None, ["Mode must be 'queues', 'machine' or 'edit'."]
    opts = {'mode': mode, 'iqm_token': str(data.get('iqm_token') or "").strip(), 'max_task_time_limit': None,
            'default_task_time_limit': None, 'decay_half_time': None, 'fit_queues': flag(data.get('fit_queues'))}
    keys = [f for f, _, _ in LIMIT_FIELDS] if mode == 'edit' else ['max_task_time_limit'] if mode == 'machine' else []
    errors = []
    for key, _, label in LIMIT_FIELDS:
        if key not in keys:
            continue
        raw = str(data.get(key) or "").strip()
        if raw and not core.DURATION_RE.match(raw):
            errors.append(f"{label} must be a duration with a unit, e.g. 30m or 2h.")
        elif raw and core.duration_ms(raw) < 1:
            errors.append(f"{label} must be at least 1ms.")
        opts[key] = raw or None
    if mode == 'edit' and not errors and not any(opts[k] for k in keys) and not opts['fit_queues']:
        errors.append("Enter at least one limit to change.")
    if mode == 'edit' and not errors and opts['max_task_time_limit'] and opts['default_task_time_limit']:
        err = core.check_time_limits(opts)
        if err:
            errors.append(err)
    return (None, errors) if errors else (opts, [])


def _put_queue_walltime(controller, session_code, cluster, nt, walltime, log):
    group = nt.get('cluster_node_type_aggregation') or {}
    controller.heappe_management_cluster_node_type_put(body={
        "Id": nt.get('id'), "Name": nt.get('name'), "Description": nt.get('description'),
        "NumberOfNodes": nt.get('number_of_nodes'), "CoresPerNode": nt.get('cores_per_node'), "Queue": nt.get('queue'),
        "QualityOfService": nt.get('quality_of_service'), "MaxWalltime": walltime,
        "ClusterAllocationName": nt.get('cluster_allocation_name'), "ClusterId": cluster.get('id'),
        "FileTransferMethodId": nt.get('file_transfer_method_id'),
        "ClusterNodeTypeAggregationId": group.get('id') if isinstance(group, dict) else None,
        "SessionCode": session_code})
    log(f"Queue '{nt.get('name')}' (ID {nt.get('id')}): MaxWalltime {nt.get('max_walltime')} -> {walltime} s.")


def _store_machine_limits(inst, machine, changes_ms):
    """Keeps the stored machine definition (used by Restore) in line with the changed limits."""
    stored = QSchedulerMachine.objects.filter(qscheduler=inst, name=machine).first()
    if stored:
        options = dict(stored.options or {})
        for key, field, _ in LIMIT_FIELDS:
            if field in changes_ms:
                options[key] = core.format_duration(changes_ms[field])
        stored.options = options
        stored.save(update_fields=["options", "updated_at"])


def fix_time_limits_worker(log, result, instance_name, cluster_id, opts):
    """
    mode 'queues': lower the MaxWalltime of the cluster's queues to the machine max task time limit.
    mode 'machine': raise the machine max task time limit to max_task_time_limit (default: the longest queue
    walltime). mode 'edit': set the given time limits of the machine (raise or lower); with fit_queues the queues
    above the new max are lowered too. The machine may be shared by other HEAppE instances.
    """
    controller, session_code, cluster, inst, asg = _context(instance_name, cluster_id, log)
    machine = core.cluster_machine(cluster)
    log(f"=== QSCHEDULER: TIME LIMITS OF CLUSTER '{cluster.get('name')}' (machine '{machine}', '{inst.name}') ===")
    target = core.target_for(inst)
    try:
        if not core.supports_030(target.version()):
            raise RuntimeError("Task time limit maximums need QScheduler 0.3.0 or newer.")
        state = target.machine_states(log).get(machine)
        if not state:
            raise RuntimeError(f"Machine '{machine}' is not registered in '{inst.name}'.")
        max_ms = state.get('max_task_time_limit_ms')
        too_long = queue_walltime_problems(cluster, machine, max_ms)
        changes = {}
        if opts['mode'] == 'machine':
            wanted = (core.duration_ms(opts['max_task_time_limit']) if opts['max_task_time_limit'] else
                      max([int(q['max_walltime'] or 0) * 1000 for q in too_long] or [max_ms]))
            if wanted <= max_ms:
                log(f"The machine already accepts tasks of {core.format_duration(max_ms)}; nothing to change.")
            else:
                changes['max_task_time_limit_ms'] = wanted
        elif opts['mode'] == 'edit':
            for key, field, label in LIMIT_FIELDS:
                if opts.get(key) and core.duration_ms(opts[key]) != state.get(field):
                    changes[field] = core.duration_ms(opts[key])
                    log(f"{label}: {core.format_duration(state.get(field) or 0)} -> {opts[key]}.")
            if not changes:
                log("The machine already has these limits; nothing to change.")
        if changes:
            target.update_machine_settings(machine, changes, log, opts['iqm_token'],
                                           what="Changing the task time limits")
            _store_machine_limits(inst, machine, changes)
            max_ms = changes.get('max_task_time_limit_ms', max_ms)
            log(f"Machine '{machine}' updated; QScheduler restarted it (an open session was closed). Other HEAppE "
                f"instances using it are affected too.")
        too_long = queue_walltime_problems(cluster, machine, max_ms)
    finally:
        target.close()
    changed = []
    if opts['mode'] == 'queues' or (opts['mode'] == 'edit' and opts.get('fit_queues')):
        for nt in cluster.get('node_types') or []:
            if nt.get('id') in {q['id'] for q in too_long}:
                _put_queue_walltime(controller, session_code, cluster, nt, max_ms // 1000, log)
                changed.append(nt.get('id'))
        if not changed:
            log("All queues already fit the machine's max task time limit.")
    elif too_long:
        log(f"WARNING: {len(too_long)} queue(s) allow longer jobs than {core.format_duration(max_ms)}: QScheduler "
            f"rejects them. Lower the queue walltime on the cluster page.")
    result.update({'cluster': cluster.get('name'), 'machine': machine, 'mode': opts['mode'],
                   'max_task_time_limit': core.format_duration(max_ms), 'queues': changed,
                   'changed': {k: core.format_duration(v) for k, v in changes.items()} if opts['mode'] != 'queues'
                   else {}})
    log(f"SUCCESS: jobs of cluster '{cluster.get('name')}' may run up to {core.format_duration(max_ms)}.")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _version_error(request):
    version = request.session.get("middleware_deployed_version", "") or ""
    if not core.supports_qscheduler(version):
        return core.unsupported_version_message(request.session.get("chosen_instance") or "current", version)
    return None


@login_required
def qscheduler_cluster_status_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    instance_name = request.session.get("chosen_instance")
    try:
        controller, session_code = _connect(instance_name, lambda *_: None)
        status = cluster_status(instance_name, _qs_cluster(controller, session_code, cluster_id),
                                request.session.get("middleware_deployed_version", "") or None)
    except Exception as e:
        return _error(f"Cannot read cluster {cluster_id}: {str(e).splitlines()[0][:300]}", 500)
    return JsonResponse(dict(status, status='success'))


@login_required
def qscheduler_cluster_recreate_notifier_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    err = _version_error(request)
    if err:
        return _error(err)
    ok, msg = core.start_operation("recreate_notifier", recreate_notifier_worker,
                                   request.session.get("chosen_instance"), cluster_id)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)


@login_required
def qscheduler_cluster_recover_machine_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    err = _version_error(request)
    if err:
        return _error(err)
    data = _json_body(request)
    opts, errors = parse_recover_options(data, str(data.get('current_machine') or "").strip() or "machine")
    if errors:
        return _error(" ".join(errors))
    ok, msg = core.start_operation("recover_machine", recover_machine_worker,
                                   request.session.get("chosen_instance"), cluster_id, opts)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)


@login_required
def qscheduler_cluster_move_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    err = _version_error(request)
    if err:
        return _error(err)
    data = _json_body(request)
    opts, errors = parse_move_options(data, str(data.get('current_machine') or "").strip() or "machine")
    if errors:
        return _error(" ".join(errors))
    if not _assignment_for(request.session.get("chosen_instance"), opts['qscheduler_id']):
        return _error("This HEAppE instance is not assigned to the selected QScheduler instance.")
    ok, msg = core.start_operation("move_cluster", move_cluster_worker, request.session.get("chosen_instance"),
                                   cluster_id, opts)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)


@login_required
def qscheduler_cluster_time_limits_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    """Changes the machine task time limits or fixes queue walltimes above the max task time limit."""
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    err = _version_error(request)
    if err:
        return _error(err)
    opts, errors = parse_time_limit_options(_json_body(request))
    if errors:
        return _error(" ".join(errors))
    ok, msg = core.start_operation("fix_time_limits", fix_time_limits_worker, request.session.get("chosen_instance"),
                                   cluster_id, opts)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)


@login_required
def qscheduler_cluster_rename_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    """Renames a QScheduler cluster after its machine (its jobs fail when the names differ)."""
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    err = _version_error(request)
    if err:
        return _error(err)
    lines = []
    try:
        controller, session_code = _connect(request.session.get("chosen_instance"), lambda *_: None)
        cluster = _qs_cluster(controller, session_code, cluster_id)
        machine = core.cluster_machine(cluster)
        if core.cluster_name_matches(cluster):
            return JsonResponse({'status': 'success', 'message': f"Cluster is already named '{machine}'.",
                                 'cluster_name': machine})
        core.check_cluster_name_free(controller, session_code, machine, cluster.get('id'))
        core.rename_cluster(controller, session_code, cluster, machine, lines.append)
    except Exception as e:
        return _error(str(e).splitlines()[0][:500])
    return JsonResponse({'status': 'success', 'message': lines[-1] if lines else "Renamed.", 'cluster_name': machine})
