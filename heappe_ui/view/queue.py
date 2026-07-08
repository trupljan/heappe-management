from django.conf import settings
from django.urls import reverse
from django.http import JsonResponse

from .imports import *
from .utils import _create_payload, _handle_api_call, PROTOCOL_CHOICES, login_view, login_required, ACCOUNTING_OPERATORS, ACCOUNTING_TIMES, ACCOUNTING_NUMBERS, _parse_datetime_local, clean_ver





@login_required
def queues_view(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "bulk_delete":
            selected_ids = request.POST.getlist("selected_ids")
            success_count = 0
            for qid in selected_ids:
                try:
                    payload = _create_payload(request.session_code, {"Id": int(qid)})
                    controller.heappe_management_cluster_node_type_delete(**payload)
                    success_count += 1
                except Exception as e:
                    print(f"Error deleting queue {qid}: {e}")
            if success_count > 0:
                messages.success(request, f"Successfully deleted {success_count} queue(s).")
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to delete {len(selected_ids) - success_count} queue(s).")
            cluster_id = request.POST.get("ClusterId")
            if cluster_id:
                return redirect(f"/clusters/{cluster_id}/?tab=queues")
            return redirect("queues_view")

    raw_queues = controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code)
    queues = [c.to_dict() for c in raw_queues] if raw_queues else []
    
    filetransfer_methods = controller.heappe_management_file_transfer_methods_get(SessionCode=request.session_code) or []
    ftm_dict = {}
    for ftm in filetransfer_methods:
        protocol_name = dict(PROTOCOL_CHOICES).get(ftm.protocol, "Unknown")
        ftm_dict[ftm.id] = f"{ftm.server_hostname} ({protocol_name})"
        
    for queue in queues:
        queue['fileTransferMethodName'] = ftm_dict.get(queue.get('file_transfer_method_id'), 'N/A')
        
    return render(request, "queues.html", {"queues": queues})

@login_required
def queue_detail(request: HttpRequest, queue_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    node_type = controller.heappe_management_cluster_node_type_get(Id=queue_id, SessionCode=request.session_code).to_dict()
    if request.method == "POST":
        # check if cluster has scheduler_type == 32 (QScheduler)
        scheduler_type = None
        cluster_id = node_type.get("cluster_id")
        if cluster_id:
            try:
                cluster_data = controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=request.session_code).to_dict()
                scheduler_type = cluster_data.get("scheduler_type")
            except Exception as e:
                print(f"Error fetching cluster in queue_detail: {e}")
        
        deployed_version = request.session.get("middleware_deployed_version", "")
        is_v6_5_0_plus = clean_ver(deployed_version) >= [6, 5, 0]

        queue_val = request.POST.get("Queue", "")
        if scheduler_type == 32:
            if not is_v6_5_0_plus:
                if not queue_val.isdigit() or int(queue_val) <= 0:
                    messages.error(request, "Validation Error: Queue identifier must be a valid positive integer representing the QScheduler Machine ID.")
                    return redirect("queue_detail", queue_id=queue_id)

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





    return render(request, "queue.html", {
        "node_type": node_type,
        "filetransfer_method": filetransfer_method,
        "clusternodetypeaggregation": clusternodetypeaggregation,
        "cluster": cluster,
        "filetransfer_methods": cluster_filetransfer_methods,
        "queue_groups": queue_groups,
        "PROTOCOL_CHOICES": PROTOCOL_CHOICES,
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

        queue_groups = [g.to_dict() for g in
                        controller.heappe_management_cluster_node_type_aggregations_get(
                            SessionCode=request.session_code)]
        # map protocol to cluster_filetransfer_methods
        for ftm in cluster_filetransfer_methods:
            ftm['protocol_name'] = dict(PROTOCOL_CHOICES).get(ftm['protocol'], "Unknown")
        return render(request, "queue.html", {
            "cluster": cluster,
            "filetransfer_methods": cluster_filetransfer_methods,
            "queue_groups": queue_groups,
            "PROTOCOL_CHOICES": PROTOCOL_CHOICES,
        })

    if request.method == "POST":
        # check if cluster has scheduler_type == 32 (QScheduler)
        scheduler_type = None
        try:
            cluster_data = controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=request.session_code).to_dict()
            scheduler_type = cluster_data.get("scheduler_type")
        except Exception as e:
            print(f"Error fetching cluster in queue_create: {e}")
        
        deployed_version = request.session.get("middleware_deployed_version", "")
        is_v6_5_0_plus = clean_ver(deployed_version) >= [6, 5, 0]

        queue_val = request.POST.get("Queue", "")
        if scheduler_type == 32:
            if not is_v6_5_0_plus:
                if not queue_val.isdigit() or int(queue_val) <= 0:
                    messages.error(request, "Validation Error: Queue identifier must be a valid positive integer representing the QScheduler Machine ID.")
                    return redirect("queue_create", cluster_id=cluster_id)

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
            return redirect("queue_detail", queue_id=result['Id'])

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
    if cluster_id:
        return redirect(f"/clusters/{cluster_id}/?tab=queues")
    return redirect("queues_view")


@login_required
def queue_groups(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete_queue_group":
            group_id = int(request.POST.get("QueueGroupId"))
            payload = _create_payload(request.session_code, {"Id": group_id})
            _handle_api_call(
                request,
                lambda: controller.heappe_management_cluster_node_type_aggregation_delete(**payload),
                "Queue Group deleted successfully!",
                "Failed to delete Queue Group"
            )
            return redirect("queue_groups")
        elif action == "bulk_delete":
            selected_ids = request.POST.getlist("selected_ids")
            success_count = 0
            for gid in selected_ids:
                try:
                    payload = _create_payload(request.session_code, {"Id": int(gid)})
                    controller.heappe_management_cluster_node_type_aggregation_delete(**payload)
                    success_count += 1
                except Exception as e:
                    print(f"Error deleting queue group {gid}: {e}")
            if success_count > 0:
                messages.success(request, f"Successfully deleted {success_count} queue group(s).")
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to delete {len(selected_ids) - success_count} queue group(s).")
            return redirect("queue_groups")

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
        if action == "bulk_unassign_group":
            selected_ids = request.POST.getlist("selected_ids")
            success_count = 0
            for pid in selected_ids:
                try:
                    payload = _create_payload(request.session_code, {
                        "ClusterNodeTypeAggregationId": group_id,
                        "ProjectId": int(pid)
                    })
                    controller.heappe_management_project_cluster_node_type_aggregation_delete(**payload)
                    success_count += 1
                except Exception as e:
                    print(f"Error unassigning project {pid} from group {group_id}: {e}")
            if success_count > 0:
                messages.success(request, f"Successfully unassigned {success_count} project(s) from group.")
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to unassign {len(selected_ids) - success_count} project(s) from group.")
            return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=projects")


    if request.method == "GET":
        if tab == "detail":
            tab = "detail"
        elif tab == "queues":
            all_queues = controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code) or []
            queues = []
            for queue in all_queues:
                if queue.cluster_node_type_aggregation and queue.cluster_node_type_aggregation.id == group_id:
                    queues.append(queue.to_dict())
            
            filetransfer_methods = controller.heappe_management_file_transfer_methods_get(SessionCode=request.session_code) or []
            ftm_dict = {}
            for ftm in filetransfer_methods:
                protocol_name = dict(PROTOCOL_CHOICES).get(ftm.protocol, "Unknown")
                ftm_dict[ftm.id] = f"{ftm.server_hostname} ({protocol_name})"
                
            for queue in queues:
                queue['fileTransferMethodName'] = ftm_dict.get(queue.get('file_transfer_method_id'), 'N/A')
                
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
    if request.method == "GET":
        return render(request, 'queue_group.html', {"active_tab": tab})
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        allocation_type = request.POST.get("AllocationType")
        if allocation_type == "optional":
            allocation_type = request.POST.get("AllocationTypeCustom")

        payload_data = {
            "Name": request.POST.get("Name"),
            "Description": request.POST.get("Description"),
            "AllocationType": allocation_type,
            "ValidityFrom": _parse_datetime_local(request.POST.get("ValidityFrom")),
            "ValidityTo": _parse_datetime_local(request.POST.get("ValidityTo")),
        }
        payload = _create_payload(request.session_code, payload_data)
        
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('format') == 'json'
        
        if is_ajax:
            try:
                result_obj = controller.heappe_management_cluster_node_type_aggregation_post(**payload)
                if hasattr(result_obj, "data"):
                    import json
                    raw_data = result_obj.data
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode("utf-8")
                    result = json.loads(raw_data)
                else:
                    result = result_obj.to_dict() if hasattr(result_obj, "to_dict") else result_obj
                
                if isinstance(result, str):
                    import json
                    try:
                        result = json.loads(result)
                    except Exception:
                        pass
                
                new_id = None
                if isinstance(result, dict):
                    new_id = result.get('Id') or result.get('id')
                elif hasattr(result_obj, 'Id'):
                    new_id = result_obj.Id
                elif hasattr(result_obj, 'id'):
                    new_id = result_obj.id
                else:
                    new_id = result
                
                if new_id:
                    return JsonResponse({"status": "success", "id": new_id, "name": payload_data["Name"]})
                    
                return JsonResponse({"status": "error", "message": "Failed to retrieve new Queue Group ID."}, status=400)
            except Exception as e:
                return JsonResponse({"status": "error", "message": str(e)}, status=400)

        result =  _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_post(**payload),
            "Queue Group created successfully!",
            "Failed to create Queue Group"
        )
        if result:
            return redirect(f"queue_group_detail", group_id=result['Id'])


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
            "ValidityFrom": _parse_datetime_local(request.POST.get("ValidityFrom")),
            "ValidityTo": _parse_datetime_local(request.POST.get("ValidityTo")),
        }
        payload = _create_payload(request.session_code, payload_data)
        result =  _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_node_type_aggregation_put(**payload),
            "Queue Group updated successfully!",
            "Failed to update Queue Group"
        )
        if result:
            return redirect(f"queue_group_detail", group_id=group_id)

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

        return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=formulas")


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

        return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=formulas")


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
            "ValidityFrom": _parse_datetime_local(validityFrom),
            "ValidityTo": _parse_datetime_local(validityTo),
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_accounting_post(**payload),
            "Formula created successfully!",
            "Failed to create formula"
        )
        return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=formulas")

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
            "ValidityFrom": _parse_datetime_local(validityFrom),
            "ValidityTo": _parse_datetime_local(validityTo),
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_accounting_put(**payload),
            "Formula created successfully!",
            "Failed to create formula"
        )
        return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=formulas")

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
        return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=projects")



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
    return redirect(f"{reverse('queue_group_detail', kwargs={'group_id': group_id})}?tab=projects")

