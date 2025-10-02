from .imports import *
from .utils import _create_payload, _handle_api_call, PROTOCOL_CHOICES, login_view, login_required, ACCOUNTING_OPERATORS, ACCOUNTING_TIMES, ACCOUNTING_NUMBERS





@login_required
def queues_view(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    queues = [c.to_dict() for c in controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code)]
    return render(request, "queues.html", {"queues": queues})

@login_required
def queue_detail(request: HttpRequest, queue_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    node_type = controller.heappe_management_cluster_node_type_get(Id=queue_id, SessionCode=request.session_code).to_dict()
    queue_groups = [g.to_dict() for g in
                    controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=request.session_code)]

    cluster = None
    if node_type['cluster_id']:
        cluster = controller.heappe_management_cluster_get(Id=node_type['cluster_id'], SessionCode=request.session_code).to_dict()

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

    filetransfer_methods = controller.heappe_management_file_transfer_methods_get(SessionCode=request.session_code)
    cluster_filetransfer_methods = []
    # get only filetransfer methods for this cluster
    if cluster:
        cluster_filetransfer_methods = [ftm.to_dict() for ftm in filetransfer_methods if ftm.cluster_id == cluster['id']]
    # map protocol to cluster_filetransfer_methods
        for ftm in cluster_filetransfer_methods:
            ftm['protocol_name'] = dict(PROTOCOL_CHOICES).get(ftm['protocol'], "Unknown")

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
            "ClusterId": node_type["cluster_id"],
            "FileTransferMethodId": int(request.POST.get("FileTransferMethodId")) if request.POST.get("FileTransferMethodId") else None,
            "ClusterNodeTypeAggregationId": int(request.POST.get("ClusterNodeTypeAggregationId")) if request.POST.get("ClusterNodeTypeAggregationId") else None,
        }
        payload = _create_payload(request.session_code, payload_data)
        result =  _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_put(**payload),
            "Queue updated successfully!",
            "Failed to update Queue"
        )
        if result:
            return redirect(f"/queues/{queue_id}/")

    return render(request, "queue.html", {
        "node_type": node_type,
        "filetransfer_method": filetransfer_method,
        "clusternodetypeaggregation": clusternodetypeaggregation,
        "cluster": cluster,
        "filetransfer_methods": cluster_filetransfer_methods,
        "queue_groups": queue_groups
    })

@login_required
def queue_create(request: HttpRequest, cluster_id:int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "GET":
        cluster = controller.heappe_management_cluster_get(Id=cluster_id,
                                                            SessionCode=request.session_code).to_dict()
        filetransfer_methods = controller.heappe_management_file_transfer_methods_get(SessionCode=request.session_code)
        # get only filetransfer methods for this cluster
        cluster_filetransfer_methods = [ftm.to_dict() for ftm in filetransfer_methods if ftm.cluster_id == cluster_id]
        # map protocol to cluster_filetransfer_methods
        for ftm in cluster_filetransfer_methods:
            ftm['protocol_name'] = dict(PROTOCOL_CHOICES).get(ftm['protocol'], "Unknown")
        return render(request, "queue.html", {
            "cluster": cluster,
            "filetransfer_methods": cluster_filetransfer_methods
        })

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
            "ClusterId": cluster_id,
            "FileTransferMethodId": int(request.POST.get("FileTransferMethodId")) if request.POST.get("FileTransferMethodId") else None,
            "ClusterNodeTypeAggregationId": int(request.POST.get("ClusterNodeTypeAggregationId")) if request.POST.get("ClusterNodeTypeAggregationId") else None,
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_post(**payload),
            "Queue created successfully!",
            "Failed to create Queue"
        )
        if result:
            return redirect(f"/queues/{result['Id']}/")

    return render(request, "queue.html")

@login_required
def queue_delete(request: HttpRequest, queue_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    cluster_id = request.POST.get("ClusterId")
    payload = _create_payload(request.session_code, {"Id": queue_id})
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_cluster_node_type_delete(**payload),
        "Queue deleted successfully!",
        "Failed to delete Queue"
    )
    return redirect(f"/clusters/{cluster_id}/?tab=queues")


@login_required
def queue_groups(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    queue_groups = [g.to_dict() for g in controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=request.session_code)]
    return render(request, "queue_groups.html", {"queue_groups": queue_groups})


@login_required
def queue_group_detail(request: HttpRequest, group_id: int) -> HttpResponse:
    tab = request.GET.get('tab', 'detail')
    controller = hp.ManagementApi(request.api_instance)
    queue_group = controller.heappe_management_cluster_node_type_aggregation_get(Id=group_id, SessionCode=request.session_code).to_dict()
    context = {"queue_group": queue_group}
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "queue_group_modify":
            return queue_group_modify(request, group_id)
        if action == "assign_formula":
            return assign_formula(request, group_id)
        if action == "unassign_formula":
            return unassign_formula(request, group_id)
        if action == "add_formula":
            return add_formula(request, group_id)
        if action == "edit_formula":
            return edit_formula(request, group_id)
        if action == "assign_project_to_group":
            return assign_project_to_group(request, group_id)
        if action == "unassign_project_to_group":
            return unassign_project_to_group(request, group_id)


    if request.method == "GET":
        if tab == "detail":
            tab = "detail"
        elif tab == "queues":
            all_queues = controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code) or []
            queues = []
            for queue in all_queues:
                if queue.cluster_node_type_aggregation and queue.cluster_node_type_aggregation.id == group_id:
                    queues.append(queue)
            context['queues'] = queues
        elif tab == "projects":
            all_projects = controller.heappe_management_projects_get(SessionCode=request.session_code) or []
            project_aggregations = controller.heappe_management_project_cluster_node_type_aggregations_get(
                SessionCode=request.session_code
            ) or []

            projects = []
            assigned_project_ids = set()

            for group in project_aggregations:
                if group.cluster_node_type_aggregation_id == group_id:
                    for project in all_projects:
                        if project.id == group.project_id:
                            projects.append(project)
                            assigned_project_ids.add(project.id)

            not_assigned_projects = [p for p in all_projects if p.id not in assigned_project_ids]

            context['projects'] = projects
            context['not_assigned_projects'] = not_assigned_projects

        elif tab == "formulas":
            accountings = controller.heappe_management_accountings_get(SessionCode=request.session_code) or []
            mappings = controller.heappe_management_cluster_node_type_aggregation_accountings_get(
                SessionCode=request.session_code
            ) or []
            formulas = []
            for mapping in mappings:
                if mapping.cluster_node_type_aggregation_id == group_id:
                    for accounting in accountings:
                        if accounting.id == mapping.accounting_id:
                            formulas.append(accounting)
            context['formulas'] = formulas
            context['all_formulas'] = [a for a in accountings if a not in formulas]
            context['ACCOUNTING_OPERATORS'] = ACCOUNTING_OPERATORS
            context['ACCOUNTING_TIMES'] = ACCOUNTING_TIMES
            context['ACCOUNTING_NUMBERS'] = ACCOUNTING_NUMBERS







    context['active_tab'] = tab
    return render(request, "queue_group.html", context)

@login_required
def queue_group_create(request: HttpRequest) -> HttpResponse:
    tab = request.GET.get('tab', 'detail')
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        allocation_type = request.POST.get("AllocationType")
        if allocation_type == "optional":
            allocation_type = request.POST.get("AllocationTypeCustom")

        payload_data = {
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "AllocationType": allocation_type,
            "ValidityFrom": None if request.POST.get("ValidityFrom") == "" else request.POST.get("ValidityFrom"),
            "ValidityTo": None if request.POST.get("ValidityTo") == "" else request.POST.get("ValidityTo"),
        }
        payload = _create_payload(request.session_code, payload_data)
        result =  _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_post(**payload),
            "Queue Group created successfully!",
            "Failed to create Queue Group"
        )
        if result:
            return redirect(f"/queue-groups/{result['Id']}/")

    return render(request, 'queue_group.html', {"active_tab": tab})

@login_required
def queue_group_modify(request: HttpRequest, group_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    queue_group = controller.heappe_management_cluster_node_type_aggregation_get(Id=group_id, SessionCode=request.session_code).to_dict()

    if request.method == "POST":
        allocation_type = request.POST.get("AllocationType")
        if allocation_type == "optional":
            allocation_type = request.POST.get("AllocationTypeCustom")

        payload_data = {
            "Id": group_id,
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "AllocationType": allocation_type,
            "ValidityFrom": None if request.POST.get("ValidityFrom") == "" else request.POST.get("ValidityFrom"),
            "ValidityTo": None if request.POST.get("ValidityTo") == "" else request.POST.get("ValidityTo"),
        }
        payload = _create_payload(request.session_code, payload_data)
        result =  _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_put(**payload),
            "Queue Group updated successfully!",
            "Failed to update Queue Group"
        )
        if result:
            return redirect(f"/queue-groups/{group_id}/")

    return redirect(f"/queue-groups/{group_id}/")

@login_required
def assign_formula(request: HttpRequest, group_id: int) -> HttpResponse:
    # ClusterNodeTypeAggregationAccounting
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        formulaId = request.POST.get("FormulaId")

        payload_data = {
            "ClusterNodeTypeAggregationId": group_id,
            "AccountingId": formulaId
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_accounting_post(**payload),
            "Formula assigned successfully to Queue Group!",
            "Failed to assign formula to Queue Group"
        )
        if result:
            return redirect(f"/queue-groups/{group_id}/?tab=formulas")

    return redirect(f"/queue-groups/{group_id}/?tab=formulas")

@login_required
def unassign_formula(request: HttpRequest, group_id: int) -> HttpResponse:
    # ClusterNodeTypeAggregationAccounting
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        formulaId = request.POST.get("FormulaId")

        payload_data = {
            "ClusterNodeTypeAggregationId": group_id,
            "AccountingId": formulaId
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_accounting_delete(**payload),
            "Formula unassigned successfully to Queue Group!",
            "Failed to unassign formula to Queue Group"
        )
        if result:
            return redirect(f"/queue-groups/{group_id}/?tab=formulas")

    return redirect(f"/queue-groups/{group_id}/?tab=formulas")

@login_required
def add_formula(request: HttpRequest, group_id: int) -> HttpResponse:
    # ClusterNodeTypeAggregationAccounting
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        formula = request.POST.get("Formula")
        validityFrom = request.POST.get("ValidityFrom")
        validityTo = request.POST.get("ValidityTo")

        payload_data = {
            "Formula": formula,
            "ValidityFrom": None if validityFrom == "" else validityFrom,
            "ValidityTo": None if validityTo == "" else validityTo,
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_accounting_post(**payload),
            "Formula created successfully!",
            "Failed to create formula"
        )
        if result:
            return redirect(f"/queue-groups/{group_id}/?tab=formulas")

    return redirect(f"/queue-groups/{group_id}/?tab=formulas")

@login_required
def edit_formula(request: HttpRequest, group_id: int) -> HttpResponse:
    # ClusterNodeTypeAggregationAccounting
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        formulaId = int(request.POST.get("FormulaId"))
        formula = request.POST.get("Formula")
        validityFrom = request.POST.get("ValidityFrom")
        validityTo = request.POST.get("ValidityTo")

        payload_data = {
            "Id": formulaId,
            "Formula": formula,
            "ValidityFrom": None if validityFrom == "" else validityFrom,
            "ValidityTo": None if validityTo == "" else validityTo,
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_accounting_put(**payload),
            "Formula created successfully!",
            "Failed to create formula"
        )
        if result:
            return redirect(f"/queue-groups/{group_id}/?tab=formulas")

    return redirect(f"/queue-groups/{group_id}/?tab=formulas")

@login_required
def assign_project_to_group(request: HttpRequest, group_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = 0
    if request.method == "POST":
        project_id = int(request.POST.get("ProjectId"))
        aggregation_id = group_id
        allocation_amount = int(request.POST.get("AllocationAmount", 0))

        payload_data = {
            "ProjectId": project_id,
            "ClusterNodeTypeAggregationId": aggregation_id,
            "AllocationAmount": allocation_amount,
        }
        payload = _create_payload(request.session_code, payload_data)

        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_project_cluster_node_type_aggregation_post(**payload),
            "Project assigned successfully!",
            "Failed to assign Project"
        )
    if result:
            return redirect(f"/queue-groups/{group_id}/?tab=projects")

    return redirect(f"/queue-groups/{group_id}/?tab=projects")

@login_required
def unassign_project_to_group(request: HttpRequest, group_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    group_id = group_id
    payload = _create_payload(request.session_code,
                              {
                                  "ClusterNodeTypeAggregationId": group_id,
                                  "ProjectId": project_id
                              })

    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_cluster_node_type_aggregation_delete(**payload),
        "Queue Group unassigned successfully!",
        "Failed to unassign Queue Group"
    )
    if result:
            return redirect(f"/queue-groups/{group_id}/?tab=projects")

    return redirect(f"/queue-groups/{group_id}/?tab=projects")

