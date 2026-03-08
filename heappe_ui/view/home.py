from heappe_ui.view.imports import *
from heappe_ui.view.utils import *
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from heappe_ui.models import InstanceCredentials

@login_required
def index(request: HttpRequest) -> HttpResponse:
    return dashboard_view(request)

@login_required
def home(request: HttpRequest) -> HttpResponse:
    return dashboard_view(request)

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
        #distinct all jobs by ID
        all_jobs = list({job.id: job for job in all_jobs}.values())

        # Paginator
        paginator = Paginator(all_jobs, 10)  # 10 jobs per page
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        context["job_details"] = page_obj.object_list
        context["page_obj"] = page_obj
    except Exception as e:
        print(f"Error fetching job details: {e}")

    return render(request, "dashboard.html", context)

