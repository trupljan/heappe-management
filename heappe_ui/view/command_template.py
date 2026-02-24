from .imports import *
from .utils import _create_payload, _handle_api_call, login_view, login_required

@login_required
def command_template_detail(request: HttpRequest, command_template_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    command_template = controller.heappe_management_command_template_get(
        Id=command_template_id, SessionCode=request.session_code
    ).to_dict()
    project = controller.heappe_management_project_get(
        Id=command_template['project_id'], SessionCode=request.session_code
    ).to_dict()


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

    clusters = [c.to_dict() for c in controller.heappe_management_clusters_get(SessionCode=request.session_code)]
    project_assignments = []
    if command_template['project_id'] is not 0:
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

    cluster_node_types = []
    for assignment in project_assignments:
        cluster = controller.heappe_management_cluster_get(Id=assignment['cluster_id'],
                                                           SessionCode=request.session_code)
        node_types = cluster.node_types
        cluster_node_types.extend([ntype.to_dict() for ntype in node_types])

    return render(request, "command_template.html", {
        "command_template": command_template,
        "node_types": cluster_node_types,
        "project": project,
    })

@login_required
def command_template_create(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        payload_data = {
            "ProjectId": project_id,
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "Command": request.POST.get("Command"),
            "IsActive": request.POST.get("IsActive") == "on",
        }
        payload = _create_payload(request.session_code, payload_data)
        return _handle_api_call(
            request,
            lambda: controller.heappe_management_command_template_post(**payload),
            "Command Template created successfully!",
            "Failed to create Command Template",
            redirect_url=f"/projects/{project_id}/?tab=command_templates"
        )

    return render(request, "command_template_create.html", {
        "project_id": project_id,
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
            "ClusterNodeTypeId": int(request.POST.get("ClusterNodeTypeId")) if request.POST.get("ClusterNodeTypeId") else None,
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
            return redirect("command_template_detail", command_template_id=result['Id'])

    controller = hp.ManagementApi(request.api_instance)

    project = controller.heappe_management_project_get(
        Id=project_id, SessionCode=request.session_code
    ).to_dict()
    # get project to cluster references from
    clusters = [c.to_dict() for c in controller.heappe_management_clusters_get(SessionCode=request.session_code)]
    response = controller.heappe_management_project_assignment_to_clusters_get(
        ProjectId=project_id, SessionCode=request.session_code
    )
    project_assignments = [pa.to_dict() for pa in response]
    # add cluster details fror project assignments
    for assignment in project_assignments:
        for cluster in clusters:
            if cluster['id'] == assignment['cluster_id']:
                assignment['cluster_name'] = cluster['name']
                break



    cluster_node_types = []
    for assignment in project_assignments:
        cluster = controller.heappe_management_cluster_get(Id=assignment['cluster_id'], SessionCode=request.session_code)
        node_types = cluster.node_types
        cluster_node_types.extend([ntype.to_dict() for ntype in node_types])



    return render(request, 'command_template.html', {'node_types': cluster_node_types, 'project_id': project_id, 'project': project})


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