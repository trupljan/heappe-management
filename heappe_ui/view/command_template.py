from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required

# Predefined templates available for creation
COMMAND_TEMPLATE_PRESETS = {
    "test": {
        "name": "TestTemplate",
        "description": "Predefined test command template",
        "executable_file_suffix": "test.sh",
        "parameters": [
            {
                "Identifier": "inputParam",
                "Description": "Input parameter for the test script",
                "Query": None
            }
        ]
    }
}

@login_required
def command_template_detail(request: HttpRequest, command_template_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    session_code = request.session_code

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_command_template":
            return command_template_modify(request, command_template_id)
        if action == "add_parameter":
            return add_parameter_to_command_template(request, command_template_id)
        if action == "update_parameter":
            return update_parameter_in_command_template(request, command_template_id)
        if action == "delete_parameter":
            return delete_parameter_from_command_template(request, command_template_id)

    import time
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

    force_refresh = request.GET.get("refresh") == "1"

    # Cache command template details
    cache_key = f"command_template_detail_cache_{command_template_id}"
    cache_time_key = f"command_template_detail_cache_{command_template_id}_time"

    command_template = request.session.get(cache_key)
    command_template_time = request.session.get(cache_time_key, 0)

    is_from_cache = False
    if not force_refresh and command_template and (time.time() - command_template_time <= 300) and (command_template_time >= last_global_mod):
        is_from_cache = True
    else:
        try:
            command_template = controller.heappe_management_command_template_get(
                Id=command_template_id, SessionCode=session_code
            ).to_dict()
            request.session[cache_key] = command_template
            request.session[cache_time_key] = time.time()
            command_template_time = request.session[cache_time_key]
        except Exception as e:
            print(f"Error fetching command template detail: {e}")
            if not command_template:
                raise e

    if is_from_cache:
        age = int(time.time() - command_template_time)
        if age < 60:
            template_cache_age_str = f"{age}s"
        else:
            template_cache_age_str = f"{age // 60}m {age % 60}s"
    else:
        template_cache_age_str = None

    project = controller.heappe_management_project_get(
        Id=command_template['project_id'], SessionCode=session_code
    ).to_dict()

    force_refresh = request.GET.get("refresh") == "1"

    # Cache clusters list
    clusters_cache = request.session.get("clusters_cache")
    clusters_time = request.session.get("clusters_cache_time", 0)
    if force_refresh or not clusters_cache or (time.time() - clusters_time > 300) or (clusters_time < last_global_mod):
        clusters_raw = controller.heappe_management_clusters_get(SessionCode=request.session_code)
        clusters_cache = [c.to_dict() for c in clusters_raw]
        request.session["clusters_cache"] = clusters_cache
        request.session["clusters_cache_time"] = time.time()
    clusters = clusters_cache

    project_assignments = []
    if command_template['project_id'] != 0:
        response = controller.heappe_management_project_assignment_to_clusters_get(
            ProjectId=command_template['project_id'], SessionCode=request.session_code
        )
        project_assignments = [pa.to_dict() for pa in response]
        # add cluster details fror project assignments
        for assignment in project_assignments:
            for cluster in clusters:
                if cluster['id'] == assignment['cluster_id']:
                    assignment['cluster_name'] = cluster['name']
                    break

    cluster_map = {c['id']: c for c in clusters}
    cluster_node_types = []
    for assignment in project_assignments:
        cluster = cluster_map.get(assignment['cluster_id'])
        if cluster:
            cluster_name = assignment.get('cluster_name', cluster['name'])
            for ntype in cluster.get('node_types', []):
                ntype_dict = ntype.copy() if isinstance(ntype, dict) else ntype.to_dict()
                ntype_dict['cluster_name'] = cluster_name
                cluster_node_types.append(ntype_dict)

    return render(request, "command_template.html", {
        "command_template": command_template,
        "node_types": cluster_node_types,
        "project": project,
        "template_cache_age_str": template_cache_age_str,
    })

@login_required
def command_template_modify(request: HttpRequest, command_template_id: int) -> HttpResponse:
    payload_data = {
        "Id": command_template_id,
        "Name": request.POST.get("Name"),
        "Description": request.POST.get("Description"),
        "ExtendedAllocationCommand": request.POST.get("ExtendedAllocationCommand"),
        "ExecutableFile": request.POST.get("ExecutableFile"),
        "PreparationScript": request.POST.get("PreparationScript"),
        "ClusterNodeTypeId": int(request.POST.get("ClusterNodeTypeId")) if request.POST.get("ClusterNodeTypeId") else None,
        "IsEnabled": request.POST.get("IsEnabled") == "on",
    }
    payload = _create_payload(request.session_code, payload_data)
    controller = hp.ManagementApi(request.api_instance)
    _handle_api_call(
        request,
        lambda: controller.heappe_management_command_template_put(**payload),
        "Command Template modified successfully!",
        "Failed to modify Command Template"
    )
    return redirect("command_template_detail", command_template_id=command_template_id)


@login_required
def command_template_create(request: HttpRequest, project_id: int) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        payload_data = {
            "ProjectId": project_id,
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "ExtendedAllocationCommand": request.POST.get("ExtendedAllocationCommand"),
            "ExecutableFile": request.POST.get("ExecutableFile"),
            "PreparationScript": request.POST.get("PreparationScript"),
            "ClusterNodeTypeId": int(request.POST.get("ClusterNodeTypeId")) if request.POST.get(
                "ClusterNodeTypeId") else None,
            "IsEnabled": request.POST.get("IsEnabled") == "on",
            "TemplateParameters": request.POST.getlist("TemplateParameters")  # This should be a list of dicts
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_command_template_post(**payload),
            "Command Template created successfully!",
            "Failed to create Command Template"
        )
        if result:
            # Check for preset parameter addition
            preset_name = request.POST.get("preset")
            if preset_name in COMMAND_TEMPLATE_PRESETS:
                for param in COMMAND_TEMPLATE_PRESETS[preset_name].get("parameters", []):
                    try:
                        param_payload_data = {
                            "CommandTemplateId": result['Id'],
                            "Identifier": param["Identifier"],
                            "Query": param.get("Query"),
                            "Description": param.get("Description")
                        }
                        param_payload = _create_payload(request.session_code, param_payload_data)
                        controller.heappe_management_command_template_parameter_post(**param_payload)
                    except Exception as e:
                        print(f"Error adding preset parameter {param['Identifier']}: {e}")
            return redirect("command_template_detail", command_template_id=result['Id'])

    controller = hp.ManagementApi(request.api_instance)

    try:
        project = controller.heappe_management_project_get(
            Id=project_id, SessionCode=request.session_code
        ).to_dict()
    except Exception as e:
        print(f"Error fetching project {project_id}: {e}")
        raise e

    # Validate that project has a valid id before proceeding to render
    if not project or not project.get('id'):
        from django.contrib import messages as _messages
        _messages.error(request, f"Project with ID {project_id} could not be loaded.")
        return redirect("project_list")

    # Handle preset prefill
    preset_name = request.GET.get("preset")
    preset_data = None
    if preset_name in COMMAND_TEMPLATE_PRESETS:
        p_info = COMMAND_TEMPLATE_PRESETS[preset_name]
        key_scripts_dir = project.get('key_scripts_directory_path') or ''
        if key_scripts_dir and not key_scripts_dir.endswith('/'):
            exec_file = f"{key_scripts_dir}/{p_info['executable_file_suffix']}"
        else:
            exec_file = f"{key_scripts_dir}{p_info['executable_file_suffix']}"
            
        preset_data = {
            "name": p_info["name"],
            "description": p_info["description"],
            "executable_file": exec_file
        }

    import time
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

    force_refresh = request.GET.get("refresh") == "1"

    # Cache clusters list
    clusters_cache = request.session.get("clusters_cache")
    clusters_time = request.session.get("clusters_cache_time", 0)
    if force_refresh or not clusters_cache or (time.time() - clusters_time > 300) or (clusters_time < last_global_mod):
        clusters_raw = controller.heappe_management_clusters_get(SessionCode=request.session_code)
        clusters_cache = [c.to_dict() for c in clusters_raw]
        request.session["clusters_cache"] = clusters_cache
        request.session["clusters_cache_time"] = time.time()
    clusters = clusters_cache

    response = controller.heappe_management_project_assignment_to_clusters_get(
        ProjectId=project_id, SessionCode=request.session_code
    )
    project_assignments = [pa.to_dict() for pa in response]

    # add cluster details for project assignments
    for assignment in project_assignments:
        for cluster in clusters:
            if cluster['id'] == assignment['cluster_id']:
                assignment['cluster_name'] = cluster['name']
                break

    cluster_map = {c['id']: c for c in clusters}
    cluster_node_types = []
    for assignment in project_assignments:
        cluster = cluster_map.get(assignment['cluster_id'])
        if cluster:
            cluster_name = assignment.get('cluster_name', cluster['name'])
            for ntype in cluster.get('node_types', []):
                ntype_dict = ntype.copy() if isinstance(ntype, dict) else ntype.to_dict()
                ntype_dict['cluster_name'] = cluster_name
                cluster_node_types.append(ntype_dict)

    return render(request, 'command_template.html', {
        'node_types': cluster_node_types,
        'project_id': project_id,
        'project': project,
        'command_template': None,
        'preset': preset_data,
        'preset_name': preset_name or ''
    })


@login_required
def command_template_delete(request: HttpRequest, command_template_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    try:
        template = controller.heappe_management_command_template_get(
            Id=command_template_id, SessionCode=request.session_code
        )
        project_id = template.project_id
    except Exception:
        project_id = request.GET.get('project_id')

    payload_data = {"CommandTemplateId": command_template_id}
    payload = _create_payload(request.session_code, payload_data)

    _handle_api_call(
        request,
        lambda: controller.heappe_management_remove_command_template_delete(**payload),
        "Command Template deleted successfully!",
        "Failed to delete Command Template"
    )

    if project_id:
        response = redirect("project_detail", project_id=project_id)
        response['Location'] += "?tab=commandtemplates"
        return response

    return redirect("project_list")



@login_required
def add_parameter_to_command_template(request: HttpRequest, command_template_id: int) -> HttpResponse:

    controller = hp.ManagementApi(request.api_instance)
    payload_data = {
        "CommandTemplateId": command_template_id,
        "Identifier": request.POST.get("Identifier"),
        "Query": request.POST.get("Query"),
        "Description": request.POST.get("Description")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_command_template_parameter_post(**payload),
        "Parameter added successfully!",
        "Failed to add parameter",
    )
    return redirect("command_template_detail", command_template_id=command_template_id)

def update_parameter_in_command_template(request: HttpRequest, command_template_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    parameter_id = int(request.POST.get("ParameterId"))
    payload_data = {
        "Id": parameter_id,
        "CommandTemplateId": command_template_id,
        "Identifier": request.POST.get("Identifier"),
        "Query": request.POST.get("Query"),
        "Description": request.POST.get("Description")
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_command_template_parameter_put(**payload),
        "Parameter updated successfully!",
        "Failed to update parameter",
    )
    return redirect("command_template_detail", command_template_id=command_template_id)

def delete_parameter_from_command_template(request: HttpRequest, command_template_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    parameter_id = int(request.POST.get("ParameterId"))
    payload_data = {
        "Id": parameter_id,
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_command_template_parameter_delete(**payload),
        "Parameter deleted successfully!",
        "Failed to delete parameter"
    )
    return redirect("command_template_detail", command_template_id=command_template_id)