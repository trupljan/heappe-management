from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required


KEY_TYPE_CHOICES = {
    1: "None",
    2: "RSA3072",
    3: "RSA4096",
    4: "nistP256",
    5: "nistP521",
    6: "Ed25519",
}

@login_required
def project_detail(request: HttpRequest, project_id: int, _tab: str=None) -> HttpResponse:
    filter_type = request.GET.get("project_filter", "own")
    controller = hp.ManagementApi(request.api_instance)
    if _tab is not None:
        tab = _tab
    else:
        tab = request.GET.get("tab", "detail")

    clusters = [c.to_dict() for c in controller.heappe_management_clusters_get(SessionCode=request.session_code)]
    not_assigned_clusters = clusters.copy()
    command_templates, project_accounts, project_data, project_assignments = [], [], None, []

    #if post
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_project":
            return project_update(request, project_id)
        if action == "project_assign_to_cluster":
            return project_assign_to_cluster_with_project_id(request, project_id)
        if action == "delete_assignment":
            return delete_assignment(request, project_id)
        if action == "test_hpc_access":
            return test_cluster_authentication_credential_HPC_access(request)
        if action == "initialize_hpc_account":
            return initialize_hpc_account(request)
        if action == "create_new_hpc_account":
            return create_new_hpc_account(request)
        if action == "regenerate_ssh_key":
            return regenerate_ssh_key(request)
        if action == "delete_hpc_account":
            return delete_hpc_account(request)


    if project_id:
        project_data = controller.heappe_management_project_get(
            Id=project_id, SessionCode=request.session_code
        ).to_dict()
        command_templates = [ct.to_dict() for ct in controller.heappe_management_command_templates_get(
            ProjectId=project_id, SessionCode=request.session_code
        )]

        dict_ntypes = {}
        for ct in command_templates:
            node_type_id = ct.get('cluster_node_type_id')
            if node_type_id and node_type_id not in dict_ntypes:
                dict_ntypes[node_type_id] = controller.heappe_management_cluster_node_type_get(
                    Id=node_type_id, SessionCode=request.session_code
                ).to_dict()


        project_accounts = [pa.to_dict() for pa in controller.heappe_management_secure_shell_keys_get(
            ProjectId=project_id, SessionCode=request.session_code
        )]

        for pa in project_accounts:
            pa['key_type_name'] = KEY_TYPE_CHOICES.get(pa.get('key_type'), 'Unknown')
            try:
                #result = test_cluster_authentication_credential_HPC_access_manual(request, project_id, pa['username'])
                #if result is None:
                #    pa['has_access']  = False
                #else:
                #    pa['has_access'] = True

                controller = hp.ManagementApi(request.api_instance)
                result = _handle_api_call(
                    request,
                    lambda: controller.heappe_management_cluster_account_status_get(ProjectId=project_id,
                                                                                             Username=pa['username'],
                                                                                             SessionCode=request.session_code),
                    "Cluster account is initialized",
                    "Cluster account is not initialized",
                    silent=True
                )
                init_fail = 0
                init_ok = 0
                for status in result:
                    if status.is_initialized:
                        init_ok = init_ok + 1
                    else:
                        init_fail = init_fail + 1

                if init_fail == 0 and init_ok > 0:
                    pa['is_initialized'] = True
                else:
                    pa['is_initialized'] = False

            except Exception as e:
                print(e)





        response = controller.heappe_management_project_assignment_to_clusters_get(
            ProjectId=project_id, SessionCode=request.session_code
        )
        project_assignments = [pa.to_dict() for pa in response]
        # add cluster details fror project assignments
        for assignment in project_assignments:
            for cluster in clusters:
                if cluster['id'] == assignment['cluster_id']:
                    assignment['cluster_name'] = cluster['name']
                    not_assigned_clusters.remove(cluster)
                    break

    if filter_type == "shared":
        command_templates = [ct for ct in command_templates if ct['project_id'] == 0]
    elif filter_type == "all":
        # žádná změna, necháme všechny v listu
        pass
    else:
        # "own" nebo default - vyfiltrovat, kde project_id není 0
        command_templates = [ct for ct in command_templates if ct['project_id'] != 0]

    return render(request, "project.html", {
        "project": project_data,
        "clusters": clusters,
        "not_assigned_clusters": not_assigned_clusters,
        "project_assignments": project_assignments,
        "active_tab": tab,
        "command_templates": command_templates,
        "project_accounts": project_accounts,
        "node_types": list(dict_ntypes.values()),
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
            result = _handle_api_call(
                request,
                lambda: controller.heappe_job_management_create_job_post(**payload),
                "Job created successfully!",
                "Job failed to create"
            )
            if result:
                payload_data = {
                      "CreatedJobInfoId": result['Id']
                    }
                payload = _create_payload(request.session_code, payload_data)
                result = _handle_api_call(
                    request,
                    lambda: controller.heappe_job_management_submit_job_put(**payload),
                    "Job submitted successfully!",
                    "Job failed to submit"
                )
                if result:
                    return redirect("job_status_view", job_id=result['Id'])

    context = {
        "project": project,
        "cluster": cluster,
        "node_type": node_type,
        "command_template": command_template,
    }
    return render(request, "submit_test_job.html", context)


@login_required
def job_status_view(request: HttpRequest, job_id:int) -> HttpResponse:
    controller = hp.JobManagementApi(request.api_instance)

    result = _handle_api_call(
        request,
        lambda: controller.heappe_job_management_current_info_for_job_get(SubmittedJobInfoId=job_id, SessionCode=request.session_code),
        "OK",
        "FAIL"
    )

    context = {
        "job": result
    }
    return render(request, "job_status.html", context)



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
        "LocalBasepath": request.POST.get("LocalBasepath", ""),
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
        "LocalBasepath": request.POST.get("LocalBasepath", ""),
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

@login_required
def test_cluster_authentication_credential_HPC_access(request: HttpRequest):
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    username = request.POST.get("username")

    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_test_cluster_access_for_account_get(ProjectId=project_id, Username=request.POST.get("username"), SessionCode=request.session_code),
        "Cluster authentication credential has access to HPC.",
        "Cluster authentication credential does not have access to HPC."
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
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
        "ProjectId": project_id,
        "Username": request.POST.get("username"),
        "Password": request.POST.get("password")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_secure_shell_key_post(**payload),
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