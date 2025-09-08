from .imports import *
from .utils import _create_payload, _handle_api_call

def cluster_list(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    clusters = controller.heappe_management_clusters_get(SessionCode=request.session_code)
    cluster_list = [c.to_dict() for c in clusters]
    return render(request, "clusters.html", {"clusters": cluster_list})


def cluster_detail(request: HttpRequest, cluster_id: int, _tab: str = None) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    tab = request.GET.get('tab', 'detail')
    if _tab:
        tab = _tab
    if request.method == "POST":
        payload_data = {
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "MasterNodeName": request.POST.get("MasterNodeName"),
            "SchedulerType": int(request.POST.get("SchedulerType")) if request.POST.get("SchedulerType") else None,
            "ConnectionProtocol": int(request.POST.get("ConnectionProtocol")) if request.POST.get("ConnectionProtocol") else None,
            "TimeZone": request.POST.get("TimeZone"),
            "Port": int(request.POST.get("Port")) if request.POST.get("Port") else None,
            "UpdateJobStateByServiceAccount": request.POST.get("UpdateJobStateByServiceAccount") == "on",
            "DomainName": request.POST.get("DomainName"),
            "ProxyConnectionId": int(request.POST.get("ProxyConnectionId")) if request.POST.get("ProxyConnectionId") else None,
        }
        payload = _create_payload(request.session_code, payload_data)
        payload["body"]["Id"] = cluster_id
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_put(**payload),
            "Cluster updated successfully!",
            "Failed to update cluster"
        )
        if result:
            return redirect("cluster_detail", cluster_id=cluster_id)

    cluster = controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=request.session_code)
    context = {'cluster': cluster.to_dict(), 'active_tab': tab}

    if tab == 'queues':
        context['queues'] = cluster.to_dict()['node_types']
        print(context['queues'][0] if context['queues'] else "No queues found")
    elif tab == 'projects':
        node_types_projects = {
            project['id']: project
            for node_type in cluster.to_dict()['node_types']
            for project in node_type['projects']
        }
        context['projects'] = list(node_types_projects.values())
        user_api = hp.UserAndLimitationManagementApi(request.api_instance)
        projects_for_user = user_api.heappe_user_and_limitation_management_projects_for_current_user_get(
            SessionCode=request.session_code
        )
        seen_ids = {p['id'] for p in context['projects']}
        context['projectsForCurrentUser'] = [
            item.project for item in projects_for_user
            if item.project.id not in seen_ids
        ]

    return render(request, "cluster_detail.html", context)


def cluster_delete(request: HttpRequest, cluster_id: int) -> HttpResponse:
    controller = hp.ClusterInformationApi(request.api_instance)
    return _handle_api_call(
        request,
        lambda: controller.heappe_cluster_information_delete_cluster_delete(cluster_id, request.session_code),
        "Cluster deleted successfully!",
        "Failed to delete cluster",
        redirect_url='cluster_list'
    )

