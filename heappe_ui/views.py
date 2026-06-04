from heappe_ui.auth_backend import HeappeAuthBackend
from heappe_ui.view.imports import *
from heappe_ui.view.utils import *
from heappe_ui.view.clusters import *
from heappe_ui.view.queue import *
from heappe_ui.view.file_transfer_method import *
from heappe_ui.view.project import *
from heappe_ui.view.accounting import *
from heappe_ui.view.deploy import *
from heappe_ui.view.command_template import *
from heappe_ui.view.adaptor_user import *
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
    last_auth_ts = request.session.get("heappe_last_auth")

    if last_auth_ts:
        last_auth = datetime.fromtimestamp(float(last_auth_ts))
    else:
        last_auth = None

    return render(request, "user_profile.html", {"user": request.user,  "last_auth": last_auth})

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
    # reload
    return redirect(request.META.get('HTTP_REFERER', '/'))  # Redirect back to the previous page or home if no referrer


@login_required
def chose_instance_view(request):
    if request.method == "POST":
        instance_name = request.POST.get("InstanceName")
        if instance_name:
            request.session["chosen_instance"] = instance_name
            request.session["force_reauth"] = True
            return redirect("dashboard_view")

    instances = InstanceCredentials.objects.all()
    return render(request, "chose_instances.html", {"instances": instances})



from django.core.paginator import Paginator
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from datetime import datetime, timedelta

@login_required
def dashboard_view(request):
    context = {}
    if request.session.get("chosen_instance") is None:
        return redirect("instance_credentials_list")

    # Initialize controller
    controller = hp.ManagementApi(request.api_instance)
    jr_controller = hp.JobReportingApi(request.api_instance)
    health_controller = hp.HealthApi(request.api_instance)

    # Get HEAppE Health Info
    deployed_version = ""
    try:
        health_info = health_controller.heappe_health_get()
        # Převést na dict, pokud má objekt metodu to_dict()
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

    # HEAppE Middleware Update Banner Logic for Dashboard
    instance_name = request.session.get("chosen_instance")
    if instance_name:
        import time
        import os
        now_time = time.time()
        last_check = request.session.get("last_middleware_check_time", 0)
        last_checked_instance = request.session.get("last_middleware_checked_instance", "")

        # Fallback to cached deployed version if still not found
        if not deployed_version:
            deployed_version = request.session.get("middleware_deployed_version", "")

        # Fallback to appsettings if still empty
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

        # Fetch latest version from git if cache expired or not present
        if (now_time - last_check > 3600) or (instance_name != last_checked_instance) or not latest_version:
            from heappe_ui.view.deploy import get_remote_tags
            repo_url = "https://github.com/It4innovations/HEAppE"
            branches = get_remote_tags(repo_url)
            if branches:
                latest_version = branches[0].lstrip("vV")

        update_available = False
        if deployed_version and isinstance(deployed_version, str) and latest_version and isinstance(latest_version, str):
            def clean_ver(v):
                res = [int(n) for n in v.lower().lstrip('v').split('.') if n.isdigit()]
                return res if res else [0]
            try:
                if clean_ver(latest_version) > clean_ver(deployed_version):
                    update_available = True
            except Exception:
                if latest_version.lower().lstrip('v') != deployed_version.lower().lstrip('v'):
                    update_available = True

        # Save back to session so other pages are in sync
        request.session["last_middleware_check_time"] = now_time
        request.session["last_middleware_checked_instance"] = instance_name
        request.session["middleware_update_available"] = update_available
        request.session["middleware_deployed_version"] = deployed_version
        request.session["middleware_latest_version"] = latest_version

        # Inject into render context
        context["middleware_update_available"] = update_available
        context["middleware_deployed_version"] = deployed_version
        context["middleware_latest_version"] = latest_version

    # Get version information
    try:
        result = controller.heappe_management_version_information_get(SessionCode=request.session_code)
        context["heappe"] = result
    except Exception as e:
        print(f"Error fetching version information: {e}")

    # Get cluster information
    try:
        clusters = controller.heappe_management_clusters_get(SessionCode=request.session_code)
        context["clusters"] = clusters
    except Exception as e:
        print(f"Error fetching clusters: {e}")

    # Get project information
    try:
        projects = controller.heappe_management_projects_get(SessionCode=request.session_code)
        context["projects"] = projects
    except Exception as e:
        print(f"Error fetching projects: {e}")

    # Get queue information
    try:
        queues = [c.to_dict() for c in controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code)]
        context['queues'] = queues
    except Exception as e:
        print(f"Error fetching queues: {e}")

    # Get queue groups
    try:
        queue_groups = controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=request.session_code)
        context['queue_groups'] = queue_groups if queue_groups else []
    except Exception as e:
        print(f"Error fetching queue groups: {e}")
        context['queue_groups'] = []

    # Get job stats
    try:
        job_stats = jr_controller.heappe_job_reporting_jobs_state_agregation_report_get(SessionCode=request.session_code)
        all_states = [
            'Configuring', 'Submitted', 'Queued', 'Running', 'Finished',
            'Failed', 'Canceled', 'WaitingForServiceAccount', 'Deleted'
        ]
        job_counts = {s: 0 for s in all_states}
        for js in job_stats:
            job_counts[js.job_state_name] = js.count
        context["job_counts"] = job_counts
        context["total_jobs"] = sum(job_counts.values())
    except Exception as e:
        print(f"Error fetching job stats: {e}")

    # Get detailed job report
    try:
        # Set default time range: TimeTo=Now, TimeFrom=Now-1day
        time_to = request.GET.get('time_to', datetime.now().isoformat())
        time_from = request.GET.get('time_from', (datetime.now() - timedelta(days=1)).isoformat())

        # Convert string dates to datetime if needed by API
        try:
            time_to = datetime.fromisoformat(time_to)
            time_from = datetime.fromisoformat(time_from)
        except ValueError:
            time_to = datetime.now()
            time_from = datetime.now() - timedelta(days=1)

        # Enforce maximum scope of 90 days back and maximum range of 90 days
        now = datetime.now()
        min_allowed_date = now - timedelta(days=90)
        adjusted = False

        if time_to < min_allowed_date:
            time_to = now
            adjusted = True
        elif time_to > now + timedelta(hours=1):
            time_to = now
            adjusted = True

        if time_from < min_allowed_date:
            time_from = min_allowed_date
            adjusted = True
        elif time_from > time_to:
            time_from = time_to - timedelta(days=1)
            adjusted = True

        if (time_to - time_from) > timedelta(days=90):
            time_from = time_to - timedelta(days=90)
            adjusted = True

        if adjusted:
            from django.contrib import messages
            messages.warning(
                request,
                "The requested reporting time range was adjusted. The maximum allowed query range and scope is 90 days."
            )

        # Store for template
        context["time_to"] = time_to.strftime('%Y-%m-%dT%H:%M')
        context["time_from"] = time_from.strftime('%Y-%m-%dT%H:%M')
        context["min_date"] = min_allowed_date.strftime('%Y-%m-%dT%H:%M')
        context["max_date"] = now.strftime('%Y-%m-%dT%H:%M')

        # Get job details from API with date filters
        job_details_raw = jr_controller.heappe_job_reporting_jobs_detailed_report_get(
            SessionCode=request.session_code,
            TimeFrom=time_from,
            TimeTo=time_to
        )

        all_jobs = []
        seen_job_ids = set()
        for job in job_details_raw:
            for cluster in job.clusters:
                for node_type in cluster.cluster_node_types:
                    for job_item in node_type.jobs:
                        if job_item.id not in seen_job_ids:
                            seen_job_ids.add(job_item.id)
                            all_jobs.append(job_item)
        all_jobs.sort(key=lambda x: x.id or 0, reverse=True)



        # Paginator
        paginator = Paginator(all_jobs, 10)  # 10 jobs per page
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        context["job_details"] = page_obj.object_list  # teď obsahuje jen job_itemy, které se zobrazí
        context["page_obj"] = page_obj
    except Exception as e:
        print(f"Error fetching job details: {e}")

    return render(request, "dashboard.html", context)



class DatabaseSettingsError(Exception):
    pass

from django.db import connections
from django.shortcuts import render
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from collections import Counter
from datetime import datetime
import pymssql


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

        # Filtry z GET parametrů
        date_from = request.GET.get('date_from')
        if date_from is not None:
            date_from = date_from.replace('T', ' ')
        date_to = request.GET.get('date_to')
        if date_to is not None:
            date_to = date_to.replace('T', ' ')
        level_filter = request.GET.get('level')
        search = request.GET.get('search', '').lower()

        # SQL dotaz s podmínkami
        query = "SELECT * FROM Log WHERE 1=1"
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
    if pk is not None:
        instance = get_object_or_404(InstanceCredentials, pk=pk)
        if instance:
            request.session["chosen_instance"] = instance.instance_name
            request.session["force_reauth"] = True
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
        instance.delete()
        messages.success(request, f"Instance '{instance_name}' deleted successfully.")
        return redirect('instance_credentials_list')
    return render(request, 'instance_credentials.html', {'object_list': InstanceCredentials.objects.all()})


import subprocess
import os
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse

# Skript je umístěn PŘÍMO v kořenovém adresáři projektu, vedle manage.py
DEPLOY_SCRIPT_NAME = "deploy.sh"
# Sestavení plné cesty
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
from django.core.files.storage import default_storage # Volitelně, pro lepší práci s cestami

# --- DEFINE THESE CONSTANTS BASED ON YOUR PROJECT SETUP ---
# Example: Define the path to your deployment script relative to BASE_DIR
DEPLOY_SCRIPT_NAME = 'deploy.sh'
# Assuming the script is in the project's root directory
# Ujistěte se, že toto je správná cesta, např. /cesta/k/projektu/deploy.sh
DEPLOY_SCRIPT_PATH = os.path.join(settings.BASE_DIR, DEPLOY_SCRIPT_NAME)

# PŘED POUŽITÍM ZKONTROLUJTE, ŽE settings.BASE_DIR JE SPRÁVNĚ NASTAVENO!
# ---------------------------------------------------------


import subprocess
from django.http import JsonResponse
from django.conf import settings


import subprocess
from django.conf import settings
from django.http import JsonResponse


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
            'changes': cached_changes or []
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

    response = JsonResponse({
        'update_available': update_available,
        'current_version': current_version,
        'latest_version': latest_version,
        'changes': changes
    })
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


# ... tvoje existující error handling ...







@require_http_methods(["POST"])
@login_required # Důležité: Tuto kritickou operaci smí spustit jen přihlášený uživatel.
def trigger_deployment_direct(request):
    """Final API endpoint to execute the deployment script."""
    # 1. Input Validation and Parsing
    try:
        # Použijeme .decode('utf-8') pro jistotu
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
        # Ensure script is executable (rwx pro vlastníka, r-- pro skupinu/ostatní)
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

        # Doporučené: Použít shlex pro správné formátování příkazu
        # Ale jelikož je spouštěn jen skript, stačí i tento zápis
        process = subprocess.Popen(
            ['/bin/bash', DEPLOY_SCRIPT_PATH],
            cwd=settings.BASE_DIR,
            start_new_session=True,  # Důležité: Proces se odpojí a běží nezávisle (daemonizace)
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

def parse_log_line(line):
    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', line)
    timestamp_str = timestamp_match.group(1) if timestamp_match else None

    level = "INFO"
    if "ERROR" in line or "Exception" in line:
        level = "ERROR"
    elif "WARN" in line:
        level = "WARN"
    elif "DEBUG" in line:
        level = "DEBUG"

    return {
        'timestamp_str': timestamp_str,
        'level': level,
        'content': line
    }


def render_log_row(entry):
    border_class = "level-info"
    text_class = "badge-info"
    if entry['level'] == "ERROR":
        border_class = "level-error"
        text_class = "badge-danger"
    elif entry['level'] == "WARN":
        border_class = "level-warning"
        text_class = "badge-warning"
    elif entry['level'] == "DEBUG":
        border_class = "level-debug"
        text_class = "badge-secondary"

    formatted_content = escape(entry['content'])

    # Highlight time
    formatted_content = re.sub(
        r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
        r'<span class="time-badge">\1</span>',
        formatted_content
    )

    def json_repl(match):
        try:
            raw_json = match.group(0).replace('&quot;', '"').replace('&#x27;', "'")
            parsed = json.loads(raw_json)
            pretty = json.dumps(parsed, indent=2)
            return f'<pre class="json-block">{escape(pretty)}</pre>'
        except:
            return match.group(0)

    formatted_content = re.sub(r'(\{.*?\})', json_repl, formatted_content, flags=re.DOTALL)

    return f"""
    <tr class="log-row {border_class}">
        <td class="log-level-cell">
            <span class="log-level-badge {text_class}">{entry['level']}</span>
        </td>
        <td class="log-content-cell">
            <div class="log-content-text">{formatted_content}</div>
        </td>
    </tr>
    """


import re
import os
from datetime import datetime
from collections import deque
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


def process_log_entry(buffer, logs, stats, time_from, time_to, search_query, level_filter=''):
    combined_line = "".join(buffer)
    parsed = parse_log_line(combined_line)

    show_row = True
    if level_filter and parsed['level'] != level_filter:
        show_row = False

    if parsed['timestamp_str']:
        try:
            time_part = parsed['timestamp_str'].split(' ')[1]
            if time_from and time_part < (time_from + ":00"): show_row = False
            if time_to and time_part > (time_to + ":59"): show_row = False
        except:
            pass

    if search_query and search_query not in combined_line.lower():
        show_row = False

    if show_row:
        if parsed['level'] in stats:
            stats[parsed['level']] += 1
        logs.append(render_log_row(parsed))


@login_required
def log_viewer_view(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.now().strftime('%Y-%m-%d')
    selected_date = request.GET.get('date', today)
    time_from = request.GET.get('time_from', '')
    time_to = request.GET.get('time_to', '')
    search_query = request.GET.get('search', '').lower()
    level_filter = request.GET.get('level', '').upper()

    log_path = get_log_file_path(instance, selected_date)
    logs = deque(maxlen=3000)
    stats = {"ERROR": 0, "WARN": 0}

    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                buffer = []
                for line in f:
                    if re.search(r'\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}', line):
                        if buffer:
                            process_log_entry(buffer, logs, stats, time_from, time_to, search_query, level_filter)
                        buffer = [line]
                    else:
                        buffer.append(line)

                if buffer:
                    process_log_entry(buffer, logs, stats, time_from, time_to, search_query, level_filter)
        except Exception as e:
            logs.append(f"<tr><td colspan='2'>Error: {str(e)}</td></tr>")

    return render(request, 'file_log_viewer.html', {
        'logs': list(logs),
        'stats': stats,
        'selected_date': selected_date,
        'time_from': time_from,
        'time_to': time_to,
        'search_query': search_query,
        'level_filter': level_filter,
        'instance': instance
    })

def render_log_row(entry):
    border_class = "level-info"
    text_class = "badge-info"
    if entry['level'] == "ERROR":
        border_class = "level-error"
        text_class = "badge-danger"
    elif entry['level'] == "WARN":
        border_class = "level-warning"
        text_class = "badge-warning"
    elif entry['level'] == "DEBUG":
        border_class = "level-debug"
        text_class = "badge-secondary"

    formatted_content = escape(entry['content'])

    # Highlight time
    formatted_content = re.sub(
        r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
        r'<span class="time-badge">\1</span>',
        formatted_content
    )

    # Format JSON if present
    if "{" in formatted_content and "}" in formatted_content:
        def json_repl(match):
            try:
                raw_json = match.group(0).replace('&quot;', '"').replace('&#x27;', "'")
                parsed = json.loads(raw_json)
                pretty = json.dumps(parsed, indent=2)
                return f'<pre class="json-block">{escape(pretty)}</pre>'
            except:
                return match.group(0)

        formatted_content = re.sub(r'(\{.*?\})', json_repl, formatted_content, flags=re.DOTALL)

    return f"""
    <tr class="log-row {border_class}">
        <td class="log-level-cell">
            <span class="log-level-badge {text_class}">{entry['level']}</span>
        </td>
        <td class="log-content-cell">
            <div class="log-content-text">{formatted_content}</div>
        </td>
    </tr>
    """


def get_log_file_path(instance, date_str):
    base_path = f"/opt/heappe-deployment/{instance}/app/logs/API/"
    date_formatted = date_str.replace("-", "_")

    if not os.path.exists(base_path):
        return None

    files = sorted([f for f in os.listdir(base_path) if f.startswith(date_formatted) and f.endswith(".log")])

    if files:
        return os.path.join(base_path, files[-1])
    return None


# --- VIEWS ---

def parse_log_line(line):
    timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})', line)
    timestamp_str = timestamp_match.group(1) if timestamp_match else None

    level = "INFO"
    if "ERROR" in line or "Exception" in line:
        level = "ERROR"
    elif "WARN" in line:
        level = "WARN"
    elif "DEBUG" in line:
        level = "DEBUG"

    return {
        'timestamp_str': timestamp_str,
        'level': level,
        'content': line
    }

@login_required
def stream_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.now().strftime('%Y-%m-%d')
    log_path = get_log_file_path(instance, today)

    def event_stream():
        if not log_path or not os.path.exists(log_path):
            yield "data: <tr><td colspan='2'>Log file not found.</td></tr>\n\n"
            return

        with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, os.SEEK_END)

            while True:
                line = f.readline()
                if line:
                    parsed = parse_log_line(line)
                    html_row = render_log_row(parsed)
                    clean_html = html_row.replace('\n', '')
                    yield f"data: {clean_html}\n\n"
                else:
                    time.sleep(0.5)

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


import os
import json
from datetime import datetime
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def fetch_new_logs(request):
    instance = request.session.get('chosen_instance', 'develop')
    today = datetime.now().strftime('%Y-%m-%d')
    log_path = get_log_file_path(instance, today)
    level_filter = request.GET.get('level', '').upper()

    try:
        offset = int(request.GET.get('offset', 0))
    except ValueError:
        offset = 0

    if not log_path or not os.path.exists(log_path):
        return JsonResponse({'html': '', 'offset': offset})

    new_rows = []
    file_size = os.path.getsize(log_path)

    if offset == -1:
        return JsonResponse({'html': '', 'offset': file_size})

    if offset > file_size:
        offset = 0

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        f.seek(offset)
        for line in f:
            if line.strip():
                parsed = parse_log_line(line)
                if level_filter and parsed['level'] != level_filter:
                    continue
                new_rows.append(render_log_row(parsed))

        new_offset = f.tell()

    return JsonResponse({
        'html': "".join(new_rows),
        'offset': new_offset
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
            except Exception:
                pass


            all_adaptor_users = [u.to_dict() for u in
                                 controller.heappe_management_adaptor_users_get(SessionCode=session_code)]
            existing_usernames = {u['username'] for u in adaptor_users_in_project}
            available_users = [u for u in all_adaptor_users if u['username'] not in existing_usernames]

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create_user":
            new_user = request.POST.get("new_username")
            new_pass = request.POST.get("new_password")
            payload = _create_payload(session_code, {"Username": new_user, "Password": new_pass})

            _handle_api_call(request,
                             lambda: controller.heappe_management_adaptor_user_post(**payload),
                             f"User {new_user} created.", "Creation failed.")

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

            return redirect("manage_project_adaptor_users", project_id=project_id)

    return render(request, "manage_project_users.html", {
        "project": project_data,
        "all_projects": all_projects,
        "adaptor_users": adaptor_users_in_project,
        "available_users": available_users,
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