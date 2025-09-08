from .imports import *


from .utils import _create_payload, _handle_api_call  # předpokládám, že to máš v utils.py


def queue_list(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    clusters = [c.to_dict() for c in controller.heappe_management_clusters_get(SessionCode=request.session_code)]
    return render(request, "queue_list.html", {"clusters": clusters})


def queue_detail(request: HttpRequest, queue_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    node_type = controller.heappe_management_cluster_node_type_get(Id=queue_id, SessionCode=request.session_code).to_dict()

    filetransfer_method = (
        controller.heappe_management_file_transfer_method_get(
            Id=node_type['file_transfer_method_id'], SessionCode=request.session_code
        ).to_dict()
        if node_type.get("file_transfer_method_id")
        else None
    )
    clusternodetypeaggregation = (
        controller.heappe_management_cluster_node_type_aggregation_get(
            Id=node_type["cluster_node_type_aggregation"]["id"], SessionCode=request.session_code
        ).to_dict()
        if node_type.get("cluster_node_type_aggregation")
        else None
    )

    if request.method == "POST":
        # update queue
        payload_data = {
            "Id": queue_id,
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "NumberOfNodes": int(request.POST.get("NumberOfNodes")) if request.POST.get("NumberOfNodes") else None,
            "CoresPerNode": int(request.POST.get("CoresPerNode")) if request.POST.get("CoresPerNode") else None,
            "Queue": request.POST.get("Queue"),
            "QualityOfService": request.POST.get("QualityOfService"),
            "MaxWalltime": int(request.POST.get("MaxWalltime")) if request.POST.get("MaxWalltime") else None,
            "ClusterAllocationName": request.POST.get("ClusterAllocationName"),
            "ClusterId": int(request.POST.get("ClusterId")) if request.POST.get("ClusterId") else None,
            "FileTransferMethodId": int(request.POST.get("FileTransferMethodId")) if request.POST.get("FileTransferMethodId") else None,
            "ClusterNodeTypeAggregationId": int(request.POST.get("ClusterNodeTypeAggregationId")) if request.POST.get("ClusterNodeTypeAggregationId") else None,
        }
        payload = _create_payload(request.session_code, payload_data)
        return _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_put(**payload),
            "Queue updated successfully!",
            "Failed to update Queue",
            redirect_url=f"/queues/{queue_id}/"
        )

    return render(request, "queue.html", {
        "node_type": node_type,
        "filetransfer_method": filetransfer_method,
        "clusternodetypeaggregation": clusternodetypeaggregation,
    })


def queue_create(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        payload_data = {
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "NumberOfNodes": int(request.POST.get("NumberOfNodes")) if request.POST.get("NumberOfNodes") else None,
            "CoresPerNode": int(request.POST.get("CoresPerNode")) if request.POST.get("CoresPerNode") else None,
            "Queue": request.POST.get("Queue"),
            "QualityOfService": request.POST.get("QualityOfService"),
            "MaxWalltime": int(request.POST.get("MaxWalltime")) if request.POST.get("MaxWalltime") else None,
            "ClusterAllocationName": request.POST.get("ClusterAllocationName"),
            "ClusterId": int(request.POST.get("ClusterId")) if request.POST.get("ClusterId") else None,
            "FileTransferMethodId": int(request.POST.get("FileTransferMethodId")) if request.POST.get("FileTransferMethodId") else None,
            "ClusterNodeTypeAggregationId": int(request.POST.get("ClusterNodeTypeAggregationId")) if request.POST.get("ClusterNodeTypeAggregationId") else None,
        }
        payload = _create_payload(request.session_code, payload_data)
        return _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_post(**payload),
            "Queue created successfully!",
            "Failed to create Queue",
            redirect_url=f"/queues/"
        )

    return render(request, "queue.html")


def queue_delete(request: HttpRequest, queue_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    return _handle_api_call(
        request,
        lambda: controller.heappe_management_cluster_node_type_delete(Id=queue_id, SessionCode=request.session_code),
        "Queue deleted successfully!",
        "Failed to delete Queue",
        redirect_url="/queues/"
    )
