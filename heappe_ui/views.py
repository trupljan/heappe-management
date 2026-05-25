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


@login_required
def profile_view(request):
    last_auth_ts = request.session.get("heappe_last_auth")

    if last_auth_ts:
        last_auth = datetime.fromtimestamp(float(last_auth_ts))
    else:
        last_auth = None

    return render(request, "user_profile.html", {"user": request.user,  "last_auth": last_auth})

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
    try:
        health_info = health_controller.heappe_health_get()
        # Převést na dict, pokud má objekt metodu to_dict()
        health = health_info.to_dict() if hasattr(health_info, "to_dict") else health_info
        context["health"] = health
    except Exception as e:
        print(f"Error fetching health info: {e}")
        context["health"] = {
            "IsHealthy": False,
            "Error": str(e)
        }

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

        # Store for template
        context["time_to"] = time_to.strftime('%Y-%m-%dT%H:%M')
        context["time_from"] = time_from.strftime('%Y-%m-%dT%H:%M')

        # Get job details from API with date filters
        job_details_raw = jr_controller.heappe_job_reporting_jobs_detailed_report_get(
            SessionCode=request.session_code,
            TimeFrom=time_from,
            TimeTo=time_to
        )

        # Rozbalit všechny job_itemy do jednoho seznamu
        all_jobs = []
        for job in job_details_raw:
            for cluster in job.clusters:
                for node_type in cluster.cluster_node_types:
                    all_jobs.extend(node_type.jobs)
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
    repo_path = settings.BASE_DIR
    try:
        subprocess.run(['git', 'fetch', '--all'], cwd=repo_path, check=True, timeout=15, capture_output=True)

        local_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo_path).decode().strip()
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=repo_path).decode().strip()
        remote_hash = subprocess.check_output(['git', 'rev-parse', '@{u}'], cwd=repo_path).decode().strip()

        update_available = local_hash != remote_hash
        commit_messages = []

        if update_available:
            log_output = subprocess.check_output(
                ['git', 'log', 'HEAD..@{u}', '--format=%s'],
                cwd=repo_path
            ).decode().strip()

            if log_output:
                commit_messages = log_output.split('\n')

        return JsonResponse({
            'update_available': update_available,
            'local': local_hash[:7],
            'remote': remote_hash[:7],
            'branch': branch,
            'changes': commit_messages
        })


    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        return JsonResponse({'error': f'Git error: {error_msg}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ... tvoje existující error handling ...

@login_required
def update_server_page(request):
    """Renders the page with the update button and form."""
    return render(request, 'update_server.html')


def execute_git_ls_remote(git_url, git_username=None, git_password=None):
    """
    Executes 'git ls-remote' to get branches and tags, handling credentials.
    Returns (list_of_refs, error_message, status_code).
    """

    # 1. Prepare Git URL with credentials for HTTPS access
    if git_username and git_password:
        url_parts = git_url.split('://', 1)
        if len(url_parts) == 2:
            # Format: https://<username>:<password>@<domain>/<repo.git>
            domain_and_path = url_parts[1]
            auth_url = f"{url_parts[0]}://{git_username}:{git_password}@{domain_and_path}"
        else:
            # Nevalidní URL formát, použijeme původní
            auth_url = git_url
    else:
        auth_url = git_url

    # 2. Prepare the command: list all branches (--heads) and tags (--tags)
    command = ['git', 'ls-remote', '--heads', '--tags', auth_url]

    try:
        # Použijeme nastavení ověřování SSL z prostředí Git (je-li potřeba)
        # Tímto se zamezí chybám SSL, pokud není certifikát známý
        env = os.environ.copy()
        # env['GIT_SSL_NO_VERIFY'] = 'true' # Povolte pouze v testovacím prostředí

        result = subprocess.run(command,
                                capture_output=True,
                                text=True,
                                check=False,
                                timeout=15,
                                env=env) # Předáme upravené prostředí

        # 3. Handle Git errors
        if result.returncode != 0:
            error_output = result.stderr.lower()

            # Authentication failure check
            if any(auth_error in error_output for auth_error in
                   ['authentication failed', '401 unauthorized', '403 forbidden', 'credential', 'could not read username']):
                return None, "Authentication required or failed for Git URL. Status code: 401.", 401

            return None, f"Git error: {result.stderr.strip()}", 500

        # 4. Parse the successful output
        refs = []
        for line in result.stdout.splitlines():
            if '\t' in line:
                ref = line.split('\t')[1]

                # Clean up: strip 'refs/heads/' or 'refs/tags/' prefix
                if ref.startswith('refs/heads/'):
                    refs.append(ref.replace('refs/heads/', ''))
                elif ref.startswith('refs/tags/'):
                    # Ignore the dereferenced tag lines (e.g., 'v1.0.0^{}')
                    if not ref.endswith('^{}'):
                        refs.append(ref.replace('refs/tags/', ''))

        # Return unique and sorted refs (e.g., ['main', 'v1.0.0'])
        return sorted(list(set(refs))), None, 200

    except subprocess.TimeoutExpired:
        return None, "Git operation timed out (15s).", 504
    except Exception as e:
        return None, f"Internal server error during Git check: {e}", 500


# -----------------------------------------------------------------
# --- VIEW FOR STEP 1: Check Repo and Fetch Branches (API Endpoint - Neměněno) ---
# -----------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
# Použití @csrf_exempt je zde v pořádku, protože na backendu dojde k ověření přes GIT,
# ale v produkci zvažte přidání např. @login_required + @ensure_csrf_cookie nebo jiný token pro AJAX.
# Pokud je tento endpoint volán jen po úspěšném přihlášení, je to mírně bezpečnější.
def check_repo_and_fetch_branches(request):
    """API endpoint to check a Git URL and fetch available branches/tags."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Invalid JSON.")

    git_url = data.get('git_url')
    git_username = data.get('git_username')
    # Opatrně s heslem - zde ho přijímáme a rovnou posíláme do helper funkce, kde je použito v URL
    git_password = data.get('git_password')

    if not git_url:
        return JsonResponse({'message': 'Git URL is required.'}, status=400)

    # Volání helper funkce, která provede Git operaci
    tags_and_branches, error_message, status_code = execute_git_ls_remote(
        git_url, git_username, git_password
    )

    if tags_and_branches:
        return JsonResponse({
            'status': 'success',
            'message': 'Repository check successful.',
            'git_url': git_url,
            'tags_and_branches': tags_and_branches
        }, status=status_code)
    else:
        # Authentication failure (401) or general error (500)
        return JsonResponse({
            'status': 'error',
            'message': error_message,
            'git_url': git_url,
        }, status=status_code)


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
    border_class = "border-info"
    text_class = "text-info"
    if entry['level'] == "ERROR":
        border_class = "border-danger";
        text_class = "text-danger"
    elif entry['level'] == "WARN":
        border_class = "border-warning";
        text_class = "text-warning"

    formatted_content = escape(entry['content'])

    formatted_content = re.sub(
        r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
        r'<span class="time-badge" style="background:#f1f5f9;border:1px solid #e2e8f0;padding:0 4px;border-radius:4px;color:#64748b;margin-right:8px;font-size:0.85em">\1</span>',
        formatted_content
    )

    def json_repl(match):
        try:
            raw_json = match.group(0).replace('&quot;', '"').replace('&#x27;', "'")
            parsed = json.loads(raw_json)
            pretty = json.dumps(parsed, indent=2)
            return f'<div class="json-block" style="background:#f8fafc;border-left:3px solid #0dcaf0;padding:8px;margin:8px 0;white-space:pre;font-size:0.85em;color:#1e293b;border-radius:0 4px 4px 0;">{escape(pretty)}</div>'
        except:
            return match.group(0)

    formatted_content = re.sub(r'(\{.*?\})', json_repl, formatted_content, flags=re.DOTALL)

    return f"""
    <tr class="log-row {border_class}" style="border-left: 4px solid;">
        <td style="width: 100px; vertical-align: top;" class="ps-3 py-2">
            <span class="badge {text_class} bg-light border fw-bold">{entry['level']}</span>
        </td>
        <td class="py-2 pe-3">
            <div class="log-content" style="font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-all;">{formatted_content}</div>
        </td>
    </tr>
    """


import re
import os
from datetime import datetime
from collections import deque
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


def process_log_entry(buffer, logs, stats, time_from, time_to, search_query):
    combined_line = "".join(buffer)
    parsed = parse_log_line(combined_line)

    show_row = True
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
                            process_log_entry(buffer, logs, stats, time_from, time_to, search_query)
                        buffer = [line]
                    else:
                        buffer.append(line)

                if buffer:
                    process_log_entry(buffer, logs, stats, time_from, time_to, search_query)
        except Exception as e:
            logs.append(f"<tr><td colspan='2'>Error: {str(e)}</td></tr>")

    return render(request, 'file_log_viewer.html', {
        'logs': list(logs),
        'stats': stats,
        'selected_date': selected_date,
        'time_from': time_from,
        'time_to': time_to,
        'search_query': search_query,
        'instance': instance
    })

def render_log_row(entry):
    border_class = "border-info"
    text_class = "text-info"
    if entry['level'] == "ERROR":
        border_class = "border-danger";
        text_class = "text-danger"
    elif entry['level'] == "WARN":
        border_class = "border-warning";
        text_class = "text-warning"
    elif entry['level'] == "DEBUG":
        border_class = "border-secondary";
        text_class = "text-muted"

    formatted_content = escape(entry['content'])

    # Highlight time
    formatted_content = re.sub(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
                               r'<span class="time-badge" style="background:#f1f5f9;border:1px solid #e2e8f0;padding:0 4px;border-radius:4px;color:#64748b;margin-right:8px;font-size:0.85em">\1</span>',
                               formatted_content)

    # Format JSON if present
    if "{" in formatted_content and "}" in formatted_content:
        def json_repl(match):
            try:
                raw_json = match.group(0).replace('&quot;', '"')
                parsed = json.loads(raw_json)
                pretty = json.dumps(parsed, indent=2)
                return f'<div class="json-block" style="background:#f8fafc;border-left:3px solid #cbd5e1;padding:5px;margin:5px 0;white-space:pre;font-size:0.8em;color:#334155">{escape(pretty)}</div>'
            except:
                return match.group(0)

        formatted_content = re.sub(r'(\{.*?\})', json_repl, formatted_content)

    return f"""
    <tr class="log-row {border_class}" style="border-left: 4px solid;">
        <td style="width: 100px; vertical-align: top;" class="ps-3 py-2">
            <span class="badge {text_class} bg-light border fw-bold">{entry['level']}</span>
        </td>
        <td class="py-2 pe-3">
            <div class="log-content" style="font-family: monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-all;">{formatted_content}</div>
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
def logs_analyzer_view(request):
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

    errors = []
    is_demo_mode = False
    error_msg = None

    try:
        # Check if database is fully configured
        if not db_settings or not db_settings.get('server') or not db_settings.get('database'):
            raise DatabaseSettingsError("Log database is not configured. Falling back to Demo Mode.")
        
        # Connect and fetch latest errors
        conn = pymssql.connect(**db_settings)
        cursor = conn.cursor(as_dict=True)
        
        # Fetch LoggingLevelType first
        cursor.execute("SELECT * FROM LoggingLevelType")
        level_rows = cursor.fetchall()
        levels_map = {row['Id']: row['Name'] for row in level_rows}
        
        # Fetch errors
        cursor.execute("""
            SELECT TOP 50 l.*
            FROM dbo.Log l
            WHERE l.LevelId IN (4, 5)
            ORDER BY l.Date DESC
        """)
        rows = cursor.fetchall()
        for r in rows:
            r['LevelName'] = levels_map.get(r['LevelId'], 'Error' if r['LevelId'] == 4 else 'Critical')
            errors.append(r)
            
        cursor.close()
        conn.close()
    except Exception as e:
        is_demo_mode = True
        error_msg = str(e)
        errors = _get_mock_errors(instance)

    return render(request, 'logs_analyzer.html', {
        'errors': errors,
        'is_demo_mode': is_demo_mode,
        'error_msg': error_msg,
        'instance': instance,
    })


def _get_mock_errors(instance):
    from datetime import datetime, timedelta
    now = datetime.now()
    
    mock_templates = [
        {
            "Id": 1,
            "IP": "192.168.1.105",
            "InstanceName": instance,
            "InstanceVersion": "v6.0.0",
            "LevelId": 4,
            "LevelName": "Error",
            "Date": now - timedelta(minutes=5),
            "UserId": 42,
            "UserName": "johndoe",
            "UserEmail": "john.doe@it4i.cz",
            "JobId": 45091,
            "Message": "Failed to allocate resource: CPU limit exceeded on node node-042.",
            "Class": "HEAppE.Core.Scheduler",
            "Exception": "ResourceAllocationException: Requested cores (128) exceeds current free capacity on node-042.\n   at HEAppE.Core.Scheduler.AllocationManager.Allocate(JobContext context)\n   at HEAppE.Core.Scheduler.SubmitTask.Execute()"
        },
        {
            "Id": 2,
            "IP": "192.168.1.102",
            "InstanceName": instance,
            "InstanceVersion": "v6.0.0",
            "LevelId": 4,
            "LevelName": "Error",
            "Date": now - timedelta(minutes=18),
            "UserId": 1,
            "UserName": "admin",
            "UserEmail": "admin@it4i.cz",
            "JobId": 45092,
            "Message": "Database connection timed out during active transaction commit.",
            "Class": "HEAppE.Core.Database",
            "Exception": "TimeoutException: Database transaction checkout failed to commit within 15 seconds.\n   at HEAppE.Core.Database.ConnectionPool.Commit(Transaction tx)\n   at HEAppE.Core.Services.JobService.UpdateState(Int32 jobId, Int32 state)"
        },
        {
            "Id": 3,
            "IP": "10.0.4.15",
            "InstanceName": instance,
            "InstanceVersion": "v6.0.0",
            "LevelId": 5,
            "LevelName": "Critical",
            "Date": now - timedelta(minutes=42),
            "UserId": None,
            "UserName": None,
            "UserEmail": None,
            "JobId": None,
            "Message": "Staging area space critical: less than 1% free space left.",
            "Class": "HEAppE.Core.Storage",
            "Exception": "IOException: Disk full on partition /var/heappe/staging\n   at System.IO.DiskSpaceTracker.CheckStorageLimits()\n   at HEAppE.Core.Storage.StagingCleanupManager.Run()"
        },
        {
            "Id": 4,
            "IP": "192.168.1.109",
            "InstanceName": instance,
            "InstanceVersion": "v6.0.0",
            "LevelId": 4,
            "LevelName": "Error",
            "Date": now - timedelta(hours=1, minutes=5),
            "UserId": 18,
            "UserName": "cluster_agent",
            "UserEmail": "agent@it4i.cz",
            "JobId": 45095,
            "Message": "Unauthorized attempt to access job data for JobId #45095.",
            "Class": "HEAppE.Core.Security",
            "Exception": "SecurityException: Principal has insufficient permissions to modify or access this job context.\n   at HEAppE.Core.Security.AuthManager.VerifyAccess(UserPrincipal principal, Job job)"
        },
        {
            "Id": 5,
            "IP": "127.0.0.1",
            "InstanceName": instance,
            "InstanceVersion": "v6.0.0",
            "LevelId": 5,
            "LevelName": "Critical",
            "Date": now - timedelta(hours=2, minutes=10),
            "UserId": None,
            "UserName": None,
            "UserEmail": None,
            "JobId": None,
            "Message": "Vault token renewal failed: secret engine unreachable.",
            "Class": "HEAppE.Core.Security",
            "Exception": "VaultException: Service unavailable (status code 503)\n   at HEAppE.Core.Security.VaultClient.RenewToken(String token)\n   at HEAppE.Core.Security.VaultTokenRefresher.Tick()"
        },
        {
            "Id": 6,
            "IP": "192.168.1.200",
            "InstanceName": instance,
            "InstanceVersion": "v6.0.0",
            "LevelId": 4,
            "LevelName": "Error",
            "Date": now - timedelta(hours=3, minutes=30),
            "UserId": 12,
            "UserName": "api_user",
            "UserEmail": "api@it4i.cz",
            "JobId": None,
            "Message": "Scheduler synchronization failed: response code 503 from backend.",
            "Class": "HEAppE.Core.Api",
            "Exception": "HttpRequestException: Server returned service unavailable status.\n   at HEAppE.Core.Api.BackendClient.SyncSchedulerState()\n   at HEAppE.Core.Services.SyncService.Process()"
        }
    ]
    return mock_templates


@login_required
def logs_analyzer_context_api(request):
    error_id = request.GET.get('error_id')
    mode = request.GET.get('mode', 'instance') # instance, user, job
    
    # We also pass search details from frontend just in case
    error_date_str = request.GET.get('date')
    instance_name = request.GET.get('instance')
    user_name = request.GET.get('user')
    job_id = request.GET.get('job_id')
    
    # Safe parsing of error_id
    try:
        error_id_int = int(error_id) if error_id and error_id != 'undefined' else 1
    except ValueError:
        error_id_int = 1
        
    # Safe parsing of job_id
    job_id_int = None
    if job_id and job_id != 'None' and job_id != 'undefined' and job_id != '':
        try:
            job_id_int = int(job_id)
        except ValueError:
            pass
            
    # Parse date
    if error_date_str:
        try:
            error_date = datetime.fromisoformat(error_date_str.replace('Z', '+00:00'))
        except Exception:
            error_date = datetime.now()
    else:
        error_date = datetime.now()

    # Database settings
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

    context_logs = []
    is_demo = False

    try:
        if not db_settings or not db_settings.get('server') or not db_settings.get('database'):
            raise DatabaseSettingsError()
            
        conn = pymssql.connect(**db_settings)
        cursor = conn.cursor(as_dict=True)
        
        cursor.execute("SELECT * FROM LoggingLevelType")
        level_rows = cursor.fetchall()
        levels_map = {row['Id']: row['Name'] for row in level_rows}
        
        # Build query
        query_base = """
            SELECT TOP 15 l.*
            FROM dbo.Log l
            WHERE l.Date <= %s
        """
        params = [error_date]
        
        # We will try filtering by InstanceName first
        query = query_base + " AND l.InstanceName = %s"
        params_with_instance = params + [instance_name or instance]
        
        if mode == 'user' and user_name:
            query += " AND l.UserName = %s"
            params_with_instance.append(user_name)
        elif mode == 'job' and job_id_int is not None:
            query += " AND l.JobId = %s"
            params_with_instance.append(job_id_int)
            
        query += " ORDER BY l.Date DESC"
        
        cursor.execute(query, params_with_instance)
        rows = cursor.fetchall()
        
        # Fallback: if no rows are found, try without InstanceName filter
        if not rows:
            query_fallback = query_base
            params_fallback = params.copy()
            if mode == 'user' and user_name:
                query_fallback += " AND l.UserName = %s"
                params_fallback.append(user_name)
            elif mode == 'job' and job_id_int is not None:
                query_fallback += " AND l.JobId = %s"
                params_fallback.append(job_id_int)
                
            query_fallback += " ORDER BY l.Date DESC"
            cursor.execute(query_fallback, params_fallback)
            rows = cursor.fetchall()
            
        for r in rows:
            r['LevelName'] = levels_map.get(r['LevelId'], 'Information')
            # Format datetime to string for json serialization
            if isinstance(r['Date'], datetime):
                r['Date'] = r['Date'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            context_logs.append(r)
            
        cursor.close()
        conn.close()
        
        # Chronological order
        context_logs.reverse()
        
    except Exception:
        is_demo = True
        context_logs = _get_mock_context_logs(error_id_int, mode, user_name, job_id_int)

    return JsonResponse({
        'status': 'success',
        'is_demo': is_demo,
        'logs': context_logs
    })


def _get_mock_context_logs(error_id, mode, user_name, job_id):
    from datetime import datetime, timedelta
    now = datetime.now()
    logs = []
    
    # We generate context depending on error_id
    if error_id == 1: # CPU Limit error
        base_time = now - timedelta(minutes=5)
        raw_logs = [
            ("Information", "HEAppE.Core.Scheduler", "Job submission request for JobId #45091 (NodeCount=8, CoreCount=128) by user johndoe.", -120),
            ("Debug", "HEAppE.Core.Scheduler", "Validating limits for user 'johndoe'. Max cores allowed: 512, currently using: 256.", -100),
            ("Debug", "HEAppE.Core.Scheduler", "Scheduler queued JobId #45091 in queue 'Q_Standard'.", -90),
            ("Information", "HEAppE.Core.Scheduler", "Scheduler assigned JobId #45091 to cluster node-042.", -60),
            ("Debug", "HEAppE.Core.Api", "Sending deployment command payload to sshagent for node-042.", -45),
            ("Debug", "HEAppE.Core.Api", "Executing remote command: /opt/heappe/bin/run_hpc_job.sh --job-id 45091.", -30),
            ("Warning", "HEAppE.Core.Scheduler", "Node node-042 reported high memory load: 94%.", -10),
            ("Error", "HEAppE.Core.Scheduler", "Failed to allocate resource: CPU limit exceeded on node node-042.", 0),
        ]
    elif error_id == 2: # DB Timeout error
        base_time = now - timedelta(minutes=18)
        raw_logs = [
            ("Information", "HEAppE.Core.Api", "Transaction checkout request received for session admin_session_91a.", -50),
            ("Debug", "HEAppE.Core.Database", "Acquired DB connection from connection pool (Active connections: 48/50).", -40),
            ("Debug", "HEAppE.Core.Database", "Executing query: UPDATE JobState SET State = 4 WHERE Id = 45092.", -30),
            ("Warning", "HEAppE.Core.Database", "DB lock contention detected on table JobState for page 984.", -20),
            ("Warning", "HEAppE.Core.Database", "Retrying transaction commit (attempt 1/3)...", -10),
            ("Error", "HEAppE.Core.Database", "Database connection timed out during active transaction commit.", 0),
        ]
    elif error_id == 3: # Disk full error
        base_time = now - timedelta(minutes=42)
        raw_logs = [
            ("Information", "HEAppE.Core.Storage", "Staging folder clean-up task initiated by scheduler.", -300),
            ("Information", "HEAppE.Core.Storage", "Checked directory size for /opt/heappe-deployment/develop/staging/temp: 954 GB.", -240),
            ("Warning", "HEAppE.Core.Storage", "Failed to remove temporary file: Permission denied for /opt/heappe-deployment/develop/staging/temp/job_4412_out.tar.", -180),
            ("Warning", "HEAppE.Core.Storage", "Clean-up task completed with warnings. Freed 0 bytes.", -120),
            ("Critical", "HEAppE.Core.Storage", "Staging area space critical: less than 1% free space left.", 0),
        ]
    elif error_id == 4: # Unauthorized JobAccess error
        base_time = now - timedelta(hours=1, minutes=5)
        raw_logs = [
            ("Debug", "HEAppE.Core.Security", "Authenticating user 'cluster_agent' via session token.", -50),
            ("Information", "HEAppE.Core.Security", "User 'cluster_agent' authenticated successfully (Roles: Agent).", -45),
            ("Debug", "HEAppE.Core.Api", "API call received: GetJobDetails for JobId #45095.", -40),
            ("Debug", "HEAppE.Core.Security", "Checking ownership permissions for principal 'cluster_agent' on JobId #45095.", -20),
            ("Error", "HEAppE.Core.Security", "Unauthorized attempt to access job data for JobId #45095.", 0),
        ]
    elif error_id == 5: # Vault error
        base_time = now - timedelta(hours=2, minutes=10)
        raw_logs = [
            ("Information", "HEAppE.Core.Security", "Vault client tick interval reached (300s).", -300),
            ("Debug", "HEAppE.Core.Security", "Vault client sending token renewal request to http://vault:8200.", -200),
            ("Warning", "HEAppE.Core.Security", "Connection to Vault host timed out. Retrying in 10s...", -150),
            ("Warning", "HEAppE.Core.Security", "Vault client sending token renewal request to http://vault:8200 (Attempt 2/3).", -140),
            ("Critical", "HEAppE.Core.Security", "Vault token renewal failed: secret engine unreachable.", 0),
        ]
    else: # API Sync error
        base_time = now - timedelta(hours=3, minutes=30)
        raw_logs = [
            ("Information", "HEAppE.Core.Api", "Synchronization routine started.", -60),
            ("Debug", "HEAppE.Core.Api", "Connecting to backend service at https://backend.heappe.org/api/sync.", -45),
            ("Warning", "HEAppE.Core.Api", "HTTP request to backend service failed (status code: 503 Service Unavailable).", -30),
            ("Information", "HEAppE.Core.Api", "Retrying backend sync in 10 seconds...", -20),
            ("Error", "HEAppE.Core.Api", "Scheduler synchronization failed: response code 503 from backend.", 0)
        ]

    # Now filter by mode
    for level, clz, msg, offset in raw_logs:
        log_date = base_time + timedelta(seconds=offset)
        
        # User filter check
        if mode == 'user' and user_name and user_name != 'admin' and user_name != 'johndoe' and user_name != 'cluster_agent' and user_name != 'api_user':
            # Skip logs that don't match the requested user
            continue
            
        # Job filter check
        if mode == 'job' and job_id and str(job_id) not in msg:
            # Skip if doesn't match job id
            continue
            
        logs.append({
            "Id": len(logs) + 100,
            "IP": "192.168.1.100",
            "InstanceName": "develop",
            "InstanceVersion": "v6.0.0",
            "LevelId": 2 if level == "Information" else (1 if level == "Debug" else (3 if level == "Warning" else (4 if level == "Error" else 5))),
            "LevelName": level,
            "Date": log_date.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            "UserId": 42 if user_name == 'johndoe' else (1 if user_name == 'admin' else None),
            "UserName": user_name or ("johndoe" if error_id == 1 else ("admin" if error_id == 2 else None)),
            "UserEmail": f"{user_name}@it4i.cz" if user_name else None,
            "JobId": job_id if job_id is not None else (45091 if error_id == 1 else (45092 if error_id == 2 else None)),
            "Message": msg,
            "Class": clz,
            "Exception": ""
        })
        
    return logs