from heappe_ui.auth_backend import HeappeAuthBackend
from heappe_ui.view.imports import *
from heappe_ui.view.utils import *
from heappe_ui.view.utils import _create_payload, _handle_api_call
from heappe_ui.view.clusters import *
from heappe_ui.view.qscheduler_deploy import (qscheduler_page, qscheduler_local_docker_api, qscheduler_git_refs_api, qscheduler_operation_status_api,
                                              qscheduler_deploy_api, qscheduler_register_api, qscheduler_heappe_info_api,
                                              qscheduler_live_api, qscheduler_update_api, qscheduler_restart_api,
                                              qscheduler_undeploy_api, qscheduler_assign_api, qscheduler_unassign_api,
                                              qscheduler_notifier_remove_api)
from heappe_ui.view.qscheduler_recovery import (qscheduler_archive_api, qscheduler_unarchive_api,
                                                qscheduler_cascade_preview_api, qscheduler_cascade_delete_api,
                                                qscheduler_restore_info_api, qscheduler_restore_api)
from heappe_ui.view.qscheduler_machines import (qscheduler_machine_defaults_api, qscheduler_machine_list_api,
                                                qscheduler_machine_add_api, qscheduler_machine_remove_api)
from heappe_ui.view.queue import *
from heappe_ui.view.file_transfer_method import *
from heappe_ui.view.project import *
from heappe_ui.view.accounting import *
from heappe_ui.view.deploy import *
from heappe_ui.view.command_template import *
from heappe_ui.view.adaptor_user import *
from heappe_ui.view.backups import *
from heappe_ui.view.admin_users import *
from heappe_ui.view.docs import *
from heappe_ui.view.integration import *
from heappe_ui.view.telemetry import *

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
import datetime


from .DeployService import get_instance_settings

@login_required
def index(request: HttpRequest) -> HttpResponse:
    return dashboard_view(request)

@login_required
def home(request: HttpRequest) -> HttpResponse:
    return dashboard_view(request)


@login_required
def logout_view(request):
    from django.contrib.auth import logout
    HeappeAuthBackend.api_instance = None
    HeappeAuthBackend.session_code = None
    request.session.flush()
    logout(request)
    return redirect("login")

@login_required
def aggregation_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        payload_data = {
            "Name": request.POST.get("Name", ""),
            "Description": request.POST.get("Description", ""),
            "AllocationType": request.POST.get("AllocationType", "NodeHour"),
            "ValidityFrom": request.POST.get("ValidityFrom"),
            "ValidityTo": request.POST.get("ValidityTo"),
        }
        payload = _create_payload(request.session_code, payload_data)
        return _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_post(**payload),
            "Cluster Node Type Aggregation created successfully!",
            "Failed to create Cluster Node Type Aggregation",
            redirect_url='aggregations'
        )
    return render(request, 'create_aggregation.html')



@login_required
def assign_project_to_cluster(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        action = request.POST.get("action")
        if action == "assign_cluster":
            payload_data = {
                "ProjectId": int(request.POST.get("ProjectId")),
                "ClusterId": int(request.POST.get("ClusterId")),
                "ScratchStoragePath": request.POST.get("ScratchStoragePath", ""),
                "PermanentStoragePath": request.POST.get("PermanentStoragePath", ""),
                "ProjectStoragePath": request.POST.get("ProjectStoragePath", "")
            }
            payload = _create_payload(request.session_code, payload_data)
            return _handle_api_call(
                request,
                lambda: controller.heappe_management_project_assignment_to_cluster_post(**payload),
                "Project assigned to cluster successfully!",
                "Failed to assign project to cluster",
                redirect_url=f"/clusters/{int(request.POST.get('ClusterId'))}/?tab=projects"
            )
    return render(request, "assign_project_to_cluster.html")

@login_required
def list_jobs(request: HttpRequest) -> HttpResponse:
    # Placeholder for listing jobs
    return HttpResponse(status=204)


import subprocess
import os
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_protect
from django.conf import settings

import os
import subprocess
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render

import json
import subprocess
import os
from django.http import JsonResponse
from django.shortcuts import render
from django.conf import settings




@login_required
def profile_view(request):
    from django.contrib.auth.models import User
    from django.contrib.auth import update_session_auth_hash

    user = request.user
    if request.method == "POST" and "update_profile" in request.POST:
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "").strip()
        confirm_password = request.POST.get("confirm_password", "").strip()

        if not username:
            messages.error(request, "Username cannot be empty.")
        elif User.objects.filter(username=username).exclude(id=user.id).exists():
            messages.error(request, f"Username '{username}' is already taken.")
        elif password and password != confirm_password:
            messages.error(request, "Passwords do not match.")
        else:
            user.username = username
            user.email = email
            if password:
                user.set_password(password)
            user.save()
            if password:
                update_session_auth_hash(request, user)
            messages.success(request, "Your profile details have been updated successfully.")
            return redirect("profile_view")

    last_auth_ts = request.session.get("heappe_last_auth")
    if last_auth_ts:
        try:
            last_auth = datetime.fromtimestamp(float(last_auth_ts))
        except (ValueError, TypeError):
            last_auth = None
    else:
        last_auth = None

    return render(request, "user_profile.html", {"user": user, "last_auth": last_auth})

@login_required
def generate_session_code_view(request):
    from django.http import JsonResponse
    import py4heappe.heappe_v6.core as hp
    import json
    from heappe_ui.auth_backend import patch_api_client

    username = request.session.get("heappe_username")
    password = request.session.get("heappe_password")
    host = request.session.get("heappe_host")

    if not all([username, password, host]):
        return JsonResponse({"status": "error", "message": "Missing credentials in session."}, status=400)

    config = hp.Configuration()
    host_url = 'http://' + host if not host.startswith('http') else host
    config.host = host_url
    config.verify_ssl = True

    api_instance = hp.ApiClient(config)
    patch_api_client(api_instance)

    ulm = hp.UserAndLimitationManagementApi(api_instance)
    cred = {
        "_preload_content": False,
        "body": {
            "Credentials": {
                "Username": username,
                "Password": password,
            }
        }
    }

    try:
        r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(**cred)
        session_code = json.loads(r.data)
        if session_code:
            request.session["heappe_session_code"] = session_code
            return JsonResponse({"status": "success", "session_code": session_code})
        else:
            return JsonResponse({"status": "error", "message": "HEAppE returned empty session code."}, status=500)
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Failed to authenticate with HEAppE: {str(e)}"}, status=500)

@login_required
def reconnect_view(request):
    request.session["force_reauth"] = True
    # Clear middleware update cache
    request.session.pop("last_middleware_check_time", None)
    request.session.pop("last_middleware_checked_instance", None)
    request.session.pop("middleware_update_available", None)
    request.session.pop("middleware_deployed_version", None)
    request.session.pop("middleware_latest_version", None)
    # reload
    return redirect(request.META.get('HTTP_REFERER', '/'))  # Redirect back to the previous page or home if no referrer


@login_required
def chose_instance_view(request):
    if request.method == "POST":
        instance_name = request.POST.get("InstanceName")
        if instance_name:
            request.session["chosen_instance"] = instance_name
            request.session["force_reauth"] = True
            # Clear old instance connection variables to prevent leakage/fallback
            request.session.pop("heappe_session_code", None)
            request.session.pop("heappe_host", None)
            request.session.pop("heappe_host_url", None)
            request.session.pop("heappe_use_api_key", None)
            request.session.pop("heappe_last_auth", None)
            request.session.pop("heappe_last_failed_auth", None)
            return redirect("dashboard_view")

    instances = InstanceCredentials.objects.all()
    return render(request, "chose_instances.html", {"instances": instances})



from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from datetime import datetime, timedelta, timezone as dt_timezone

@login_required
def dashboard_view(request):
    context = {}
    if request.session.get("chosen_instance") is None:
        return redirect("instance_credentials_list")

    # Set default time range: TimeTo=Now, TimeFrom=Now-1day (using UTC timezone-aware datetimes)
    time_to = request.GET.get('time_to', datetime.now(dt_timezone.utc).isoformat())
    time_from = request.GET.get('time_from', (datetime.now(dt_timezone.utc) - timedelta(days=1)).isoformat())

    # Convert string dates to datetime if needed by API, ensuring they are timezone-aware in UTC
    try:
        time_to = datetime.fromisoformat(time_to)
        if time_to.tzinfo is None:
            time_to = time_to.replace(tzinfo=dt_timezone.utc)
        time_from = datetime.fromisoformat(time_from)
        if time_from.tzinfo is None:
            time_from = time_from.replace(tzinfo=dt_timezone.utc)
    except ValueError:
        time_to = datetime.now(dt_timezone.utc)
        time_from = datetime.now(dt_timezone.utc) - timedelta(days=1)

    # Enforce maximum scope of 90 days back and maximum range of 90 days
    now = datetime.now(dt_timezone.utc)
    min_allowed_date = now - timedelta(days=90)

    if time_to < min_allowed_date:
        time_to = now
    elif time_to > now + timedelta(hours=1):
        time_to = now

    if time_from < min_allowed_date:
        time_from = min_allowed_date
    elif time_from > time_to:
        time_from = time_to - timedelta(days=1)

    if (time_to - time_from) > timedelta(days=90):
        time_from = time_to - timedelta(days=90)

    # Check if HEAppE version >= 6.5.0 (Admin API support)
    current_version = request.session.get("middleware_deployed_version", "")
    if not current_version:
        try:
            health_api = hp.HealthApi(request.api_instance)
            health_info = health_api.heappe_health_get()
            current_version = health_info.version.lstrip("vV") if health_info and getattr(health_info, 'version', None) else "0.0.0"
            if current_version and current_version != "0.0.0":
                request.session["middleware_deployed_version"] = current_version
        except Exception as e:
            current_version = "0.0.0"

    is_admin_api = False
    try:
        if clean_ver(current_version) >= clean_ver("6.5.0"):
            is_admin_api = True
    except Exception:
        is_admin_api = False

    context["is_admin_api"] = is_admin_api

    # Store for template
    context["time_to"] = time_to.strftime('%Y-%m-%dT%H:%M')
    context["time_from"] = time_from.strftime('%Y-%m-%dT%H:%M')
    context["min_date"] = min_allowed_date.strftime('%Y-%m-%dT%H:%M')
    context["max_date"] = now.strftime('%Y-%m-%dT%H:%M')

    return render(request, "dashboard.html", context)


@login_required
def dashboard_health_partial(request: HttpRequest) -> HttpResponse:
    context = {}
    controller = hp.ManagementApi(request.api_instance)
    health_controller = hp.HealthApi(request.api_instance)

    # Get HEAppE Health Info
    deployed_version = ""
    try:
        health_info = health_controller.heappe_health_get()
        health = health_info.to_dict() if hasattr(health_info, "to_dict") else health_info
        context["health"] = health
        if health_info:
            if hasattr(health_info, "version") and health_info.version:
                deployed_version = health_info.version.lstrip("vV")
            elif isinstance(health_info, dict) and health_info.get("version"):
                deployed_version = health_info["version"].lstrip("vV")
    except Exception as e:
        print(f"Error fetching health info: {e}")
        context["health"] = {
            "IsHealthy": False,
            "Error": str(e)
        }

    # HEAppE Middleware Banner Logic
    instance_name = request.session.get("chosen_instance")
    if instance_name:
        import time
        import os
        now_time = time.time()
        last_check = request.session.get("last_middleware_check_time", 0)
        last_checked_instance = request.session.get("last_middleware_checked_instance", "")

        if not deployed_version:
            deployed_version = request.session.get("middleware_deployed_version", "")

        if not deployed_version:
            base_path = "/opt/heappe-deployment/"
            appsettings_path = os.path.join(base_path, instance_name, "app", "confs", "appsettings.json")
            if os.path.exists(appsettings_path):
                try:
                    import json
                    with open(appsettings_path, "r", encoding="utf-8") as f:
                        appsettings_data = json.load(f)
                    deployed_version = appsettings_data.get("ApplicationAPISettings", {}).get("DeploymentSettings", {}).get("Version", "").lstrip("vV")
                except Exception:
                    pass

        latest_version = request.session.get("middleware_latest_version", "")

        if (now_time - last_check > 3600) or (instance_name != last_checked_instance) or not latest_version:
            from heappe_ui.view.deploy import get_remote_tags
            repo_url = "https://github.com/It4innovations/HEAppE"
            branches = get_remote_tags(repo_url)
            if branches:
                latest_version = branches[0].lstrip("vV")

        update_available = False
        if deployed_version and isinstance(deployed_version, str) and latest_version and isinstance(latest_version, str):
            try:
                from heappe_ui.view.utils import clean_ver
                if clean_ver(latest_version) > clean_ver(deployed_version):
                    update_available = True
            except Exception:
                if latest_version.lower().lstrip('v') != deployed_version.lower().lstrip('v'):
                    update_available = True

        request.session["last_middleware_check_time"] = now_time
        request.session["last_middleware_checked_instance"] = instance_name
        request.session["middleware_update_available"] = update_available
        request.session["middleware_deployed_version"] = deployed_version
        request.session["middleware_latest_version"] = latest_version

        context["middleware_update_available"] = update_available
        context["middleware_deployed_version"] = deployed_version
        context["middleware_latest_version"] = latest_version

    try:
        result = controller.heappe_management_version_information_get(SessionCode=request.session_code)
        context["heappe"] = result
    except Exception as e:
        print(f"Error fetching version information: {e}")
        context["heappe"] = None

    # Fetch API and Swagger URLs for the selected instance
    if instance_name:
        try:
            from heappe_ui.view.utils import get_instance_api_links
            api_links = get_instance_api_links(instance_name)
            context.update(api_links)
        except Exception as e:
            print(f"Error getting instance API links: {e}")

    # Fetch quick external telemetry summary
    telemetry_summary = None
    try:
        from heappe_ui.view.telemetry import _get_live_statuses
        live_statuses, _ = _get_live_statuses(request)
        if live_statuses:
            avail_count = sum(1 for s in live_statuses if s.get('IsAvailable') or s.get('is_available'))
            total_count = len(live_statuses)
            telemetry_summary = {
                'available': avail_count,
                'total': total_count,
                'all_healthy': (avail_count == total_count)
            }
    except Exception:
        pass
    context["telemetry_summary"] = telemetry_summary

    return render(request, "partials/dashboard_health.html", context)


@login_required
def dashboard_metrics_partial(request: HttpRequest) -> HttpResponse:
    context = {}
    controller = hp.ManagementApi(request.api_instance)
    jr_controller = hp.JobReportingApi(request.api_instance)

    # Get cluster information
    try:
        clusters = controller.heappe_management_clusters_get(SessionCode=request.session_code)
        context["clusters"] = clusters
    except Exception as e:
        print(f"Error fetching clusters: {e}")
        context["clusters"] = []

    # Get project information
    try:
        projects = controller.heappe_management_projects_get(SessionCode=request.session_code)
        context["projects"] = projects
    except Exception as e:
        print(f"Error fetching projects: {e}")
        context["projects"] = []

    # Get queue information
    try:
        raw_queues = controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code)
        queues = [c.to_dict() for c in raw_queues] if raw_queues else []
        context['queues'] = queues
    except Exception as e:
        print(f"Error fetching queues: {e}")
        context['queues'] = []

    # Get queue groups
    try:
        queue_groups = controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=request.session_code)
        context['queue_groups'] = queue_groups if queue_groups else []
    except Exception as e:
        print(f"Error fetching queue groups: {e}")
        context['queue_groups'] = []

    # Get job stats for total count
    try:
        job_stats = jr_controller.heappe_job_reporting_jobs_state_agregation_report_get(SessionCode=request.session_code)
        context["total_jobs"] = sum(js.count for js in job_stats) if job_stats else 0
    except Exception as e:
        print(f"Error fetching job stats: {e}")
        context["total_jobs"] = 0

    return render(request, "partials/dashboard_metrics.html", context)


@login_required
def dashboard_jobs_distribution_partial(request: HttpRequest) -> HttpResponse:
    jr_controller = hp.JobReportingApi(request.api_instance)
    try:
        job_stats = jr_controller.heappe_job_reporting_jobs_state_agregation_report_get(SessionCode=request.session_code)
        all_states = [
            'Configuring', 'Submitted', 'Queued', 'Running', 'Finished',
            'Failed', 'Canceled', 'WaitingForServiceAccount', 'Deleted'
        ]
        job_counts = {s: 0 for s in all_states}
        for js in (job_stats or []):
            job_counts[js.job_state_name] = js.count
        total_jobs = sum(job_counts.values())
        return JsonResponse({
            "status": "success",
            "job_counts": job_counts,
            "total_jobs": total_jobs
        })
    except Exception as e:
        print(f"Error fetching job stats for distribution: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def dashboard_jobs_history_partial(request: HttpRequest) -> HttpResponse:
    context = {}

    job_states = request.GET.get('job_states', '').strip()
    search = request.GET.get('search', '').strip()
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        limit = max(1, int(request.GET.get('limit', 10)))
    except (ValueError, TypeError):
        limit = 10

    offset = (page - 1) * limit

    context["job_states"] = job_states
    context["search"] = search
    context["page"] = page
    context["limit"] = limit

    # Check HEAppE Core version (ListDetailedJobsForAdmin requires >= 6.5.0)
    use_admin_api = False
    current_version = request.session.get("middleware_deployed_version", "")
    if not current_version:
        try:
            health_api = hp.HealthApi(request.api_instance)
            health_info = health_api.heappe_health_get()
            current_version = health_info.version.lstrip("vV") if health_info and getattr(health_info, 'version', None) else "0.0.0"
            if current_version and current_version != "0.0.0":
                request.session["middleware_deployed_version"] = current_version
        except Exception as e:
            print(f"[dashboard_jobs_history] Version check error: {e}")
            current_version = "0.0.0"

    try:
        if clean_ver(current_version) >= clean_ver("6.5.0"):
            use_admin_api = True
    except Exception:
        use_admin_api = False

    if use_admin_api:
        try:
            jm_api = hp.JobManagementApi(request.api_instance)
            kwargs = {
                'session_code': request.session_code,
                'limit': limit,
                'offset': offset,
            }
            if job_states:
                kwargs['job_states'] = job_states
            if search:
                kwargs['search'] = search

            res = jm_api.heappe_job_management_list_detailed_jobs_for_admin_get(**kwargs)
            
            items = getattr(res, 'items', []) or []
            total_count = getattr(res, 'total_count', 0) or 0
            
            import math
            total_pages = max(1, math.ceil(total_count / limit)) if total_count > 0 else 1

            admin_context = dict(context)
            admin_context["job_details"] = items
            admin_context["total_count"] = total_count
            admin_context["total_pages"] = total_pages
            admin_context["has_previous"] = page > 1
            admin_context["has_next"] = page < total_pages
            admin_context["previous_page_number"] = page - 1
            admin_context["next_page_number"] = page + 1
            admin_context["page_range"] = list(range(1, total_pages + 1))
            admin_context["is_admin_api"] = True
            return render(request, "partials/dashboard_jobs_history.html", admin_context)
        except Exception as e:
            print(f"[dashboard_jobs_history] ListDetailedJobsForAdmin failed: {e}. Falling back to legacy JobReportingApi.")

    # Legacy fallback logic using JobReportingApi
    jr_controller = hp.JobReportingApi(request.api_instance)
    try:
        time_to_str = request.GET.get('time_to', datetime.now(dt_timezone.utc).isoformat())
        time_from_str = request.GET.get('time_from', (datetime.now(dt_timezone.utc) - timedelta(days=1)).isoformat())

        try:
            time_to = datetime.fromisoformat(time_to_str)
            if time_to.tzinfo is None:
                time_to = time_to.replace(tzinfo=dt_timezone.utc)
            time_from = datetime.fromisoformat(time_from_str)
            if time_from.tzinfo is None:
                time_from = time_from.replace(tzinfo=dt_timezone.utc)
        except ValueError:
            time_to = datetime.now(dt_timezone.utc)
            time_from = datetime.now(dt_timezone.utc) - timedelta(days=1)

        now = datetime.now(dt_timezone.utc)
        min_allowed_date = now - timedelta(days=90)

        if time_to < min_allowed_date:
            time_to = now
        elif time_to > now + timedelta(hours=1):
            time_to = now

        if time_from < min_allowed_date:
            time_from = min_allowed_date
        elif time_from > time_to:
            time_from = time_to - timedelta(days=1)

        if (time_to - time_from) > timedelta(days=90):
            time_from = time_to - timedelta(days=90)

        context["time_to"] = time_to.strftime('%Y-%m-%dT%H:%M')
        context["time_from"] = time_from.strftime('%Y-%m-%dT%H:%M')

        job_details_raw = jr_controller.heappe_job_reporting_jobs_detailed_report_get(
            SessionCode=request.session_code,
            TimeFrom=time_from,
            TimeTo=time_to
        )

        all_jobs = []
        seen_job_ids = set()
        if job_details_raw:
            for job in job_details_raw:
                if not job or not hasattr(job, 'clusters') or job.clusters is None:
                    continue
                for cluster in job.clusters:
                    if not cluster or not hasattr(cluster, 'cluster_node_types') or cluster.cluster_node_types is None:
                        continue
                    for node_type in cluster.cluster_node_types:
                        if not node_type or not hasattr(node_type, 'jobs') or node_type.jobs is None:
                            continue
                        for job_item in node_type.jobs:
                            if job_item and getattr(job_item, 'id', None) is not None:
                                if job_item.id not in seen_job_ids:
                                    if job_states:
                                        allowed_states = [int(s) for s in job_states.split(',') if s.strip().isdigit()]
                                        if getattr(job_item, 'state', None) not in allowed_states:
                                            continue
                                    if search:
                                        job_name = str(getattr(job_item, 'name', '') or '').lower()
                                        job_id = str(getattr(job_item, 'id', '') or '').lower()
                                        if search.lower() not in job_name and search.lower() not in job_id:
                                            continue
                                    seen_job_ids.add(job_item.id)
                                    all_jobs.append(job_item)
        all_jobs.sort(key=lambda x: x.id or 0, reverse=True)

        paginator = Paginator(all_jobs, limit)
        page_obj = paginator.get_page(page)

        context["job_details"] = page_obj.object_list
        context["page_obj"] = page_obj
        context["total_count"] = len(all_jobs)
        context["is_admin_api"] = False
    except Exception as e:
        print(f"Error fetching job details: {e}")
        context["job_details"] = []
        context["page_obj"] = None
        context["total_count"] = 0
        context["is_admin_api"] = False

    return render(request, "partials/dashboard_jobs_history.html", context)



class DatabaseSettingsError(Exception):
    pass

from django.db import connections
from django.shortcuts import render
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from collections import Counter
from datetime import datetime
try:
    import pymssql
except ImportError:
    pymssql = None


from django.shortcuts import render, redirect
from .models import InstanceCredentials
from django.utils import timezone

@login_required
def logs_view(request):
    context = {}
    context['default_date_from'] = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    # Handle database configuration form submission
    if request.method == 'POST' and request.POST.get('config_submit'):
        InstanceCredentials.objects.update_or_create(
            instance_name=request.session['chosen_instance'],
            defaults={
                "heappe_host": request.session["heappe_host"],
                "heappe_login": request.session["heappe_username"],
                "log_db_host": request.POST.get('server'),
                "log_db_port": request.POST.get('port'),
                "log_db_user": request.POST.get('user'),
                "log_db_password": request.POST.get('password'),
                "log_db_database": request.POST.get('database'),
            }
        )

    credentials = get_instance_settings(instance_name=request.session['chosen_instance'])
    db_settings = {}
    if credentials:
        db_settings = {
            'server': credentials.log_db_host,
            'port': credentials.log_db_port,
            'user': credentials.log_db_user,
            'password': credentials.log_db_password,
            'database': credentials.log_db_database,
            'tds_version': '8.0',
        }

    if db_settings:
        # Pass current database settings to template
        context['db_server'] = db_settings['server']
        context['db_port'] = db_settings['port']
        context['db_user'] = db_settings['user']
        context['db_password'] = db_settings['password']
        context['db_database'] = db_settings['database']

    # Initialize default context values to prevent template errors
    context['levels'] = []
    context['logs'] = []
    context['summary_levels'] = Counter()
    context['summary_classes'] = []
    context['chart_dates'] = []
    context['chart_errors'] = []
    context['chart_warnings'] = []
    context['chart_info'] = []
    context['chart_debug'] = []
    context['chart_critical'] = []
    context['error_count'] = 0
    context['warning_count'] = 0
    context['info_count'] = 0
    context['debug_count'] = 0
    context['critical_count'] = 0

    # Attempt database connection
    try:
        if db_settings:
            required_fields = ['server', 'port', 'user', 'password', 'database']
            missing_fields = [field for field in required_fields if db_settings[field] is None or db_settings[field] == '']
            if missing_fields:
                raise DatabaseSettingsError(f"Missing required database settings: {', '.join(missing_fields)}")
        else:
            raise DatabaseSettingsError(f"Please configure Log Database.")
        conn = pymssql.connect(**db_settings)
        cursor = conn.cursor(as_dict=True)
        cursor.execute("SELECT * FROM LoggingLevelType")
        rows = cursor.fetchall()
        LoggingLevelType = {row['Id']: row['Name'] for row in rows}
        context['levels'] = [{'Id': k, 'Name': v} for k, v in LoggingLevelType.items()]
        cursor.close()

        # Filters from GET parameters
        date_from = request.GET.get('date_from')
        if date_from is not None:
            date_from = date_from.replace('T', ' ')
        date_to = request.GET.get('date_to')
        if date_to is not None:
            date_to = date_to.replace('T', ' ')
        level_filter = request.GET.get('level')
        search = request.GET.get('search', '').lower()

        # SQL query with conditions
        query = "SELECT TOP 1000 * FROM Log WHERE 1=1"
        params = []

        if date_from:
            query += " AND Date >= %s"
            params.append(date_from)
        if date_to:
            query += " AND Date <= %s"
            params.append(date_to)
        if level_filter:
            query += " AND LevelId = %s"
            params.append(level_filter)
        if search:
            query += " AND (LOWER(Message) LIKE %s OR LOWER(Class) LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        query += " ORDER BY Date DESC"

        cursor = conn.cursor(as_dict=True)
        cursor.execute(query, params)
        logs = cursor.fetchall()
        for log in logs:
            log_date = log['Date']
            if isinstance(log_date, str):
                log['Date'] = datetime.strptime(log_date[:26], "%Y-%m-%d %H:%M:%S.%f")
            log['LevelName'] = LoggingLevelType.get(log['LevelId'], 'Unknown')

        cursor.close()
        conn.close()

        # Pagination
        paginator = Paginator(logs, 10)  # Show 10 logs per page
        page_number = request.GET.get('page')
        try:
            logs_page = paginator.page(page_number)
        except PageNotAnInteger:
            logs_page = paginator.page(1)  # Default to page 1 if page is not an integer
        except EmptyPage:
            logs_page = paginator.page(paginator.num_pages)  # Show last page if page is out of range

        context['logs'] = logs_page  # Pass paginated logs to template

        # Souhrny a grafy (calculated on full logs, not paginated)
        level_counts = Counter([log['LevelName'] for log in logs])
        context['summary_levels'] = level_counts
        context['summary_classes'] = Counter([log['Class'] for log in logs]).most_common(10)
        dates = sorted({log['Date'].date() for log in logs})
        context['chart_dates'] = [d.strftime("%Y-%m-%d") for d in dates]

        def counts_per_day(level=None):
            return [
                sum(1 for log in logs if (level is None or log['LevelName'] == level) and log['Date'].date() == d)
                for d in dates
            ]

        context['chart_errors'] = counts_per_day('Error')
        context['chart_warnings'] = counts_per_day('Warning')
        context['chart_info'] = counts_per_day('Information')
        context['chart_debug'] = counts_per_day('Debug')
        context['chart_critical'] = counts_per_day('Critical')

        context['error_count'] = level_counts.get('Error', 0)
        context['warning_count'] = level_counts.get('Warning', 0)
        context['info_count'] = level_counts.get('Information', 0)
        context['debug_count'] = level_counts.get('Debug', 0)
        context['critical_count'] = level_counts.get('Critical', 0)

    except DatabaseSettingsError as e:
        context['error'] = f"Database connection failed: {str(e)}"
    except pymssql.Error as e:
        context['error'] = f"Database connection failed: {str(e)}"

    return render(request, "logs.html", context)
    # Pagination
    paginator = Paginator(logs, 10)  # Show 10 logs per page
    page_number = request.GET.get('page')
    try:
        logs_page = paginator.page(page_number)
    except PageNotAnInteger:
        logs_page = paginator.page(1)  # Default to page 1 if page is not an integer
    except EmptyPage:
        logs_page = paginator.page(paginator.num_pages)  # Show last page if page is out of range

    context['logs'] = logs_page  # Pass paginated logs to template

    # Souhrny a grafy (calculated on full logs, not paginated)
    level_counts = Counter([log['LevelName'] for log in logs])
    context['summary_levels'] = level_counts
    context['summary_classes'] = Counter([log['Class'] for log in logs]).most_common(10)
    dates = sorted({log['Date'].date() for log in logs})
    context['chart_dates'] = [d.strftime("%Y-%m-%d") for d in dates]

    def counts_per_day(level=None):
        return [
            sum(1 for log in logs if (level is None or log['LevelName'] == level) and log['Date'].date() == d)
            for d in dates
        ]

    context['chart_errors'] = counts_per_day('Error')
    context['chart_warnings'] = counts_per_day('Warning')
    context['chart_info'] = counts_per_day('Information')
    context['chart_debug'] = counts_per_day('Debug')
    context['chart_critical'] = counts_per_day('Critical')

    context['error_count'] = level_counts.get('Error', 0)
    context['warning_count'] = level_counts.get('Warning', 0)
    context['info_count'] = level_counts.get('Information', 0)
    context['debug_count'] = level_counts.get('Debug', 0)
    context['critical_count'] = level_counts.get('Critical', 0)

    return render(request, "logs.html", context)



from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import InstanceCredentials
from .forms import InstanceCredentialsForm

@login_required
def instance_credentials_list(request, pk=None):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "bulk_delete":
            selected_ids = request.POST.getlist("selected_ids")
            stop_containers = request.POST.get('stop_containers', 'true') in ['true', '1', 'on', True]
            delete_files = request.POST.get('delete_files', 'true') in ['true', '1', 'on', True]
            success_count = 0
            for cid in selected_ids:
                try:
                    instance = InstanceCredentials.objects.get(pk=int(cid))
                    inst_name = instance.instance_name
                    if request.session.get("chosen_instance") == inst_name:
                        request.session.pop("chosen_instance", None)
                        request.session.pop("heappe_session_code", None)
                        request.session.pop("heappe_host", None)
                        request.session.pop("heappe_host_url", None)
                        request.session.pop("heappe_use_api_key", None)
                        request.session.pop("heappe_last_auth", None)
                        request.session.pop("heappe_last_failed_auth", None)
                    teardown_instance(
                        instance_name=inst_name,
                        stop_containers=stop_containers,
                        delete_files=delete_files
                    )
                    instance.delete()
                    success_count += 1
                except Exception as e:
                    print(f"Error deleting credential {cid}: {e}")
            if success_count > 0:
                msg = f"Successfully deleted {success_count} instance credential(s)."
                if stop_containers:
                    msg += " Associated Docker containers were stopped and shut down."
                messages.success(request, msg)
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to delete {len(selected_ids) - success_count} instance credential(s).")
            return redirect("instance_credentials_list")

    if pk is not None:
        instance = get_object_or_404(InstanceCredentials, pk=pk)
        if instance:
            request.session["chosen_instance"] = instance.instance_name
            request.session["force_reauth"] = True
            # Clear old instance connection variables to prevent leakage/fallback
            request.session.pop("heappe_session_code", None)
            request.session.pop("heappe_host", None)
            request.session.pop("heappe_host_url", None)
            request.session.pop("heappe_use_api_key", None)
            request.session.pop("heappe_last_auth", None)
            request.session.pop("heappe_last_failed_auth", None)
            return redirect("dashboard_view")

    instances = InstanceCredentials.objects.all().order_by('instance_name')
    return render(request, 'instance_credentials.html', {'object_list': instances})

@login_required
def instance_credentials_create(request):
    if request.method == 'POST':
        form = InstanceCredentialsForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Instance '{form.cleaned_data['instance_name']}' created successfully.")
            return redirect('instance_credentials_list')
        else:
            messages.error(request, 'Error creating instance. Please check the form.')
    else:
        form = InstanceCredentialsForm()
    return render(request, 'instance_credentials_form.html', {'form': form})


@login_required
def instance_credentials_edit(request, pk):
    instance = get_object_or_404(InstanceCredentials, pk=pk)

    if request.method == 'POST':
        data = request.POST.copy()

        if not data.get('heappe_password'):
            data['heappe_password'] = instance.heappe_password
        if not data.get('log_db_password'):
            data['log_db_password'] = instance.log_db_password

        form = InstanceCredentialsForm(data, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"Instance '{form.cleaned_data['instance_name']}' updated successfully.")
            return redirect('instance_credentials_list')
        else:
            messages.error(request, 'Error updating instance. Please check the form.')
    else:
        form = InstanceCredentialsForm(instance=instance)
        form.fields['heappe_password'].initial = ""
        form.fields['log_db_password'].initial = ""

    return render(request, 'instance_credentials_form.html', {'form': form})

@login_required
def instance_credentials_delete(request, pk):
    instance = get_object_or_404(InstanceCredentials, pk=pk)
    if request.method == 'POST':
        instance_name = instance.instance_name
        stop_containers = request.POST.get('stop_containers', 'true') in ['true', '1', 'on', True]
        delete_files = request.POST.get('delete_files', 'true') in ['true', '1', 'on', True]

        teardown_result = teardown_instance(
            instance_name=instance_name,
            stop_containers=stop_containers,
            delete_files=delete_files
        )

        if request.session.get("chosen_instance") == instance_name:
            request.session.pop("chosen_instance", None)
            request.session.pop("heappe_session_code", None)
            request.session.pop("heappe_host", None)
            request.session.pop("heappe_host_url", None)
            request.session.pop("heappe_use_api_key", None)
            request.session.pop("heappe_last_auth", None)
            request.session.pop("heappe_last_failed_auth", None)

        instance.delete()

        msg = f"Instance '{instance_name}' deleted successfully."
        if stop_containers:
            msg += " Associated Docker containers were stopped and shut down."
        if delete_files and teardown_result.get("files_removed"):
            msg += " Deployment files on disk were cleaned up."
        messages.success(request, msg)
        return redirect('instance_credentials_list')
    return render(request, 'instance_credentials.html', {'object_list': InstanceCredentials.objects.all()})


@login_required
def instance_health_check_api(request, pk):
    import time
    instance = get_object_or_404(InstanceCredentials, pk=pk)
    
    db_host = instance.heappe_host
    db_port = instance.heappe_port
    full_host = f"{db_host}:{db_port}" if db_port and db_port not in ['80', '443', ''] else db_host
    host_url = 'http://' + full_host if not full_host.startswith('http') else full_host
    
    config = hp.Configuration()
    config.host = host_url
    config.verify_ssl = True
    
    api_client = hp.ApiClient(config)
    
    # Patch the API client and associate with the request to apply consistent settings (like timeout)
    from heappe_ui.auth_backend import patch_api_client
    api_client._request = request
    patch_api_client(api_client)
    
    start_time = time.time()
    try:
        health_api = hp.HealthApi(api_client)
        # Use a short timeout of 2 seconds for quick response in grid check
        health_info = health_api.heappe_health_get(_request_timeout=2)
        duration = int((time.time() - start_time) * 1000)
        
        db_healthy = True
        vault_healthy = True
        if health_info and hasattr(health_info, 'component') and health_info.component:
            comp = health_info.component
            if hasattr(comp, 'database') and comp.database:
                db_healthy = getattr(comp.database, 'is_healthy', True)
            if hasattr(comp, 'vault') and comp.vault:
                vault_healthy = getattr(comp.vault, 'is_healthy', True)
                
        version = "unknown"
        if health_info and hasattr(health_info, 'version') and health_info.version:
            version = str(health_info.version).lstrip("vV")
            
        instance_identifier = "unknown"
        if health_info and hasattr(health_info, 'instance_identifier') and health_info.instance_identifier:
            instance_identifier = health_info.instance_identifier

        if instance_identifier in ("unknown", "", None):
            try:
                base_path = "/opt/heappe-deployment/"
                appsettings_path = os.path.join(base_path, instance.instance_name, "app", "confs", "appsettings.json")
                if os.path.exists(appsettings_path):
                    with open(appsettings_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    instance_identifier = cfg.get("HPCConnectionFrameworkSettings", {}).get("ScriptsSettings", {}).get("InstanceIdentifierPath") or instance.instance_name
            except Exception:
                pass

        return JsonResponse({
            "status": "online",
            "version": version,
            "instance_identifier": instance_identifier,
            "database_healthy": db_healthy,
            "vault_healthy": vault_healthy,
            "latency_ms": duration,
            "message": "Healthy"
        })
    except Exception as e:
        instance_identifier = None
        try:
            base_path = "/opt/heappe-deployment/"
            appsettings_path = os.path.join(base_path, instance.instance_name, "app", "confs", "appsettings.json")
            if os.path.exists(appsettings_path):
                with open(appsettings_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                instance_identifier = cfg.get("HPCConnectionFrameworkSettings", {}).get("ScriptsSettings", {}).get("InstanceIdentifierPath") or instance.instance_name
        except Exception:
            pass

        return JsonResponse({
            "status": "offline",
            "version": None,
            "instance_identifier": instance_identifier,
            "database_healthy": False,
            "vault_healthy": False,
            "latency_ms": None,
            "message": str(e)
        })


import subprocess
import os
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse

# Script is located DIRECTLY in the project root directory, next to manage.py
DEPLOY_SCRIPT_NAME = "deploy.sh"
# Build full path
DEPLOY_SCRIPT_PATH = os.path.join(settings.BASE_DIR, DEPLOY_SCRIPT_NAME)


@login_required
def is_superuser(user):
    """Checks if the user is active and a superuser."""
    return user.is_active and user.is_superuser

import json
import subprocess
import os
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.conf import settings
from django.core.files.storage import default_storage # Optional, for file paths

# --- DEFINE THESE CONSTANTS BASED ON YOUR PROJECT SETUP ---
# Example: Define the path to your deployment script relative to BASE_DIR
DEPLOY_SCRIPT_NAME = 'deploy.sh'
# Assuming the script is in the project's root directory
# Ensure this is the correct path, e.g. /path/to/project/deploy.sh
DEPLOY_SCRIPT_PATH = os.path.join(settings.BASE_DIR, DEPLOY_SCRIPT_NAME)

# BEFORE USE, VERIFY THAT settings.BASE_DIR IS CONFIGURED CORRECTLY!
# ---------------------------------------------------------


import subprocess
from django.http import JsonResponse
from django.conf import settings


import subprocess
from django.conf import settings
from django.http import JsonResponse


@login_required
def check_for_updates(request):
    import time
    now = time.time()
    last_check = request.session.get("last_update_check_time", 0)
    force = request.GET.get('force') == '1'

    # Cache status in session for 6 hours (21600 seconds) to avoid slow page loads
    cached_available = request.session.get("update_available")
    cached_current = request.session.get("update_current_version")
    cached_latest = request.session.get("update_latest_version")
    cached_changes = request.session.get("update_changes")
    cached_branch = request.session.get("update_current_branch", "HEAD")

    actual_version = "unknown"
    try:
        actual_version = subprocess.check_output(
            ['git', 'describe', '--tags', '--always'],
            cwd=settings.BASE_DIR, stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip().lstrip('vV')
    except Exception:
        pass

    if not force and last_check and (now - last_check < 21600) and cached_current and cached_latest and cached_current == actual_version:
        response = JsonResponse({
            'update_available': cached_available,
            'current_version': cached_current,
            'latest_version': cached_latest,
            'changes': cached_changes or [],
            'current_branch': cached_branch
        })
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response

    repo_path = settings.BASE_DIR
    update_available = False
    current_version = "unknown"
    latest_version = ""
    changes = []

    def parse_ver(v):
        try:
            res = [int(x) for x in v.split('-')[0].split('.') if x.isdigit()]
            return res if res else [0]
        except Exception:
            return [0]

    try:
        # Get current branch
        try:
            current_branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
            ).decode().strip()
        except Exception:
            current_branch = "HEAD"

        if current_branch and current_branch != "HEAD":
            # 1. Branch-based check: Compare current HEAD with remote tracking branch
            try:
                subprocess.run(['git', 'fetch', 'origin'], cwd=repo_path, stderr=subprocess.DEVNULL, timeout=10)
            except Exception:
                pass

            try:
                local_hash = subprocess.check_output(
                    ['git', 'rev-parse', 'HEAD'],
                    cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                ).decode().strip()
                remote_hash = subprocess.check_output(
                    ['git', 'rev-parse', f'origin/{current_branch}'],
                    cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                ).decode().strip()
            except Exception:
                local_hash = ""
                remote_hash = ""

            if local_hash and remote_hash and local_hash != remote_hash:
                try:
                    behind_count = subprocess.check_output(
                        ['git', 'rev-list', '--count', f'HEAD..origin/{current_branch}'],
                        cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                    ).decode().strip()
                    update_available = int(behind_count) > 0
                except Exception:
                    update_available = True

                if update_available:
                    try:
                        current_version = subprocess.check_output(
                            ['git', 'describe', '--tags', '--always'],
                            cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                        ).decode().strip().lstrip('vV')
                    except Exception:
                        current_version = local_hash[:7]

                    try:
                        latest_version = subprocess.check_output(
                            ['git', 'describe', f'origin/{current_branch}', '--tags', '--always'],
                            cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                        ).decode().strip().lstrip('vV')
                    except Exception:
                        latest_version = remote_hash[:7]

                    try:
                        log_output = subprocess.check_output(
                            ['git', 'log', f'HEAD..origin/{current_branch}', '--format=%s'],
                            cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                        ).decode().strip()
                        if log_output:
                            changes = log_output.split('\n')[:10]
                    except Exception:
                        pass
                else:
                    # Local branch has all remote commits (either up to date or ahead)
                    try:
                        current_version = subprocess.check_output(
                            ['git', 'describe', '--tags', '--always'],
                            cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                        ).decode().strip().lstrip('vV')
                    except Exception:
                        current_version = local_hash[:7] if local_hash else "unknown"
                    latest_version = current_version
            else:
                # Up to date on this branch
                try:
                    current_version = subprocess.check_output(
                        ['git', 'describe', '--tags', '--always'],
                        cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                    ).decode().strip().lstrip('vV')
                except Exception:
                    current_version = local_hash[:7] if local_hash else "unknown"
                latest_version = current_version
        else:
            # 2. Tag-based fallback: Check remote tags
            # 1. Get current base tag (e.g. "1.1.0" from "v1.1.0-230-gabcdef")
            try:
                current_version = subprocess.check_output(
                    ['git', 'describe', '--tags', '--abbrev=0'],
                    cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                ).decode().strip().lstrip('vV')
            except Exception:
                current_version = subprocess.check_output(
                    ['git', 'describe', '--tags', '--always'],
                    cwd=repo_path, stderr=subprocess.DEVNULL, timeout=5
                ).decode().strip().lstrip('vV')

            # 2. Get all remote tags via git ls-remote (no full fetch needed)
            raw = subprocess.check_output(
                ['git', 'ls-remote', '--tags', 'origin'],
                cwd=repo_path, timeout=15, stderr=subprocess.DEVNULL
            ).decode().strip()

            tags = []
            for line in raw.splitlines():
                parts = line.split('\t')
                if len(parts) == 2 and not parts[1].endswith('^{}'):
                    tag = parts[1].replace('refs/tags/', '').strip().lstrip('vV')
                    # Only semver-like tags (e.g. 1.2.3)
                    base = tag.split('-')[0]
                    if base and all(c.isdigit() or c == '.' for c in base):
                        tags.append(tag)

            tags.sort(key=parse_ver, reverse=True)

            if tags:
                latest_version = tags[0]
                try:
                    if parse_ver(latest_version) > parse_ver(current_version):
                        update_available = True
                        # Try to get recent commit messages between tags
                        try:
                            log = subprocess.check_output(
                                ['git', 'log', f'v{current_version}..v{latest_version}', '--format=%s'],
                                cwd=repo_path, timeout=10, stderr=subprocess.DEVNULL
                            ).decode().strip()
                            if log:
                                changes = log.split('\n')[:10]
                        except Exception:
                            pass
                except Exception:
                    if latest_version.split('-')[0] != current_version.split('-')[0]:
                        update_available = True

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        return JsonResponse({'error': f'Git error: {error_msg}', 'update_available': False}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e), 'update_available': False}, status=500)

    # Store in session cache
    request.session["last_update_check_time"] = now
    request.session["update_available"] = update_available
    request.session["update_current_version"] = current_version
    request.session["update_latest_version"] = latest_version
    request.session["update_changes"] = changes
    request.session["update_current_branch"] = current_branch

    response = JsonResponse({
        'update_available': update_available,
        'current_version': current_version,
        'latest_version': latest_version,
        'changes': changes,
        'current_branch': current_branch
    })
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


# ... error handling ...







@require_http_methods(["POST"])
@login_required # Important: Only authenticated users may trigger this critical operation.
def trigger_deployment_direct(request):
    """Final API endpoint to execute the deployment script."""
    # 1. Input Validation and Parsing
    try:
        # Decode as utf-8
        data = json.loads(request.body.decode('utf-8'))
        git_url = data.get('git_url')
        git_tag = data.get('git_tag')
        git_user = data.get('git_username', '')
        git_pass = data.get('git_password', '')

        if not all([git_url, git_tag]):
            return JsonResponse({"status": "error", "message": "Missing Git URL or selected Tag/Branch."}, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"status": "error", "message": "Invalid JSON request body."}, status=400)

    # 2. Check for Script and Permissions
    if not os.path.exists(DEPLOY_SCRIPT_PATH):
        return JsonResponse({"status": "error", "message": f"Deployment script not found at {DEPLOY_SCRIPT_PATH}"},
                            status=500)
    try:
        # Ensure script is executable (rwx for owner, r-- for group/others)
        os.chmod(DEPLOY_SCRIPT_PATH, 0o744)
    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Error setting permissions on script: {e}"}, status=500)

    # 3. Launch Subprocess with Environment Variables
    try:
        env_vars = os.environ.copy()

        # Pass the dynamic inputs as environment variables
        env_vars['GIT_URL'] = git_url
        env_vars['GIT_TAG'] = git_tag
        env_vars['GIT_USER'] = git_user
        env_vars['GIT_PASS'] = git_pass  # SENSITIVE!

        # Use shlex/list format for secure command execution
        process = subprocess.Popen(
            ['/bin/bash', DEPLOY_SCRIPT_PATH],
            cwd=settings.BASE_DIR,
            start_new_session=True,  # Important: detach process to run independently (daemonize)
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env_vars
        )

        return JsonResponse({
            "status": "success",
            "message": f"Deployment script ({DEPLOY_SCRIPT_NAME}) launched on background process {process.pid}. Server will restart shortly.",
            "git_tag": git_tag,
            "git_url": git_url
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": f"Fatal error launching script: {e}"}, status=500)


@require_http_methods(["GET"])
def system_update_status_api(request):
    """API endpoint to poll the status of the admin panel deployment/update."""
    log_file_paths = [
        "/var/log/deploy_adminpanel.log",
        os.path.join(settings.BASE_DIR, "deploy_adminpanel.log"),
    ]

    log_content = ""
    for path in log_file_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    log_content = "".join(lines[-300:])
                break
            except Exception:
                pass

    last_start_idx = log_content.rfind("=== START DEPLOYMENT")
    current_run = log_content[last_start_idx:] if last_start_idx != -1 else log_content

    is_process_running = False
    try:
        ps_out = subprocess.check_output(["pgrep", "-f", "deploy.sh"]).decode().strip()
        is_process_running = bool(ps_out)
    except Exception:
        is_process_running = False

    if is_process_running:
        is_running = True
        is_success = False
        is_failed = False
    else:
        is_failed = ("FAILED" in current_run) or ("ERROR: Step failed" in current_run)
        is_success = not is_failed and (
            ("=== SUCCESS ===" in current_run)
            or ("static files copied" in current_run)
            or ("collectstatic" in current_run)
        )
        is_running = False

    response = JsonResponse({
        "status": "ok",
        "is_running": is_running,
        "is_success": is_success,
        "is_failed": is_failed,
        "logs": current_run,
        "current_commit": getattr(settings, "GIT_VERSION", ""),
    })
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


import os
import re
from datetime import datetime
from django.shortcuts import render
from django.utils.html import escape
from django.contrib.auth.decorators import login_required

import os
import re
import time
import json
from datetime import datetime
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.http import StreamingHttpResponse
from django.template.loader import render_to_string

import os
import re
import time
import json
from datetime import datetime
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.http import StreamingHttpResponse


# --- HELPERS ---

def get_lines_backwards(file_path):
    with open(file_path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        position = f.tell()
        chunk_size = 65536
        remnant = b''
        
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            f.seek(position)
            chunk = f.read(read_size)
            
            if remnant:
                chunk = chunk + remnant
                remnant = b''
                
            lines = chunk.splitlines(keepends=True)
            if position > 0 and lines:
                remnant = lines[0]
                lines = lines[1:]
                
            for line in reversed(lines):
                yield line.decode('utf-8', errors='ignore')
                
        if remnant:
            yield remnant.decode('utf-8', errors='ignore')


def parse_json_log_line(line, service="API"):
    if not line or line[0] != '{' or line[-1] != '}':
        return None
    try:
        data = json.loads(line)
        if not isinstance(data, dict):
            return None
        
        # Support various casing and Serilog/OTel timestamp keys
        raw_ts = (
            data.get('timestamp') or 
            data.get('Timestamp') or 
            data.get('@t') or 
            data.get('time') or 
            data.get('Time') or 
            data.get('date') or 
            data.get('Date')
        )
        timestamp_str = None
        if raw_ts and isinstance(raw_ts, str):
            cleaned_ts = raw_ts.replace('T', ' ').rstrip('Z')
            if '.' in cleaned_ts:
                cleaned_ts = cleaned_ts.split('.')[0]
            if '+' in cleaned_ts:
                cleaned_ts = cleaned_ts.split('+')[0]
            timestamp_str = cleaned_ts.strip()
            
        raw_level = (
            data.get('level') or 
            data.get('Level') or 
            data.get('@l') or 
            data.get('severity') or 
            'INFO'
        )
        level = str(raw_level).upper()
        if 'INFO' in level:
            level = 'INFO'
        elif 'WARN' in level:
            level = 'WARN'
        elif 'ERR' in level or 'CRIT' in level or 'FATAL' in level:
            level = 'ERROR'
        elif 'DEBUG' in level or 'TRACE' in level or 'VERBOSE' in level:
            level = 'DEBUG'
        
        request_id = (
            data.get('requestId') or 
            data.get('RequestId') or 
            data.get('TraceId') or 
            data.get('traceId')
        )
        if not request_id and isinstance(data.get('Properties'), dict):
            request_id = data['Properties'].get('RequestId') or data['Properties'].get('TraceId')
        conn_str = f"[{request_id}]" if request_id else "[-]"
        
        user_name = data.get('userName') or data.get('UserName')
        user_id = data.get('userId') or data.get('UserId')
        if not (user_name or user_id) and isinstance(data.get('Properties'), dict):
            user_name = data['Properties'].get('UserName')
            user_id = data['Properties'].get('UserId')
        if user_name or user_id:
            user_str = f"{user_name or ''}({user_id or ''})".strip()
        else:
            user_str = "-"
            
        logger = data.get('logger') or data.get('Logger') or data.get('SourceContext') or ''
        message = (
            data.get('message') or 
            data.get('Message') or 
            data.get('@m') or 
            data.get('messageTemplate') or 
            data.get('MessageTemplate') or 
            data.get('@mt') or 
            ''
        )
        exception = data.get('exception') or data.get('Exception') or ''
        
        if exception:
            full_msg = f"{message}\n{exception}" if message else str(exception)
        else:
            full_msg = str(message)
            
        formatted_content = f"{level}  {timestamp_str or ''}  {conn_str}  {user_str}  {logger} - {full_msg}"
        
        return {
            'timestamp_str': timestamp_str,
            'level': level,
            'service': service,
            'content': formatted_content,
            'conn': conn_str,
            'user': user_str,
            'logger': logger,
            'msg': full_msg
        }
    except Exception:
        return None


def parse_log_line(line, service="API"):
    line_stripped = line.strip()
    if line_stripped.startswith('{') and line_stripped.endswith('}'):
        parsed_json = parse_json_log_line(line_stripped, service=service)
        if parsed_json:
            return parsed_json

    ts_match = re.search(r'(\d{4}[-_/]\d{2}[-_/]\d{2}[T\s]\d{2}:\d{2}:\d{2})', line)
    if ts_match:
        timestamp_str = ts_match.group(1).replace('T', ' ').replace('/', '-').replace('_', '-')
    else:
        time_only_match = re.search(r'\b(\d{2}:\d{2}:\d{2})\b', line)
        if time_only_match:
            timestamp_str = time_only_match.group(1)
        else:
            timestamp_str = None

    level = "INFO"
    if ts_match or timestamp_str:
        prefix_end = ts_match.start() if ts_match else line.find(timestamp_str)
        prefix = line[:prefix_end].strip().upper() if prefix_end > 0 else ""
        if "ERROR" in prefix or "ERR" in prefix:
            level = "ERROR"
        elif "WARN" in prefix:
            level = "WARN"
        elif "DEBUG" in prefix:
            level = "DEBUG"
        elif "INFO" in prefix:
            level = "INFO"
        else:
            upper_line = line.upper()
            if "ERROR" in upper_line or "EXCEPTION" in upper_line:
                level = "ERROR"
            elif "WARN" in upper_line:
                level = "WARN"
            elif "DEBUG" in upper_line:
                level = "DEBUG"
    else:
        upper_line = line.upper()
        if "ERROR" in upper_line or "EXCEPTION" in upper_line:
            level = "ERROR"
        elif "WARN" in upper_line:
            level = "WARN"
        elif "DEBUG" in upper_line:
            level = "DEBUG"

    svc = service
    if "datastaging" in line.lower():
        svc = "DATASTAGING"

    dash_idx = line.find(' - ')
    if dash_idx != -1 and dash_idx < 150:
        msg = line[dash_idx + 3:]
        header = line[:dash_idx]
    else:
        header = line
        msg = line

    tokens = header.split()
    conn_str = "[-]"
    user_str = "-"
    logger = ""
    for t in tokens:
        if t.startswith('[') and t.endswith(']'):
            conn_str = t
        elif '(' in t and t.endswith(')'):
            user_str = t
        elif '.' in t or 'Controller' in t:
            logger = t

    if dash_idx == -1 and conn_str != "[-]":
        conn_idx = line.find(conn_str)
        if conn_idx != -1:
            candidate_msg = line[conn_idx + len(conn_str):].strip()
            if candidate_msg:
                msg = candidate_msg

    return {
        'timestamp_str': timestamp_str,
        'level': level,
        'service': svc,
        'content': line,
        'conn': conn_str,
        'user': user_str,
        'logger': logger,
        'msg': msg
    }


def matches_filters(parsed, level_filter, search_query, time_from, time_to):
    if not level_filter and not search_query and not time_from and not time_to:
        return True

    if level_filter and parsed.get('level') != level_filter:
        return False
        
    if time_from or time_to:
        ts = parsed.get('timestamp_str')
        if not ts:
            return False

        time_match = re.search(r'(\d{2}:\d{2}(?::\d{2})?)', str(ts))
        if not time_match:
            return False

        time_part = time_match.group(1)
        if len(time_part) == 5:
            time_part += ":00"

        tf = (time_from + ":00") if (time_from and len(time_from) == 5) else (time_from or "")
        tt = (time_to + ":59") if (time_to and len(time_to) == 5) else (time_to or "")

        if tf and time_part < tf:
            return False
        if tt and time_part > tt:
            return False
            
    if search_query:
        content = parsed.get('content', '')
        if search_query not in content.lower():
            return False
            
    return True


def is_rotated_log_file(filepath):
    """Determine if a file is an archived/rotated log file (e.g. ends with .1, .2, etc.)."""
    return bool(re.search(r'\.(?:log|json)\.\d+(?:\.gz)?$', os.path.basename(filepath), re.IGNORECASE))


def log_file_sort_key(file_entry):
    """Sort log files chronologically: older rotated files first, active file last."""
    filepath = file_entry[0] if isinstance(file_entry, tuple) else file_entry
    fname = os.path.basename(filepath)
    mtime = 0
    try:
        mtime = os.path.getmtime(filepath)
    except OSError:
        pass

    rot_match = re.search(r'\.(?:log|json)\.(\d+)$', fname, re.IGNORECASE)
    seq_match = re.search(r'[_\-](\d+)\.(?:log|json)', fname, re.IGNORECASE)

    rot_num = int(rot_match.group(1)) if rot_match else 0
    seq_num = int(seq_match.group(1)) if seq_match else 0

    return (mtime, -rot_num, seq_num, filepath)


def get_log_entries_backwards(log_paths, max_entries=1000, level_filter=None, search_query=None, time_from=None, time_to=None):
    timestamp_re = re.compile(r'(?:\d{4}[-_/]\d{2}[-_/]\d{2}[T\s])?\d{2}:\d{2}:\d{2}')
    entries_count = 0
    
    normalized = []
    for item in log_paths:
        if isinstance(item, tuple):
            normalized.append(item)
        else:
            svc = 'DATASTAGING' if 'datastaging' in str(item).lower() else 'API'
            normalized.append((item, svc))

    all_entries = []

    buffer_limit = max_entries + 100

    for log_path, default_svc in reversed(normalized):
        if not log_path or not os.path.exists(log_path):
            continue
            
        is_json = log_path.endswith('.json') or '.json.' in os.path.basename(log_path)
        
        file_entries_count = 0
        if is_json:
            for line in get_lines_backwards(log_path):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                parsed = parse_json_log_line(line_stripped, service=default_svc)
                if parsed and matches_filters(parsed, level_filter, search_query, time_from, time_to):
                    all_entries.append(parsed)
                    file_entries_count += 1
                    entries_count += 1
                    if entries_count >= buffer_limit or file_entries_count >= max_entries:
                        break
        else:
            current_entry_lines = []
            
            for line in get_lines_backwards(log_path):
                ts_match = timestamp_re.search(line[:35])
                
                if ts_match:
                    current_entry_lines.append(line)
                    entry_text = "".join(reversed(current_entry_lines))
                    current_entry_lines = []
                    
                    parsed = parse_log_line(entry_text, service=default_svc)
                    if matches_filters(parsed, level_filter, search_query, time_from, time_to):
                        all_entries.append(parsed)
                        file_entries_count += 1
                        entries_count += 1
                        if entries_count >= buffer_limit or file_entries_count >= max_entries:
                            break
                else:
                    current_entry_lines.append(line)
                    
            if current_entry_lines:
                entry_text = "".join(reversed(current_entry_lines))
                parsed = parse_log_line(entry_text, service=default_svc)
                if matches_filters(parsed, level_filter, search_query, time_from, time_to):
                    all_entries.append(parsed)
                    entries_count += 1

        if entries_count >= buffer_limit:
            break

    all_entries.sort(key=lambda x: x.get('timestamp_str') or '', reverse=True)
    for entry in all_entries[:max_entries]:
        yield entry


def get_log_file_paths(instance, date_str, service="API"):
    base_logs_dir = f"/opt/heappe-deployment/{instance}/app/logs"
    date_formatted_us = date_str.replace("-", "_")
    date_formatted_hy = date_str.replace("_", "-")

    if not os.path.exists(base_logs_dir):
        return []

    service_upper = (service or "API").upper()
    matching_files = []

    date_pattern = re.compile(
        rf"^(?:[a-zA-Z0-9_\-]*?_)?(?:{re.escape(date_formatted_us)}|{re.escape(date_formatted_hy)})(?:[_\-]\d+)?\.(?:log|json)(?:\.\d+)?$",
        re.IGNORECASE
    )

    def scan_dir(dir_path, svc_tag):
        if os.path.exists(dir_path):
            try:
                entries = os.listdir(dir_path)
            except OSError:
                return
            for f in entries:
                filepath = os.path.join(dir_path, f)
                if not os.path.isdir(filepath):
                    if date_pattern.match(f):
                        if (filepath, svc_tag) not in matching_files:
                            matching_files.append((filepath, svc_tag))

    service_map = {
        "API": (["API", "api", "HEAppE"], []),
        "DATASTAGING": (["DataStaging-API", "DataStaging", "DataStagingAPI", "datastaging", "datastagingapi", "DataStaging_API"], []),
        "RATELIMIT-API": (["RateLimit-API", "ratelimit-api", "RateLimit_API"], []),
        "RATELIMIT-DATASTAGING": (["RateLimit-DataStaging", "ratelimit-datastaging", "RateLimit_DataStaging"], []),
        "VAULT": (["Vault", "vault"], []),
        "DEPLOY": ([], ["deploy.log"]),
        "UPDATE": ([], ["update.log"]),
    }

    if service_upper == "ALL":
        target_services = list(service_map.keys())
    elif service_upper in service_map:
        target_services = [service_upper]
    else:
        target_services = [service_upper]
        service_map[service_upper] = ([service], [])

    scanned_dirs = set()
    for s in target_services:
        folders, root_files = service_map.get(s, ([s], []))
        for folder in folders:
            folder_path = os.path.join(base_logs_dir, folder)
            scanned_dirs.add(os.path.abspath(folder_path))
            scan_dir(folder_path, s)
        for root_file in root_files:
            filepath = os.path.join(base_logs_dir, root_file)
            if os.path.exists(filepath) and not os.path.isdir(filepath):
                if (filepath, s) not in matching_files:
                    matching_files.append((filepath, s))

    if service_upper == "ALL":
        try:
            base_entries = os.listdir(base_logs_dir)
        except OSError:
            base_entries = []
        for entry in base_entries:
            full_path = os.path.join(base_logs_dir, entry)
            if os.path.isdir(full_path) and os.path.abspath(full_path) not in scanned_dirs:
                tag_name = entry.upper()
                scan_dir(full_path, tag_name)

    matching_files.sort(key=log_file_sort_key)
    return matching_files


def get_log_file_path(instance, date_str, service="API"):
    paths = get_log_file_paths(instance, date_str, service=service)
    if paths:
        return paths[-1][0] if isinstance(paths[-1], tuple) else paths[-1]
    return None


@login_required
def log_viewer_view(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    selected_date = request.GET.get('date', today) or today
    time_from = request.GET.get('time_from', '').strip()
    time_to = request.GET.get('time_to', '').strip()
    search_query = request.GET.get('search', '').lower()
    level_filter = request.GET.get('level', '').upper()
    service_filter = request.GET.get('service', 'API').upper()

    limit_param = request.GET.get('limit', '1000')
    try:
        limit = int(limit_param)
        if limit not in [100, 300, 500, 1000, 2500, 5000]:
            limit = 1000
    except (ValueError, TypeError):
        limit = 1000

    effective_time_to = time_to
    if time_from and not effective_time_to:
        try:
            parts = time_from.split(':')
            h = int(parts[0]) + 1
            m = int(parts[1])
            if h >= 24:
                effective_time_to = "23:59"
            else:
                effective_time_to = f"{h:02d}:{m:02d}"
        except Exception:
            effective_time_to = ""

    log_paths = get_log_file_paths(instance, selected_date, service=service_filter)
    
    try:
        entries = list(get_log_entries_backwards(
            log_paths=log_paths,
            max_entries=limit,
            level_filter=level_filter,
            search_query=search_query,
            time_from=time_from,
            time_to=effective_time_to
        ))
        entries.reverse()
    except Exception as e:
        entries = [{
            'timestamp_str': None,
            'level': 'ERROR',
            'service': 'API',
            'content': f"Error reading logs: {str(e)}"
        }]

    logs_json = json.dumps(entries)

    return render(request, 'file_log_viewer.html', {
        'logs_json': mark_safe(logs_json),
        'logs_count': len(entries),
        'selected_date': selected_date,
        'time_from': time_from,
        'time_to': time_to or effective_time_to,
        'search_query': search_query,
        'level_filter': level_filter,
        'service_filter': service_filter,
        'instance': instance,
        'limit': limit
    })


MAX_LOG_ENTRIES_PER_PULL = 300
MAX_CHUNK_READ_BYTES = 512 * 1024  # 512 KB per file read chunk


@login_required
def fetch_new_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.utcnow().strftime('%Y-%m-%d')
    selected_date = request.GET.get('date', today) or today
    service_filter = request.GET.get('service', 'API').upper()
    level_filter = request.GET.get('level', '').upper()
    search_query = request.GET.get('search', '').lower()
    time_from = request.GET.get('time_from', '').strip()
    time_to = request.GET.get('time_to', '').strip()

    raw_offset = request.GET.get('offset', '0')
    is_dict_offset = False
    offset_dict = {}

    if isinstance(raw_offset, str) and raw_offset.strip().startswith('{'):
        try:
            offset_dict = json.loads(raw_offset)
            is_dict_offset = True
        except Exception:
            offset_dict = {}

    num_offset = 0
    if not is_dict_offset:
        try:
            num_offset = int(raw_offset)
        except ValueError:
            num_offset = 0

    log_paths = get_log_file_paths(instance, selected_date, service=service_filter)
    if not log_paths and selected_date == today:
        utc_today = datetime.utcnow().strftime('%Y-%m-%d')
        if utc_today != today:
            log_paths = get_log_file_paths(instance, utc_today, service=service_filter)

    # Initial tail request (offset = -1): capture current file ends
    if (not is_dict_offset and num_offset == -1) or (is_dict_offset and offset_dict.get('__init__')):
        new_offsets = {}
        for item in log_paths:
            lp = item[0] if isinstance(item, tuple) else item
            if os.path.exists(lp):
                new_offsets[lp] = os.path.getsize(lp)
        ret_offset = new_offsets if (is_dict_offset or len(log_paths) > 1) else (list(new_offsets.values())[0] if new_offsets else 0)
        return JsonResponse({
            'entries': [],
            'offset': ret_offset
        })

    if not log_paths:
        return JsonResponse({
            'entries': [],
            'offset': offset_dict if is_dict_offset else num_offset
        })

    new_entries = []
    updated_offsets = dict(offset_dict)

    for item in log_paths:
        if len(new_entries) >= MAX_LOG_ENTRIES_PER_PULL:
            break

        log_path = item[0] if isinstance(item, tuple) else item
        svc_tag = item[1] if isinstance(item, tuple) else 'API'

        if not os.path.exists(log_path):
            continue

        file_size = os.path.getsize(log_path)

        if log_path in offset_dict:
            cur_file_offset = offset_dict[log_path]
        else:
            if is_dict_offset:
                # If offset_dict is active and a rotated file appears, do NOT read from 0!
                if is_rotated_log_file(log_path):
                    cur_file_offset = file_size
                else:
                    cur_file_offset = 0
            else:
                cur_file_offset = num_offset

        # File was truncated or rolled
        if cur_file_offset > file_size:
            cur_file_offset = 0

        if cur_file_offset >= file_size:
            updated_offsets[log_path] = file_size
            continue

        bytes_to_read = min(file_size - cur_file_offset, MAX_CHUNK_READ_BYTES)

        with open(log_path, 'rb') as f:
            f.seek(cur_file_offset)
            chunk = f.read(bytes_to_read)

        if not chunk:
            updated_offsets[log_path] = cur_file_offset
            continue

        is_json = log_path.endswith('.json') or '.json.' in os.path.basename(log_path)
        decoded = chunk.decode('utf-8', errors='ignore')

        if is_json:
            lines = decoded.splitlines(keepends=True)
            processed_bytes = 0
            for idx, line in enumerate(lines):
                line_stripped = line.strip()
                if not line_stripped:
                    processed_bytes += len(line.encode('utf-8'))
                    continue
                parsed = parse_json_log_line(line_stripped, service=svc_tag)
                if parsed:
                    processed_bytes += len(line.encode('utf-8'))
                    if matches_filters(parsed, level_filter, search_query, time_from, time_to):
                        new_entries.append(parsed)
                    if len(new_entries) >= MAX_LOG_ENTRIES_PER_PULL:
                        break
                else:
                    # Incomplete JSON line at boundary, leave for next read
                    if idx == len(lines) - 1 and not chunk.endswith(b'\n'):
                        break
                    processed_bytes += len(line.encode('utf-8'))
            updated_offsets[log_path] = cur_file_offset + processed_bytes
        else:
            last_newline = chunk.rfind(b'\n')
            if last_newline != -1 and last_newline < len(chunk) - 1:
                valid_chunk = chunk[:last_newline + 1]
                consumed_bytes = len(valid_chunk)
                decoded_lines = valid_chunk.decode('utf-8', errors='ignore').splitlines(keepends=True)
            else:
                consumed_bytes = len(chunk)
                decoded_lines = decoded.splitlines(keepends=True)

            current_entry_lines = []
            timestamp_re = re.compile(r'(?:\d{4}[-_/]\d{2}[-_/]\d{2}[T\s])?\d{2}:\d{2}:\d{2}')

            lines_consumed_bytes = 0
            for line in decoded_lines:
                line_len = len(line.encode('utf-8'))
                if timestamp_re.search(line[:35]):
                    if current_entry_lines:
                        entry_text = "".join(current_entry_lines)
                        parsed = parse_log_line(entry_text, service=svc_tag)
                        if matches_filters(parsed, level_filter, search_query, time_from, time_to):
                            new_entries.append(parsed)
                    current_entry_lines = [line]
                else:
                    current_entry_lines.append(line)
                lines_consumed_bytes += line_len
                if len(new_entries) >= MAX_LOG_ENTRIES_PER_PULL:
                    break

            if current_entry_lines and len(new_entries) < MAX_LOG_ENTRIES_PER_PULL:
                entry_text = "".join(current_entry_lines)
                parsed = parse_log_line(entry_text, service=svc_tag)
                if matches_filters(parsed, level_filter, search_query, time_from, time_to):
                    new_entries.append(parsed)

            updated_offsets[log_path] = cur_file_offset + (lines_consumed_bytes if len(new_entries) >= MAX_LOG_ENTRIES_PER_PULL else consumed_bytes)

    new_entries.sort(key=lambda x: x.get('timestamp_str') or '')

    if is_dict_offset or len(log_paths) > 1:
        ret_offset = updated_offsets
    else:
        ret_offset = list(updated_offsets.values())[0] if updated_offsets else 0

    return JsonResponse({
        'entries': new_entries,
        'offset': ret_offset
    })

@login_required
def heappe_check_api(request, min_version):
    try:
        controller = hp.HealthApi(request.api_instance)
        health_info = controller.heappe_health_get()
        current_version = health_info.version.lstrip("vV")

        is_ok = current_version >= min_version

        return JsonResponse({
            "status": "success" if is_ok else "version_mismatch",
            "current_version": current_version,
            "required_version": min_version,
            "message": "OK" if is_ok else f"Version {current_version} is less than required {min_version} for that feature."
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


import os
import time
from datetime import datetime
from django.http import StreamingHttpResponse
from django.contrib.auth.decorators import login_required


@login_required
def stream_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    log_base_path = f"/opt/heappe-deployment/{instance}/app/logs/API/"

    def event_stream():
        today_prefix = datetime.now().strftime('%Y_%m_%d')
        latest_file = None

        while True:
            files = sorted([f for f in os.listdir(log_base_path) if f.startswith(today_prefix) and f.endswith(".log")])

            if not files:
                time.sleep(1)
                continue

            current_target = files[-1]
            file_path = os.path.join(log_base_path, current_target)

            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                f.seek(0, os.SEEK_END)

                while True:
                    line = f.readline()
                    if not line:
                        check_files = sorted([f for f in os.listdir(log_base_path) if f.startswith(today_prefix)])
                        if check_files and check_files[-1] != current_target:
                            break

                        time.sleep(0.5)
                        continue

                    entry = process_log_entry(line, current_target, {'colors': True, 'meta': True, 'json': True})

                    html = f'<tr class="log-row {entry["border_class"]}"><td class="ps-4 py-3"><span class="badge {entry["text_class"]}">LIVE</span></td><td class="py-3 pe-4">{entry["content"]}</td></tr>'

                    clean_html = html.replace('\n', '')

                    yield f"data: {clean_html}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@login_required
def manage_project_adaptor_users(request: HttpRequest, project_id: int = None) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    session_code = request.session_code

    all_projects = [p.to_dict() for p in controller.heappe_management_projects_get(SessionCode=session_code)]

    project_data = None
    adaptor_users_in_project = []
    available_users = []
    all_adaptor_users = []

    system_role_assignments = []
    system_role_user_map = {}

    try:
        raw_adaptor_users = controller.heappe_management_adaptor_users_get(SessionCode=session_code)
        all_adaptor_users = [u.to_dict() for u in raw_adaptor_users] if raw_adaptor_users else []
    except Exception as e:
        print(f"Error fetching adaptor users: {e}")

    try:
        raw_sys_roles = controller.heappe_management_system_role_assignments_get(SessionCode=session_code)
        if raw_sys_roles:
            seen_sys = set()
            for sr in raw_sys_roles:
                u = getattr(sr, 'username', None) or (sr.get('username') if isinstance(sr, dict) else None)
                r = getattr(sr, 'role', None) or (sr.get('role') if isinstance(sr, dict) else None)
                s = getattr(sr, 'source', None) or (sr.get('source') if isinstance(sr, dict) else None) or "Dynamic"
                if not u or not r:
                    continue
                role_display = ADAPTOR_USER_INT_TO_STR.get(r, ADAPTOR_USER_INT_TO_STR.get(int(r) if str(r).isdigit() else None, r))
                u_str = str(u).strip()
                key = (u_str.lower(), str(role_display).lower(), str(s).lower())
                if key in seen_sys:
                    continue
                seen_sys.add(key)
                entry = {'username': u_str, 'role': role_display, 'source': s}
                system_role_assignments.append(entry)
                for k in {u_str, u_str.lower(), u_str.upper(), str(u)}:
                    system_role_user_map.setdefault(k, []).append(entry)
    except Exception as e:
        print(f"[manage_project_adaptor_users] Error fetching system roles: {e}")

    def _attach_user_roles(user_list):
        for u in user_list:
            u_name = str(u.get("username") or "")
            u_email = str(u.get("email") or "")
            u_idp = str(u.get("idp_sid") or u.get("IdpSid") or "")
            matched_sys = []
            seen_sys_keys = set()
            for cand in (u_name, u_name.strip(), u_name.strip().lower(),
                         u_email, u_email.strip(), u_email.strip().lower(),
                         u_idp, u_idp.strip(), u_idp.strip().lower()):
                if cand and cand in system_role_user_map:
                    for sr in system_role_user_map[cand]:
                        sk = (str(sr.get('role')).lower(), str(sr.get('source')).lower())
                        if sk not in seen_sys_keys:
                            seen_sys_keys.add(sk)
                            matched_sys.append(sr)
            u["system_roles"] = matched_sys

            proj_roles = []
            for group in (u.get("adaptor_user_groups") or []):
                g_proj = group.get("project")
                pname = g_proj.get("name") if g_proj else None
                for r in (group.get("roles") or []):
                    r_display = ADAPTOR_USER_INT_TO_STR.get(r, ADAPTOR_USER_INT_TO_STR.get(int(r) if str(r).isdigit() else None, r))
                    role_str = f"{pname} ({r_display})" if pname else str(r_display)
                    if role_str not in proj_roles:
                        proj_roles.append(role_str)
            u["proj_roles"] = proj_roles

    _attach_user_roles(all_adaptor_users)

    if project_id:
        project_data = next((p for p in all_projects if p['id'] == project_id), None)
        if not project_data:
            try:
                project_data = controller.heappe_management_project_get(Id=project_id,
                                                                        SessionCode=session_code).to_dict()
            except Exception:
                pass

        if project_data:
            try:
                adaptor_users_in_project = [u.to_dict() for u in
                                            controller.heappe_management_adaptor_users_in_project_get(
                                                SessionCode=session_code, ProjectId=project_id
                                            )]
                for u in adaptor_users_in_project:
                    roles = []
                    for group in (u.get("adaptor_user_groups") or []):
                        g_proj = group.get("project")
                        if g_proj and g_proj.get("id") == project_id:
                            for r in (group.get("roles") or []):
                                r_display = ADAPTOR_USER_INT_TO_STR.get(r, ADAPTOR_USER_INT_TO_STR.get(int(r) if str(r).isdigit() else None, r))
                                if r_display not in roles:
                                    roles.append(r_display)
                    u["roles"] = roles
                _attach_user_roles(adaptor_users_in_project)
            except Exception as e:
                print(f"Error fetching adaptor users in project: {e}")

            existing_usernames = {str(u['username']).strip().lower() for u in adaptor_users_in_project if u.get('username')}
            available_users = [u for u in all_adaptor_users if str(u.get('username', '')).strip().lower() not in existing_usernames]

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_user":
            new_user = request.POST.get("new_username")
            new_pass = request.POST.get("new_password")
            payload = _create_payload(session_code, {"Username": new_user, "Password": new_pass})

            _handle_api_call(request,
                             lambda: controller.heappe_management_adaptor_user_post(**payload),
                             f"User {new_user} created.", "Creation failed.")
            invalidate_adaptor_users_cache(request)

            target_url = reverse("manage_project_adaptor_users",
                                 kwargs={"project_id": project_id}) if project_id else reverse(
                "manage_project_adaptor_users_base")
            return redirect(target_url)

        if project_id:
            if action == "assign":
                username = request.POST.get("username")
                role_id = int(request.POST.get("role_id"))
                payload = _create_payload(session_code,
                                          {"Username": username, "ProjectId": project_id, "Role": role_id})
                _handle_api_call(request,
                                 lambda: controller.heappe_management_assign_adaptor_user_to_project_post(**payload),
                                 f"User {username} assigned.", "Assignment failed.")
                invalidate_adaptor_users_cache(request)

            elif action == "unassign":
                username = request.POST.get("username")
                role_name = request.POST.get("role_name")
                role_id = ADAPTOR_USER_STR_TO_INT.get(role_name, 3)
                payload = _create_payload(session_code,
                                          {"Username": username, "ProjectId": project_id, "Role": role_id})
                _handle_api_call(request,
                                 lambda: controller.heappe_management_remove_adaptor_user_from_project_delete(
                                     **payload),
                                 f"User {username} removed.", "Removal failed.")
                invalidate_adaptor_users_cache(request)

            return redirect("manage_project_adaptor_users", project_id=project_id)


    return render(request, "manage_project_users.html", {
        "project": project_data,
        "all_projects": all_projects,
        "adaptor_users": adaptor_users_in_project,
        "available_users": available_users,
        "all_adaptor_users": all_adaptor_users,
        "system_role_assignments": system_role_assignments,
        "system_role_user_map": system_role_user_map,
        "roles_mapping": ADAPTOR_USER_STR_TO_INT
    })


def invalidate_cache_api(request):
    """
    API endpoint to invalidate the Django metadata cache from external components.
    Can be triggered via HTTP GET/POST from background scripts/daemons.
    """
    import os
    import time
    from django.conf import settings
    from django.http import JsonResponse

    timestamp_file = os.path.join(settings.BASE_DIR, "metadata_last_modified.txt")
    try:
        with open(timestamp_file, "w") as f:
            f.write(str(time.time()))
        return JsonResponse({"status": "ok", "message": "Cache invalidated globally"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def logs_context_api(request):
    log_date_str = request.GET.get('date')
    instance_name = request.GET.get('instance')
    filter_same_instance = request.GET.get('same_instance') == 'true'

    if not log_date_str:
        return JsonResponse({"status": "error", "message": "No date provided"}, status=400)

    instance = request.session.get('chosen_instance', 'develop')
    credentials = get_instance_settings(instance_name=instance)
    db_settings = {}
    if credentials:
        db_settings = {
            'server': credentials.log_db_host,
            'port': credentials.log_db_port,
            'user': credentials.log_db_user,
            'password': credentials.log_db_password,
            'database': credentials.log_db_database,
            'tds_version': '8.0',
        }

    try:
        if not db_settings or not db_settings.get('server') or not db_settings.get('database'):
            raise DatabaseSettingsError("Log database is not configured.")

        from datetime import datetime
        try:
            dt = datetime.strptime(log_date_str.replace('T', ' ')[:23], "%Y-%m-%d %H:%M:%S.%f")
            cleaned_date_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        except Exception:
            cleaned_date_str = log_date_str

        conn = pymssql.connect(**db_settings)
        cursor = conn.cursor(as_dict=True)

        cursor.execute("SELECT * FROM LoggingLevelType")
        levels_map = {row['Id']: row['Name'] for row in cursor.fetchall()}

        query = """
            SELECT TOP 15 l.*
            FROM Log l
            WHERE l.Date <= %s
        """
        params = [cleaned_date_str]

        if filter_same_instance and instance_name:
            query += " AND l.InstanceName = %s"
            params.append(instance_name)

        query += " ORDER BY l.Date DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()

        context_logs = []
        for r in rows:
            r['LevelName'] = levels_map.get(r['LevelId'], 'Unknown')
            if isinstance(r['Date'], datetime):
                r['Date'] = r['Date'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            context_logs.append(r)

        cursor.close()
        conn.close()

        context_logs.reverse()

        return JsonResponse({
            'status': 'success',
            'logs': context_logs
        })
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def report_error_view(request):
    """Standalone form + API endpoint for sending problem reports to HEAppE support."""
    import base64
    import datetime
    from django.core.mail import EmailMessage
    from django.http import JsonResponse
    from django.shortcuts import render

    last_error = request.session.get('last_error_report', {})

    # ── GET ── render standalone form page ───────────────────────────────────
    if request.method == 'GET':
        sent = request.GET.get('sent') == '1'
        return render(request, 'report_error_form.html', {
            'current_path': request.path,
            'last_error': last_error if last_error else None,
            'success': sent,
        })

    # ── POST ── validate, compose and send the email ─────────────────────────
    if request.method == 'POST':
        screenshot_data = request.POST.get('screenshot', '')
        summary         = request.POST.get('summary', '').strip()
        description     = request.POST.get('description', '').strip()
        category        = request.POST.get('category', 'other')
        affected_url    = request.POST.get('affected_url', '').strip()
        contact_email   = request.POST.get('contact_email', '').strip()

        if not contact_email:
            return JsonResponse({'status': 'error', 'message': 'Contact email is required.'}, status=400)
        if not summary or not description:
            return JsonResponse({'status': 'error', 'message': 'Summary and description are required.'}, status=400)

        category_labels = {
            'ui_error':       'UI / Interface Error',
            'heappe_error':   'HEAppE Instance Error',
            'deployment':     'Deployment Issue',
            'data_incorrect': 'Incorrect Data',
            'other':          'Other',
        }
        category_label = category_labels.get(category, category)
        username = request.user.username if hasattr(request, 'user') and request.user.is_authenticated else 'Anonymous'
        timestamp = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

        # Get admin panel version and branch
        try:
            from heappe_ui.context_processors import get_git_info
            git_info = get_git_info()
            admin_version = git_info.get('version', 'unknown')
            admin_branch = git_info.get('branch', 'unknown')
        except Exception:
            admin_version = 'unknown'
            admin_branch = 'unknown'

        # Get HEAppE middleware version
        heappe_version = request.session.get("middleware_deployed_version", "unknown")

        # Get additional debugging details
        import sys
        import platform
        python_version = sys.version.split()[0]
        server_os = platform.platform()
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        chosen_instance = request.session.get("chosen_instance", "unknown")

        subject = f"[HEAppE Support] {category_label}: {summary[:80]}"

        body = f"""HEAppE Management — Problem Report
====================================

Reporter:       {username} <{contact_email}>
Category:       {category_label}
Affected URL:   {affected_url or 'N/A'}
Timestamp(UTC): {timestamp}
Chosen Instance: {chosen_instance}

Environment & Versions:
-----------------------
HEAppE Admin Panel:  {admin_version} ({admin_branch})
HEAppE Middleware:   {heappe_version}
Python Version:      {python_version}
Server OS:           {server_os}
Browser User Agent:  {user_agent}

Summary
-------
{summary}

Description
-----------
{description}
"""
        details_only = f"""Description
-----------
{description}
"""
        # Append session HEAppE error details if available
        if last_error:
            body += f"""
Attached HEAppE Error Details
------------------------------
Instance Name:  {last_error.get('instance_name')}
Host URL:       {last_error.get('host_url')}
Error Type:     {last_error.get('error_type')}
Error Status:   {last_error.get('error_status')}
Error Message:
{last_error.get('error_message')}

Traceback:
{last_error.get('traceback')}
"""
            details_only += f"""
Attached HEAppE Error Details
------------------------------
Instance Name:  {last_error.get('instance_name')}
Host URL:       {last_error.get('host_url')}
Error Type:     {last_error.get('error_type')}
Error Status:   {last_error.get('error_status')}
Error Message:
{last_error.get('error_message')}

Traceback:
{last_error.get('traceback')}
"""

        from django.conf import settings
        support_email = getattr(settings, 'SUPPORT_EMAIL', 'jakub.konvicka@vsb.cz')

        # Clean cached error details from session as they are now compiled into the report
        request.session.pop('last_error_report', None)

        return JsonResponse({
            'status': 'manual',
            'to_email': support_email,
            'subject': subject,
            'body': body,
            'details_only': details_only,
            'admin_version': admin_version,
            'admin_branch': admin_branch,
            'heappe_version': heappe_version,
            'python_version': python_version,
            'server_os': server_os,
            'user_agent': user_agent,
            'chosen_instance': chosen_instance
        })

    return JsonResponse({'status': 'error', 'message': 'Method not allowed.'}, status=405)