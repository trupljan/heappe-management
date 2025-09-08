from .imports import *
from .utils import _create_payload, _handle_api_call

def project_detail(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    tab = request.GET.get("tab", "detail")
    clusters = [c.to_dict() for c in controller.heappe_management_clusters_get(SessionCode=request.session_code)]
    command_templates, project_accounts, project_data, project_assignments = [], [], None, []

    #if post
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_project":
            return project_update(request, project_id)
        if action == "project_assign_to_cluster":
            return project_assign_to_cluster(request, project_id)
        if action == "delete_assignment":
            return delete_assignment(request, project_id)

    if project_id:
        project_data = controller.heappe_management_project_get(
            Id=project_id, SessionCode=request.session_code
        ).to_dict()
        command_templates = [ct.to_dict() for ct in controller.heappe_management_command_templates_get(
            ProjectId=project_id, SessionCode=request.session_code
        )]
        project_accounts = [pa.to_dict() for pa in controller.heappe_management_secure_shell_keys_get(
            ProjectId=project_id, SessionCode=request.session_code
        )]
        for cluster in clusters:
            try:
                response = controller.heappe_management_project_assignment_to_cluster_get(
                    ProjectId=project_id, ClusterId=cluster['id'], SessionCode=request.session_code
                )
                project_assignments.append({
                    "cluster_name": cluster['name'],
                    "cluster_id": cluster['id'],
                    "local_basepath": response.local_basepath,
                })
            except Exception:
                continue



    return render(request, "project.html", {
        "project": project_data,
        "clusters": clusters,
        "project_assignments": project_assignments,
        "active_tab": tab,
        "command_templates": command_templates,
        "project_accounts": project_accounts,
    })


def project_create(request: HttpRequest) -> HttpResponse:
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

def project_assign_to_cluster(request: HttpRequest, project_id) -> HttpResponse:
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


def delete_assignment(request: HttpRequest, project_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    payload_data = {
        "ProjectId": project_id,
        "ClusterId": int(request.POST.get("ClusterId")),
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_assignment_to_cluster_delete(**payload),
        "Cluster assignment removed successfully!",
        "Failed to remove cluster assignment"
    )
    return redirect("project_detail", project_id=project_id)
