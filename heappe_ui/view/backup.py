from heappe_ui.view.imports import *
from heappe_ui.view.utils import *
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from datetime import datetime, timedelta

@login_required
def backup_restore_view(request: HttpRequest) -> HttpResponse:
    """
    Simple UI for managing HEAppE database backups and restore operations.
    """
    controller = hp.ManagementApi(request.api_instance)

    # Handle actions
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "backup_database":
            _handle_api_call(
                request,
                lambda: controller.heappe_management_backup_database_post(SessionCode=request.session_code),
                "Full database backup triggered successfully.",
                "Failed to trigger full database backup",
            )
            return redirect("backup_restore")

        if action == "backup_transaction_logs":
            _handle_api_call(
                request,
                lambda: controller.heappe_management_backup_database_transaction_logs_post(SessionCode=request.session_code),
                "Transaction log backup triggered successfully.",
                "Failed to trigger transaction log backup",
            )
            return redirect("backup_restore")

        if action == "restore_database":
            backup_file_name = request.POST.get("backup_file_name")
            include_logs = request.POST.get("include_logs") == "on"

            if not backup_file_name:
                messages.error(request, "Backup file name is required for restore.")
                return redirect("backup_restore")

            payload_data = {
                "BackupFileName": backup_file_name,
                "IncludeLogs": include_logs,
            }
            payload = _create_payload(request.session_code, payload_data)

            _handle_api_call(
                request,
                lambda: controller.heappe_management_restore_database_post(**payload),
                f"Restore from '{backup_file_name}' triggered successfully.",
                "Failed to trigger database restore",
            )
            return redirect("backup_restore")

    # Filters for backups list
    raw_from = request.GET.get("from")
    raw_to = request.GET.get("to")
    raw_type = request.GET.get("type") or ""

    if raw_from is None and raw_to is None:
        raw_from = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M")
        raw_to = datetime.now().strftime("%Y-%m-%dT%H:%M")
    else:
        raw_from = raw_from or ""
        raw_to = raw_to or ""

    from_dt = None
    to_dt = None
    backup_type = None

    def _parse_dt(value: str):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    from_dt = _parse_dt(raw_from)
    to_dt = _parse_dt(raw_to)

    if raw_type != "":
        try:
            backup_type = int(raw_type)
        except ValueError:
            backup_type = None

    backups = []
    try:
        kwargs = {"SessionCode": request.session_code}
        if from_dt:
            kwargs["FromDateTime"] = from_dt
        if to_dt:
            kwargs["ToDateTime"] = to_dt
        if backup_type is not None:
            kwargs["Type"] = backup_type

        backups = controller.heappe_management_backups_get(**kwargs) or []
    except Exception as e:
        print(f"Error fetching backups: {e}")
        messages.error(request, f"Failed to load backups: {e}")

    context = {
        "backups": backups,
        "filters": {
            "from": raw_from,
            "to": raw_to,
            "type": raw_type,
            "is_type_0": str(raw_type) == "0",
            "is_type_1": str(raw_type) == "1",
        },
    }

    return render(request, "backup_restore.html", context)

