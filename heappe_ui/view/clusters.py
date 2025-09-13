from .imports import *
from .utils import _create_payload, _handle_api_call, PROTOCOL_CHOICES, SCHEDULER_CHOICES, CONNECTION_PROTOCOL_CHOICES, login_view, login_required

@login_required(login_url="/login/")
def cluster_list(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    clusters = controller.heappe_management_clusters_get(SessionCode=request.session_code)
    cluster_list = [c.to_dict() for c in clusters]

    for cluster in cluster_list:
        cluster['scheduler_name'] = dict(SCHEDULER_CHOICES).get(cluster['scheduler_type'], "Unknown")
        cluster['connection_protocol_name'] = dict(CONNECTION_PROTOCOL_CHOICES).get(cluster['connection_protocol'], "Unknown")



    return render(request, "clusters.html",
                  {
                            "clusters": cluster_list
                          })


@login_required(login_url="/login/")
def cluster_create(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return render(request, "cluster_detail.html", {
            'PROTOCOL_CHOICES': PROTOCOL_CHOICES,
            'SCHEDULER_CHOICES': SCHEDULER_CHOICES,
            'CONNECTION_PROTOCOL_CHOICES': CONNECTION_PROTOCOL_CHOICES,
            'active_tab': 'detail',
        })
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
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
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_post(**payload),
            "Cluster created successfully!",
            "Failed to create cluster"
        )
        if result:
            # cluster_detail
            return redirect("cluster_detail", cluster_id=result["Id"])

@login_required(login_url="/login/")
def cluster_detail(request: HttpRequest, cluster_id: int, _tab: str = None) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    tab = request.GET.get('tab', 'detail')
    if _tab:
        tab = _tab
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "edit_filetransfer" or action == "add_filetransfer":
            return create_or_edit_filetransfer_method(request, cluster_id)
        elif action == "delete_filetransfer":
            filetransfer_id = int(request.POST.get("Id"))
            return delete_filetransfer_method(request, cluster_id, filetransfer_id)

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
    context['PROTOCOL_CHOICES'] = PROTOCOL_CHOICES
    if tab == 'detail':
        filetarnsfer_methods = controller.heappe_management_file_transfer_methods_get(SessionCode=request.session_code)
        # filtr for cluster_id
        cluster_filetransfer_methods = [ftm.to_dict() for ftm in filetarnsfer_methods if ftm.cluster_id == cluster_id]
        for ftm in cluster_filetransfer_methods:
            ftm['protocol_name'] = dict(PROTOCOL_CHOICES).get(ftm['protocol'], "Unknown")
        context['filetransfer_methods'] = cluster_filetransfer_methods

    elif tab == 'queues':
        context['queues'] = cluster.to_dict()['node_types']

        filetarnsfer_methods = controller.heappe_management_file_transfer_methods_get(SessionCode=request.session_code)
        # filtr for cluster_id
        cluster_filetransfer_methods = [ftm.to_dict() for ftm in filetarnsfer_methods if ftm.cluster_id == cluster_id]
        for ftm in cluster_filetransfer_methods:
            ftm['protocol_name'] = dict(PROTOCOL_CHOICES).get(ftm['protocol'], "Unknown")
        context['filetransfer_methods'] = cluster_filetransfer_methods

        # set fileTransferMethodName for each queue
        for queue in context['queues']:
            ftm = next((ftm for ftm in cluster_filetransfer_methods if ftm['id'] == queue.get('file_transfer_method_id')), None)
            queue['fileTransferMethodName'] = ftm['server_hostname'] + ' (' + ftm['protocol_name']+ ' )' if ftm else 'N/A'


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
        context['queues'] = cluster.to_dict()['node_types']

    return render(request, "cluster_detail.html", context)

@login_required(login_url="/login/")
def cluster_delete(request: HttpRequest, cluster_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    payload_data = {
        "Id": cluster_id
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_cluster_delete(**payload),
        "Cluster deleted successfully!",
        "Failed to delete cluster"
    )
    return redirect("cluster_list")

@login_required(login_url="/login/")
def create_or_edit_filetransfer_method(request: HttpRequest, cluster_id: int) -> HttpResponse:
    server_hostname = request.POST.get("ServerHostname")
    port = int(request.POST.get("Port")) if request.POST.get("Port") else None
    protocol = int(request.POST.get("Protocol")) if request.POST.get("Protocol") else None
    id = int(request.POST.get("Id")) if request.POST.get("Id") else None



    controller = hp.ManagementApi(request.api_instance)
    if id:
        payload_data = {
            "ClusterId": cluster_id,
            "ServerHostname": server_hostname,
            "Port": port,
            "Protocol": protocol,
            "Id": id
        }

        payload = _create_payload(request.session_code, payload_data)
        # Update existing file transfer method
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_file_transfer_method_put(**payload),
            "File transfer method updated successfully!",
            "Failed to update file transfer method"
        )
    else:
        payload_data = {
            "ClusterId": cluster_id,
            "ServerHostname": server_hostname,
            "Port": port,
            "Protocol": protocol
        }

        payload = _create_payload(request.session_code, payload_data)
        # Create new file transfer method
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_file_transfer_method_post(**payload),
            "File transfer method created successfully!",
            "Failed to create file transfer method"
        )
    return redirect("cluster_detail", cluster_id=cluster_id)

@login_required(login_url="/login/")
def delete_filetransfer_method(request: HttpRequest, cluster_id: int, filetransfer_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    payload_data = {
        "Id": filetransfer_id
    }
    payload = _create_payload(request.session_code, payload_data)
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_file_transfer_method_delete(**payload),
        "File transfer method deleted successfully!",
        "Failed to delete file transfer method"
    )
    return redirect("cluster_detail", cluster_id=cluster_id)


