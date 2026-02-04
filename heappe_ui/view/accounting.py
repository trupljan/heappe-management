from .imports import *
from .utils import _create_payload, _handle_api_call, PROTOCOL_CHOICES, login_view, login_required
from django.shortcuts import render
from datetime import datetime, date

@login_required
def accounting_view(request, project_id:int):
    context = {}
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "assign-queue-group-to-project":
            return assign_queue_group_to_project(request)
        if action == "unassign_queue_group_from_project":
            return unassign_queue_group_from_project(request)

    # Fetch data from API
    accountings = controller.heappe_management_accountings_get(SessionCode=request.session_code) or []
    queue_groups = controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=request.session_code) or []
    mappings = controller.heappe_management_cluster_node_type_aggregation_accountings_get(
        SessionCode=request.session_code
    ) or []
    queues = controller.heappe_management_cluster_node_types_get(SessionCode=request.session_code) or []

    from collections import defaultdict

    aggregation_dict = defaultdict(list)
    for m in mappings:
        aggregation_dict[m.cluster_node_type_aggregation_id].append(m.accounting_id)

    # v Pythonu
    context['agg_mappings'] = [(agg_id, ids) for agg_id, ids in aggregation_dict.items()]


    project = controller.heappe_management_project_get(SessionCode=request.session_code, Id=project_id)

    projects = controller.heappe_management_projects_get(SessionCode=request.session_code) or []

    project_mappings = {}

    project_aggregations = controller.heappe_management_project_cluster_node_type_aggregations_get(
        ProjectId=project_id,
        SessionCode=request.session_code
    ) or []

    # filtrujeme queue_groups podle id
    project_aggregations_ids = {a.cluster_node_type_aggregation_id for a in project_aggregations}
    filtered_queue_groups = [q for q in queue_groups if
                             q.id in project_aggregations_ids]

    current_date = datetime.now().date()

    today = date.today()
    for project_agg in project_aggregations:
        for group in queue_groups:
            if project_agg.cluster_node_type_aggregation_id == group.id:
                project_agg.group = group
                project_agg.group.accountings = []
                for accounting_id in aggregation_dict[group.id]:
                    for accounting in accountings:
                        if accounting.id == accounting_id:
                            project_agg.group.accountings.append(accounting)
                            break
                active_accounting = None
                for accounting in project_agg.group.accountings:
                    validity_from = datetime.fromisoformat(
                        accounting.validity_from).date() if accounting.validity_from else None
                    validity_to = datetime.fromisoformat(
                        accounting.validity_to).date() if accounting.validity_to else None

                    if (validity_from is None or validity_from <= current_date) and \
                            (validity_to is None or validity_to >= current_date):
                        if active_accounting is None or \
                                (validity_from and validity_from > (datetime.fromisoformat(
                                    active_accounting.validity_from).date() if active_accounting.validity_from else datetime.min.date())) or \
                                (
                                        validity_from == active_accounting.validity_from and accounting.id > active_accounting.id):
                            active_accounting = accounting

                # označení aktivního
                for accounting in project_agg.group.accountings:
                    accounting.is_active = accounting == active_accounting

                break
        for project in projects:
            if project_agg.project_id == project.id:
                project_agg.project = project
                break
        project_agg.queues = []
        for queue in queues:
            if queue.cluster_node_type_aggregation and queue.cluster_node_type_aggregation.id == project_agg.cluster_node_type_aggregation_id:
                project_agg.queues.append(queue)


    context['project_aggregations'] = project_aggregations
    assigned_group_ids = {a.cluster_node_type_aggregation_id for a in project_aggregations}
    available_queue_groups = [g for g in queue_groups if g.id not in assigned_group_ids]
    context['queue_groups'] = available_queue_groups
    context['project_id'] = project_id
    context['project'] = project

    return render(request, "accounting.html", context)


@login_required
def assign_queue_group_to_project(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    project_id = 0
    if request.method == "POST":
        project_id = int(request.POST.get("ProjectId"))
        aggregation_id = int(request.POST.get("ClusterNodeTypeAggregationId"))
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
            "Queue Group assigned successfully!",
            "Failed to assign Queue Group"
        )

        if result:
            return redirect("accounting", project_id=project_id)

    return redirect("accounting", project_id=project_id)


@login_required
def unassign_queue_group_from_project(request: HttpRequest) -> HttpResponse:
    """mapping_id je Id záznamu ProjectClusterNodeTypeAggregation"""
    controller = hp.ManagementApi(request.api_instance)
    project_id = int(request.POST.get("ProjectId"))
    mapping_id = int(request.POST.get("MappingId"))
    payload = _create_payload(request.session_code,
                              {
                                    "ClusterNodeTypeAggregationId": mapping_id,
                                    "ProjectId": project_id
                                     })

    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_project_cluster_node_type_aggregation_delete(**payload),
        "Queue Group unassigned successfully!",
        "Failed to unassign Queue Group"
    )

    return redirect("accounting", project_id=project_id)
