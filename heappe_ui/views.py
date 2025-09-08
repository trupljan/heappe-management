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