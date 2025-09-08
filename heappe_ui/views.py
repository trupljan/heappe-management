from heappe_ui.view.imports import *
from heappe_ui.view.index import index
from heappe_ui.view.utils import *
from heappe_ui.view.clusters import *
from heappe_ui.view.queue import *
from heappe_ui.view.file_transfer_method import *
from heappe_ui.view.project import *
from heappe_ui.view.command_template import *






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
                ['python', 'manage.py', 'migrate'],  # Runs database migrations
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
