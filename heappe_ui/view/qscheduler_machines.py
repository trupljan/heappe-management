"""
Clusters page -> QScheduler: add / remove a quantum machine for the chosen HEAppE instance.

A machine lives in a QScheduler instance and can be shared by several HEAppE instances; each HEAppE has its
own cluster for it (Cluster: SchedulerType=QScheduler, ConnectionProtocol=Http, MasterNodeName = QScheduler
host; Queue = machine name). Only QScheduler instances assigned to the chosen HEAppE are offered.

Notifications are per cluster: when the assignment has notifications on, every new cluster gets its own
QScheduler notifier "<HEAppE identifier>.<machine>" with a freshly generated token. The cluster gets
EnableCallback=true, QSchedulerNotifier=<name> and QSchedulerNotifyToken=<token>, always stored in HEAppE Vault.
Removing the cluster removes its notifier.

HEAppE itself registers the project in QScheduler (POST /projects) on the first job submission, with the summed
QPU allocation as the limit. HEAppE >= 6.7.0 names it "<QSchedulerProjectPrefix>.<AccountingString>" (users
likewise): every new cluster gets the prefix of its HEAppE on this QScheduler (see qscheduler_prefix), so HEAppEs
sharing a QScheduler never share projects. QScheduler 0.2.2+ needs HEAppE 6.7.0+.

QScheduler 0.3.0 rejects tasks asking for more than the machine's max task time limit (default 15m), and HEAppE
sends the job walltime as the task time limit: the queue's MaxWalltime is the machine's max task time limit.
"""
import json
import re
import secrets
import uuid
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from heappe_ui.models import InstanceCredentials, QSchedulerAssignment, QSchedulerInstance as Q, QSchedulerMachine

from . import qscheduler_core as core
from .qscheduler_core import (CONNECTION_PROTOCOL_HTTP, DEFAULT_ACCOUNTING_FORMULA, DURATION_RE,
                              FILE_TRANSFER_PROTOCOL_HTTP, MACHINE_RE, MIN_HEAPPE_VERSION, NAME_RE,
                              SCHEDULER_TYPE_QSCHEDULER, USAGE_TYPE_QPU_SECONDS)
from .utils import clean_ver


# MaxWalltime of the queue of a machine on QScheduler < 0.3.0 (no maximum task time limit there)
LEGACY_QUEUE_WALLTIME = 86400


def parse_machine_options(data: dict, uid: str) -> tuple:
    """Options of the 'Add quantum machine' form. Returns (opts, errors)."""
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

    def i(key, default, lo, hi, label):
        raw = s(key)
        if raw == "":
            return default
        try:
            val = int(float(raw)) if re.fullmatch(r"\d+(\.0+)?", raw) else int(raw)
        except ValueError:
            errors.append(f"{label} must be an integer.")
            return default
        if not lo <= val <= hi:
            errors.append(f"{label} must be between {lo} and {hi}.")
        return val

    opts = {
        'qscheduler_id': s('qscheduler_id'),
        'machine_mode': s('machine_mode', 'new').lower(),
        'machine_name': s('machine_name', 'SimulatorMachine'),
        'backend': s('backend', 'test').lower(),
        'queue_size': i('queue_size', 4, 1, 100000, "Queue size"),
        'limit_check_interval': s('limit_check_interval', '2s'),
        'max_session_time': s('max_session_time', '2h'),
        'default_task_time_limit': s('default_task_time_limit', core.DEFAULT_TASK_TIME_LIMIT_030),
        'max_task_time_limit': s('max_task_time_limit', core.DEFAULT_MAX_TASK_TIME_LIMIT),   # QScheduler 0.3.0+
        'max_clock_skew': s('max_clock_skew', '4s'),
        'decay_half_time': s('decay_half_time', core.DEFAULT_DECAY_HALF_TIME),               # QScheduler 0.3.0+
        'pulse_access': b('pulse_access', False),   # pulse-level tasks (kind=pulse), QScheduler 0.2.2+
        'iqm_url': s('iqm_url'),
        'iqm_token': s('iqm_token'),
        'iqm_device': s('iqm_device'),
        'iqm_poll_interval': s('iqm_poll_interval', '500ms'),
        'host': s('host').lower(),          # "" = service host; or one of the instance's aliases
        'use_sessions': b('use_sessions', True),
        'create_project': b('create_project', True),
        'custom_name': b('custom_name', False),
        'project_name': s('project_name', f"qs-{uid}"),
        'qpu_allocation_seconds': i('qpu_allocation_seconds', None, 1, 10 ** 9, "QPU allocation"),
        'accounting_formula': s('accounting_formula', DEFAULT_ACCOUNTING_FORMULA),
    }
    if not opts['qscheduler_id'].isdigit():
        errors.append("Select the QScheduler instance.")
    if opts['machine_mode'] not in ('new', 'existing'):
        errors.append("Machine must be 'new' or 'existing'.")
    if not MACHINE_RE.match(opts['machine_name']):
        errors.append("Machine name may contain only letters, digits, '_', '.', '-' (max 30 chars).")
    # The cluster must be named after its machine (HEAppE uses the cluster name as the QScheduler machine).
    opts['cluster_name'] = opts['machine_name']
    if not opts['create_project']:
        opts.update({'custom_name': False, 'project_name': None, 'qpu_allocation_seconds': None})
    else:
        if not opts['custom_name']:
            opts['project_name'] = f"qs-{uid}"
        if not NAME_RE.match(opts['project_name']):
            errors.append("QScheduler project name may contain only letters, digits, '_', '.', '-'.")
    if opts['machine_mode'] != 'new':
        opts['pulse_access'] = False          # an existing machine keeps its own setting
    if opts['machine_mode'] == 'new':
        bad = []
        for key, label in (('limit_check_interval', "Limit check interval"), ('max_session_time', "Max session time"),
                           ('default_task_time_limit', "Default task time limit"),
                           ('max_task_time_limit', "Max task time limit"), ('max_clock_skew', "Max clock skew"),
                           ('decay_half_time', "Fair share decay half-time")):
            if not DURATION_RE.match(opts[key]):
                errors.append(f"{label} must be a duration with a unit, e.g. 2s, 30m, 2h.")
                bad.append(key)
        if not bad:
            if core.duration_ms(opts['decay_half_time']) < 1:
                errors.append("Fair share decay half-time must be at least 1ms.")
            limit_error = core.check_time_limits(opts)
            if limit_error:
                errors.append(limit_error)
        if opts['backend'] not in ('test', 'iqm'):
            errors.append("Backend must be 'test' or 'iqm'.")
        if opts['backend'] == 'iqm':
            if not opts['iqm_url'].startswith(("http://", "https://")):
                errors.append("IQM server URL is required (http/https).")
            if not opts['iqm_device']:
                errors.append("IQM device name (e.g. star24) is required.")
            if not opts['iqm_token']:
                errors.append("IQM token is required.")
            if not DURATION_RE.match(opts['iqm_poll_interval']):
                errors.append("IQM poll interval needs a unit suffix, e.g. 500ms or 1s.")
    return opts, errors


def _assignment_for(instance_name, inst_id):
    return (QSchedulerAssignment.objects.select_related("qscheduler", "heappe_instance")
            .filter(qscheduler_id=inst_id, heappe_instance__instance_name=instance_name).first())


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

def add_machine_worker(log, result, instance_name, opts, uid):
    from .clusters import connect_heappe_management_api

    asg = _assignment_for(instance_name, int(opts['qscheduler_id']))
    if not asg:
        raise RuntimeError(f"HEAppE '{instance_name}' is not assigned to this QScheduler instance (QScheduler page).")
    inst = asg.qscheduler
    if inst.is_archived:
        raise RuntimeError(f"QScheduler instance '{inst.name}' is archived. Restore it on the QScheduler page first.")
    machine = opts['machine_name']
    result.update({'qscheduler': inst.name, 'machine_name': machine, 'backend': opts['backend'],
                   'project_name': opts['project_name'], 'machine_mode': opts['machine_mode'], 'notifier': None})
    log(f"=== QSCHEDULER: ADD {'NEW' if opts['machine_mode'] == 'new' else 'EXISTING'} MACHINE '{machine}' "
        f"on '{inst.name}' for HEAppE '{instance_name}' ===")

    host = opts.get('host') or inst.service_host
    if host not in inst.hosts:
        raise RuntimeError(f"'{host}' is not the service host or an alias of '{inst.name}' "
                           f"(aliases: {', '.join(inst.aliases or []) or 'none'}).")
    result['host'] = host

    controller, session_code, _ = connect_heappe_management_api(instance_name, log)
    for c in core.qscheduler_clusters(controller, session_code, inst):
        if core.cluster_machine(c) == machine:
            raise RuntimeError(f"HEAppE cluster '{c.get('name')}' (ID {c.get('id')}) already uses machine '{machine}' "
                               f"on this QScheduler.")
        if host != inst.service_host and core.cluster_host(c) == host:
            raise RuntimeError(f"Alias '{host}' is already used by HEAppE cluster '{c.get('name')}' (ID {c.get('id')}): "
                               f"one cluster per alias (it moves with the cluster on a redirect).")
    core.check_cluster_name_free(controller, session_code, machine)

    # Notifier of this cluster (own token, kept in HEAppE Vault)
    notifier = None
    version, identifier = core.heappe_identity(asg.heappe_instance)
    if not core.supports_qscheduler(version):
        raise RuntimeError(core.unsupported_version_message(instance_name, version))
    # Project prefix of this HEAppE on this QScheduler (HEAppE >= 6.7.0 names projects and users "<prefix>.<name>")
    from .qscheduler_prefix import ensure_assignment_prefix
    prefix = ensure_assignment_prefix(asg, identifier, core.qscheduler_clusters(controller, session_code, inst))
    log(f"QScheduler project prefix of this HEAppE: '{prefix}' (projects and users '{prefix}.<name>').")
    if asg.notifications_enabled:
        if not asg.callback_url:
            raise RuntimeError("The assignment has notifications on but no callback URL. Edit the assignment on the "
                               "QScheduler page first.")
        else:
            if not asg.heappe_identifier:
                asg.heappe_identifier = identifier
                asg.save(update_fields=["heappe_identifier", "updated_at"])
            notifier = (core.cluster_notifier_name(asg.heappe_identifier, machine), core.new_notify_token())
    else:
        log("Notifications are off for this HEAppE on this QScheduler: no notifier, HEAppE polls task state.")

    target = core.target_for(inst)
    loaded = True
    cli_changed = False
    try:
        qs_version = target.version()
        error = core.compatibility_error(instance_name, version, inst.name, qs_version)
        if error:
            raise RuntimeError(error)
        result['qscheduler_version'] = qs_version
        machines = target.list_machines(log)
        names = {m['name'] for m in machines} if machines is not None else None
        if opts['machine_mode'] == 'new':
            if names is not None and machine in names:
                raise RuntimeError(f"Machine '{machine}' already exists in '{inst.name}' (it may be used by another HEAppE). "
                                   f"Choose 'Use existing machine' to share it, or another name.")
            log(f"Registering machine '{machine}' ({opts['backend']} backend)...")
            res = target.add_machine(opts, log)
            if res.returncode != 0:
                if re.search(r"already exists", res.output, re.I):
                    raise RuntimeError(f"Machine '{machine}' already exists in '{inst.name}'. Choose 'Use existing machine'.")
                raise RuntimeError(f"Machine registration failed:\n{res.output[-3000:]}")
            log("Machine registered.")
            backend, options = core.machine_definition(opts)
            QSchedulerMachine.objects.update_or_create(qscheduler=inst, name=machine,
                                                       defaults={'backend': backend, 'options': options})
            cli_changed = True
        else:
            if names is not None and machine not in names:
                raise RuntimeError(f"Machine '{machine}' does not exist in '{inst.name}' (known: {', '.join(sorted(names)) or 'none'}).")
            if names is None:
                log("Note: machines of this instance cannot be listed; the machine is verified over the REST API.")
            log(f"Using existing machine '{machine}' (shared with other HEAppE instances).")
            if core.supports_030(qs_version):
                cfg = target.machine_config(machine) or {}
                if cfg.get('max_task_time_limit_ms'):
                    opts['max_task_time_limit'] = core.format_duration(cfg['max_task_time_limit_ms'])
                    log(f"Machine '{machine}' accepts tasks of at most {opts['max_task_time_limit']}.")
        if notifier:
            current = {n['name']: n for n in target.list_notifiers(log)}
            if notifier[0] in current:
                log(f"Replacing stale notifier '{notifier[0]}' (no cluster of this HEAppE uses machine '{machine}').")
            cli_changed |= core.replace_notifiers(target, {notifier[0]: (asg.callback_url, notifier[1])}, (), current, log)
            result['notifier'] = notifier[0]
        if cli_changed:
            loaded = core.apply_changes(inst, target, log)   # one restart for machine + notifier
    finally:
        target.close()

    heappe_container = core.find_heappe_api_container(instance_name, log)
    if heappe_container and loaded:
        try:
            core.check_from_heappe(heappe_container, host, inst.port, f"/machine/{machine}/about", log, attempts=5)
        except RuntimeError as e:
            if opts['machine_mode'] == 'existing':
                raise RuntimeError(f"Machine '{machine}' is not served by '{inst.name}': {e}")
            log(f"WARNING: {e}")
    elif not loaded:
        log(f"WARNING: '{inst.name}' must be restarted before the machine is available.")

    # HEAppE registration
    custom_config, vault_toggles = core.build_cluster_custom_configuration(inst, notifier, opts['use_sessions'], host,
                                                                           prefix)
    opts['queue_walltime'] = (core.walltime_seconds(opts['max_task_time_limit']) if core.supports_030(qs_version)
                              else LEGACY_QUEUE_WALLTIME)
    opts['project_prefix'] = prefix
    log("Creating QScheduler Cluster in HEAppE (protocol HTTP, direct REST calls)...")
    try:
        cluster_id = _create_cluster(controller, session_code, inst, machine, opts, custom_config, vault_toggles)
    except Exception:
        if notifier:
            log(f"Cluster creation failed: removing notifier '{notifier[0]}' again.")
            cleanup = core.target_for(inst)
            try:
                cleanup.remove_notifier(notifier[0], log, check=False)
            finally:
                cleanup.close()
        raise
    result['cluster_id'] = cluster_id
    log(f"Cluster created (ID: {cluster_id}); callbacks "
        f"{'via notifier ' + repr(notifier[0]) + ', token stored in Vault' if notifier else 'disabled (HEAppE polls task state)'}.")
    _register_cluster_resources(log, result, controller, session_code, inst, machine, opts, uid, cluster_id)


def _create_cluster(controller, session_code, inst, machine, opts, custom_config, vault_toggles):
    return core.id_of(controller.heappe_management_cluster_post(body={
        "Name": opts['cluster_name'],
        "Description": f"QScheduler machine {machine} ({inst.name})",
        "MasterNodeName": opts.get('host') or inst.service_host,
        "SchedulerType": SCHEDULER_TYPE_QSCHEDULER,
        "ConnectionProtocol": CONNECTION_PROTOCOL_HTTP,
        "TimeZone": "UTC",
        "Port": inst.port,
        "UpdateJobStateByServiceAccount": False,
        "DomainName": "",
        "ProxyConnectionId": None,
        "CustomConfiguration": custom_config,
        "CustomConfigurationVaultToggles": vault_toggles,
        "SessionCode": session_code,
    }))


def _register_cluster_resources(log, result, controller, session_code, inst, machine, opts, uid, cluster_id):
    """File transfer method, queue group + accounting, queue and the optional project of a new cluster."""
    now = datetime.utcnow() - timedelta(minutes=5)
    valid_to = now + timedelta(days=365)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    ftm_id = core.id_of(controller.heappe_management_file_transfer_method_post(body={
        "ClusterId": cluster_id, "ServerHostname": opts.get('host') or inst.service_host,
        "Protocol": FILE_TRANSFER_PROTOCOL_HTTP,
        "Port": inst.port, "SessionCode": session_code}))
    log(f"File Transfer Method created (ID: {ftm_id}).")

    group_id = core.id_of(controller.heappe_management_cluster_node_type_aggregation_post(body={
        "Name": f"QPU Group {uid}", "Description": f"QPU time on {machine}",
        "AllocationType": "QPU", "ValidityFrom": now.strftime(fmt), "ValidityTo": valid_to.strftime(fmt),
        "SessionCode": session_code}))
    log(f"Queue Group created (ID: {group_id}).")

    accounting_id = core.id_of(controller.heappe_management_accounting_post(body={
        "Formula": opts['accounting_formula'], "ValidityFrom": now.strftime(fmt),
        "ValidityTo": valid_to.strftime(fmt), "SessionCode": session_code}))
    controller.heappe_management_cluster_node_type_aggregation_accounting_post(body={
        "ClusterNodeTypeAggregationId": group_id, "AccountingId": accounting_id, "SessionCode": session_code})
    log(f"Accounting formula '{opts['accounting_formula']}' created (ID: {accounting_id}) and mapped.")

    queue_id = core.id_of(controller.heappe_management_cluster_node_type_post(body={
        "Name": machine[:50], "Description": f"QScheduler machine {machine}",
        "NumberOfNodes": 1, "CoresPerNode": 1, "Queue": machine, "QualityOfService": None,
        "MaxWalltime": opts.get('queue_walltime') or LEGACY_QUEUE_WALLTIME, "ClusterAllocationName": None,
        "ClusterId": cluster_id, "FileTransferMethodId": ftm_id, "ClusterNodeTypeAggregationId": group_id,
        "SessionCode": session_code}))
    log(f"Queue '{machine}' created (ID: {queue_id}, max walltime {opts.get('queue_walltime') or LEGACY_QUEUE_WALLTIME} s"
        f"{': the machine max task time limit' if opts.get('queue_walltime') else ''}).")

    project_id = None
    if opts['create_project']:
        project_id = core.id_of(controller.heappe_management_project_post(body={
            "Name": opts['project_name'], "Description": f"Quantum project on {machine}",
            "AccountingString": opts['project_name'], "StartDate": now.strftime(fmt),
            "EndDate": valid_to.strftime(fmt), "UsageType": USAGE_TYPE_QPU_SECONDS,
            "UseAccountingStringForScheduler": True, "IsOneToOneMapping": False, "PIEmail": "",
            "SessionCode": session_code}))
        qs_name = f"{opts['project_prefix']}.{opts['project_name']}" if opts.get('project_prefix') else opts['project_name']
        log(f"Project created (ID: {project_id}, QScheduler project name '{qs_name}', registered by HEAppE on the "
            f"first job).")
        controller.heappe_management_project_assignment_to_cluster_post(body={
            "ProjectId": project_id, "ClusterId": cluster_id, "ScratchStoragePath": "/tmp",
            "PermanentStoragePath": "/tmp", "ProjectStoragePath": "/tmp", "SessionCode": session_code})
        if opts.get('qpu_allocation_seconds') is not None:
            controller.heappe_management_project_cluster_node_type_aggregation_post(body={
                "ProjectId": project_id, "ClusterNodeTypeAggregationId": group_id,
                "AllocationAmount": opts['qpu_allocation_seconds'], "SessionCode": session_code})
            log(f"Project assigned to cluster with {opts['qpu_allocation_seconds']} QPU seconds.")
        else:
            log("No QPU allocation given: HEAppE rejects QScheduler jobs for this project until an allocation is added "
                "(Projects > Queue Groups).")
        # HTTP clusters ignore the credential content, but HEAppE needs one per project/cluster to submit.
        try:
            controller.heappe_management_generate_secure_shell_key_post(body={
                "Credentials": [{"Username": "qscheduler", "Password": secrets.token_urlsafe(16)}],
                "ProjectId": project_id, "SessionCode": session_code})
            log("Service credential for the project created.")
        except Exception as e_cred:
            log(f"WARNING: could not create project credential ({e_cred}). Add one in Projects > Credentials before submitting jobs.")
    else:
        log("Project creation skipped (not requested). Add a project, QPU allocation and credential in HEAppE "
            "(Projects) before submitting QScheduler jobs.")

    result.update({'project_id': project_id, 'queue_id': queue_id})
    log("SUCCESS: quantum machine available in HEAppE.")


def remove_machine_worker(log, result, instance_name, opts):
    from .clusters import connect_heappe_management_api

    controller, session_code, _ = connect_heappe_management_api(instance_name, log)
    cluster = core.as_dict(controller.heappe_management_cluster_get(Id=opts['cluster_id'], SessionCode=session_code))
    if cluster.get('scheduler_type') != SCHEDULER_TYPE_QSCHEDULER:
        raise RuntimeError(f"Cluster {opts['cluster_id']} is not a QScheduler cluster.")
    machine = core.cluster_machine(cluster)
    inst = _instance_of_cluster(cluster)
    notifier = (cluster.get('custom_configuration') or {}).get(core.NOTIFIER_KEY) or None
    result.update({'cluster_id': cluster.get('id'), 'cluster_name': cluster.get('name'), 'machine_name': machine,
                   'qscheduler': inst.name if inst else None, 'removed_from_qscheduler': False,
                   'removed_notifier': None})
    log(f"=== QSCHEDULER: REMOVE MACHINE '{machine}' (cluster '{cluster.get('name')}', HEAppE '{instance_name}') ===")

    # 1. QScheduler first: without --force it refuses while the machine has tasks/sessions, nothing is changed then.
    if opts['remove_from_qscheduler'] and not inst:
        raise RuntimeError("The cluster's QScheduler instance is not registered in HEAppE Management; "
                           "cannot remove the machine from QScheduler (untick the option to delete only the cluster).")
    if inst and inst.is_archived:
        if opts['remove_from_qscheduler']:
            raise RuntimeError(f"QScheduler instance '{inst.name}' is archived (its service is gone); untick "
                               f"'Also remove the machine from QScheduler' to delete only the HEAppE cluster.")
        log(f"QScheduler instance '{inst.name}' is archived: QScheduler is not contacted"
            f"{f' (notifier {notifier!r} is gone with it)' if notifier else ''}.")
    elif inst and (opts['remove_from_qscheduler'] or notifier):
        target = core.target_for(inst)
        try:
            changed = False
            if opts['remove_from_qscheduler']:
                res = target.remove_machine(machine, opts['force'], log)
                if res.returncode != 0:
                    if re.search(r"not found", res.output, re.I):
                        log(f"Machine '{machine}' is not registered in '{inst.name}' (already removed).")
                    else:
                        hint = "" if opts['force'] else " If it still has tasks or sessions, retry with 'Force removal'."
                        raise RuntimeError(f"Removing machine '{machine}' failed: {res.output.splitlines()[-1] if res.output else 'no output'}."
                                           f"{hint}\n{res.output[-3000:]}")
                else:
                    log(res.stdout.strip() or "Machine removed.")
                    result['removed_from_qscheduler'] = True
                    changed = True
                QSchedulerMachine.objects.filter(qscheduler=inst, name=machine).delete()
            if notifier:
                current = {n['name']: n for n in target.list_notifiers(log)}
                if notifier in current:
                    changed |= core.replace_notifiers(target, {}, {notifier}, current, log)
                    result['removed_notifier'] = notifier
                else:
                    log(f"Notifier '{notifier}' is not registered in '{inst.name}'.")
            if changed:
                core.apply_changes(inst, target, log)
        finally:
            target.close()
    elif notifier:
        log(f"WARNING: notifier '{notifier}' could not be removed: the QScheduler instance is not registered here.")
    if opts['remove_from_qscheduler']:
        log("NOTE: clusters of other HEAppE instances that used this machine stop working.")
    else:
        log("Machine kept in QScheduler (other HEAppE instances may use it).")

    # 2. HEAppE cluster
    try:
        controller.heappe_management_cluster_delete(body={"Id": cluster.get('id'), "SessionCode": session_code})
    except Exception as e:
        msg = f"Deleting HEAppE cluster '{cluster.get('name')}' failed: {e}"
        if result['removed_from_qscheduler']:
            msg = f"Machine '{machine}' was removed from QScheduler, but d{msg[1:]}"
        raise RuntimeError(msg)
    log(f"Deleted HEAppE cluster '{cluster.get('name')}' (ID: {cluster.get('id')}). Projects, allocations and "
        f"credentials are kept; delete them in HEAppE if no longer needed.")
    log("SUCCESS: quantum machine removed.")


def _instance_of_cluster(cluster):
    cfg = cluster.get('custom_configuration') or {}
    host = cfg.get("QSchedulerHost") or cluster.get('master_node_name')
    port = str(cfg.get("QSchedulerPort") or cluster.get('port') or "")
    for inst in Q.objects.filter(service_host=host):
        if str(inst.port) == port:
            return inst
    for inst in Q.objects.all():                          # clusters using an alias of the instance
        if host in (inst.aliases or []) and str(inst.port) == port:
            return inst
    return None


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


@login_required
def qscheduler_machine_defaults_api(request: HttpRequest) -> HttpResponse:
    """Assigned QScheduler instances of the chosen HEAppE, and its QScheduler clusters (for removal)."""
    from .clusters import connect_heappe_management_api
    instance_name = request.session.get("chosen_instance")
    version = request.session.get("middleware_deployed_version", "") or ""
    assignments = (QSchedulerAssignment.objects.select_related("qscheduler")
                   .filter(heappe_instance__instance_name=instance_name).order_by("qscheduler__name"))
    instances = [{'id': a.qscheduler.id, 'name': a.qscheduler.name, 'kind': a.qscheduler.get_kind_display(),
                  'kind_code': a.qscheduler.kind,
                  'endpoint': f"{a.qscheduler.service_host}:{a.qscheduler.port}",
                  'service_host': a.qscheduler.service_host, 'aliases': a.qscheduler.aliases or [],
                  'notifications_enabled': a.notifications_enabled, 'callback_url': a.callback_url,
                  'restart_pending': a.qscheduler.restart_pending,
                  'archived': a.qscheduler.is_archived} for a in assignments]
    clusters, clusters_error = [], None
    try:
        controller, session_code, _ = connect_heappe_management_api(instance_name, lambda *_: None)
        by_id = {a.qscheduler.id: a.qscheduler for a in assignments}
        for c in controller.heappe_management_clusters_get(SessionCode=session_code) or []:
            d = core.as_dict(c)
            if d.get('scheduler_type') != SCHEDULER_TYPE_QSCHEDULER:
                continue
            inst = _instance_of_cluster(d)
            clusters.append({'id': d.get('id'), 'name': d.get('name'), 'machine': core.cluster_machine(d),
                             'qscheduler_id': inst.id if inst else None,
                             'qscheduler_kind': inst.kind if inst else None,
                             'qscheduler_archived': bool(inst and inst.is_archived),
                             'qscheduler': inst.name if inst else f"{d.get('master_node_name')} (not registered)",
                             'assigned': bool(inst and inst.id in by_id)})
    except Exception as e:
        clusters_error = str(e).splitlines()[0][:300]
    return JsonResponse({
        'status': 'success', 'instance_name': instance_name, 'instances': instances, 'clusters': clusters,
        'clusters_error': clusters_error, 'version': version,
        'version_supported': core.supports_qscheduler(version),
        'min_version': core.MIN_HEAPPE_VERSION_TEXT,
    })


@login_required
def qscheduler_machine_list_api(request: HttpRequest, inst_id: int) -> HttpResponse:
    """Machines registered in an assigned QScheduler instance (None when they cannot be listed)."""
    asg = _assignment_for(request.session.get("chosen_instance"), inst_id)
    if not asg:
        return _error("This QScheduler instance is not assigned to the current HEAppE instance.", 404)
    target = None
    try:
        target = core.target_for(asg.qscheduler)
        return JsonResponse({'status': 'success', 'machines': target.list_machines()})
    except Exception as e:
        return JsonResponse({'status': 'success', 'machines': None, 'message': str(e).splitlines()[0][:300]})
    finally:
        if target:
            target.close()


@login_required
def qscheduler_machine_add_api(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    version = request.session.get("middleware_deployed_version", "") or ""
    if not core.supports_qscheduler(version):
        return _error(core.unsupported_version_message(request.session.get("chosen_instance") or "current", version))
    uid = str(uuid.uuid4())[:8]
    opts, errors = parse_machine_options(_json_body(request), uid)
    if errors:
        return _error(" ".join(errors))
    instance_name = request.session.get("chosen_instance")
    if not _assignment_for(instance_name, int(opts['qscheduler_id'])):
        return _error("This QScheduler instance is not assigned to the current HEAppE instance. Assign it on the QScheduler page.")
    ok, msg = core.start_operation("add_machine", add_machine_worker, instance_name, opts, uid)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)


@login_required
def qscheduler_machine_remove_api(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    data = _json_body(request)
    raw_id = str(data.get('cluster_id') or "").strip()
    if not raw_id.isdigit():
        return _error("Select the cluster to remove.")
    flag = lambda k, d=False: (data.get(k) if isinstance(data.get(k), bool)
                               else str(data.get(k, d)).strip().lower() in ("1", "true", "on", "yes"))
    opts = {'cluster_id': int(raw_id), 'remove_from_qscheduler': flag('remove_from_qscheduler'), 'force': flag('force')}
    ok, msg = core.start_operation("remove_machine", remove_machine_worker, request.session.get("chosen_instance"), opts)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)
