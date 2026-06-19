from .imports import *
from django.urls import reverse
from .utils import _create_payload, _handle_api_call, PROTOCOL_CHOICES, SCHEDULER_CHOICES, CONNECTION_PROTOCOL_CHOICES, login_view, login_required, clean_ver

@login_required
def cluster_list(request: HttpRequest) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "bulk_delete":
            selected_ids = request.POST.getlist("selected_ids")
            success_count = 0
            for cid in selected_ids:
                try:
                    payload = _create_payload(request.session_code, {"Id": int(cid)})
                    controller.heappe_management_cluster_delete(**payload)
                    success_count += 1
                except Exception as e:
                    print(f"Error deleting cluster {cid}: {e}")
            if success_count > 0:
                messages.success(request, f"Successfully deleted {success_count} cluster(s).")
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to delete {len(selected_ids) - success_count} cluster(s).")
            return redirect("cluster_list")

    clusters = controller.heappe_management_clusters_get(SessionCode=request.session_code)
    cluster_list = [c.to_dict() for c in clusters]

    for cluster in cluster_list:
        cluster['scheduler_name'] = dict(SCHEDULER_CHOICES).get(cluster['scheduler_type'], "Unknown")
        cluster['connection_protocol_name'] = dict(CONNECTION_PROTOCOL_CHOICES).get(cluster['connection_protocol'], "Unknown")



    return render(request, "clusters.html",
                  {
                            "clusters": cluster_list
                          })


@login_required
def cluster_create(request: HttpRequest) -> HttpResponse:
    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]

    controller = hp.ManagementApi(request.api_instance)

    def get_proxy_list():
        proxy_connections = []
        try:
            pcs = controller.heappe_management_cluster_proxy_connections_get(SessionCode=request.session_code)
            if pcs:
                proxy_connections = pcs
        except Exception as e:
            print(f"Error fetching proxy connections in cluster_create: {e}")

        PROXY_TYPE_NAMES = {1: "SOCKS4", 2: "SOCKS5", 3: "HTTP"}
        proxy_list = []
        for pc in proxy_connections:
            pc_dict = pc.to_dict()
            type_val = pc_dict.get('type')
            try:
                t_int = int(type_val) if type_val is not None else 1
            except (ValueError, TypeError):
                t_int = 1
            pc_dict['type_name'] = PROXY_TYPE_NAMES.get(t_int, "SOCKS4")
            proxy_list.append(pc_dict)
        return proxy_list

    if request.method == "GET":
        return render(request, "cluster_detail.html", {
            'PROTOCOL_CHOICES': PROTOCOL_CHOICES,
            'SCHEDULER_CHOICES': SCHEDULER_CHOICES,
            'CONNECTION_PROTOCOL_CHOICES': CONNECTION_PROTOCOL_CHOICES,
            'proxy_connections': get_proxy_list(),
            'active_tab': 'detail',
            'custom_configuration_json': '{}',
            'is_v6_4_0_plus': is_v6_4_0_plus,
        })
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

        if is_v6_4_0_plus:
            custom_config_raw = request.POST.get("CustomConfiguration", "")
            if custom_config_raw.strip():
                try:
                    custom_config_parsed = json.loads(custom_config_raw)
                    if not isinstance(custom_config_parsed, dict):
                        raise ValueError("Custom configuration must be a JSON object (dictionary)")
                    
                    if payload_data.get("SchedulerType") == 16:
                        expirio_secret = custom_config_parsed.get("ExpirioSecretName", "").strip()
                        idp_url = custom_config_parsed.get("IdpUrl", "").strip()
                        if not expirio_secret and not idp_url:
                            raise ValueError("For FirecREST scheduler, either IdpUrl (for Direct Authentication) or ExpirioSecretName (for Expirio Integration) must be specified.")

                    custom_configuration = {str(k): str(v) for k, v in custom_config_parsed.items()}
                    payload_data["CustomConfiguration"] = custom_configuration
                except Exception as e:
                    messages.error(request, f"Invalid Custom Configuration JSON: {e}")
                    return render(request, "cluster_detail.html", {
                        'PROTOCOL_CHOICES': PROTOCOL_CHOICES,
                        'SCHEDULER_CHOICES': SCHEDULER_CHOICES,
                        'CONNECTION_PROTOCOL_CHOICES': CONNECTION_PROTOCOL_CHOICES,
                        'proxy_connections': get_proxy_list(),
                        'active_tab': 'detail',
                        'cluster': {
                            'name': request.POST.get("Name"),
                            'description': request.POST.get("Description"),
                            'master_node_name': request.POST.get("MasterNodeName"),
                            'scheduler_type': int(request.POST.get("SchedulerType")) if request.POST.get("SchedulerType") else None,
                            'connection_protocol': int(request.POST.get("ConnectionProtocol")) if request.POST.get("ConnectionProtocol") else None,
                            'time_zone': request.POST.get("TimeZone"),
                            'port': int(request.POST.get("Port")) if request.POST.get("Port") else None,
                            'update_job_state_by_service_account': request.POST.get("UpdateJobStateByServiceAccount") == "on",
                            'domain_name': request.POST.get("DomainName"),
                            'proxy_connection': int(request.POST.get("ProxyConnectionId")) if request.POST.get("ProxyConnectionId") else None,
                        },
                        'custom_configuration_json': custom_config_raw,
                        'is_v6_4_0_plus': is_v6_4_0_plus,
                    })
            else:
                if payload_data.get("SchedulerType") == 16:
                    messages.error(request, "Validation Error: For FirecREST scheduler, either IdpUrl (for Direct Authentication) or ExpirioSecretName (for Expirio Integration) must be specified.")
                    return render(request, "cluster_detail.html", {
                        'PROTOCOL_CHOICES': PROTOCOL_CHOICES,
                        'SCHEDULER_CHOICES': SCHEDULER_CHOICES,
                        'CONNECTION_PROTOCOL_CHOICES': CONNECTION_PROTOCOL_CHOICES,
                        'proxy_connections': get_proxy_list(),
                        'active_tab': 'detail',
                        'cluster': {
                            'name': request.POST.get("Name"),
                            'description': request.POST.get("Description"),
                            'master_node_name': request.POST.get("MasterNodeName"),
                            'scheduler_type': 16,
                            'connection_protocol': int(request.POST.get("ConnectionProtocol")) if request.POST.get("ConnectionProtocol") else None,
                            'time_zone': request.POST.get("TimeZone"),
                            'port': int(request.POST.get("Port")) if request.POST.get("Port") else None,
                            'update_job_state_by_service_account': request.POST.get("UpdateJobStateByServiceAccount") == "on",
                            'domain_name': request.POST.get("DomainName"),
                            'proxy_connection': int(request.POST.get("ProxyConnectionId")) if request.POST.get("ProxyConnectionId") else None,
                        },
                        'custom_configuration_json': "{}",
                        'is_v6_4_0_plus': is_v6_4_0_plus,
                    })
                payload_data["CustomConfiguration"] = {}

        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_post(**payload),
            "Cluster created successfully!",
            "Failed to create cluster"
        )
        if result:
            cid = None
            if isinstance(result, dict):
                cid = result.get("Id") or result.get("id")
            elif hasattr(result, "id"):
                cid = result.id
            elif hasattr(result, "Id"):
                cid = result.Id
            
            if cid:
                return redirect("cluster_detail", cluster_id=cid)
        return redirect("cluster_list")

@login_required
def cluster_detail(request: HttpRequest, cluster_id: int, _tab: str = None) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    tab = request.GET.get('tab', 'detail')
    if _tab:
        tab = _tab

    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "edit_filetransfer" or action == "add_filetransfer":
            return create_or_edit_filetransfer_method(request, cluster_id)
        elif action == "delete_filetransfer":
            filetransfer_id = int(request.POST.get("Id"))
            return delete_filetransfer_method(request, cluster_id, filetransfer_id)
        elif action == "add_proxy_connection" or action == "edit_proxy_connection":
            return create_or_edit_proxy_connection(request, cluster_id)
        elif action == "delete_proxy_connection":
            proxy_id = int(request.POST.get("Id"))
            return delete_proxy_connection(request, cluster_id, proxy_id)
        elif action == "bulk_unassign_cluster":
            selected_ids = request.POST.getlist("selected_ids")
            success_count = 0
            for pid in selected_ids:
                try:
                    payload = _create_payload(request.session_code, {
                        "ProjectId": int(pid),
                        "ClusterId": cluster_id
                    })
                    controller.heappe_management_project_assignment_to_cluster_delete(**payload)
                    success_count += 1
                except Exception as e:
                    print(f"Error unassigning project {pid} from cluster {cluster_id}: {e}")
            if success_count > 0:
                messages.success(request, f"Successfully unassigned {success_count} project(s) from cluster.")
            if len(selected_ids) > success_count:
                messages.error(request, f"Failed to unassign {len(selected_ids) - success_count} project(s) from cluster.")
            return redirect(f"{reverse('cluster_detail', kwargs={'cluster_id': cluster_id})}?tab=projects")

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

        if is_v6_4_0_plus:
            custom_config_raw = request.POST.get("CustomConfiguration", "")
            if custom_config_raw.strip():
                try:
                    custom_config_parsed = json.loads(custom_config_raw)
                    if not isinstance(custom_config_parsed, dict):
                        raise ValueError("Custom configuration must be a JSON object (dictionary)")
                    
                    if payload_data.get("SchedulerType") == 16:
                        expirio_secret = custom_config_parsed.get("ExpirioSecretName", "").strip()
                        idp_url = custom_config_parsed.get("IdpUrl", "").strip()
                        if not expirio_secret and not idp_url:
                            raise ValueError("For FirecREST scheduler, either IdpUrl (for Direct Authentication) or ExpirioSecretName (for Expirio Integration) must be specified.")

                    custom_configuration = {str(k): str(v) for k, v in custom_config_parsed.items()}
                    payload_data["CustomConfiguration"] = custom_configuration
                except Exception as e:
                    messages.error(request, f"Invalid Custom Configuration JSON: {e}")
                    request.session['invalid_custom_config'] = custom_config_raw
                    return redirect("cluster_detail", cluster_id=cluster_id)
            else:
                if payload_data.get("SchedulerType") == 16:
                    messages.error(request, "Validation Error: For FirecREST scheduler, either IdpUrl (for Direct Authentication) or ExpirioSecretName (for Expirio Integration) must be specified.")
                    request.session['invalid_custom_config'] = "{}"
                    return redirect("cluster_detail", cluster_id=cluster_id)
                payload_data["CustomConfiguration"] = {}

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
    
    proxy_connections = []
    try:
        pcs = controller.heappe_management_cluster_proxy_connections_get(SessionCode=request.session_code)
        if pcs:
            proxy_connections = pcs
    except Exception as e:
        print(f"Error fetching proxy connections in cluster_detail: {e}")

    PROXY_TYPE_NAMES = {1: "SOCKS4", 2: "SOCKS5", 3: "HTTP"}
    proxy_list = []
    for pc in proxy_connections:
        pc_dict = pc.to_dict()
        type_val = pc_dict.get('type')
        try:
            t_int = int(type_val) if type_val is not None else 1
        except (ValueError, TypeError):
            t_int = 1
        pc_dict['type_name'] = PROXY_TYPE_NAMES.get(t_int, "SOCKS4")
        proxy_list.append(pc_dict)

    cluster_dict = cluster.to_dict()
    custom_config_json = request.session.pop('invalid_custom_config', None)
    if custom_config_json is None:
        if 'custom_configuration' in cluster_dict:
            custom_config = cluster_dict.get('custom_configuration') or {}
            custom_config_json = json.dumps(custom_config, indent=4)
        else:
            custom_config_json = '{}'

    context = {
        'cluster': cluster_dict,
        'active_tab': tab,
        'proxy_connections': proxy_list,
        'custom_configuration_json': custom_config_json,
        'is_v6_4_0_plus': is_v6_4_0_plus,
    }
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
        all_projects = controller.heappe_management_projects_get(SessionCode=request.session_code) or []
        seen_ids = {p['id'] for p in context['projects']}
        context['projectsForCurrentUser'] = [
            p for p in all_projects
            if p.id not in seen_ids
        ]
        context['queues'] = cluster.to_dict()['node_types']

    return render(request, "cluster_detail.html", context)

@login_required
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

@login_required
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

@login_required
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


@login_required
def create_or_edit_proxy_connection(request: HttpRequest, cluster_id: int) -> HttpResponse:
    host = request.POST.get("Host")
    port = int(request.POST.get("Port")) if request.POST.get("Port") else None
    type_val = int(request.POST.get("Type")) if request.POST.get("Type") else None
    username = request.POST.get("Username") or None
    password = request.POST.get("Password") or None
    id_val = int(request.POST.get("Id")) if request.POST.get("Id") else None

    controller = hp.ManagementApi(request.api_instance)
    if id_val:
        from py4heappe.heappe_v6.core import ModifyClusterProxyConnectionModel
        body = ModifyClusterProxyConnectionModel(
            session_code=request.session_code,
            id=id_val,
            host=host,
            port=port,
            type=type_val,
            username=username,
            password=password
        )
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_proxy_connection_put(body=body),
            "Proxy connection updated successfully!",
            "Failed to update proxy connection"
        )
    else:
        from py4heappe.heappe_v6.core import CreateClusterProxyConnectionModel
        body = CreateClusterProxyConnectionModel(
            session_code=request.session_code,
            host=host,
            port=port,
            type=type_val,
            username=username,
            password=password
        )
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_proxy_connection_post(body=body),
            "Proxy connection created successfully!",
            "Failed to create proxy connection"
        )
        if result and result != []:
            new_proxy_id = None
            if isinstance(result, dict):
                new_proxy_id = result.get("Id") or result.get("id")
            else:
                new_proxy_id = getattr(result, "id", None) or getattr(result, "Id", None)

            if new_proxy_id:
                try:
                    cluster = controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=request.session_code)
                    if not getattr(cluster, "proxy_connection", None):
                        payload_data = {
                            "Name": getattr(cluster, "name", None),
                            "Description": getattr(cluster, "description", None),
                            "MasterNodeName": getattr(cluster, "master_node_name", None),
                            "SchedulerType": getattr(cluster, "scheduler_type", None),
                            "ConnectionProtocol": getattr(cluster, "connection_protocol", None),
                            "TimeZone": getattr(cluster, "time_zone", None),
                            "Port": getattr(cluster, "port", None),
                            "UpdateJobStateByServiceAccount": getattr(cluster, "update_job_state_by_service_account", False),
                            "DomainName": getattr(cluster, "domain_name", None),
                            "ProxyConnectionId": new_proxy_id,
                        }
                        payload = _create_payload(request.session_code, payload_data)
                        payload["body"]["Id"] = cluster_id
                        controller.heappe_management_cluster_put(**payload)
                        messages.success(request, f"Automatically assigned new proxy connection to cluster.")
                except Exception as e:
                    print(f"Error auto-assigning proxy connection to cluster {cluster_id}: {e}")
    return redirect(f"{reverse('cluster_detail', kwargs={'cluster_id': cluster_id})}?tab=proxy_connections")


@login_required
def delete_proxy_connection(request: HttpRequest, cluster_id: int, proxy_id: int) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)
    from py4heappe.heappe_v6.core import RemoveClusterProxyConnectionModel
    body = RemoveClusterProxyConnectionModel(
        session_code=request.session_code,
        id=proxy_id
    )
    result = _handle_api_call(
        request,
        lambda: controller.heappe_management_cluster_proxy_connection_delete(body=body),
        "Proxy connection deleted successfully!",
        "Failed to delete proxy connection"
    )
    return redirect(f"{reverse('cluster_detail', kwargs={'cluster_id': cluster_id})}?tab=proxy_connections")


