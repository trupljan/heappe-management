from .imports import *
from .utils import _create_payload, _handle_api_call, login_required
from django.contrib import messages
from django.urls import reverse
import py4heappe.heappe_v6.core as hp
import json

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
            backups_list = [b.to_dict() for b in backups]
    except Exception as e:
        messages.error(request, f"Failed to retrieve database backups list: {e}")

    # Map backup types for display
    # 0 = Full Backup, 1 = Transaction Logs
    for b in backups_list:
        b_type = str(b.get("type", ""))
        if b_type == "0":
            b["type_name"] = "Full Backup"
            b["badge_class"] = "bg-primary"
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
