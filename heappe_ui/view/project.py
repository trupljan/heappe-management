from concurrent.futures import ThreadPoolExecutor
import time
from django.http import JsonResponse
from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required, _parse_datetime_local, clean_ver
from .command_template import COMMAND_TEMPLATE_PRESETS


KEY_TYPE_CHOICES = {
    1: "None",
    2: "RSA3072",
    3: "RSA4096",
    4: "nistP256",
    5: "nistP521",
    6: "Ed25519",
}

PREFERRED_AUTH_TYPES_NO_PROXY = [
    (0, "Unknown"),
    (1, "Password"),
    (2, "Password Interactive"),
    (3, "Password and Private Key"),
    (4, "Private Key"),
    (9, "Private Key in SSH Agent"),
    (10, "Private Key in Vault and SSH Agent"),
    (11, "SSH Certificate"),
    (13, "Kerberos"),
    (14, "FirecRest IdP"),
]

PREFERRED_AUTH_TYPES_WITH_PROXY = [
    (5, "Password via Proxy"),
    (6, "Password Interactive via Proxy"),
    (7, "Password and Private Key via Proxy"),
    (8, "Private Key via Proxy"),
    (11, "SSH Certificate via Proxy"),
    (12, "SSH Certificate via Proxy"),
    (13, "Kerberos via Proxy"),
    (14, "FirecRest IdP via Proxy"),
]

PREFERRED_AUTH_TYPE_NO_PROXY_DICT = dict(PREFERRED_AUTH_TYPES_NO_PROXY)
PREFERRED_AUTH_TYPE_WITH_PROXY_DICT = dict(PREFERRED_AUTH_TYPES_WITH_PROXY)
# Merged dict for backwards compatibility – note: shared keys (e.g. 13) resolve to the with-proxy label.
# Use PREFERRED_AUTH_TYPE_NO_PROXY_DICT / PREFERRED_AUTH_TYPE_WITH_PROXY_DICT for context-aware lookups.
PREFERRED_AUTH_TYPE_CHOICES = dict(PREFERRED_AUTH_TYPES_NO_PROXY + PREFERRED_AUTH_TYPES_WITH_PROXY)



@login_required
def project_detail(request: HttpRequest, project_id: int, _tab: str = None) -> HttpResponse:
    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]
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
    disable_cache = getattr(settings, 'DISABLE_CACHE', False)
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
        if action in ("update_project", "project_update"): return project_update(request, project_id)
        if action == "project_assign_to_cluster": return project_assign_to_cluster_with_project_id(request, project_id)
        if action == "delete_assignment": return delete_assignment(request, project_id)
        if action == "update_assignment": return update_assignment(request)
        if action == "test_hpc_access": return test_cluster_authentication_credential_HPC_access(request)
        if action == "initialize_hpc_account": return initialize_hpc_account(request)
        if action == "create_new_hpc_account": return create_new_hpc_account(request)
        if action == "regenerate_ssh_key": return regenerate_ssh_key(request)
        if action == "rename_hpc_account": return rename_hpc_account(request)
        if action == "delete_hpc_account": return delete_hpc_account(request)
        if action == "bulk_delete_command_templates": return bulk_delete_command_templates(request, project_id)
        if action == "create_preset_template": return _create_preset_template(request, project_id, controller, session_code)
        if action == "create_credential": return create_credential(request, project_id)
        if action == "modify_credential": return modify_credential(request, project_id)
        if action == "delete_credential": return delete_credential(request, project_id)

    # Initialize context variables with defaults
    clusters = []
    not_assigned_clusters = []
    project_assignments = []
    command_templates = []
    project_accounts = []
    project_credentials = []
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
        if disable_cache or force_refresh or not clusters_cache or (time.time() - clusters_time > 300) or (clusters_time < last_global_mod):
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
            cluster_obj = next((c for c in clusters if c['id'] == a['cluster_id']), None)
            a['cluster_has_proxy'] = bool(cluster_obj.get('proxy_connection')) if cluster_obj else False
            pref_auth = a.get('preferred_auth_type')
            if pref_auth is not None:
                try:
                    auth_int = int(pref_auth)
                    # Use proxy-aware lookup so that e.g. value 13 shows "Kerberos" (no proxy)
                    # or "Kerberos via Proxy" (with proxy) rather than always the with-proxy label.
                    if a['cluster_has_proxy']:
                        primary, fallback = PREFERRED_AUTH_TYPE_WITH_PROXY_DICT, PREFERRED_AUTH_TYPE_NO_PROXY_DICT
                    else:
                        primary, fallback = PREFERRED_AUTH_TYPE_NO_PROXY_DICT, PREFERRED_AUTH_TYPE_WITH_PROXY_DICT
                    a['preferred_auth_type_name'] = primary.get(auth_int) or fallback.get(auth_int, "Unknown")
                except (ValueError, TypeError):
                    a['preferred_auth_type_name'] = str(pref_auth)

    elif tab == "commandtemplates":
        cache_key = f"command_templates_cache_{project_id}"
        cache_time_key = f"command_templates_cache_{project_id}_time"

        all_templates = request.session.get(cache_key)
        all_templates_time = request.session.get(cache_time_key, 0)

        is_from_cache = False
        if not disable_cache and not force_refresh and all_templates and (time.time() - all_templates_time <= 300) and (all_templates_time >= last_global_mod):
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
        if disable_cache or force_refresh or not node_types_cache or (time.time() - node_types_time > 300) or (node_types_time < last_global_mod):
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

        # Build all available cluster node types for preset template modal
        project_assignments_for_presets = controller.heappe_management_project_assignment_to_clusters_get(
            ProjectId=project_id, SessionCode=session_code
        )
        assigned_cluster_ids_for_presets = {a.cluster_id for a in project_assignments_for_presets}
        all_cluster_node_types = []
        for c_obj in clusters_cache:
            if c_obj['id'] in assigned_cluster_ids_for_presets:
                for nt in c_obj.get('node_types', []):
                    nt_copy = nt.copy() if isinstance(nt, dict) else nt
                    nt_copy['cluster_name'] = c_obj['name']
                    all_cluster_node_types.append(nt_copy)

    elif tab == "accounts":
        try:
            project_accounts = [pa.to_dict() for pa in controller.heappe_management_secure_shell_keys_get(
                ProjectId=project_id, SessionCode=session_code
            )]
            for pa in project_accounts:
                pa['key_type_name'] = KEY_TYPE_CHOICES.get(pa.get('key_type'), 'Unknown')
        except:
            project_accounts = []

        if is_v6_4_0_plus:
            cred_ctrl = hp.CredentialsApi(request.api_instance)
            project_credentials = [pc.to_dict() for pc in cred_ctrl.heappe_credentials_get_credentials_get(
                ProjectId=project_id, SessionCode=session_code
            )]
            adaptor_users = [u.to_dict() for u in controller.heappe_management_adaptor_users_in_project_get(
                SessionCode=session_code, ProjectId=project_id
            )]
            # add adaptor_username to dictionary
            for project_credential in project_credentials:
                project_credential["auth_type_str"] = PREFERRED_AUTH_TYPE_CHOICES.get(project_credential["auth_type"], "Unknown")
                
                matched_users = [user["username"] for user in adaptor_users if user["id"] == project_credential["adaptor_user_id"]]
                project_credential["adaptor_username"] = matched_users[0] if matched_users else "Unknown"
                
                # add status safely
                try:
                    status_results = controller.heappe_management_cluster_account_status_get(
                        ProjectId=project_id, Username=project_credential["username"], SessionCode=session_code
                    )
                    init_ok = sum(1 for s in status_results if s.is_initialized)
                    project_credential["status"] = "Active" if len(status_results) > 0 and init_ok == len(status_results) else "Inactive"
                except Exception as e:
                    print(f"Error checking status for credential {project_credential['username']}: {e}")
                    project_credential["status"] = "Inactive"
                
                # add key type and public keys safely from public_key_ext
                pk_ext = project_credential.get("public_key_ext")
                if pk_ext:
                    ktype = pk_ext.get("key_type")
                    project_credential["key_type"] = KEY_TYPE_CHOICES.get(ktype, "Unknown")
                    project_credential["public_key_open_ssh"] = pk_ext.get("public_key_open_ssh")
                    project_credential["public_key_pem"] = pk_ext.get("public_key_pem")
                else:
                    project_credential["key_type"] = None
                    project_credential["public_key_open_ssh"] = None
                    project_credential["public_key_pem"] = None

                if not project_credential["key_type"] and project_accounts:
                    proj_account = next(iter([pa for pa in project_accounts if pa["username"] == project_credential["username"]]), None)
                    if proj_account:
                        project_credential["key_type"] = proj_account.get("key_type_name")
                        project_credential["public_key_open_ssh"] = proj_account.get("public_key_open_ssh")
                        project_credential["public_key_pem"] = proj_account.get("public_key_pem")

    elif tab == "adaptor_users" and has_adaptor_users:
        try:
            adaptor_users = [u.to_dict() for u in controller.heappe_management_adaptor_users_in_project_get(
                SessionCode=session_code, ProjectId=project_id
            )]
            
            # Cache all adaptor users
            all_adaptor_users_cache = request.session.get("all_adaptor_users_cache")
            all_adaptor_users_time = request.session.get("all_adaptor_users_cache_time", 0)
            if disable_cache or force_refresh or not all_adaptor_users_cache or (time.time() - all_adaptor_users_time > 300) or (all_adaptor_users_time < last_global_mod):
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

        # 6. SSH Account/Credentials active check
        if is_v6_4_0_plus:
            try:
                cred_ctrl = hp.CredentialsApi(request.api_instance)
                credentials = cred_ctrl.heappe_credentials_get_credentials_get(
                    ProjectId=project_id, SessionCode=session_code
                ) or []
                for credential in credentials:
                    try:
                        status_results = controller.heappe_management_cluster_account_status_get(
                            ProjectId=project_id, Username=credential.username, SessionCode=session_code
                        ) or []
                        init_ok = sum(1 for s in status_results if s.is_initialized)
                        if len(status_results) > 0 and init_ok == len(status_results):
                            setup_checklist["ssh_account_active"] = True
                            break
                    except Exception:
                        pass
            except Exception as ex:
                print(f"Error checking credentials in checklist: {ex}")
        else:
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

    setup_checklist_completed = sum(1 for k in [
        "clusters_exist",
        "project_cluster_linked",
        "queues_exist",
        "project_group_linked",
        "formulas_exist_and_mapped",
        "command_template_exists",
        "ssh_account_active"
    ] if setup_checklist.get(k))

    return render(request, "project.html", {
        "project": project_data,
        "clusters": clusters,
        "not_assigned_clusters": not_assigned_clusters,
        "project_assignments": project_assignments,
        "active_tab": tab,
        "command_templates": command_templates,
        "project_accounts": project_accounts,
        "project_credentials": project_credentials,
        "node_types": node_types,
        "all_cluster_node_types": all_cluster_node_types if tab == "commandtemplates" else [],
        "preset_templates": COMMAND_TEMPLATE_PRESETS if tab == "commandtemplates" else {},
        "adaptor_users": adaptor_users,
        "adaptor_users_not_in_project": adaptor_users_not_in_project,
        "ui_features": ui_features,
        "templates_cache_age_str": templates_cache_age_str if tab == "commandtemplates" else None,
        "setup_checklist": setup_checklist,
        "setup_checklist_completed": setup_checklist_completed,
        "is_v6_4_0_plus": is_v6_4_0_plus,
        "preferred_auth_types_no_proxy": PREFERRED_AUTH_TYPES_NO_PROXY,
        "preferred_auth_types_with_proxy": PREFERRED_AUTH_TYPES_WITH_PROXY,
        "preferred_auth_type_choices": PREFERRED_AUTH_TYPE_CHOICES,
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

    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]

    if request.method == "POST":
        if request.POST.get("action") == "submit_job":
            # Job-level data
            job_name = request.POST.get("JobName")
            project_id = request.POST.get("ProjectId")
            cluster_id = request.POST.get("ClusterId")
            notify_email = request.POST.get("NotificationEmail", "").strip()
            if not notify_email:
                notify_email = ""
                notify_start = False
                notify_finish = False
                notify_abort = False
            else:
                notify_start = request.POST.get("NotifyOnStart") == "true"
                notify_finish = request.POST.get("NotifyOnFinish") == "true"
                notify_abort = request.POST.get("NotifyOnAbort") == "true"

            # Task-level data
            task_name = request.POST.get("TaskName")
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

            task_spec = {
                "Name": task_name,
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

            max_cores_val = request.POST.get("MaxCores")
            if not is_v6_4_0_plus:
                task_spec["MinCores"] = int(request.POST.get("MinCores") or 1)
                task_spec["MaxCores"] = int(max_cores_val or 1)
            else:
                if max_cores_val and max_cores_val.strip():
                    task_spec["MaxCores"] = int(max_cores_val)
                    min_cores_val = request.POST.get("MinCores")
                    task_spec["MinCores"] = int(min_cores_val) if (min_cores_val and min_cores_val.strip()) else 1

            if is_v6_4_0_plus:
                gpu_cores = request.POST.get("GpuCores")
                if gpu_cores and gpu_cores.strip():
                    task_spec["GpuCores"] = int(gpu_cores)
                gpu_nodes = request.POST.get("GpuNodes")
                if gpu_nodes and gpu_nodes.strip():
                    task_spec["GpuNodes"] = int(gpu_nodes)
                required_nodes = request.POST.get("RequiredNodes")
                if required_nodes and required_nodes.strip():
                    task_spec["RequiredNodes"] = [n.strip() for n in required_nodes.split(",") if n.strip()]
                memory = request.POST.get("Memory")
                if memory and memory.strip():
                    task_spec["Memory"] = int(memory)
                memory_per_cpu = request.POST.get("MemoryPerCpu")
                if memory_per_cpu and memory_per_cpu.strip():
                    task_spec["MemoryPerCPU"] = int(memory_per_cpu)
                memory_per_gpu = request.POST.get("MemoryPerGpu")
                if memory_per_gpu and memory_per_gpu.strip():
                    task_spec["MemoryPerGPU"] = int(memory_per_gpu)

            # Authentication settings
            auth_method = request.POST.get("AuthMethod", "default")
            auth_credential = request.POST.get("AuthCredential", "").strip()

            submit_api_instance = request.api_instance
            submit_session_code = request.session_code

            if auth_method != "default" and auth_credential:
                user_config = hp.Configuration()
                user_config.api_key = {}
                user_config.api_key_prefix = {}
                host = request.session.get("heappe_host")
                user_config.host = 'http://' + host if not host.startswith('http') else host
                user_config.verify_ssl = True

                submit_api_instance = hp.ApiClient(user_config)
                submit_api_instance.custom_auth = True

                if auth_method == "jwt":
                    user_config.api_key = {'Authorization': auth_credential}
                    user_config.api_key_prefix = {'Authorization': 'Bearer'}
                    submit_api_instance.set_default_header("Authorization", f"Bearer {auth_credential}")
                elif auth_method == "apikey":
                    user_config.api_key = {'X-API-Key': auth_credential}
                    user_config.api_key_prefix = {}
                    submit_api_instance.set_default_header("X-API-Key", auth_credential)

                from heappe_ui.auth_backend import patch_api_client
                submit_api_instance._request = request
                patch_api_client(submit_api_instance)
                submit_session_code = None

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
                    "Tasks": [task_spec],
                    "ProjectId": project['id']
                }
            }

            controller = hp.JobManagementApi(submit_api_instance)
            payload = _create_payload(submit_session_code, payload_data)
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
                payload = _create_payload(submit_session_code, payload_data)
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
        "is_v6_4_0_plus": is_v6_4_0_plus,
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

    project = None
    if result:
        tasks = None
        if isinstance(result, dict):
            tasks = result.get('tasks')
        elif hasattr(result, 'tasks'):
            tasks = result.tasks

        if tasks and len(tasks) > 0:
            first_task = tasks[0]
            node_type = None
            if isinstance(first_task, dict):
                node_type = first_task.get('node_type')
            elif hasattr(first_task, 'node_type'):
                node_type = first_task.node_type

            if node_type:
                proj = None
                if isinstance(node_type, dict):
                    proj = node_type.get('project')
                elif hasattr(node_type, 'project'):
                    proj = node_type.project

                if proj:
                    project = proj

    context = {
        "job": result,
        "project": project,
        "changed_files": []
    }

    # Fetch changed files list from cluster
    try:
        file_transfer_controller = hp.FileTransferApi(request.api_instance)
        changed_files_res = file_transfer_controller.heappe_file_transfer_list_changed_files_for_job_get(
            SessionCode=request.session_code,
            SubmittedJobInfoId=job_id
        )
        if changed_files_res:
            context["changed_files"] = changed_files_res
    except Exception as e:
        print(f"Error fetching changed files for job {job_id}: {e}")

    return render(request, "job_status.html", context)


@login_required
def download_job_file_view(request: HttpRequest, job_id: int) -> HttpResponse:
    file_path = request.GET.get("file_path")
    action = request.GET.get("action", "download") # "download" or "view"

    if not file_path:
        return HttpResponse("Missing file_path parameter", status=400)

    controller = hp.FileTransferApi(request.api_instance)

    from py4heappe.heappe_v6.core import DownloadFileFromClusterModel
    body = DownloadFileFromClusterModel(
        session_code=request.session_code,
        submitted_job_info_id=job_id,
        relative_file_path=file_path
    )

    try:
        import base64
        b64_content = controller.heappe_file_transfer_download_file_from_cluster_post(body=body)

        if not b64_content:
            if action == "view":
                return JsonResponse({"content": ""})
            return HttpResponse("File is empty or could not be retrieved.", status=404)

        file_bytes = base64.b64decode(b64_content)

        if action == "view":
            try:
                text_content = file_bytes.decode("utf-8")
            except Exception:
                text_content = file_bytes.decode("latin-1", errors="replace")
            
            # Sanitize control characters (including null bytes) to prevent Safari DOMException 
            # (DOMException 12: The string did not match the expected pattern)
            control_chars = {i: 0xFFFD for i in range(32) if i not in (9, 10, 13)}
            control_chars[127] = 0xFFFD
            for i in range(128, 160):
                control_chars[i] = 0xFFFD
            text_content = text_content.translate(control_chars)
            
            return JsonResponse({"content": text_content})

        # Default: download
        import os
        filename = os.path.basename(file_path) or "download"
        response = HttpResponse(file_bytes, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        if action == "view":
            return JsonResponse({"error": str(e)}, status=500)
        messages.error(request, f"Failed to retrieve file: {str(e)}")
        return redirect("job_status_view", job_id=job_id)


@login_required
def job_status_partial_view(request: HttpRequest, job_id: int) -> HttpResponse:
    controller = hp.JobManagementApi(request.api_instance)

    result = _handle_api_call(
        request,
        lambda: controller.heappe_job_management_current_info_for_job_get(SubmittedJobInfoId=job_id, SessionCode=request.session_code),
        None,
        None,
        silent=True
    )

    project = None
    if result:
        tasks = None
        if isinstance(result, dict):
            tasks = result.get('tasks')
        elif hasattr(result, 'tasks'):
            tasks = result.tasks

        if tasks and len(tasks) > 0:
            first_task = tasks[0]
            node_type = None
            if isinstance(first_task, dict):
                node_type = first_task.get('node_type')
            elif hasattr(first_task, 'node_type'):
                node_type = first_task.node_type

            if node_type:
                proj = None
                if isinstance(node_type, dict):
                    proj = node_type.get('project')
                elif hasattr(node_type, 'project'):
                    proj = node_type.project

                if proj:
                    project = proj

    changed_files = []
    try:
        file_transfer_controller = hp.FileTransferApi(request.api_instance)
        changed_files_res = file_transfer_controller.heappe_file_transfer_list_changed_files_for_job_get(
            SessionCode=request.session_code,
            SubmittedJobInfoId=job_id
        )
        if changed_files_res:
            changed_files = changed_files_res
    except Exception:
        pass

    context = {
        "job": result,
        "project": project,
        "changed_files": changed_files
    }
    return render(request, "job_status_content.html", context)


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
            "StartDate": _parse_datetime_local(request.POST.get("StartDate")),
            "EndDate": _parse_datetime_local(request.POST.get("EndDate")),
            "UsageType": int(request.POST.get("UsageType")),
            "UseAccountingStringForScheduler": request.POST.get("UseAccountingStringForScheduler") == "on",
            "IsOneToOneMapping": request.POST.get("IsOneToOneMapping") == "on",
            "PIEmail": request.POST.get("PIEmail") or "",
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
        "StartDate": _parse_datetime_local(request.POST.get("StartDate")),
        "EndDate": _parse_datetime_local(request.POST.get("EndDate")),
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
    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]
    if is_v6_4_0_plus:
        pref_auth = request.POST.get("PreferredAuthType")
        if pref_auth is not None and pref_auth != "":
            try:
                payload_data["PreferredAuthType"] = int(pref_auth)
            except ValueError:
                pass
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
    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]
    if is_v6_4_0_plus:
        pref_auth = request.POST.get("PreferredAuthType")
        if pref_auth is not None and pref_auth != "":
            try:
                payload_data["PreferredAuthType"] = int(pref_auth)
            except ValueError:
                pass
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
    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]
    if is_v6_4_0_plus:
        pref_auth = request.POST.get("PreferredAuthType")
        if pref_auth is not None and pref_auth != "":
            try:
                payload_data["PreferredAuthType"] = int(pref_auth)
            except ValueError:
                pass
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
def bulk_delete_command_templates(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    selected_ids = request.POST.getlist("selected_ids")
    success_count = 0
    for template_id in selected_ids:
        try:
            payload_data = {"CommandTemplateId": int(template_id)}
            payload = _create_payload(request.session_code, payload_data)
            controller.heappe_management_remove_command_template_delete(**payload)
            success_count += 1
        except Exception as e:
            print(f"Error deleting command template {template_id}: {e}")
            
    if success_count > 0:
        messages.success(request, f"Successfully deleted {success_count} command template(s).")
    if len(selected_ids) > success_count:
        messages.error(request, f"Failed to delete {len(selected_ids) - success_count} command template(s).")
        
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=commandtemplates")
    if "?tab=" not in reload_url:
        if "?" in reload_url:
            reload_url += "&tab=commandtemplates"
        else:
            reload_url += "?tab=commandtemplates"
    return redirect(reload_url)


def _create_preset_template(request: HttpRequest, project_id: int, controller: hp.ManagementApi, session_code: str) -> HttpResponse:
    preset_name = request.POST.get("preset_name")
    cluster_node_type_id_str = request.POST.get("ClusterNodeTypeId")

    if not preset_name or preset_name not in COMMAND_TEMPLATE_PRESETS:
        messages.error(request, f"Preset '{preset_name}' is not recognized.")
        response = redirect("project_detail", project_id=project_id)
        response['Location'] += "?tab=commandtemplates"
        return response

    if not cluster_node_type_id_str:
        messages.error(request, "Cluster Node Type must be selected.")
        response = redirect("project_detail", project_id=project_id)
        response['Location'] += "?tab=commandtemplates"
        return response

    try:
        cluster_node_type_id = int(cluster_node_type_id_str)
    except ValueError:
        messages.error(request, "Invalid Cluster Node Type selected.")
        response = redirect("project_detail", project_id=project_id)
        response['Location'] += "?tab=commandtemplates"
        return response

    try:
        project_data = controller.heappe_management_project_get(Id=project_id, SessionCode=session_code).to_dict()
    except Exception as e:
        messages.error(request, f"Failed to retrieve project info: {e}")
        response = redirect("project_detail", project_id=project_id)
        response['Location'] += "?tab=commandtemplates"
        return response

    preset = COMMAND_TEMPLATE_PRESETS[preset_name]
    key_scripts_dir = project_data.get('key_scripts_directory_path') or ''
    suffix = preset['executable_file_suffix']
    if key_scripts_dir and not key_scripts_dir.endswith('/'):
        executable_file = f"{key_scripts_dir}/{suffix}"
    else:
        executable_file = f"{key_scripts_dir}{suffix}"

    # Step 1: Create template
    payload_data = {
        "ProjectId": project_id,
        "Name": preset["name"],
        "Description": preset["description"],
        "ExtendedAllocationCommand": "",
        "ExecutableFile": executable_file,
        "PreparationScript": "",
        "ClusterNodeTypeId": cluster_node_type_id,
        "IsEnabled": True,
        "TemplateParameters": []
    }

    payload = _create_payload(session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_command_template_post(**payload),
        None,  # Do not display a generic success message
        "Failed to create Command Template"
    )

    if not result or not result.get('Id'):
        response = redirect("project_detail", project_id=project_id)
        response['Location'] += "?tab=commandtemplates"
        return response

    # Step 2: Create parameters
    template_id = result['Id']
    params_ok = True
    for param in preset.get("parameters", []):
        try:
            param_payload_data = {
                "CommandTemplateId": template_id,
                "Identifier": param["Identifier"],
                "Query": param.get("Query"),
                "Description": param.get("Description")
            }
            param_payload = _create_payload(session_code, param_payload_data)
            controller.heappe_management_command_template_parameter_post(**param_payload)
        except Exception as e:
            params_ok = False
            messages.warning(request, f"Failed to add template parameter {param['Identifier']}: {e}")

    # Invalidate command templates session cache
    cache_key = f"command_templates_cache_{project_id}"
    cache_time_key = f"command_templates_cache_{project_id}_time"
    if cache_key in request.session:
        del request.session[cache_key]
    if cache_time_key in request.session:
        del request.session[cache_time_key]

    if params_ok:
        messages.success(request, f"Quick Preset Template '{preset['name']}' created successfully with parameters!")
    else:
        messages.success(request, f"Quick Preset Template '{preset['name']}' created, but some parameters failed to add.")

    response = redirect("project_detail", project_id=project_id)
    response['Location'] += "?tab=commandtemplates"
    return response


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


@login_required
def create_credential(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.CredentialsApi(request.api_instance)
    #project_id = int(request.POST.get("ProjectId"))

    cred_passphrase = None
    cred_password = None
    generate_new_key = None
    provided_private_key = None

    auth_type_int = 0
    auth_type = request.POST.get("auth_type")
    if auth_type == "sshkeypair":
        auth_type_int = 4
        cred_passphrase = request.POST.get("cred_passphrase") 
        generate_new_key = request.POST.get("key_gen") == "generate" 
    elif auth_type == "password":
        auth_type_int = 1
        cred_password = request.POST.get("cred_password")

    payload_data = {
        "ProjectId": project_id,
        "SessionCode": request.session_code,
        "AdaptorUserId": request.POST.get("adaptor_user"),
        "Username": request.POST.get("username"),
        "AuthType": auth_type_int,
        "GenerateNewKey": generate_new_key,
        "ProvidedPrivateKey": provided_private_key,
        "Passphrase": cred_passphrase,
        "Password": cred_password
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_credentials_create_credential_post(**payload),
        "HPC account credential created successfully!",
        "Failed to create HPC account credential"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)


@login_required
def modify_credential(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.CredentialsApi(request.api_instance)
    #project_id = int(request.POST.get("ProjectId"))

    old_username = request.POST.get("mod_cred_username")
    new_username = request.POST.get("mod_cred_new_username")
    if new_username == '':
        new_username = old_username 

    payload_data = {
        "ProjectId": project_id,
        "SessionCode": request.session_code,
        "AdaptorUserId": request.POST.get("mod_cred_adaptor_user_id"),
        "OldUsername": old_username,
        "NewUsername": new_username,
        "NewPassword": request.POST.get("mod_cred_new_password")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_credentials_modify_credential_put(**payload),
        "HPC account credential modifications saved!",
        "Failed to modify HPC account credential"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)


@login_required
def delete_credential(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.CredentialsApi(request.api_instance)
    #project_id = int(request.POST.get("ProjectId"))

    payload_data = {
        "ProjectId": project_id,
        "SessionCode": request.session_code,
        #"CredentialId": request.POST.get("CredentialId"),
        "AdaptorUserId": request.POST.get("AdaptorUserId"),
        "Username": request.POST.get("Username"),
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_credentials_remove_credential_delete(**payload),
        "HPC account credential deleted!",
        "Failed to delete HPC account credential"
    )
    reload_url = request.META.get('HTTP_REFERER', f"/projects/{project_id}/?tab=accounts")
    return redirect(reload_url)