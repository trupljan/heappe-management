from .imports import *
from .utils import _create_payload, _handle_api_call, login_required
from django.contrib import messages
from django.urls import reverse
import py4heappe.heappe_v6.core as hp
import json
import re

from datetime import datetime

def parse_backup_dt(ts):
    if not ts:
        return None
    if hasattr(ts, 'strftime'):
        return ts
    if isinstance(ts, str):
        val = ts.replace('T', ' ').replace('Z', '').strip()
        if '.' in val:
            val = val.split('.', 1)[0]
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                pass
    return None

@login_required
def database_backups(request: HttpRequest) -> HttpResponse:
    # Ensure version >= 6.4.0
    version_error = ensure_heappe_version(
        request,
        "6.4.0",
        "Database Backup & Restore is only supported on HEAppE version 6.4.0 or newer.",
        "dashboard_view"
    )
    if version_error:
        return version_error

    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "backup_full":
            result = _handle_api_call(
                request,
                lambda: controller.heappe_management_backup_database_post(SessionCode=request.session_code),
                "Full database backup initiated successfully!",
                "Failed to initiate full database backup"
            )
            return redirect("database_backups")
        elif action == "backup_logs":
            result = _handle_api_call(
                request,
                lambda: controller.heappe_management_backup_database_transaction_logs_post(SessionCode=request.session_code),
                "Transaction logs backup initiated successfully!",
                "Failed to initiate transaction logs backup"
            )
            return redirect("database_backups")
        elif action == "restore":
            backup_file_name = request.POST.get("backup_file_name")
            include_logs = request.POST.get("include_logs") == "true"
            if not backup_file_name:
                messages.error(request, "Backup file name must be provided for restore.")
                return redirect("database_backups")
            
            from py4heappe.heappe_v6.core import RestoreDatabaseModel
            body = RestoreDatabaseModel(
                session_code=request.session_code,
                backup_file_name=backup_file_name,
                include_logs=include_logs
            )
            result = _handle_api_call(
                request,
                lambda: controller.heappe_management_restore_database_post(body=body),
                f"Database restore from '{backup_file_name}' initiated successfully!",
                "Failed to restore database"
            )
            return redirect("database_backups")

    # GET request - List backups
    backups_list = []
    try:
        backups = controller.heappe_management_backups_get(SessionCode=request.session_code)
        if backups:
            seen_file_names = set()
            for b in backups:
                d = b.to_dict()
                fn = d.get("file_name")
                if fn not in seen_file_names:
                    seen_file_names.add(fn)
                    backups_list.append(d)
    except Exception as e:
        messages.error(request, f"Failed to retrieve database backups list: {e}")

    # Read retention policy and scheduled runtime from appsettings.json
    daily_days = 7
    scheduled_runtime = "02:00:00"
    instance_name = request.session.get("chosen_instance")
    if instance_name:
        import os
        base_path = "/opt/heappe-deployment/"
        app_settings_path = os.path.join(base_path, instance_name, "app", "confs", "appsettings.json")
        if os.path.exists(app_settings_path):
            try:
                with open(app_settings_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    backup_settings = config.get("DatabaseFullBackupSettings", {})
                    retention = backup_settings.get("RetentionPolicy", {})
                    if "Daily" in retention:
                        daily_days = int(retention["Daily"])
                    if "ScheduledRuntime" in backup_settings:
                        scheduled_runtime = str(backup_settings["ScheduledRuntime"])
            except Exception as e:
                print(f"Error reading appsettings retention: {e}")

    scheduled_hour = 2
    scheduled_minute = 0
    if scheduled_runtime:
        parts = scheduled_runtime.split(":")
        if len(parts) >= 2:
            try:
                scheduled_hour = int(parts[0])
                scheduled_minute = int(parts[1])
            except ValueError:
                pass

    from datetime import datetime, timedelta, date, time

    # Determine reference date for daily checks based on the latest full backup in the list
    latest_dt = None
    for b in backups_list:
        b_type = str(b.get("type", ""))
        if b_type == "0":
            dt = parse_backup_dt(b.get("time_stamp"))
            if dt:
                if not latest_dt or dt > latest_dt:
                    latest_dt = dt

    ref_date = latest_dt.date() if latest_dt else date.today()

    # Map backup types for display
    # 0 = Full Backup, 1 = Transaction Logs
    for b in backups_list:
        b_type = str(b.get("type", ""))
        if b_type == "0":
            b["type_name"] = "Full Backup"
            b["badge_class"] = "bg-primary"

            # Retention policy flagging
            dt = parse_backup_dt(b.get("time_stamp"))
            retention_flags = []
            is_manual = True  # assume manual unless proven scheduled

            if dt:
                # Check if this matches the scheduled runtime within a 5-minute window
                sched_dt = datetime.combine(dt.date(), time(scheduled_hour, scheduled_minute))
                time_diff = abs((dt - sched_dt).total_seconds())
                is_scheduled = (time_diff <= 300)  # 5 minutes tolerance
                is_manual = not is_scheduled

                if is_scheduled:
                    # Monthly: 1st day of the month
                    if dt.day == 1:
                        retention_flags.append({
                            "label": "monthly",
                            "class": "bg-danger-subtle text-danger border-danger-subtle"
                        })
                    # Weekly: Sunday
                    if dt.weekday() == 6:
                        retention_flags.append({
                            "label": "weekly",
                            "class": "bg-warning-subtle text-warning-emphasis border-warning-subtle"
                        })
                    # Daily: within daily_days relative to ref_date
                    if dt.date() >= ref_date - timedelta(days=daily_days):
                        retention_flags.append({
                            "label": "daily",
                            "class": "bg-success-subtle text-success border-success-subtle"
                        })

            b["retention_flags"] = retention_flags
            b["is_manual"] = is_manual

        elif b_type == "1":
            b["type_name"] = "Transaction Logs"
            b["badge_class"] = "bg-info text-dark"
        else:
            b["type_name"] = f"Unknown ({b_type})"
            b["badge_class"] = "bg-secondary"

    # Sort backups by timestamp descending
    backups_list.sort(key=lambda x: x.get("time_stamp") or "", reverse=True)

    return render(request, "database_backups.html", {
        "backups": backups_list,
    })


# ── Migration Package ─────────────────────────────────────────────────────────

@login_required
def migration_package_view(request: HttpRequest) -> HttpResponse:
    """Render the Migration Package export/import page."""
    version_error = ensure_heappe_version(
        request,
        "6.4.0",
        "Migration Package is only supported on HEAppE version 6.4.0 or newer.",
        "dashboard_view"
    )
    if version_error:
        return version_error

    return render(request, "migration_package.html", {})


@login_required
def export_migration_package(request: HttpRequest) -> HttpResponse:
    """Export migration package – streams the binary .enc file to the browser."""
    if request.method != "POST":
        return redirect("migration_package")

    passphrase = request.POST.get("passphrase", "").strip()

    # Validate passphrase client-side validation is repeated here for safety
    if not _validate_passphrase(passphrase):
        messages.error(request, "Passphrase does not meet the security requirements (min 12 chars, uppercase, lowercase, special character).")
        return redirect("migration_package")

    controller = hp.ManagementApi(request.api_instance)

    try:
        kwargs = {
            "SessionCode": request.session_code,
            "_preload_content": False,
            "_return_http_data_only": True,
        }
        if passphrase:
            kwargs["Passphrase"] = passphrase

        raw_response = controller.heappe_management_export_migration_package_post(**kwargs)

        # When _preload_content=False the client returns a urllib3/RESTResponse object
        if hasattr(raw_response, "data"):
            content = raw_response.data
        elif hasattr(raw_response, "read"):
            content = raw_response.read()
        else:
            content = raw_response

        if not content:
            messages.error(request, "Export returned empty content. Verify that the HEAppE instance supports this operation.")
            return redirect("migration_package")

        http_response = HttpResponse(content, content_type="application/octet-stream")
        http_response["Content-Disposition"] = 'attachment; filename="migration_package.enc"'
        return http_response

    except Exception as e:
        messages.error(request, f"Failed to export migration package: {e}")
        return redirect("migration_package")


@login_required
def import_migration_package(request: HttpRequest) -> HttpResponse:
    """Import an .enc migration package file into HEAppE."""
    if request.method != "POST":
        return redirect("migration_package")

    passphrase = request.POST.get("passphrase", "").strip()
    uploaded_file = request.FILES.get("migration_file")

    if not uploaded_file:
        messages.error(request, "No migration package file was uploaded.")
        return redirect("migration_package")

    if not uploaded_file.name.endswith(".enc"):
        messages.error(request, "Invalid file type. Please upload an encrypted migration package (.enc) file.")
        return redirect("migration_package")

    if not _validate_passphrase(passphrase):
        messages.error(request, "Passphrase does not meet the security requirements (min 12 chars, uppercase, lowercase, special character).")
        return redirect("migration_package")

    try:
        import requests as req_lib

        # py4heappe's generated client has an incomplete multipart implementation
        # for this endpoint (empty if-block for local_var_files), so we call the
        # REST API directly using the base URL from the configured api_instance.
        base_url = request.api_instance.configuration.host

        params = {"SessionCode": request.session_code}
        if passphrase:
            params["Passphrase"] = passphrase

        file_bytes = uploaded_file.read()
        files = {"file": (uploaded_file.name, file_bytes, "application/octet-stream")}

        resp = req_lib.post(
            f"{base_url}/heappe/Management/ImportMigrationPackage",
            params=params,
            files=files,
            verify=False,
            timeout=300,
        )

        if resp.status_code == 200:
            messages.success(request, "Migration package imported and restored successfully!")
        else:
            try:
                detail = resp.json()
                messages.error(request, f"Import failed ({resp.status_code}): {detail}")
            except Exception:
                messages.error(request, f"Import failed ({resp.status_code}): {resp.text[:300]}")

    except Exception as e:
        messages.error(request, f"Failed to import migration package: {e}")

    return redirect("migration_package")


def _validate_passphrase(passphrase: str) -> bool:
    """Server-side passphrase validation mirroring the client-side rules."""
    if len(passphrase) < 12:
        return False
    if not re.search(r"[A-Z]", passphrase):
        return False
    if not re.search(r"[a-z]", passphrase):
        return False
    if not re.search(r"[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]", passphrase):
        return False
    return True
