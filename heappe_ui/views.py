from heappe_ui.auth_backend import HeappeAuthBackend
from heappe_ui.view.imports import *
from heappe_ui.view.utils import *
from heappe_ui.view.clusters import *
from heappe_ui.view.queue import *
from heappe_ui.view.file_transfer_method import *
from heappe_ui.view.project import *
from heappe_ui.view.accounting import *
from heappe_ui.view.command_template import *
from django.contrib.auth.decorators import login_required

from django.shortcuts import render
import datetime


@login_required(login_url="/login/")
def index(request: HttpRequest) -> HttpResponse:
    return dashboard_view(request)

@login_required(login_url="/login/")
def home(request: HttpRequest) -> HttpResponse:
    return dashboard_view(request)



@login_required(login_url="/login/")
def logout_view(request):
    from django.contrib.auth import logout
    HeappeAuthBackend.api_instance = None
    HeappeAuthBackend.session_code = None
    request.session.flush()
    logout(request)
    return redirect("login")

@login_required(login_url="/login/")
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



@login_required(login_url="/login/")
def assign_project_to_cluster(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        action = request.POST.get("action")
        if action == "assign_cluster":
            payload_data = {
                "ProjectId": int(request.POST.get("ProjectId")),
                "ClusterId": int(request.POST.get("ClusterId")),
                "LocalBasepath": request.POST.get("LocalBasepath", "")
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

@login_required(login_url="/login/")
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

@login_required(login_url="/login/")
def update_app(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'message': 'Invalid JSON'}, status=400)

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return JsonResponse({'message': 'Username and password are required'}, status=401)

        try:
            # Path to the repository (e.g., project root directory)
            repo_path = settings.BASE_DIR

            # Get the current Git remote URL
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            remote_url = result.stdout.strip()

            # Modify the remote URL to include credentials for HTTPS
            if remote_url.startswith('https://'):
                # Insert credentials into the URL (e.g., https://username:password@domain.com/...)
                remote_url_parts = remote_url.split('https://')
                auth_remote_url = f'https://{username}:{password}@{remote_url_parts[1]}'
            else:
                return JsonResponse({'message': 'Git remote is not HTTPS'}, status=400)

            # Commands for the update
            commands = [
                ['git', 'pull', auth_remote_url],  # Pull with authenticated URL
                ['pip', 'install', '-r', 'requirements.txt'],  # Updates dependencies
                ['python3', 'manage.py', 'migrate'],  # Runs database migrations
            ]

            # Execute commands
            for cmd in commands:
                result = subprocess.run(
                    cmd,
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True
                )
                if result.returncode != 0:
                    return JsonResponse({'message': f'Error during {cmd}: {result.stderr}'}, status=500)

            # Optional: Restart the server
            # Note: This depends on your deployment (e.g., Gunicorn, uWSGI).
            touch_file = os.path.join(repo_path, 'reload.trigger')
            with open(touch_file, 'a'):
                os.utime(touch_file, None)

            return JsonResponse({'message': 'Application updated successfully!'})

        except subprocess.CalledProcessError as e:
            return JsonResponse({'message': f'Update error: {e.stderr}'}, status=500)
        except Exception as e:
            return JsonResponse({'message': f'Unexpected error: {str(e)}'}, status=500)

    return render(request, "update_app.html")


@login_required(login_url="/login/")
def profile_view(request):
    last_auth_ts = request.session.get("heappe_last_auth")

    if last_auth_ts:
        last_auth = datetime.fromtimestamp(float(last_auth_ts))
    else:
        last_auth = None

    return render(request, "user_profile.html", {"user": request.user,  "last_auth": last_auth})


@login_required(login_url="/login/")
def dashboard_view(request):
    context = {}
    #get version information
    controller = hp.ManagementApi(request.api_instance)
    try:
        result = controller.heappe_management_version_information_get(SessionCode=request.session_code)
        context["heappe"] = result
    except Exception as e:
        print(f"Error fetching version information: {e}")

    #get cluster information
    try:
        clusters = controller.heappe_management_clusters_get(SessionCode=request.session_code)
        context["clusters"] = clusters
    except Exception as e:
        print(f"Error fetching clusters: {e}")

    #get project information
    try:
        projects = controller.heappe_management_projects_get(SessionCode=request.session_code)
        context["projects"] = projects
    except Exception as e:
        print(f"Error fetching projects: {e}")

    try:
        queues = [c.to_dict() for c in
                  controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code)]
        context['queues'] = queues
    except Exception as e:
        print(f"Error fetching projects: {e}")

    # get job stats JobsStateAgregationReport
    try:
        jrController = hp.JobReportingApi(request.api_instance)
        job_stats = jrController.heappe_job_reporting_jobs_state_agregation_report_get(SessionCode=request.session_code)
        all_states = [
            'Configuring', 'Submitted', 'Queued', 'Running', 'Finished',
            'Failed', 'Canceled', 'WaitingForServiceAccount', 'Deleted'
        ]

        # převedeme job_stats na dict {state_name: count}
        job_counts = {s: 0 for s in all_states}
        for js in job_stats:
            job_counts[js.job_state_name] = js.count
        context["job_counts"] = job_counts
    except Exception as e:
        print(f"Error fetching job stats: {e}")


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
from .models import LogDatabaseCredentials

from .models import LogDatabaseCredentials


def save_log_credentials(heappe_host, heappe_login,
                         log_db_host, log_db_port,
                         log_db_user, log_db_password,
                         log_db_database):
    obj, created = LogDatabaseCredentials.objects.update_or_create(
        heappe_host=heappe_host,
        heappe_login=heappe_login,
        defaults={
            'log_db_host': log_db_host,
            'log_db_port': log_db_port,
            'log_db_user': log_db_user,
            'log_db_password': log_db_password,
            'log_db_database': log_db_database,
        }
    )
    return obj, created


def get_log_credentials(heappe_host, heappe_login):
    try:
        return LogDatabaseCredentials.objects.get(
            heappe_host=heappe_host,
            heappe_login=heappe_login
        )
    except LogDatabaseCredentials.DoesNotExist:
        return None

@login_required(login_url="/login/")
def logs_view(request):
    context = {}

    # Handle database configuration form submission
    if request.method == 'POST' and request.POST.get('config_submit'):
        save_log_credentials(
            heappe_host=request.session["heappe_host"],
            heappe_login=request.session["heappe_username"],
            log_db_host=request.POST.get('server'),
            log_db_port=request.POST.get('port'),
            log_db_user=request.POST.get('user'),
            log_db_password=request.POST.get('password'),
            log_db_database=request.POST.get('database'))


    credentials = get_log_credentials(heappe_host = request.session["heappe_host"],
    heappe_login = request.session["heappe_username"])
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