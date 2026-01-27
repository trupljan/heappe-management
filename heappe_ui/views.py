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
                "ProjectStoragePath": request.POST.get("PermanentStoragePath", "")
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
        form = InstanceCredentialsForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, f"Instance '{form.cleaned_data['instance_name']}' updated successfully.")
            return redirect('instance_credentials_list')
        else:
            messages.error(request, 'Error updating instance. Please check the form.')
    else:
        form = InstanceCredentialsForm(instance=instance)
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


# --- HTML Renderer View ---
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


def get_log_files(log_path, selected_date_str):
    formatted_date = selected_date_str.replace("-", "_")
    files = []
    if os.path.exists(log_path):
        for f in os.listdir(log_path):
            if f.startswith(formatted_date) and ".log" in f:
                files.append(f)
    return sorted(files)


def colorize_log_line(line):
    line_lower = line.upper()
    color = "#d4d4d4"
    if "ERROR" in line_lower:
        color = "#ff5555"
    elif "WARNING" in line_lower:
        color = "#ffb86c"
    elif "DEBUG" in line_lower:
        color = "#8be9fd"
    elif "INFO" in line_lower:
        color = "#50fa7b"

    line = re.sub(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', r'<span style="color: #bd93f9">\1</span>', line)
    line = re.sub(r'(\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}(?:\s?[AP]M)?)',
                  r'<span style="color: #bd93f9">\1</span>', line)
    line = re.sub(r'(\[User:\d+\])',
                  r'<span style="background: #44475a; padding: 2px 4px; border-radius: 3px; color: #f8f8f2;">\1</span>',
                  line)
    return f'<span style="color: {color}">{line}</span>'


@login_required
def log_viewer_view(request):
    instance = request.session.get('chosen_instance', 'develop')
    log_base_path = f"/opt/heappe-deployment/{instance}/app/logs/API/"

    selected_date = request.GET.get('date', datetime.now().strftime('%Y-%m-%d'))
    search_query = request.GET.get('search', '').lower()

    log_files = get_log_files(log_base_path, selected_date)
    all_logs_content = []

    for file_name in log_files:
        file_path = os.path.join(log_base_path, file_name)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if not search_query or search_query in line.lower():
                        all_logs_content.append({
                            'file': file_name,
                            'content': colorize_log_line(line.strip())
                        })
        except Exception as e:
            all_logs_content.append({'file': file_name, 'content': str(e)})

    return render(request, 'file_log_viewer.html', {
        'logs': all_logs_content,
        'selected_date': selected_date,
        'search_query': search_query,
        'available_files': log_files,
        'instance': instance
    })