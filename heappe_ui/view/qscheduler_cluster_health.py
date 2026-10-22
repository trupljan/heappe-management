"""
QScheduler panel of a HEAppE QScheduler cluster (cluster detail, Cluster Configuration):

  * which QScheduler instance the cluster is attached to (by QSchedulerHost / MasterNodeName + port) and whether the
    current HEAppE instance is assigned to it,
  * whether the cluster's notification settings match the assignment: QSchedulerNotifier = "<identifier>.<machine>",
    callbacks on, a QSchedulerNotifyToken set (Vault), the notifier registered in QScheduler with the callback URL;
    otherwise "Recreate notifier" (new notifier + token, or callbacks disabled when notifications are off),
  * whether the cluster's machine (the queue of its node type) exists in QScheduler; otherwise "Recover machine":
    register a new machine with that name, or switch the cluster to an existing machine.
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from heappe_ui.models import QSchedulerMachine

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

def cluster_status(instance_name, cluster):
    """Status of one QScheduler cluster of HEAppE `instance_name` (dict for the cluster detail panel)."""
    cfg = cluster.get('custom_configuration') or {}
    machine = core.cluster_machine(cluster)
    endpoint = f"{cfg.get('QSchedulerHost') or cluster.get('master_node_name')}:{cfg.get('QSchedulerPort') or cluster.get('port')}"
    out = {'cluster_id': cluster.get('id'), 'machine': machine, 'endpoint': endpoint, 'instance': None,
           'assigned': False, 'notifications': None, 'machine_status': None, 'error': None}
    inst = _instance_of_cluster(cluster)
    if not inst:
        return out
    out['instance'] = {'id': inst.id, 'name': inst.name, 'kind': inst.get_kind_display(), 'archived': inst.is_archived}
    asg = _assignment_for(instance_name, inst.id)
    out['assigned'] = bool(asg)
    if not asg or inst.is_archived:
        return out

    configured = cfg.get(core.NOTIFIER_KEY) or ""
    callbacks = str(cfg.get("EnableCallback", "")).lower() == "true"
    token_set = bool(cfg.get(core.NOTIFY_TOKEN_KEY))
    expected = core.cluster_notifier_name(_identifier(asg), machine) if asg.notifications_enabled else ""
    n = {'enabled': asg.notifications_enabled, 'expected': expected, 'configured': configured, 'callbacks': callbacks,
         'token_set': token_set, 'registered': None, 'url': None, 'callback_url': asg.callback_url, 'problems': []}
    out['notifications'] = n

    target = None
    names = None
    try:
        target = core.target_for(inst)
        notifiers = {x['name']: x for x in target.list_notifiers()}
        if expected:
            n['registered'] = expected in notifiers
            n['url'] = (notifiers.get(expected) or {}).get('url')
        names = target.list_machines()
    except Exception as e:
        out['error'] = f"QScheduler '{inst.name}' cannot be checked: {str(e).splitlines()[0][:300]}"
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
            core.apply_cli_change(inst, target, log)
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
            res = target.cli(core.machine_args(dict(opts, machine_name=old_machine, action='add')), log, check=False)
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
            core.apply_cli_change(inst, target, log)
    finally:
        target.close()

    if new_machine != old_machine:
        _set_queue(controller, session_code, cluster, old_machine, new_machine, log)
    core.update_cluster_notifications(controller, session_code, cluster, notifier, log)
    result.update({'cluster': cluster.get('name'), 'machine': new_machine, 'mode': opts['mode'],
                   'notifier': notifier[0] if notifier else None})
    log(f"SUCCESS: cluster '{cluster.get('name')}' uses machine '{new_machine}'"
        f"{' and notifier ' + repr(notifier[0]) + ' with a new token' if notifier else ''}.")


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
        status = cluster_status(instance_name, _qs_cluster(controller, session_code, cluster_id))
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
