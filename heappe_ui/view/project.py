from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required
from datetime import datetime
import base64


KEY_TYPE_CHOICES = {
    1: "None",
    2: "RSA3072",
    3: "RSA4096",
    4: "nistP256",
    5: "nistP521",
    6: "Ed25519",
}



def _ensure_datetimes(obj):
    """
    Recursively check for timestamp strings and convert them to datetime objects
    if the SDK failed to do so (e.g. if python-dateutil is missing).
    """
    if not obj:
        return obj
    
    # Common HEAppE date fields
    fields = ['creation_time', 'submit_time', 'start_time', 'end_time']
    for field in fields:
        val = getattr(obj, field, None)
        if isinstance(val, str) and val.strip():
            try:
                # Python 3.11+ handles the 'Z' suffix correctly in fromisoformat.
                # If on older Python, we'd need to replace 'Z' with '+00:00'.
                # Given we're on 3.12, this should be fine.
                setattr(obj, field, datetime.fromisoformat(val.replace('Z', '+00:00')))
            except (ValueError, TypeError):
                pass
                
    # Recurse into tasks if they exist
    tasks = getattr(obj, 'tasks', None)
    if tasks and isinstance(tasks, list):
        for task in tasks:
            _ensure_datetimes(task)
            
    return obj


@login_required
def project_detail(request: HttpRequest, project_id: int, _tab: str = None) -> HttpResponse:
    filter_type = request.GET.get("project_filter", "own")
    controller = hp.ManagementApi(request.api_instance)
    session_code = request.session_code

    if _tab is not None:
        tab = _tab
    else:
        tab = request.GET.get("tab", "detail")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_project": return project_update(request, project_id)
        if action == "project_assign_to_cluster": return project_assign_to_cluster_with_project_id(request, project_id)
        if action == "delete_assignment": return delete_assignment(request, project_id)
        if action == "update_assignment": return update_assignment(request)
        if action == "test_hpc_access": return test_cluster_authentication_credential_HPC_access(request)
        if action == "initialize_hpc_account": return initialize_hpc_account(request)
        if action == "create_new_hpc_account": return create_new_hpc_account(request)
        if action == "regenerate_ssh_key": return regenerate_ssh_key(request)
        if action == "rename_hpc_account": return rename_hpc_account(request)
        if action == "delete_hpc_account": return delete_hpc_account(request)

    clusters_raw = controller.heappe_management_clusters_get(SessionCode=session_code)
    cluster_lookup = {c.id: c.name for c in clusters_raw}
    clusters = [c.to_dict() for c in clusters_raw]

    all_node_types_raw = controller.heappe_management_cluster_node_types_get(SessionCode=session_code)
    node_type_map = {nt.id: nt.to_dict() for nt in all_node_types_raw}

    for c_obj in clusters_raw:
        for nt in c_obj.node_types:
            if nt.id in node_type_map:
                node_type_map[nt.id]['cluster_name'] = c_obj.name

    project_data = controller.heappe_management_project_get(Id=project_id, SessionCode=session_code).to_dict()

    all_templates_raw = controller.heappe_management_command_templates_get(SessionCode=session_code,
                                                                           ProjectId=project_id)
    all_templates = [ct.to_dict() for ct in all_templates_raw]

    if filter_type == "shared":
        command_templates = [ct for ct in all_templates if ct['project_id'] == 0]
    elif filter_type == "own":
        command_templates = [ct for ct in all_templates if ct['project_id'] == project_id]
    else:
        command_templates = [ct for ct in all_templates if ct['project_id'] in (0, project_id)]

    dict_ntypes = {}
    for ct in command_templates:
        nt_id = ct.get('cluster_node_type_id')
        if nt_id and nt_id in node_type_map:
            dict_ntypes[nt_id] = node_type_map[nt_id]

    project_accounts = [pa.to_dict() for pa in controller.heappe_management_secure_shell_keys_get(
        ProjectId=project_id, SessionCode=session_code
    )]

    user_status_cache = {}
    for pa in project_accounts:
        pa['key_type_name'] = KEY_TYPE_CHOICES.get(pa.get('key_type'), 'Unknown')
        username = pa.get('username')
        if username not in user_status_cache:
            try:
                status_results = controller.heappe_management_cluster_account_status_get(
                    ProjectId=project_id, Username=username, SessionCode=session_code
                )
                init_ok = sum(1 for s in status_results if s.is_initialized)
                user_status_cache[username] = (len(status_results) > 0 and init_ok == len(status_results))
            except Exception:
                user_status_cache[username] = False
        pa['is_initialized'] = user_status_cache[username]

    adaptor_users, adaptor_users_not_in_project, ui_features = [], [], {}
    try:
        adaptor_users = [u.to_dict() for u in controller.heappe_management_adaptor_users_in_project_get(
            SessionCode=session_code, ProjectId=project_id
        )]
        all_adaptor_users = [u.to_dict() for u in
                             controller.heappe_management_adaptor_users_get(SessionCode=session_code)]
        existing_ids = {u['id'] for u in adaptor_users}
        adaptor_users_not_in_project = [u for u in all_adaptor_users if u['id'] not in existing_ids]
        ui_features.update({'adaptor_users': True, 'adaptor_users_not_in_project': True})
    except Exception:
        pass

    assignments_raw = controller.heappe_management_project_assignment_to_clusters_get(
        ProjectId=project_id, SessionCode=session_code
    )
    project_assignments = [a.to_dict() for a in assignments_raw]
    assigned_ids = {a['cluster_id'] for a in project_assignments}
    not_assigned_clusters = [c for c in clusters if c['id'] not in assigned_ids]

    for a in project_assignments:
        a['cluster_name'] = cluster_lookup.get(a['cluster_id'], "Unknown")

    return render(request, "project.html", {
        "project": project_data,
        "clusters": clusters,
        "not_assigned_clusters": not_assigned_clusters,
        "project_assignments": project_assignments,
        "active_tab": tab,
        "command_templates": command_templates,
        "project_accounts": project_accounts,
        "node_types": list(dict_ntypes.values()),
        "adaptor_users": adaptor_users,
        "adaptor_users_not_in_project": adaptor_users_not_in_project,
        "ui_features": ui_features,
    })



@login_required
def submit_job_view(request, command_template_id:int):
    controller = hp.ManagementApi(request.api_instance)

    all_clusters = [c.to_dict() for c in controller.heappe_management_clusters_get(SessionCode=request.session_code)]


    command_template = controller.heappe_management_command_template_get(
        Id=command_template_id, SessionCode=request.session_code
    ).to_dict()


    project = controller.heappe_management_project_get(
        Id=command_template['project_id'], SessionCode=request.session_code
    ).to_dict()

    node_type = controller.heappe_management_cluster_node_type_get(
        Id=command_template['cluster_node_type_id'], SessionCode=request.session_code
    ).to_dict()

    cluster = controller.heappe_management_cluster_get(
        Id=node_type['cluster_id'], SessionCode=request.session_code
    ).to_dict()

    if request.method == "POST":
        if request.POST.get("action") == "submit_job":
            # Job-level data
            job_name = request.POST.get("JobName")
            project_id = request.POST.get("ProjectId")
            cluster_id = request.POST.get("ClusterId")
            notify_email = request.POST.get("NotificationEmail")
            notify_start = request.POST.get("NotifyOnStart") == "true"
            notify_finish = request.POST.get("NotifyOnFinish") == "true"
            notify_abort = request.POST.get("NotifyOnAbort") == "true"

            # Task-level data
            task_name = request.POST.get("TaskName")
            min_cores = int(request.POST.get("MinCores") or 1)
            max_cores = int(request.POST.get("MaxCores") or 1)
            walltime = int(request.POST.get("WalltimeLimit") or 600)
            node_type_id = request.POST.get("ClusterNodeTypeId")
            command_template_id = request.POST.get("CommandTemplateId")
            is_exclusive = request.POST.get("IsExclusive") == "true"
            is_rerunnable = request.POST.get("IsRerunnable") == "true"

            # Extract TemplateParameters from POST data
            template_parameters = []
            for key, value in request.POST.items():
                if key.startswith("TemplateParameters["):
                    # Extract the identifier from the key (e.g., TemplateParameters[param1] -> param1)
                    identifier = key[len("TemplateParameters["):-1]
                    if value:  # Only include non-empty values
                        template_parameters.append({
                            "CommandParameterIdentifier": identifier,
                            "ParameterValue": value
                        })

            # Build JSON payload
            payload_data = {
                "JobSpecification": {
                    "Name": job_name,
                    "ProjectId": int(project_id),
                    "NotificationEmail": notify_email,
                    "NotifyOnStart": notify_start,
                    "NotifyOnFinish": notify_finish,
                    "NotifyOnAbort": notify_abort,
                    "ClusterId": int(cluster_id),
                    "FileTransferMethodId": node_type['file_transfer_method_id'],
                    "Tasks": [
                        {
                            "Name": task_name,
                            "MinCores": min_cores,
                            "MaxCores": max_cores,
                            "WalltimeLimit": walltime,
                            "StandardOutputFile": "stdout",
                            "StandardErrorFile": "stderr",
                            "ProgressFile": "stdprog",
                            "LogFile": "log.txt",
                            "ClusterNodeTypeId": int(node_type_id) if node_type_id else 0,
                            "CommandTemplateId": int(command_template_id) if command_template_id else 0,
                            "IsExclusive": is_exclusive,
                            "IsRerunnable": is_rerunnable,
                            "TemplateParameterValues": template_parameters
                        }
                    ],
                    "ProjectId": project['id']
                }
            }

            controller = hp.JobManagementApi(request.api_instance)
            payload = _create_payload(request.session_code, payload_data)
            payload["_preload_content"] = True
            
            result = _handle_api_call(
                request,
                lambda: controller.heappe_job_management_create_job_post(**payload),
                "Job created successfully!",
                "Job failed to create"
            )

            if result:
                # After creation, we must SUBMIT the job
                payload_data = {
                    "CreatedJobInfoId": result.id
                }
                payload = _create_payload(request.session_code, payload_data)
                payload["_preload_content"] = True
                
                result = _handle_api_call(
                    request,
                    lambda: controller.heappe_job_management_submit_job_put(**payload),
                    "Job submitted successfully!",
                    "Job failed to submit"
                )
                
                if result:
                    return redirect("job_status_view", job_id=result.id)

    context = {
        "project": project,
        "cluster": cluster,
        "node_type": node_type,
        "command_template": command_template,
    }
    return render(request, "submit_test_job.html", context)


@login_required
def job_status_view(request: HttpRequest, job_id: int) -> HttpResponse:
    controller = hp.JobManagementApi(request.api_instance)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "cancel_job":
            payload_data = {"SubmittedJobInfoId": job_id}
            payload = _create_payload(request.session_code, payload_data)
            _handle_api_call(
                request,
                lambda: controller.heappe_job_management_cancel_job_put(**payload),
                "Job canceled successfully!",
                "Failed to cancel job"
            )
            return redirect("job_status_view", job_id=job_id)
        elif action == "delete_job":
            payload_data = {"SubmittedJobInfoId": job_id}
            payload = _create_payload(request.session_code, payload_data)
            _handle_api_call(
                request,
                lambda: controller.heappe_job_management_delete_job_delete(**payload),
                "Job deleted successfully!",
                "Failed to delete job"
            )
            return redirect("dashboard_view")

    try:
        result = _handle_api_call(
            request,
            lambda: controller.heappe_job_management_current_info_for_job_get(SubmittedJobInfoId=job_id, SessionCode=request.session_code, _preload_content=True),
            "OK",
            "FAIL",
            silent=True
        )

        if not result:
            messages.error(request, f"Job with ID {job_id} not found or access denied.")
            return redirect("dashboard_view")

        # Fetch changed files
        changed_files = []
        try:
            ft_controller = hp.FileTransferApi(request.api_instance)
            changed_files = ft_controller.heappe_file_transfer_list_changed_files_for_job_get(
                SessionCode=request.session_code,
                SubmittedJobInfoId=job_id,
                _preload_content=True
            )
        except Exception as e:
            print(f"DEBUG: File listing failed: {str(e)}")

        project = None
        project_id = getattr(result, 'project_id', None)
        
        # If not at top level, try to find it in tasks
        if project_id is None and hasattr(result, 'tasks') and result.tasks:
            for t in result.tasks:
                nt = getattr(t, 'node_type', None)
                if nt:
                    p = getattr(nt, 'project', None)
                    if p:
                        project_id = getattr(p, 'id', None)
                        if project_id is not None:
                            break
        
        if project_id is not None:
            try:
                mgmt_controller = hp.ManagementApi(request.api_instance)
                project = mgmt_controller.heappe_management_project_get(Id=project_id, SessionCode=request.session_code, _preload_content=True)
            except Exception as e:
                print(f"DEBUG: Project fetch failed: {str(e)}")

        context = {
            "job": _ensure_datetimes(result),
            "project": project,
            "changed_files": changed_files
        }
        return render(request, "job_status.html", context)
    except Exception as e:
        messages.error(request, f"Error fetching job info: {str(e)}")
        return redirect("dashboard_view")

from django.http import JsonResponse

@login_required
def job_task_file_view(request: HttpRequest, job_id: int, task_id: int, file_name: str) -> JsonResponse:
    try:
        controller = hp.FileTransferApi(request.api_instance)
        
        # We now use the relative file path provided in the request
        # In the UI, we should pass the full relative path if possible.
        # For now, let's assume file_name is the relative path.
        
        body = hp.DownloadFileFromClusterModel(
            session_code=request.session_code,
            submitted_job_info_id=job_id,
            relative_file_path=file_name
        )
        
        # Overriding _preload_content=True to get the base64 string directly if parsed
        # or checking the raw response.
        
        result_b64 = _handle_api_call(
            request,
            lambda: controller.heappe_file_transfer_download_file_from_cluster_post(body=body, _preload_content=True),
            "File downloaded",
            "Failed to download file",
            silent=True
        )
        
        if result_b64:
            try:
                # result_b64 might be already the string or the model object (though response_type='str')
                content = base64.b64decode(result_b64).decode('utf-8', errors='replace')
                return JsonResponse({"status": "OK", "content": content})
            except Exception as e:
                return JsonResponse({"status": "ERROR", "message": f"Decode error: {str(e)}"})
        
        return JsonResponse({"status": "ERROR", "message": "No content returned"})
    except Exception as e:
        return JsonResponse({"status": "ERROR", "message": str(e)})




@login_required
def project_create(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return render(request, "project.html", {
        "active_tab": "detail",
        })
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        payload_data = {
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "AccountingString": request.POST.get("AccountingString"),
            "StartDate": request.POST.get("StartDate"),
            "EndDate": request.POST.get("EndDate"),
            "UsageType": int(request.POST.get("UsageType")),
            "UseAccountingStringForScheduler": request.POST.get("UseAccountingStringForScheduler") == "on",
            "IsOneToOneMapping": request.POST.get("IsOneToOneMapping") == "on",
            "PIEmail": request.POST.get("PIEmail"),
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_project_post(**payload),
            "Project created successfully!",
            "Failed to create Project"
        )
        if result:
            return redirect("project_detail", project_id=result['Id'])


@login_required
def project_list(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    projects = [p.to_dict() for p in controller.heappe_management_projects_get(SessionCode=request.session_code)]

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete_project":
            project_id = int(request.POST.get("ProjectId"))
            payload_data = {
                "Id": project_id,
            }
            payload = _create_payload(request.session_code, payload_data)
            _handle_api_call(
                request,
                lambda: controller.heappe_management_project_delete(**payload),
                "Project deleted successfully!",
                "Failed to delete Project"
            )
            return redirect("project_list")

    return render(request, "projects.html", {
        "projects": projects
    })


def project_update(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    payload_data = {
        "Id": project_id,
        "Name": request.POST.get("Name"),
        "Description": request.POST.get("Description"),
        "StartDate": request.POST.get("StartDate"),
        "EndDate": request.POST.get("EndDate"),
        "UsageType": int(request.POST.get("UsageType")),
        "UseAccountingStringForScheduler": request.POST.get("UseAccountingStringForScheduler") == "on",
        "IsOneToOneMapping": request.POST.get("IsOneToOneMapping") == "on",
    }
    payload = _create_payload(request.session_code, payload_data)
    _handle_api_call(
        request,
        lambda: controller.heappe_management_project_put(**payload),
        "Project updated successfully!",
        "Failed to update Project"
    )
    return redirect("project_detail", project_id=project_id)

from django.urls import reverse

@login_required
def project_assign_to_cluster(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    cluster_id = int(request.POST.get("ClusterId"))
    payload_data = {
        "ProjectId": project_id,
        "ClusterId": cluster_id,
        "ScratchStoragePath": request.POST.get("ScratchStoragePath", ""),
        "PermanentStoragePath": request.POST.get("PermanentStoragePath", ""),
        "ProjectStoragePath": request.POST.get("ProjectStoragePath", "")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_assignment_to_cluster_post(**payload),
        "Project assigned to cluster successfully!",
        "Failed to assign project to cluster"
    )
    # Redirect to cluster_detail with cluster_id and tab as a query parameter
    return redirect(f"{reverse('cluster_detail', kwargs={'cluster_id': cluster_id})}?tab=projects")

def project_assign_to_cluster_with_project_id(request: HttpRequest, project_id) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    cluster_id = int(request.POST.get("ClusterId"))
    payload_data = {
        "ProjectId": project_id,
        "ClusterId": cluster_id,
        "ScratchStoragePath": request.POST.get("ScratchStoragePath", ""),
        "PermanentStoragePath": request.POST.get("PermanentStoragePath", ""),
        "ProjectStoragePath": request.POST.get("ProjectStoragePath", "")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_assignment_to_cluster_post(**payload),
        "Project assigned to cluster successfully!",
        "Failed to assign project to cluster"
    )
    # Redirect to cluster_detail with cluster_id and tab as a query parameter
    return redirect("project_detail", project_id=project_id)

def update_assignment(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    cluster_id = int(request.POST.get("ClusterId"))
    payload_data = {
        "ProjectId": project_id,
        "ClusterId": cluster_id,
        "ScratchStoragePath": request.POST.get("ScratchStoragePath", ""),
        "PermanentStoragePath": request.POST.get("PermanentStoragePath", ""),
        "ProjectStoragePath": request.POST.get("ProjectStoragePath", "")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_assignment_to_cluster_put(**payload),
        "Assignment updated successfully!",
        "Failed to update assignment"
    )
    # Redirect to cluster_detail with cluster_id and tab as a query parameter
    return redirect("project_detail", project_id=project_id)

@login_required
def delete_assignment(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    cluster_id = int(request.POST.get("ClusterId"))
    payload_data = {
        "ProjectId": project_id,
        "ClusterId": cluster_id,
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_assignment_to_cluster_delete(**payload),
        "Cluster assignment removed successfully!",
        "Failed to remove cluster assignment"
    )

    redirectTo = request.POST.get("redirectTo")
    if redirectTo == "project_detail":
        return redirect(f"{reverse('project_detail', kwargs={'project_id': project_id})}")
    else:
        return redirect(f"{reverse('cluster_detail', kwargs={'cluster_id': cluster_id})}?tab=projects")

def test_cluster_authentication_credential_HPC_access_manual(request: HttpRequest, project_id: int, username: str):
    controller = hp.ManagementApi(request.api_instance)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_test_cluster_access_for_account_get(ProjectId=project_id,
                                                                                 Username=username,
                                                                                 SessionCode=request.session_code),
        "Cluster authentication credential has access to HPC.",
        "Cluster authentication credential does not have access to HPC.",
        silent=True
    )
    return result

from django.contrib import messages


@login_required
def test_cluster_authentication_credential_HPC_access(request: HttpRequest):
    project_id = request.POST.get("ProjectId")
    username = request.POST.get("username")

    print(f"DEBUG: View start. ProjectId: {project_id}, Username: {username}")

    try:
        controller = hp.ManagementApi(request.api_instance)

        # Call the helper
        response_data = _handle_api_call(
            request,
            lambda: controller.heappe_management_test_cluster_access_for_account_get(
                ProjectId=int(project_id) if project_id else 0,
                Username=username,
                SessionCode=request.session_code
            ),
            success_message="",
            error_message="Access test failed",
            silent=True
        )

        print(f"DEBUG: response_data received: {response_data}")

        if isinstance(response_data, list):
            for cluster in response_data:
                print(f"DEBUG: Processing cluster item: {cluster}")

                # Check if it's a dict or an object with attributes
                if isinstance(cluster, dict):
                    name = cluster.get('cluster_name', 'Unknown')
                    is_accessible = cluster.get('is_cluster_accessible', False)
                else:
                    # Fallback if the SDK returns objects instead of dicts
                    name = getattr(cluster, 'cluster_name', 'Unknown')
                    is_accessible = getattr(cluster, 'is_cluster_accessible', False)

                if is_accessible:
                    messages.success(request, f"Cluster {name}: Access verified.")
                else:
                    messages.error(request, f"Cluster {name}: Access denied.")
        else:
            print(f"DEBUG: response_data was not a list, it was: {type(response_data)}")

    except Exception as e:
        print(f"DEBUG: CRITICAL EXCEPTION in view: {str(e)}")
        messages.error(request, f"Internal error: {str(e)}")

    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    print(f"DEBUG: Redirecting to {reload_url}")
    return redirect(reload_url)

@login_required
def initialize_hpc_account(request: HttpRequest):
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    username = request.POST.get("Username")
    payload_data = {
        "ProjectId": project_id,
        "OverwriteExistingProjectRootDirectory": True,
        "Username": username
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_initialize_cluster_script_directory_post(**payload),
        "Cluster authentication credential has been initialized.",
        "Cluster authentication credential initialization failed."
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)


def create_new_hpc_account(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))

    payload_data = {
        "Credentials" : [
            {
                "Username": request.POST.get("username"),
                "Password": request.POST.get("password")
            }],
        "ProjectId": project_id,
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_generate_secure_shell_key_post(**payload),
        "HPC account created successfully!",
        "Failed to create HPC account"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)

@login_required
def regenerate_ssh_key(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    username = request.POST.get("username")
    password = request.POST.get("password")
    payload_data = {
        "ProjectId": project_id,
        "Username": username,
        "Password": password
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_regenerate_secure_shell_key_put(**payload),
        "SSH key regenerated successfully!",
        "Failed to regenerate SSH key"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)

def rename_hpc_account(request):
    project_id = int(request.POST.get("ProjectId"))
    redirect_result = ensure_heappe_version(
        request,
        min_version="6.1.0",
        error_message="Renaming HPC accounts is not supported in this HEAppE version. Please upgrade to HEAppE 6.1.0 or later to use this feature.",
        fallback_url=f"/projects/{project_id}/?tab=accounts",
    )

    if redirect_result:
        return redirect_result
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    old_username = request.POST.get("oldUsername")
    new_username = request.POST.get("NewUsername")
    new_password = request.POST.get("NewPassword")
    payload_data = {
        "ProjectId": project_id,
        "OldUsername": old_username,
        "NewUsername": new_username,
        "NewPassword": new_password
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_modify_cluster_authentication_credential_put(**payload),
        "HPC account renamed successfully!",
        "Failed to rename HPC account"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)

@login_required
def delete_hpc_account(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    username = request.POST.get("username")
    payload_data = {
        "ProjectId": project_id,
        "Username": username
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_remove_secure_shell_key_delete(**payload),
        "HPC account deleted successfully!",
        "Failed to delete HPC account"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)
from heappe_ui.view.imports import *
from heappe_ui.view.utils import *
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from heappe_ui.view.adaptor_user import ADAPTOR_USER_STR_TO_INT
# fallback imports if not there

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
