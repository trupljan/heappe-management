"""
Suspend / resume the QScheduler machine of a HEAppE QScheduler cluster, and the machine overview on the dashboard.

A suspension belongs to the machine, not to the cluster: while a machine is suspended, QScheduler rejects every new
task and session on it (HTTP 409 with the suspension message), for every HEAppE cluster that uses it. `cancel`
decides what happens to existing work: none (it continues), waiting (tasks not yet handed to the backend fail and
sessions close) or all (running tasks fail too, their cancellation is requested from the backend).

Machines can be shared by clusters of several HEAppE instances assigned to the same QScheduler instance. Before an
action the clusters using the machine are collected from every assigned HEAppE; when the machine is shared (or a
HEAppE cannot be checked), the action needs an explicit confirmation (`confirm_shared`).

Uses the admin API through the admin proxy (QScheduler >= 0.2.1).
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from heappe_ui.models import QSchedulerAssignment

from . import qscheduler_core as core
from .qscheduler_core import SCHEDULER_TYPE_QSCHEDULER
from .qscheduler_machines import _assignment_for, _error, _instance_of_cluster, _json_body

logger = logging.getLogger(__name__)

# Machine states shown in the UI
ONLINE = "online"                  # registered, not suspended, backend answers
OFFLINE = "offline"                # registered, not suspended, backend does not answer
SUSPENDED = "suspended"
MISSING = "missing"                # not registered in QScheduler
UNREACHABLE = "unreachable"        # QScheduler cannot be asked (down, admin token, proxy)
UNSUPPORTED = "unsupported"        # QScheduler < 0.2.1: no admin API
UNREGISTERED = "unregistered"      # the cluster's QScheduler is not registered in HEAppE Management
ARCHIVED = "archived"
NOT_ASSIGNED = "not_assigned"      # the current HEAppE is not assigned to the cluster's QScheduler


def _connect(instance_name):
    from .clusters import connect_heappe_management_api
    controller, session_code, _ = connect_heappe_management_api(instance_name, lambda *_: None)
    return controller, session_code


def _first_line(e, limit=300):
    return (str(e).splitlines() or [type(e).__name__])[0][:limit]


def parse_suspend_options(data: dict, username=""):
    """(opts, errors) of a suspend / resume request."""
    action = str(data.get('action') or "").strip().lower()
    message = str(data.get('message') or "").strip()
    cancel = str(data.get('cancel') or "none").strip().lower()
    confirm = data.get('confirm_shared')
    confirm = confirm if isinstance(confirm, bool) else str(confirm or "").strip().lower() in ("1", "true", "on", "yes")
    errors = []
    if action not in ("suspend", "resume"):
        errors.append("Action must be 'suspend' or 'resume'.")
    if action == "suspend":
        if not message:
            message = f"Suspended in HEAppE Management{' by ' + username if username else ''}"
        if len(message) > core.SUSPENSION_MESSAGE_MAX_LEN:
            errors.append(f"The message has at most {core.SUSPENSION_MESSAGE_MAX_LEN} characters.")
        if cancel not in core.SUSPENSION_CANCEL_MODES:
            errors.append(f"Existing work must be one of: {', '.join(core.SUSPENSION_CANCEL_MODES)}.")
    return {'action': action, 'message': message, 'cancel': cancel, 'confirm_shared': confirm}, errors


# ---------------------------------------------------------------------------
# Machine state
# ---------------------------------------------------------------------------

def instance_machine_states(inst, machines, check_online=True):
    """
    State of `machines` in QScheduler instance `inst`:
      {'error': text or None, 'state': UNREACHABLE | UNSUPPORTED | None,
       'machines': {name: {'state', 'suspension', 'online', 'online_reason', 'backend'}}}
    Backends are asked (GET /machine/{name}/about) in parallel when `check_online`.
    """
    out = {'error': None, 'state': None, 'machines': {}}
    target = None
    try:
        target = core.target_for(inst)
        if not target.uses_admin_api():
            out['state'] = UNSUPPORTED
            out['error'] = core.SUSPENSION_UNSUPPORTED
            return out
        registered = target.machine_states()
        known = [m for m in machines if m in registered]
        online = {}
        if check_online and known:
            with ThreadPoolExecutor(max_workers=min(8, len(known))) as pool:
                online = dict(zip(known, pool.map(target.machine_online, known)))
        for m in machines:
            info = registered.get(m)
            if info is None:
                out['machines'][m] = {'state': MISSING, 'suspension': None, 'online': None, 'online_reason': "",
                                      'backend': ""}
                continue
            ok, reason = online.get(m, (None, ""))
            state = SUSPENDED if info['suspension'] else (ONLINE if ok or ok is None else OFFLINE)
            out['machines'][m] = {'state': state, 'suspension': info['suspension'], 'online': ok,
                                  'online_reason': reason, 'backend': info['backend']}
    except Exception as e:
        from .qscheduler_admin import find_admin_token_error
        tok = find_admin_token_error(e)
        out['state'] = UNREACHABLE
        out['error'] = str(tok) if tok else f"QScheduler '{inst.name}' cannot be asked: {_first_line(e)}"
    finally:
        if target:
            target.close()
    return out


def machine_users(inst, machine, current=None):
    """
    Clusters of all HEAppE instances assigned to `inst` that use `machine`:
    (users [{'heappe', 'cluster_id', 'cluster'}], unchecked [{'heappe', 'error'}]).
    current: (instance_name, controller, session_code) of an already connected HEAppE.
    """
    users, unchecked = [], []
    for a in inst.assignments.select_related("heappe_instance").order_by("heappe_instance__instance_name"):
        name = a.heappe_instance.instance_name
        try:
            if current and current[0] == name:
                controller, session_code = current[1], current[2]
            else:
                controller, session_code = _connect(name)
            for c in core.qscheduler_clusters(controller, session_code, inst):
                if core.cluster_machine(c) == machine:
                    users.append({'heappe': name, 'cluster_id': c.get('id'), 'cluster': c.get('name')})
        except Exception as e:
            unchecked.append({'heappe': name, 'error': _first_line(e, 200)})
    return users, unchecked


def _cluster(controller, session_code, cluster_id):
    cluster = core.as_dict(controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=session_code))
    if cluster.get('scheduler_type') != SCHEDULER_TYPE_QSCHEDULER:
        raise RuntimeError(f"Cluster {cluster_id} is not a QScheduler cluster.")
    return cluster


def cluster_suspension_status(instance_name, cluster_id, with_users=True):
    """State of the machine of one QScheduler cluster of HEAppE `instance_name`, and who else uses the machine."""
    controller, session_code = _connect(instance_name)
    cluster = _cluster(controller, session_code, cluster_id)
    machine = core.cluster_machine(cluster)
    out = {'heappe': instance_name, 'cluster_id': cluster.get('id'), 'cluster': cluster.get('name'),
           'machine': machine, 'instance': None,
           'state': None, 'suspension': None, 'online': None, 'online_reason': "", 'error': None,
           'can_act': False, 'users': [], 'unchecked': [], 'shared': False}
    inst = _instance_of_cluster(cluster)
    if not inst:
        out['state'] = UNREGISTERED
        out['error'] = "The cluster's QScheduler is not registered in HEAppE Management."
        return out
    out['instance'] = {'id': inst.id, 'name': inst.name}
    if inst.is_archived:
        out['state'], out['error'] = ARCHIVED, f"QScheduler '{inst.name}' is archived."
        return out
    if not _assignment_for(instance_name, inst.id):
        out['state'] = NOT_ASSIGNED
        out['error'] = f"HEAppE '{instance_name}' is not assigned to QScheduler '{inst.name}'."
        return out
    states = instance_machine_states(inst, [machine])
    if states['state']:
        out['state'], out['error'] = states['state'], states['error']
        return out
    m = states['machines'][machine]
    out.update({k: m[k] for k in ('state', 'suspension', 'online', 'online_reason')})
    out['can_act'] = m['state'] != MISSING
    if with_users and out['can_act']:
        out['users'], out['unchecked'] = machine_users(inst, machine, (instance_name, controller, session_code))
        out['shared'] = (len({(u['heappe'], u['cluster_id']) for u in out['users']}) > 1) or bool(out['unchecked'])
    return out


def apply_suspension(instance_name, cluster_id, opts, log):
    """Suspends or resumes the cluster's machine. Raises PermissionError when a shared machine is not confirmed."""
    status = cluster_suspension_status(instance_name, cluster_id)
    if not status['can_act']:
        raise RuntimeError(status['error'] or f"Machine '{status['machine']}' cannot be suspended or resumed.")
    if status['shared'] and not opts['confirm_shared']:
        raise PermissionError(status)
    inst = QSchedulerAssignment.objects.select_related("qscheduler").get(
        heappe_instance__instance_name=instance_name, qscheduler_id=status['instance']['id']).qscheduler
    machine = status['machine']
    target = core.target_for(inst)
    try:
        if opts['action'] == "suspend":
            target.suspend_machine(machine, opts['message'], opts['cancel'], log)
        else:
            target.resume_machine(machine, log)
    finally:
        target.close()
    others = [f"{u['heappe']}/{u['cluster']}" for u in status['users'] if u['cluster_id'] != cluster_id
              or u['heappe'] != instance_name]
    logger.info("QScheduler machine %s on %s %s from HEAppE %s (cluster %s)%s", machine, inst.name,
                "suspended" if opts['action'] == "suspend" else "resumed", instance_name, cluster_id,
                f"; also affects {', '.join(others)}" if others else "")
    return cluster_suspension_status(instance_name, cluster_id, with_users=False)


# ---------------------------------------------------------------------------
# Dashboard overview
# ---------------------------------------------------------------------------

def machines_overview(instance_name):
    """QScheduler clusters of HEAppE `instance_name` with the state of their machines (dashboard)."""
    controller, session_code = _connect(instance_name)
    rows, by_inst = [], {}
    for c in controller.heappe_management_clusters_get(SessionCode=session_code) or []:
        d = core.as_dict(c)
        if d.get('scheduler_type') != SCHEDULER_TYPE_QSCHEDULER:
            continue
        inst = _instance_of_cluster(d)
        row = {'cluster_id': d.get('id'), 'cluster': d.get('name'), 'machine': core.cluster_machine(d),
               'instance': inst.name if inst else None, 'instance_id': inst.id if inst else None,
               'state': None, 'suspension': None, 'online': None, 'online_reason': "", 'error': None,
               'can_act': False}
        if not inst:
            row['state'], row['error'] = UNREGISTERED, "QScheduler not registered in HEAppE Management."
        elif inst.is_archived:
            row['state'], row['error'] = ARCHIVED, f"QScheduler '{inst.name}' is archived."
        elif not _assignment_for(instance_name, inst.id):
            row['state'], row['error'] = NOT_ASSIGNED, f"Not assigned to QScheduler '{inst.name}'."
        else:
            by_inst.setdefault(inst.id, (inst, []))[1].append(row)
        rows.append(row)
    for inst, inst_rows in by_inst.values():
        states = instance_machine_states(inst, sorted({r['machine'] for r in inst_rows}))
        for r in inst_rows:
            if states['state']:
                r['state'], r['error'] = states['state'], states['error']
                continue
            m = states['machines'][r['machine']]
            r.update({k: m[k] for k in ('state', 'suspension', 'online', 'online_reason')})
            r['can_act'] = m['state'] != MISSING
    rows.sort(key=lambda r: (r['instance'] or "~", r['machine'] or "", r['cluster'] or ""))
    return rows


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def dashboard_qscheduler_machines_api(request: HttpRequest) -> HttpResponse:
    """Dashboard card: machines of the chosen HEAppE's QScheduler clusters (empty when it uses none)."""
    instance_name = request.session.get("chosen_instance")
    if not instance_name:
        return _error("No HEAppE instance selected.")
    if not QSchedulerAssignment.objects.filter(heappe_instance__instance_name=instance_name).exists():
        return JsonResponse({'status': 'success', 'assigned': False, 'machines': []})
    try:
        rows = machines_overview(instance_name)
    except Exception as e:
        return JsonResponse({'status': 'error', 'assigned': True,
                             'message': f"Clusters of HEAppE '{instance_name}' cannot be listed: {_first_line(e)}"})
    return JsonResponse({'status': 'success', 'assigned': True, 'machines': rows})


@login_required
def qscheduler_cluster_suspension_api(request: HttpRequest, cluster_id: int) -> HttpResponse:
    """
    GET: state of the cluster's machine and the clusters that use it (for the confirmation dialog; ?users=0 skips
    collecting them).
    POST {action: suspend | resume, message, cancel, confirm_shared}: suspends / resumes the machine. A shared machine
    without confirm_shared gets HTTP 409 with status 'confirm' and the clusters that use it.
    """
    instance_name = request.session.get("chosen_instance")
    if request.method == "GET":
        with_users = request.GET.get("users", "1") != "0"      # users=0: state only (no other HEAppE is asked)
        try:
            return JsonResponse(dict(cluster_suspension_status(instance_name, cluster_id, with_users), status='success'))
        except Exception as e:
            return _error(_first_line(e))
    if request.method != "POST":
        return _error('Only GET and POST methods are allowed', 405)
    opts, errors = parse_suspend_options(_json_body(request), getattr(request.user, "username", ""))
    if errors:
        return _error(" ".join(errors))
    lines = []
    try:
        result = apply_suspension(instance_name, cluster_id, opts, lines.append)
    except PermissionError as e:
        status = e.args[0]
        return JsonResponse(dict(status, status='confirm',
                                 message=f"Machine '{status['machine']}' is used by other clusters. Confirm the action."),
                            status=409)
    except Exception as e:
        return _error(_first_line(e, 500))
    verb = "suspended" if opts['action'] == "suspend" else "resumed"
    return JsonResponse(dict(result, status='success', log=lines,
                             message=f"Machine '{result['machine']}' {verb}."))
