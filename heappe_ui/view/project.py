from concurrent.futures import ThreadPoolExecutor
import time
from django.http import JsonResponse
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
def project_detail(request: HttpRequest, project_id: int, _tab: str = None) -> HttpResponse:
    filter_type = request.GET.get("project_filter", "own")
    controller = hp.ManagementApi(request.api_instance)
    session_code = request.session_code

    if request.GET.get("action") == "check_hpc_status":
        username = request.GET.get("username")
        try:
            status_results = controller.heappe_management_cluster_account_status_get(
                ProjectId=project_id, Username=username, SessionCode=session_code
            )
            init_ok = sum(1 for s in status_results if s.is_initialized)
            is_initialized = (len(status_results) > 0 and init_ok == len(status_results))
            return JsonResponse({"username": username, "is_initialized": is_initialized})
        except Exception as ex:
            return JsonResponse({"username": username, "is_initialized": False, "error": str(ex)}, status=500)

    if _tab is not None:
        tab = _tab
    else:
        tab = request.GET.get("tab", "detail")

    # Check if a forced cache refresh is requested
    force_refresh = request.GET.get("refresh") == "1"

    # Check global metadata modification file to invalidate cache across different users' sessions
    import os
    from django.conf import settings
    timestamp_file = os.path.join(settings.BASE_DIR, "metadata_last_modified.txt")
    last_global_mod = 0.0
    if os.path.exists(timestamp_file):
        try:
            with open(timestamp_file, "r") as f:
                last_global_mod = float(f.read().strip())
        except Exception:
            pass

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

    # Initialize context variables with defaults
    clusters = []
    not_assigned_clusters = []
    project_assignments = []
    command_templates = []
    project_accounts = []
    node_types = []
    adaptor_users = []
    adaptor_users_not_in_project = []
    ui_features = {}

    # Always fetch core project details
    project_data = controller.heappe_management_project_get(Id=project_id, SessionCode=session_code).to_dict()
    # Retrieve raw project data to extract PIEmail, which is discarded by the Swagger model
    try:
        raw_resp = controller.heappe_management_project_get(
            Id=project_id, SessionCode=session_code, _preload_content=False
        )
        import json
        raw_data = json.loads(raw_resp.data.decode('utf-8'))
        project_data['pi_email'] = raw_data.get('PIEmail') or raw_data.get('pi_email')
        project_data['PIEmail'] = project_data['pi_email']
    except Exception as e:
        print(f"Error fetching raw project details for PIEmail: {e}")

    # Cache feature support for adaptor users in the session to avoid redundant API calls
    has_adaptor_users_key = f"has_adaptor_users_{project_id}"
    has_adaptor_users = None if force_refresh else request.session.get(has_adaptor_users_key)
    if has_adaptor_users is None:
        try:
            controller.heappe_management_adaptor_users_in_project_get(
                SessionCode=session_code, ProjectId=project_id
            )
            has_adaptor_users = True
        except Exception:
            has_adaptor_users = False
        request.session[has_adaptor_users_key] = has_adaptor_users

    if has_adaptor_users:
        ui_features.update({'adaptor_users': True, 'adaptor_users_not_in_project': True})

    # Caching helper for clusters metadata with 5-minute (300 seconds) expiration TTL
    def get_cached_clusters():
        clusters_cache = request.session.get("clusters_cache")
        clusters_time = request.session.get("clusters_cache_time", 0)
        if force_refresh or not clusters_cache or (time.time() - clusters_time > 300) or (clusters_time < last_global_mod):
            clusters_raw = controller.heappe_management_clusters_get(SessionCode=session_code)
            clusters_cache = [c.to_dict() for c in clusters_raw]
            request.session["clusters_cache"] = clusters_cache
            request.session["clusters_cache_time"] = time.time()
        return clusters_cache

    if tab == "detail":
        clusters = get_cached_clusters()
        cluster_lookup = {c['id']: c['name'] for c in clusters}

        assignments_raw = controller.heappe_management_project_assignment_to_clusters_get(
            ProjectId=project_id, SessionCode=session_code
        )
        project_assignments = [a.to_dict() for a in assignments_raw]
        assigned_ids = {a['cluster_id'] for a in project_assignments}
        not_assigned_clusters = [c for c in clusters if c['id'] not in assigned_ids]

        for a in project_assignments:
            a['cluster_name'] = cluster_lookup.get(a['cluster_id'], "Unknown")

    elif tab == "commandtemplates":
        cache_key = f"command_templates_cache_{project_id}"
        cache_time_key = f"command_templates_cache_{project_id}_time"

        all_templates = request.session.get(cache_key)
        all_templates_time = request.session.get(cache_time_key, 0)

        is_from_cache = False
        if not force_refresh and all_templates and (time.time() - all_templates_time <= 300) and (all_templates_time >= last_global_mod):
            is_from_cache = True
        else:
            try:
                all_templates_raw = controller.heappe_management_command_templates_get(
                    SessionCode=session_code, ProjectId=project_id
                )
                all_templates = [ct.to_dict() for ct in all_templates_raw]
                request.session[cache_key] = all_templates
                request.session[cache_time_key] = time.time()
                all_templates_time = request.session[cache_time_key]
            except Exception as e:
                print(f"Error fetching command templates: {e}")
                all_templates = all_templates or []

        if is_from_cache:
            age = int(time.time() - all_templates_time)
            if age < 60:
                templates_cache_age_str = f"{age}s"
            else:
                templates_cache_age_str = f"{age // 60}m {age % 60}s"
        else:
            templates_cache_age_str = None

        if filter_type == "shared":
            command_templates = [ct for ct in all_templates if ct['project_id'] == 0]
        elif filter_type == "own":
            command_templates = [ct for ct in all_templates if ct['project_id'] == project_id]
        else:
            command_templates = [ct for ct in all_templates if ct['project_id'] in (0, project_id)]

        # Fetch/Cache node types and clusters to map cluster names to queues with 5-minute (300s) TTL
        node_types_cache = request.session.get("node_types_cache")
        node_types_time = request.session.get("node_types_cache_time", 0)
        if force_refresh or not node_types_cache or (time.time() - node_types_time > 300) or (node_types_time < last_global_mod):
            all_node_types_raw = controller.heappe_management_cluster_node_types_get(SessionCode=session_code)
            node_types_cache = [nt.to_dict() for nt in all_node_types_raw]
            request.session["node_types_cache"] = node_types_cache
            request.session["node_types_cache_time"] = time.time()

        node_type_map = {nt['id']: nt for nt in node_types_cache}

        clusters_cache = get_cached_clusters()
        for c_obj in clusters_cache:
            for nt in c_obj.get('node_types', []):
                if nt['id'] in node_type_map:
                    node_type_map[nt['id']]['cluster_name'] = c_obj['name']

        dict_ntypes = {}
        for ct in command_templates:
            nt_id = ct.get('cluster_node_type_id')
            if nt_id and nt_id in node_type_map:
                dict_ntypes[nt_id] = node_type_map[nt_id]
        node_types = list(dict_ntypes.values())

    elif tab == "accounts":
        project_accounts = [pa.to_dict() for pa in controller.heappe_management_secure_shell_keys_get(
            ProjectId=project_id, SessionCode=session_code
        )]
        for pa in project_accounts:
            pa['key_type_name'] = KEY_TYPE_CHOICES.get(pa.get('key_type'), 'Unknown')

    elif tab == "adaptor_users" and has_adaptor_users:
        try:
            adaptor_users = [u.to_dict() for u in controller.heappe_management_adaptor_users_in_project_get(
                SessionCode=session_code, ProjectId=project_id
            )]
            
            # Cache all adaptor users
            all_adaptor_users_cache = request.session.get("all_adaptor_users_cache")
            all_adaptor_users_time = request.session.get("all_adaptor_users_cache_time", 0)
            if force_refresh or not all_adaptor_users_cache or (time.time() - all_adaptor_users_time > 300) or (all_adaptor_users_time < last_global_mod):
                all_adaptor_users_raw = controller.heappe_management_adaptor_users_get(SessionCode=session_code)
                all_adaptor_users_cache = [u.to_dict() for u in all_adaptor_users_raw]
                request.session["all_adaptor_users_cache"] = all_adaptor_users_cache
                request.session["all_adaptor_users_cache_time"] = time.time()
            all_adaptor_users = all_adaptor_users_cache

            existing_ids = {u['id'] for u in adaptor_users}
            adaptor_users_not_in_project = [u for u in all_adaptor_users if u['id'] not in existing_ids]
        except Exception:
            pass

    # Calculate project-specific setup checklist
    setup_checklist = {
        "clusters_exist": False,
        "project_cluster_linked": False,
        "queue_groups_exist": False,
        "project_group_linked": False,
        "formulas_exist_and_mapped": False,
        "queues_exist": False,
        "command_template_exists": False,
        "ssh_account_active": False,
    }

    try:
        # 1. Clusters check
        all_clusters = get_cached_clusters() or []
        setup_checklist["clusters_exist"] = len(all_clusters) > 0
        
        # 2. Project Cluster link and Queues check
        project_assignments_all = controller.heappe_management_project_assignment_to_clusters_get(
            ProjectId=project_id, SessionCode=session_code
        ) or []
        setup_checklist["project_cluster_linked"] = len(project_assignments_all) > 0
        
        # Check if the clusters that the project is assigned to have any queues
        assigned_cluster_ids = {a.cluster_id for a in project_assignments_all}
        queues_count = 0
        for cluster in all_clusters:
            if cluster.get("id") in assigned_cluster_ids:
                queues_count += len(cluster.get("node_types", []))
        setup_checklist["queues_exist"] = queues_count > 0

        # 3. Queue Groups and Project Group assignment check
        all_groups = controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=session_code) or []
        setup_checklist["queue_groups_exist"] = len(all_groups) > 0

        project_aggregations = controller.heappe_management_project_cluster_node_type_aggregations_get(
            SessionCode=session_code
        ) or []
        
        assigned_group_ids = {g.cluster_node_type_aggregation_id for g in project_aggregations if g.project_id == project_id}
        setup_checklist["project_group_linked"] = len(assigned_group_ids) > 0

        # 4. Accounting Formula check
        if assigned_group_ids:
            group_formula_mappings = controller.heappe_management_cluster_node_type_aggregation_accountings_get(
                SessionCode=session_code
            ) or []
            for mapping in group_formula_mappings:
                if mapping.cluster_node_type_aggregation_id in assigned_group_ids:
                    setup_checklist["formulas_exist_and_mapped"] = True
                    break

        # 5. Command Template check
        project_templates = controller.heappe_management_command_templates_get(
            SessionCode=session_code, ProjectId=project_id
        ) or []
        # Filter for own templates (not shared templates)
        own_templates = [t for t in project_templates if t.project_id == project_id]
        setup_checklist["command_template_exists"] = len(own_templates) > 0

        # 6. SSH Account active check
        ssh_keys = controller.heappe_management_secure_shell_keys_get(
            ProjectId=project_id, SessionCode=session_code
        ) or []
        for key in ssh_keys:
            try:
                status_results = controller.heappe_management_cluster_account_status_get(
                    ProjectId=project_id, Username=key.username, SessionCode=session_code
                ) or []
                init_ok = sum(1 for s in status_results if s.is_initialized)
                if len(status_results) > 0 and init_ok == len(status_results):
                    setup_checklist["ssh_account_active"] = True
                    break
            except Exception:
                pass
    except Exception as ex:
        print(f"Error computing project checklist: {ex}")

    return render(request, "project.html", {
        "project": project_data,
        "clusters": clusters,
        "not_assigned_clusters": not_assigned_clusters,
        "project_assignments": project_assignments,
        "active_tab": tab,
        "command_templates": command_templates,
        "project_accounts": project_accounts,
        "node_types": node_types,
        "adaptor_users": adaptor_users,
        "adaptor_users_not_in_project": adaptor_users_not_in_project,
        "ui_features": ui_features,
        "templates_cache_age_str": templates_cache_age_str if tab == "commandtemplates" else None,
        "setup_checklist": setup_checklist,
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
            # Safely extract the integer project ID from the API response.
            # The response dict may use 'Id' or 'id' depending on content parsing,
            # and the value may be an empty string if the API returned an unexpected format.
            project_id = result.get('Id') or result.get('id')
            try:
                project_id = int(project_id)
            except (TypeError, ValueError):
                project_id = None
            if project_id:
                return redirect("project_detail", project_id=project_id)
        return redirect("project_list")


@login_required
def project_list(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    
    # Retrieve raw projects list to extract PIEmail, which is discarded by the Swagger model
    try:
        raw_resp = controller.heappe_management_projects_get(
            SessionCode=request.session_code, _preload_content=False
        )
        import json
        raw_projects = json.loads(raw_resp.data.decode('utf-8'))
        raw_by_id = {p.get('Id'): p for p in raw_projects}
    except Exception as e:
        print(f"Error fetching raw projects: {e}")
        raw_by_id = {}

    projects = []
    for p in controller.heappe_management_projects_get(SessionCode=request.session_code):
        p_dict = p.to_dict()
        raw_proj = raw_by_id.get(p_dict.get('id'), {})
        p_dict['pi_email'] = raw_proj.get('PIEmail') or raw_proj.get('pi_email')
        p_dict['PIEmail'] = p_dict['pi_email']
        projects.append(p_dict)

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
        elif action == "bulk_delete":
            selected_ids = request.POST.getlist("selected_ids")
            success_count = 0
            for pid in selected_ids:
                try:
                    payload = _create_payload(request.session_code, {"Id": int(pid)})
                    controller.heappe_management_project_delete(**payload)
                    success_count += 1
                except Exception as e:
                    print(f"Error deleting project {pid}: {e}")
            if success_count > 0:
                messages.success(request, f"Successfully deleted {success_count} project(s).")
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to delete {len(selected_ids) - success_count} project(s).")
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
    import json as _json
    project_id = request.POST.get("ProjectId")
    username = request.POST.get("username")

    def _parse_clusters(data):
        """Turn a list of cluster dicts/objects into (name, is_accessible) pairs."""
        results = []
        for item in data:
            if isinstance(item, dict):
                # API returns PascalCase keys in raw JSON
                name = item.get('ClusterName') or item.get('cluster_name') or 'Unknown'
                accessible = item.get('IsClusterAccessible') if 'IsClusterAccessible' in item else item.get('is_cluster_accessible', False)
            else:
                name = getattr(item, 'cluster_name', 'Unknown')
                accessible = getattr(item, 'is_cluster_accessible', False)
            results.append((name, bool(accessible)))
        return results

    try:
        controller = hp.ManagementApi(request.api_instance)
        try:
            # Use _preload_content=False so we get the raw response and can
            # parse the body ourselves — HEAppE sometimes returns 400 even
            # when the body contains a valid cluster-access result.
            raw = controller.heappe_management_test_cluster_access_for_account_get(
                ProjectId=int(project_id) if project_id else 0,
                Username=username,
                SessionCode=request.session_code,
                _preload_content=False,
            )
            body = _json.loads(raw.data.decode('utf-8'))
            clusters = _parse_clusters(body if isinstance(body, list) else [])
        except Exception as api_exc:
            # HEAppE may return 4xx with a JSON body that still contains the result.
            # Try to extract the body from the exception before giving up.
            clusters = None
            exc_str = str(api_exc)
            # Look for the JSON body embedded in the exception message
            body_marker = "HTTP response body: b'"
            if body_marker in exc_str:
                try:
                    start = exc_str.index(body_marker) + len(body_marker)
                    end = exc_str.rindex("'")
                    raw_body = exc_str[start:end]
                    parsed = _json.loads(raw_body)
                    if isinstance(parsed, list):
                        clusters = _parse_clusters(parsed)
                except Exception:
                    pass
            if clusters is None:
                # Truly failed — no parseable body found
                messages.error(request, f"Access test for '{username}' failed. Could not reach the HEAppE service.")
                reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
                return redirect(reload_url)

        if clusters:
            for name, accessible in clusters:
                if accessible:
                    messages.success(request, f"✓ {name}: Access verified for '{username}'.")
                else:
                    messages.warning(request, f"✗ {name}: Access denied for '{username}'.")
        else:
            messages.warning(request, f"Access test returned no cluster data for '{username}'.")

    except Exception as e:
        messages.error(request, f"Internal error during access test: {str(e)}")

    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)

@login_required
def initialize_hpc_account(request: HttpRequest):
    import json as _json
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    username = request.POST.get("Username")
    payload_data = {
        "ProjectId": project_id,
        "OverwriteExistingProjectRootDirectory": True,
        "Username": username
    }
    payload = _create_payload(request.session_code, payload_data)

    def _parse_init_result(data):
        """Return list of (cluster_name, is_initialized) from a parsed JSON list."""
        results = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict):
                name = item.get('ClusterName') or item.get('cluster_name') or 'Unknown'
                initialized = item.get('IsClusterInitialized') if 'IsClusterInitialized' in item else item.get('is_cluster_initialized', False)
            else:
                name = getattr(item, 'cluster_name', 'Unknown')
                initialized = getattr(item, 'is_cluster_initialized', False)
            results.append((name, bool(initialized)))
        return results

    try:
        try:
            raw = controller.heappe_management_initialize_cluster_script_directory_post(
                **{**payload, '_preload_content': False}
            )
            body = _json.loads(raw.data.decode('utf-8'))
            clusters = _parse_init_result(body)
        except Exception as api_exc:
            clusters = None
            exc_str = str(api_exc)
            body_marker = "HTTP response body: b'"
            if body_marker in exc_str:
                try:
                    start = exc_str.index(body_marker) + len(body_marker)
                    end = exc_str.rindex("'")
                    parsed = _json.loads(exc_str[start:end])
                    clusters = _parse_init_result(parsed)
                except Exception:
                    pass
            if clusters is None:
                messages.error(request, f"Initialization of '{username}' failed. Could not reach the HEAppE service.")
                reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
                return redirect(reload_url)

        if clusters:
            for name, initialized in clusters:
                if initialized:
                    messages.success(request, f"✓ {name}: '{username}' initialized successfully.")
                else:
                    messages.warning(request, f"✗ {name}: Initialization of '{username}' did not complete.")
        else:
            messages.success(request, f"Initialization request sent for '{username}'.")

    except Exception as e:
        messages.error(request, f"Internal error during initialization: {str(e)}")

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


@login_required
def job_live_details_partial(request: HttpRequest, job_id: int) -> HttpResponse:
    controller = hp.JobManagementApi(request.api_instance)
    try:
        result = controller.heappe_job_management_current_info_for_job_get(
            SubmittedJobInfoId=job_id, SessionCode=request.session_code
        )
        if not result:
            return render(request, "job_live_details_error_partial.html", {
                "job_id": job_id,
                "error": "No details returned for this Job ID."
            })
        return render(request, "job_live_details_partial.html", {"job": result})
    except Exception as e:
        return render(request, "job_live_details_error_partial.html", {
            "job_id": job_id,
            "error": str(e)
        })