"""
QScheduler project prefix (HEAppE >= 6.7.0).

HEAppE 6.7.0 names its QScheduler projects and users "<prefix>.<name>", so several HEAppE instances can share one
QScheduler. The prefix is the cluster CustomConfiguration "QSchedulerProjectPrefix"; without it HEAppE falls back to
"QSchedulerNotifier", which is always "<identifier>.<machine>" here and contains '.', so HEAppE refuses to submit.

  * One prefix per HEAppE instance and QScheduler instance (QSchedulerAssignment.project_prefix): users keep one fair
    share across the machines of a QScheduler. It is chosen once (an explicit prefix already set on the clusters is
    adopted, otherwise the HEAppE identifier with '.' replaced) and never changed afterwards.
  * New clusters get it when they are created (Clusters page).
  * Existing clusters get it through the prefix migration below, which first renames the projects already in
    QScheduler ("<AccountingString>", or "<InstanceIdentifierPath>.<AccountingString>" written by HEAppE 6.7.0
    pre-releases without the prefix) to "<prefix>.<AccountingString>", so their consumption history stays attached.
    This replaces the manual scripts of HEAppE (QSchedulerScripts/ProjectPrefixMigration).

The rename runs in the QScheduler database while the service is stopped (it caches projects by name), after a
backup: only for instances deployed here with a shared or dedicated database. For other instances the SQL is shown
to run by hand. Users are not renamed: their history before the prefix stays under the old names.
"""
import json
from datetime import datetime, timezone

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, JsonResponse

from heappe_ui.models import QSchedulerAssignment, QSchedulerInstance as Q

from . import qscheduler_core as core
from . import qscheduler_shared_db as shared_db

QPU_USAGE_TYPES = (core.USAGE_TYPE_QPU_SECONDS, str(core.USAGE_TYPE_QPU_SECONDS), "QPUSeconds")
MAX_PROJECT_NAME = 250

# Plan row states
RENAME, DONE, NEW, CONFLICT, ERROR = "rename", "done", "new", "conflict", "error"


# ---------------------------------------------------------------------------
# Prefix of an assignment
# ---------------------------------------------------------------------------

def ensure_assignment_prefix(asg, identifier=None, clusters=(), save=True) -> str:
    """
    The project prefix of an assignment, chosen on first use: an explicit QSchedulerProjectPrefix shared by all the
    HEAppE's clusters on this QScheduler is adopted, otherwise the HEAppE identifier with '.' replaced. Unique among
    the assignments of the QScheduler instance. Never changed once set.
    """
    if asg.project_prefix:
        return asg.project_prefix
    explicit = {p for p in (core.cluster_project_prefix(c) for c in clusters or ()) if p}
    if len(explicit) == 1 and core.PREFIX_RE.match(next(iter(explicit))):
        prefix = explicit.pop()
    else:
        prefix = core.project_prefix_for(identifier or asg.heappe_identifier or asg.heappe_instance.instance_name)
    others = QSchedulerAssignment.objects.filter(qscheduler=asg.qscheduler)
    if asg.pk:
        others = others.exclude(pk=asg.pk)
    taken = set(others.exclude(project_prefix="").values_list("project_prefix", flat=True))
    base, n = prefix, 2
    while prefix in taken:
        prefix = f"{base[:core.PREFIX_MAX_LEN - 4]}-{n}"
        n += 1
    asg.project_prefix = prefix
    if save and asg.pk:
        asg.save(update_fields=["project_prefix", "updated_at"])
    return prefix


def prefix_change_error(asg, prefix) -> str:
    """Why `prefix` cannot become the assignment's prefix ("" when it can). Changeable until the first migration."""
    if not core.PREFIX_RE.match(prefix or ""):
        return (f"Prefix must be 1-{core.PREFIX_MAX_LEN} letters, digits, '-' or '_' (no '.': HEAppE splits "
                f"'<prefix>.<name>' at the first dot).")
    if prefix == asg.project_prefix:
        return ""
    if asg.projects_renamed_at:
        return (f"The prefix '{asg.project_prefix}' was migrated on {asg.projects_renamed_at:%Y-%m-%d}; it cannot "
                f"change any more (QScheduler users and their history keep the old names).")
    others = QSchedulerAssignment.objects.filter(qscheduler=asg.qscheduler, project_prefix=prefix)
    if asg.pk:
        others = others.exclude(pk=asg.pk)
    taken = others.select_related("heappe_instance").first()
    if taken:
        return f"Prefix '{prefix}' is used by HEAppE '{taken.heappe_instance.instance_name}' on this QScheduler."
    return ""


# ---------------------------------------------------------------------------
# HEAppE projects
# ---------------------------------------------------------------------------

def _get(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d.get(k)
    return None


def qpu_projects_by_cluster(controller, session_code) -> dict:
    """{cluster_id: [{'id', 'name', 'accounting_string'}]} of the HEAppE projects with usage type QPU seconds."""
    raw = controller.heappe_management_projects_get(SessionCode=session_code, _preload_content=False)
    data = raw.data.decode("utf-8") if isinstance(raw.data, bytes) else raw.data
    out = {}
    for p in json.loads(data or "[]"):
        if _get(p, 'UsageType', 'usage_type') not in QPU_USAGE_TYPES:
            continue
        acct = str(_get(p, 'AccountingString', 'accounting_string') or "").strip()
        row = {'id': _get(p, 'Id', 'id'), 'name': _get(p, 'Name', 'name'), 'accounting_string': acct}
        for sp in _get(p, 'ClusterProjectStoragePaths', 'cluster_project_storage_paths') or []:
            cid = _get(sp, 'ClusterId', 'cluster_id')
            if cid is not None:
                out.setdefault(cid, []).append(row)
    return out


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def can_rename_here(inst) -> bool:
    """The rename can run here: instance deployed by HEAppE Management with a shared or dedicated database."""
    return shared_db.can_backup(inst)


def build_plan(prefix, identifier, clusters, projects_by_cluster, qs_projects, previous=None) -> dict:
    """
    Pure part of the plan. clusters: HEAppE clusters of this HEAppE on the QScheduler; qs_projects: {name: project}.
    Returns {'clusters': [...], 'rows': [...], 'problems': [...]}; clusters with their own prefix are left alone,
    except those with `previous` (the assignment's prefix being replaced, before the first migration).
    """
    cluster_rows, rows, problems, seen = [], [], [], set()
    legacy = identifier if identifier and "." not in identifier and identifier != prefix else None
    previous = previous if previous and previous != prefix else None
    for c in clusters:
        current = core.cluster_project_prefix(c)
        replace = bool(previous and current == previous)
        cluster_rows.append({'id': c.get('id'), 'name': c.get('name'), 'machine': core.cluster_machine(c),
                             'prefix': current, 'set_prefix': not current or replace, 'replace': replace,
                             'kept': bool(current and current != prefix and not replace)})
        if current and not replace:
            if current != prefix:
                problems.append(f"Cluster '{c.get('name')}' already has prefix '{current}' (not '{prefix}'): it is "
                                f"kept, as a prefix must never change.")
            continue
        for p in projects_by_cluster.get(c.get('id'), []):
            acct = p['accounting_string']
            new = f"{prefix}.{acct}"
            if not acct or new in seen:
                continue
            seen.add(new)
            candidates = [acct] + ([f"{legacy}.{acct}"] if legacy else []) + ([f"{previous}.{acct}"] if previous else [])
            olds = [o for o in dict.fromkeys(candidates) if o in qs_projects]
            row = {'project': p['name'], 'accounting_string': acct, 'cluster': c.get('name'), 'old': None,
                   'new': new, 'consumed_ms': None, 'limit_ms': None}
            if len(new) > MAX_PROJECT_NAME:
                row['state'] = ERROR
                problems.append(f"'{new}' is longer than {MAX_PROJECT_NAME} characters.")
            elif len(olds) > 1:
                row['state'] = CONFLICT
                problems.append(f"Project '{acct}' exists in QScheduler as {' and '.join(olds)}: only one can keep its "
                                f"history. Merge or remove one of them in QScheduler first.")
            elif olds and new in qs_projects:
                row.update(state=CONFLICT, old=olds[0])
                problems.append(f"Both '{olds[0]}' and '{new}' exist in QScheduler (HEAppE already created the "
                                f"prefixed project): only one can keep its history.")
            elif olds:
                q = qs_projects[olds[0]]
                row.update(state=RENAME, old=olds[0], consumed_ms=q.get('consumed_ms'), limit_ms=q.get('limit_ms'))
            elif new in qs_projects:
                row['state'] = DONE
            else:
                row['state'] = NEW
            rows.append(row)
    return {'clusters': cluster_rows, 'rows': rows, 'problems': problems}


def _sql_literal(text):
    return "'" + str(text).replace("'", "''") + "'"


def rename_sql(rows, commit=True) -> str:
    """
    SQL renaming QScheduler projects (rows: [{'old', 'new'}]) in one transaction; fails without changes when a
    target name exists. Prints 'SHARED|<project>|<notifiers>' for projects used by several notifiers and
    'RENAMED|<count>'.
    """
    values = ",\n".join(f"  ({_sql_literal(r['old'])}, {_sql_literal(r['new'])})" for r in rows)
    return f"""BEGIN;
CREATE TEMP TABLE rename_map (old_name TEXT PRIMARY KEY, new_name TEXT NOT NULL UNIQUE) ON COMMIT DROP;
INSERT INTO rename_map (old_name, new_name) VALUES
{values};
SELECT 'SHARED|' || p.name || '|' || string_agg(DISTINCT COALESCE(n.name, '<no notifier>'), ',')
FROM projects p
JOIN rename_map m ON m.old_name = p.name
LEFT JOIN (SELECT project_id, notifier_id FROM tasks WHERE project_id IS NOT NULL
           UNION SELECT project_id, notifier_id FROM sessions) u ON u.project_id = p.id
LEFT JOIN notifiers n ON n.id = u.notifier_id
GROUP BY p.name HAVING count(DISTINCT u.notifier_id) > 1;
DO $$
DECLARE taken TEXT;
BEGIN
    SELECT string_agg(m.new_name, ', ') INTO taken FROM rename_map m JOIN projects p ON p.name = m.new_name;
    IF taken IS NOT NULL THEN
        RAISE EXCEPTION 'Target project names already exist: %', taken;
    END IF;
END $$;
UPDATE projects p SET name = m.new_name FROM rename_map m WHERE p.name = m.old_name;
SELECT 'RENAMED|' || count(*) FROM projects p JOIN rename_map m ON m.new_name = p.name;
{'COMMIT' if commit else 'ROLLBACK'};
"""


def migration_plan(asg, log=lambda *_: None, prefix=None) -> dict:
    """
    Plan of the prefix migration of one assignment (reads HEAppE and the QScheduler projects; changes nothing).
    `prefix` replaces the assignment's prefix (allowed until the first migration, see prefix_change_error).
    """
    if prefix:
        err = prefix_change_error(asg, prefix)
        if err:
            raise ValueError(err)
    from .clusters import connect_heappe_management_api

    inst, cred = asg.qscheduler, asg.heappe_instance
    version, identifier = core.heappe_identity(cred)
    controller, session_code, _ = connect_heappe_management_api(cred.instance_name, log)
    clusters = core.qscheduler_clusters(controller, session_code, inst)
    previous = asg.project_prefix if prefix and asg.project_prefix != prefix else None
    prefix = prefix or asg.project_prefix or ensure_assignment_prefix(asg, identifier, clusters, save=False)
    target = core.target_for(inst)
    try:
        qs_version = target.version()
        qs_projects = {p['name']: p for p in target.list_projects()}
    finally:
        target.close()
    plan = build_plan(prefix, identifier or asg.heappe_identifier, clusters,
                      qpu_projects_by_cluster(controller, session_code), qs_projects, previous)
    renames = [r for r in plan['rows'] if r['state'] == RENAME]
    plan.update({
        'assignment_id': asg.id, 'heappe_instance': cred.instance_name, 'heappe_version': version,
        'heappe_identifier': identifier or asg.heappe_identifier,
        'qscheduler': inst.name, 'qscheduler_version': qs_version, 'prefix': prefix,
        'prefix_saved': bool(asg.project_prefix) and prefix == asg.project_prefix, 'previous_prefix': previous,
        'saved_prefix': asg.project_prefix or None, 'prefix_editable': not asg.projects_renamed_at,
        'renamed_at': asg.projects_renamed_at.isoformat()
        if asg.projects_renamed_at else None,
        'heappe_supported': core.uses_project_prefix(version),
        'can_rename_here': can_rename_here(inst),
        'renames': len(renames), 'sql': rename_sql(renames) if renames else "",
        'pending': any(c['set_prefix'] for c in plan['clusters']) or prefix != asg.project_prefix,
    })
    plan['blocked'] = any(r['state'] in (CONFLICT, ERROR) for r in plan['rows'])
    return plan, controller, session_code, clusters


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def run_instance_sql(inst, sql, log):
    """Runs SQL in the database of an instance deployed here (shared schema or dedicated container); returns stdout."""
    docker = core.DockerCli()
    if inst.db_kind == Q.DB_SHARED:
        db = shared_db.require_running(docker)
        return shared_db.psql(docker, f"SET search_path TO {shared_db.ident(inst.db_schema)};\n" + sql, log,
                              db=db.database, container=db.name)
    if inst.db_kind == Q.DB_DEDICATED:
        return shared_db.psql(docker, sql, log, db="qscheduler", container=f"{inst.container_name}-pgsql",
                              user="qscheduler")
    raise RuntimeError("The rename runs here only for shared and dedicated databases.")


def _log_sql_output(out, log):
    renamed = None
    for line in (out or "").splitlines():
        kind, _, rest = line.partition("|")
        if kind == "SHARED":
            name, _, notifiers = rest.partition("|")
            log(f"NOTE: project '{name}' was used by several notifiers ({notifiers}): it may be shared with another "
                f"HEAppE; only this one keeps its history.")
        elif kind == "RENAMED":
            renamed = rest
    return renamed


def set_cluster_prefixes(controller, session_code, clusters, prefix, log, replace=None):
    """
    Sets QSchedulerProjectPrefix on the clusters that have none, or have `replace` (other settings and Vault values
    unchanged).
    """
    done = []
    for c in clusters:
        current = core.cluster_project_prefix(c)
        if current and not (replace and current == replace and current != prefix):
            continue
        cfg = dict(c.get('custom_configuration') or {})
        cfg[core.PREFIX_KEY] = prefix
        toggles = {k: bool(v) for k, v in (c.get('custom_configuration_vault_toggles') or {}).items()}
        controller.heappe_management_cluster_put(body=core._cluster_put_body(
            c, session_code, c.get('master_node_name'), c.get('port'), cfg, toggles))
        c.setdefault('custom_configuration', {})[core.PREFIX_KEY] = prefix
        log(f"Cluster '{c.get('name')}' (ID {c.get('id')}): {core.PREFIX_KEY} = '{prefix}'.")
        done.append(c.get('id'))
    return done


def prefix_migration_worker(log, result, asg_id, opts):
    """
    opts: dry_run (run the rename and roll it back), manual_done (the SQL was run by hand: only set the prefixes).
    Order: backup, stop QScheduler, rename, set the prefixes on the HEAppE clusters, start QScheduler. HEAppE never
    sees the clusters with the prefix while the old project names still exist.
    """
    asg = QSchedulerAssignment.objects.select_related("qscheduler", "heappe_instance").get(pk=asg_id)
    inst = asg.qscheduler
    log(f"=== QSCHEDULER: PROJECT PREFIX MIGRATION of HEAppE '{asg.heappe_instance.instance_name}' on '{inst.name}'"
        f"{' (dry run)' if opts.get('dry_run') else ''} ===")
    if inst.is_archived:
        raise RuntimeError(f"QScheduler instance '{inst.name}' is archived. Restore it first.")
    plan, controller, session_code, clusters = migration_plan(asg, log, opts.get('prefix') or None)
    prefix, previous = plan['prefix'], plan.get('previous_prefix')
    if previous:
        log(f"Prefix changes from '{previous}' to '{prefix}' (no migration has run yet).")
    log(f"HEAppE {plan['heappe_version'] or 'version unknown'}, QScheduler {plan['qscheduler_version'] or 'version unknown'}, "
        f"prefix '{prefix}'.")
    for p in plan['problems']:
        log(f"{'ERROR' if plan['blocked'] else 'NOTE'}: {p}")
    if plan['blocked']:
        raise RuntimeError("The migration is blocked by the conflicts above; nothing was changed.")
    if not plan['heappe_supported']:
        raise RuntimeError(f"HEAppE '{plan['heappe_instance']}' runs {plan['heappe_version'] or 'an unknown version'}: "
                           f"the project prefix needs HEAppE 6.7.0 or newer, older versions keep using the plain "
                           f"names. Upgrade HEAppE first, then run the migration before submitting QScheduler jobs.")
    renames = [r for r in plan['rows'] if r['state'] == RENAME]
    for r in plan['rows']:
        consumed = f" ({r['consumed_ms']} ms consumed)" if r.get('consumed_ms') is not None else ""
        log(f"  {r['state']:<8} {r['old'] or '-'} -> {r['new']}{consumed}")
    result.update({'prefix': prefix, 'renames': len(renames), 'dry_run': bool(opts.get('dry_run'))})

    if opts.get('dry_run'):
        if not renames:
            log("Nothing to rename.")
        elif not plan['can_rename_here']:
            log("The rename cannot run here (instance not deployed here with a shared or dedicated database).")
        else:
            out = run_instance_sql(inst, rename_sql(renames, commit=False), log)
            log(f"Dry run: {_log_sql_output(out, log) or 0} project(s) would be renamed; rolled back.")
        log("SUCCESS: dry run finished, nothing was changed.")
        return

    if renames and not plan['can_rename_here'] and not opts.get('manual_done'):
        raise RuntimeError("Run the shown SQL against the QScheduler database while QScheduler is stopped, start "
                           "QScheduler again and tick 'Projects renamed by hand'. Nothing was changed.")
    if opts.get('prefix'):
        asg.project_prefix = prefix
        asg.save(update_fields=["project_prefix", "updated_at"])
    else:
        ensure_assignment_prefix(asg, plan.get('heappe_identifier'), clusters)

    if renames and plan['can_rename_here']:
        shared_db.backup_instance(inst, log, plan['qscheduler_version'])
        target = core.target_for(inst)
        try:
            log(f"Stopping '{inst.container_name}' (QScheduler caches projects by name)...")
            target.docker.run(["stop", inst.container_name], log)
            try:
                out = run_instance_sql(inst, rename_sql(renames), log)
                log(f"{_log_sql_output(out, log) or 0} project(s) renamed in QScheduler.")
                result['clusters'] = set_cluster_prefixes(controller, session_code, clusters, prefix, log, previous)
            finally:
                log(f"Starting '{inst.container_name}'...")
                target.docker.run(["start", inst.container_name], log, check=False)
                target.wait_healthy(log)
        finally:
            target.close()
    else:
        if not renames:
            log("No projects to rename in QScheduler.")
        result['clusters'] = set_cluster_prefixes(controller, session_code, clusters, prefix, log, previous)

    asg.projects_renamed_at = datetime.now(timezone.utc)
    asg.save(update_fields=["project_prefix", "projects_renamed_at", "updated_at"])
    log("NOTE: QScheduler users are not renamed; the users' history before the prefix stays under the old names.")
    log(f"SUCCESS: HEAppE '{plan['heappe_instance']}' uses prefix '{prefix}' on '{inst.name}'.")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def _error(message, status=400):
    return JsonResponse({'status': 'error', 'message': message}, status=status)


@login_required
def qscheduler_prefix_plan_api(request: HttpRequest, asg_id: int) -> HttpResponse:
    asg = QSchedulerAssignment.objects.select_related("qscheduler", "heappe_instance").filter(pk=asg_id).first()
    if not asg:
        return _error("Assignment not found.", 404)
    prefix = (request.GET.get('prefix') or "").strip() or None
    try:
        plan = migration_plan(asg, prefix=prefix)[0]
    except ValueError as e:
        return _error(str(e))
    except Exception as e:
        return _error(f"Cannot build the plan: {str(e).splitlines()[0][:400]}", 500)
    return JsonResponse(dict(plan, status='success'))


@login_required
def qscheduler_prefix_migrate_api(request: HttpRequest, asg_id: int) -> HttpResponse:
    if request.method != "POST":
        return _error('Only POST method is allowed', 405)
    asg = QSchedulerAssignment.objects.select_related("qscheduler").filter(pk=asg_id).first()
    if not asg:
        return _error("Assignment not found.", 404)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = request.POST.dict()
    flag = lambda k: data.get(k) is True or str(data.get(k, "")).strip().lower() in ("1", "true", "on", "yes")
    prefix = str(data.get('prefix') or "").strip() or None
    if prefix:
        err = prefix_change_error(asg, prefix)
        if err:
            return _error(err)
    opts = {'dry_run': flag('dry_run'), 'manual_done': flag('manual_done'), 'prefix': prefix}
    ok, msg = core.start_operation("prefix_migration", prefix_migration_worker, asg_id, opts)
    return JsonResponse({'status': 'success' if ok else 'error', 'message': msg}, status=200 if ok else 409)
