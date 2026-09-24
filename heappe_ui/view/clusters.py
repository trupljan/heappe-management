from .imports import *
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_exempt
from .utils import _create_payload, _handle_api_call, PROTOCOL_CHOICES, SCHEDULER_CHOICES, CONNECTION_PROTOCOL_CHOICES, login_view, login_required, clean_ver

FALLBACK_CUSTOM_CONFIG_METADATA = [
    {
        "Id": 1, "Name": "CallbackUrl", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}, {"Id": 32, "Name": "QScheduler"}
        ]
    },
    {
        "Id": 2, "Name": "ClientId", "DefaultValue": "",
        "SupportedSchedulerTypes": [{"Id": 16, "Name": "FirecRestSlurm"}]
    },
    {
        "Id": 3, "Name": "ClientSecret", "DefaultValue": "",
        "SupportedSchedulerTypes": [{"Id": 16, "Name": "FirecRestSlurm"}]
    },
    {
        "Id": 4, "Name": "ClusterName", "DefaultValue": "",
        "SupportedSchedulerTypes": [{"Id": 16, "Name": "FirecRestSlurm"}]
    },
    {
        "Id": 5, "Name": "ClusterScriptsRepository", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 6, "Name": "ClusterScriptsRepositoryBranch", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 8, "Name": "EnableCallback", "DefaultValue": "false",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}, {"Id": 32, "Name": "QScheduler"}
        ]
    },
    {
        "Id": 9, "Name": "EnableGracefulTimeout", "DefaultValue": "false",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 10, "Name": "EventualConsistencyRetryCount", "DefaultValue": "5",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 11, "Name": "EventualConsistencyRetryDelayMs", "DefaultValue": "1000",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 12, "Name": "FirecrestUrl", "DefaultValue": "",
        "SupportedSchedulerTypes": [{"Id": 16, "Name": "FirecRestSlurm"}]
    },
    {
        "Id": 13, "Name": "GracefulTimeoutSeconds", "DefaultValue": "30",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 14, "Name": "IdpUrl", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 15, "Name": "InstanceIdentifierPath", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 16, "Name": "JobLogArchiveSubPath", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 17, "Name": "KeyScriptsDirectoryInRepository", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 19, "Name": "ScriptsBasePath", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 20, "Name": "SshCommandPrefix", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}
        ]
    },
    {
        "Id": 21, "Name": "SubExecutionsPath", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 22, "Name": "SubScriptsPath", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 23, "Name": "SyncScriptsViaSftp", "DefaultValue": "false",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}
        ]
    },
    {
        "Id": 24, "Name": "QSchedulerPort", "DefaultValue": "3000",
        "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]
    },
    {
        "Id": 25, "Name": "QSchedulerHost", "DefaultValue": "localhost",
        "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]
    },
    {
        "Id": 26, "Name": "ClusterCallbackNotifyToken", "DefaultValue": "",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}, {"Id": 32, "Name": "QScheduler"}
        ]
    },
    {
        "Id": 27, "Name": "QSchedulerUseSessions", "DefaultValue": "true",
        "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]
    },
    {
        "Id": 28, "Name": "HomeDirectoryTemplate", "DefaultValue": "/users/{username}",
        "SupportedSchedulerTypes": [
            {"Id": 1, "Name": "LinuxLocal"}, {"Id": 2, "Name": "PbsPro"}, {"Id": 4, "Name": "Slurm"},
            {"Id": 8, "Name": "HyperQueue"}, {"Id": 16, "Name": "FirecRestSlurm"}
        ]
    },
    {
        "Id": 29, "Name": "ExpirioSecretName", "DefaultValue": "",
        "SupportedSchedulerTypes": [{"Id": 16, "Name": "FirecRestSlurm"}]
    }
]

def fetch_cluster_custom_config_metadata(request) -> list:
    """
    Fetches custom configuration keys dictionary metadata from HEAppE API endpoint:
    GET /heappe/Dictionary/GetClusterCustomConfigurationKeys
    """
    try:
        if hasattr(request, 'api_instance') and request.api_instance:
            data = request.api_instance.call_api(
                '/heappe/Dictionary/GetClusterCustomConfigurationKeys',
                'GET',
                auth_settings=['Bearer', 'ServiceApiKey'],
                response_type='list[object]'
            )
            if data and isinstance(data, list):
                normalized = []
                for item in data:
                    if isinstance(item, dict):
                        d = item
                    elif hasattr(item, 'to_dict'):
                        d = item.to_dict()
                    else:
                        d = getattr(item, '__dict__', {})
                    
                    name = d.get('Name') or d.get('name')
                    if name:
                        scheds = d.get('SupportedSchedulerTypes') or d.get('supportedSchedulerTypes') or []
                        norm_scheds = []
                        for s in scheds:
                            if isinstance(s, dict):
                                s_id = s.get('Id') if s.get('Id') is not None else s.get('id')
                                s_name = s.get('Name') or s.get('name')
                            else:
                                s_id = getattr(s, 'id', getattr(s, 'Id', None))
                                s_name = getattr(s, 'name', getattr(s, 'Name', None))
                            if s_id is not None:
                                norm_scheds.append({'Id': int(s_id), 'Name': str(s_name or '')})
                        
                        normalized.append({
                            'Id': d.get('Id') or d.get('id'),
                            'Name': str(name),
                            'DefaultValue': str(d.get('DefaultValue') or d.get('defaultValue') or ''),
                            'SupportedSchedulerTypes': norm_scheds
                        })
                if normalized:
                    existing_names = {x['Name'] for x in normalized}
                    for fb in FALLBACK_CUSTOM_CONFIG_METADATA:
                        if fb['Name'] not in existing_names:
                            normalized.append(fb)
                    return normalized
    except Exception as e:
        print(f"[clusters] Error fetching GetClusterCustomConfigurationKeys: {e}")

    return FALLBACK_CUSTOM_CONFIG_METADATA

def validate_and_clean_custom_config(custom_config: dict, scheduler_type: int, metadata_list: list, old_config: dict = None) -> dict:
    """
    Validates custom config against metadata supportedSchedulerTypes for the given scheduler_type.
    Also preserves Vault masked values ("********") and normalizes/cleans boolean configuration values.
    """
    meta_map = {}
    default_map = {}
    for meta in (metadata_list or []):
        name = meta.get('Name')
        if name:
            sched_ids = [s.get('Id') for s in (meta.get('SupportedSchedulerTypes') or []) if s.get('Id') is not None]
            meta_map[name] = sched_ids
            default_map[name] = str(meta.get('DefaultValue') if meta.get('DefaultValue') is not None else '')

    KNOWN_BOOLEAN_KEYS = {
        "EnableCallback",
        "EnableGracefulTimeout",
        "SyncScriptsViaSftp",
        "QSchedulerUseSessions",
        "CheckCommandTemplatePermissions",
        "UseBearerAuth",
        "UseExpirioServiceForTokenExchange"
    }

    cleaned = {}
    for key, val in custom_config.items():
        val_str = str(val) if val is not None else ""
        
        # Vault mask check ("********")
        if val_str == "********" and old_config and key in old_config:
            val_str = str(old_config[key])
        
        # Boolean normalization / cleaning:
        default_val = default_map.get(key, "").lower()
        is_boolean_key = (
            key in KNOWN_BOOLEAN_KEYS or
            default_val in ("true", "false") or
            key.startswith("Enable") or
            key.startswith("Is") or
            key.startswith("Use")
        )

        if is_boolean_key:
            v_lower = val_str.strip().lower()
            if v_lower in ("true", "1", "yes", "on"):
                val_str = "true"
            elif v_lower in ("false", "0", "no", "off"):
                val_str = "false"
            elif v_lower == "":
                val_str = default_val if default_val in ("true", "false") else "false"
            else:
                val_str = default_val if default_val in ("true", "false") else "false"

        cleaned[key] = val_str

    return cleaned

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
    is_v6_5_0_plus = clean_ver(deployed_version) >= [6, 5, 0]

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
        custom_config_metadata = fetch_cluster_custom_config_metadata(request)
        return render(request, "cluster_detail.html", {
            'PROTOCOL_CHOICES': PROTOCOL_CHOICES,
            'SCHEDULER_CHOICES': SCHEDULER_CHOICES,
            'CONNECTION_PROTOCOL_CHOICES': CONNECTION_PROTOCOL_CHOICES,
            'proxy_connections': get_proxy_list(),
            'active_tab': 'detail',
            'custom_configuration_json': '{}',
            'custom_configuration_vault_toggles_json': '{}',
            'custom_config_metadata_json': json.dumps(custom_config_metadata),
            'is_v6_4_0_plus': is_v6_4_0_plus,
            'is_v6_5_0_plus': is_v6_5_0_plus,
        })
    if request.method == "POST":
        custom_config_metadata = fetch_cluster_custom_config_metadata(request)
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
            custom_vault_raw = request.POST.get("CustomConfigurationVaultToggles", "")

            if is_v6_5_0_plus:
                custom_vault_parsed = {}
                if custom_vault_raw.strip():
                    try:
                        custom_vault_parsed = json.loads(custom_vault_raw)
                        if not isinstance(custom_vault_parsed, dict):
                            raise ValueError("Custom configuration vault toggles must be a JSON object (dictionary)")
                        payload_data["CustomConfigurationVaultToggles"] = {str(k): bool(v) for k, v in custom_vault_parsed.items()}
                    except Exception as e:
                        messages.error(request, f"Invalid Custom Configuration Vault Toggles JSON: {e}")
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
                            'custom_configuration_vault_toggles_json': custom_vault_raw,
                            'custom_config_metadata_json': json.dumps(custom_config_metadata),
                            'is_v6_4_0_plus': is_v6_4_0_plus,
                            'is_v6_5_0_plus': is_v6_5_0_plus,
                        })
                else:
                    payload_data["CustomConfigurationVaultToggles"] = {}

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
                        home_dir = custom_config_parsed.get("HomeDirectoryTemplate", "").strip()
                        if not home_dir:
                            raise ValueError("For FirecREST scheduler, HomeDirectoryTemplate must be specified.")
                    
                    if payload_data.get("SchedulerType") == 32:
                        qs_port_str = custom_config_parsed.get("QSchedulerPort", "").strip()
                        if not qs_port_str:
                            qs_port_str = "3000"
                        try:
                            qs_port = int(qs_port_str)
                            if not (1 <= qs_port <= 65535):
                                raise ValueError()
                        except ValueError:
                            raise ValueError("For QScheduler, QSchedulerPort must be a valid integer port number (1-65535).")
                        custom_config_parsed["QSchedulerPort"] = str(qs_port)
                        
                        if is_v6_5_0_plus:
                            use_sessions = custom_config_parsed.get("QSchedulerUseSessions", "true").strip()
                            if use_sessions not in ("true", "false"):
                                use_sessions = "true"
                            custom_config_parsed["QSchedulerUseSessions"] = use_sessions

                    custom_configuration = validate_and_clean_custom_config(
                        custom_config_parsed,
                        payload_data.get("SchedulerType"),
                        custom_config_metadata
                    )
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
                        'custom_configuration_vault_toggles_json': custom_vault_raw,
                        'custom_config_metadata_json': json.dumps(custom_config_metadata),
                        'is_v6_4_0_plus': is_v6_4_0_plus,
                        'is_v6_5_0_plus': is_v6_5_0_plus,
                    })
            else:
                if payload_data.get("SchedulerType") == 16:
                    messages.error(request, "Validation Error: For FirecREST scheduler, IdpUrl/ExpirioSecretName and HomeDirectoryTemplate must be specified.")
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
                        'custom_configuration_vault_toggles_json': custom_vault_raw,
                        'custom_config_metadata_json': json.dumps(custom_config_metadata),
                        'is_v6_4_0_plus': is_v6_4_0_plus,
                        'is_v6_5_0_plus': is_v6_5_0_plus,
                    })
                elif payload_data.get("SchedulerType") == 32:
                    if is_v6_5_0_plus:
                        payload_data["CustomConfiguration"] = {"QSchedulerPort": "3000", "QSchedulerUseSessions": "true"}
                        payload_data["CustomConfigurationVaultToggles"] = {}
                    else:
                        payload_data["CustomConfiguration"] = {"QSchedulerPort": "3000"}
                else:
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
    is_v6_5_0_plus = clean_ver(deployed_version) >= [6, 5, 0]

    custom_config_metadata = fetch_cluster_custom_config_metadata(request)

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

        # Fetch existing cluster configuration to preserve Vault secrets ("********")
        old_config = {}
        try:
            old_cluster = controller.heappe_management_cluster_get(Id=cluster_id, SessionCode=request.session_code)
            if old_cluster:
                old_cluster_dict = old_cluster.to_dict()
                old_config = old_cluster_dict.get('custom_configuration') or {}
        except Exception:
            pass

        if is_v6_4_0_plus:
            custom_config_raw = request.POST.get("CustomConfiguration", "")
            custom_vault_raw = request.POST.get("CustomConfigurationVaultToggles", "")

            if is_v6_5_0_plus:
                custom_vault_parsed = {}
                if custom_vault_raw.strip():
                    try:
                        custom_vault_parsed = json.loads(custom_vault_raw)
                        if not isinstance(custom_vault_parsed, dict):
                            raise ValueError("Custom configuration vault toggles must be a JSON object (dictionary)")
                        payload_data["CustomConfigurationVaultToggles"] = {str(k): bool(v) for k, v in custom_vault_parsed.items()}
                    except Exception as e:
                        messages.error(request, f"Invalid Custom Configuration Vault Toggles JSON: {e}")
                        request.session['invalid_custom_config'] = custom_config_raw
                        request.session['invalid_custom_config_vault_toggles'] = custom_vault_raw
                        return redirect("cluster_detail", cluster_id=cluster_id)
                else:
                    payload_data["CustomConfigurationVaultToggles"] = {}

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
                        home_dir = custom_config_parsed.get("HomeDirectoryTemplate", "").strip()
                        if not home_dir:
                            raise ValueError("For FirecREST scheduler, HomeDirectoryTemplate must be specified.")
                    
                    if payload_data.get("SchedulerType") == 32:
                        qs_port_str = custom_config_parsed.get("QSchedulerPort", "").strip()
                        if not qs_port_str:
                            qs_port_str = "3000"
                        try:
                            qs_port = int(qs_port_str)
                            if not (1 <= qs_port <= 65535):
                                raise ValueError()
                        except ValueError:
                            raise ValueError("For QScheduler, QSchedulerPort must be a valid integer port number (1-65535).")
                        custom_config_parsed["QSchedulerPort"] = str(qs_port)
                        
                        if is_v6_5_0_plus:
                            use_sessions = custom_config_parsed.get("QSchedulerUseSessions", "true").strip()
                            if use_sessions not in ("true", "false"):
                                use_sessions = "true"
                            custom_config_parsed["QSchedulerUseSessions"] = use_sessions

                    custom_configuration = validate_and_clean_custom_config(
                        custom_config_parsed,
                        payload_data.get("SchedulerType"),
                        custom_config_metadata,
                        old_config=old_config
                    )
                    payload_data["CustomConfiguration"] = custom_configuration
                except Exception as e:
                    messages.error(request, f"Invalid Custom Configuration JSON: {e}")
                    request.session['invalid_custom_config'] = custom_config_raw
                    request.session['invalid_custom_config_vault_toggles'] = custom_vault_raw
                    return redirect("cluster_detail", cluster_id=cluster_id)
            else:
                if payload_data.get("SchedulerType") == 16:
                    messages.error(request, "Validation Error: For FirecREST scheduler, IdpUrl/ExpirioSecretName and HomeDirectoryTemplate must be specified.")
                    request.session['invalid_custom_config'] = "{}"
                    request.session['invalid_custom_config_vault_toggles'] = custom_vault_raw
                    return redirect("cluster_detail", cluster_id=cluster_id)
                elif payload_data.get("SchedulerType") == 32:
                    if is_v6_5_0_plus:
                        payload_data["CustomConfiguration"] = {"QSchedulerPort": "3000", "QSchedulerUseSessions": "true"}
                        payload_data["CustomConfigurationVaultToggles"] = {}
                    else:
                        payload_data["CustomConfiguration"] = {"QSchedulerPort": "3000"}
                else:
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
    # Retrieve raw cluster data to extract CustomConfigurationVaultToggles, which is discarded by the Swagger model
    try:
        raw_resp = controller.heappe_management_cluster_get(
            Id=cluster_id, SessionCode=request.session_code, _preload_content=False
        )
        if raw_resp and hasattr(raw_resp, 'data') and isinstance(raw_resp.data, (bytes, str)):
            raw_data_str = raw_resp.data.decode('utf-8') if isinstance(raw_resp.data, bytes) else raw_resp.data
            raw_data = json.loads(raw_data_str)
            vault_toggles = raw_data.get('CustomConfigurationVaultToggles') or raw_data.get('custom_configuration_vault_toggles') or {}
            cluster_dict['custom_configuration_vault_toggles'] = vault_toggles
    except Exception as e:
        print(f"Error fetching raw cluster details for Vault Toggles: {e}")

    custom_config_json = request.session.pop('invalid_custom_config', None)
    if custom_config_json is None:
        if 'custom_configuration' in cluster_dict:
            custom_config = cluster_dict.get('custom_configuration') or {}
            custom_config_json = json.dumps(custom_config, indent=4)
        else:
            custom_config_json = '{}'

    custom_vault_toggles_json = request.session.pop('invalid_custom_config_vault_toggles', None)
    if custom_vault_toggles_json is None:
        if 'custom_configuration_vault_toggles' in cluster_dict:
            custom_vault_toggles = cluster_dict.get('custom_configuration_vault_toggles') or {}
            custom_vault_toggles_json = json.dumps(custom_vault_toggles, indent=4)
        else:
            custom_vault_toggles_json = '{}'

    from .project import PREFERRED_AUTH_TYPES_NO_PROXY, PREFERRED_AUTH_TYPES_WITH_PROXY, PREFERRED_AUTH_TYPE_CHOICES

    context = {
        'cluster': cluster_dict,
        'active_tab': tab,
        'proxy_connections': proxy_list,
        'custom_configuration_json': custom_config_json,
        'custom_configuration_vault_toggles_json': custom_vault_toggles_json,
        'custom_config_metadata_json': json.dumps(custom_config_metadata),
        'is_v6_4_0_plus': is_v6_4_0_plus,
        'is_v6_5_0_plus': is_v6_5_0_plus,
        'preferred_auth_types_no_proxy': PREFERRED_AUTH_TYPES_NO_PROXY,
        'preferred_auth_types_with_proxy': PREFERRED_AUTH_TYPES_WITH_PROXY,
        'preferred_auth_type_choices': PREFERRED_AUTH_TYPE_CHOICES,
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
def cluster_export(request: HttpRequest, cluster_id: int) -> HttpResponse:
    """Export cluster configuration (without projects) as a JSON migration file."""
    import json as _json
    from datetime import datetime, timezone

    controller = hp.ManagementApi(request.api_instance)

    try:
        cluster = controller.heappe_management_cluster_get(
            Id=cluster_id, SessionCode=request.session_code
        )
        cluster_dict = cluster.to_dict()
    except Exception as e:
        messages.error(request, f"Failed to fetch cluster: {e}")
        return redirect("cluster_detail", cluster_id=cluster_id)

    # ── File transfer methods for this cluster ──────────────────────────────
    try:
        all_ftm = controller.heappe_management_file_transfer_methods_get(
            SessionCode=request.session_code
        ) or []
        cluster_ftm = [f.to_dict() for f in all_ftm if f.cluster_id == cluster_id]
    except Exception:
        cluster_ftm = []

    # Build FTM list (no ids, no cluster_id) and an id→ref lookup
    ftm_ref_map = {}  # ftm_id → "_ref" string
    ftm_export = []
    for idx, ftm in enumerate(cluster_ftm):
        ref = f"ftm_{idx}"
        ftm_ref_map[ftm["id"]] = ref
        ftm_export.append({
            "_ref": ref,
            "server_hostname": ftm.get("server_hostname"),
            "port": ftm.get("port"),
            "protocol": ftm.get("protocol"),
        })

    # ── Node types (queues) for this cluster ────────────────────────────────
    node_types = cluster_dict.get("node_types") or []

    # Collect aggregation ids referenced by any queue in this cluster
    used_agg_ids = set()
    for nt in node_types:
        agg = nt.get("cluster_node_type_aggregation")
        if agg:
            agg_id = agg.get("id") if isinstance(agg, dict) else getattr(agg, "id", None)
            if agg_id:
                used_agg_ids.add(agg_id)

    # ── Queue groups (aggregations) used by this cluster ────────────────────
    agg_ref_map = {}  # agg_id → "_ref" string
    agg_export = []
    if used_agg_ids:
        try:
            all_aggs = controller.heappe_management_cluster_node_type_aggregations_get(
                SessionCode=request.session_code
            ) or []
            for idx, agg in enumerate(all_aggs):
                agg_d = agg.to_dict() if hasattr(agg, "to_dict") else agg
                if agg_d.get("id") in used_agg_ids:
                    ref = f"qg_{len(agg_export)}"
                    agg_ref_map[agg_d["id"]] = ref
                    validity_from = agg_d.get("validity_from")
                    validity_to = agg_d.get("validity_to")
                    agg_export.append({
                        "_ref": ref,
                        "name": agg_d.get("name"),
                        "description": agg_d.get("description"),
                        "allocation_type": agg_d.get("allocation_type"),
                        "validity_from": validity_from.isoformat() if hasattr(validity_from, "isoformat") else validity_from,
                        "validity_to": validity_to.isoformat() if hasattr(validity_to, "isoformat") else validity_to,
                    })
        except Exception:
            pass

    # ── Queues export ────────────────────────────────────────────────────────
    queues_export = []
    for nt in node_types:
        agg = nt.get("cluster_node_type_aggregation")
        agg_id = None
        if agg:
            agg_id = agg.get("id") if isinstance(agg, dict) else getattr(agg, "id", None)

        queues_export.append({
            "name": nt.get("name"),
            "description": nt.get("description"),
            "number_of_nodes": nt.get("number_of_nodes"),
            "cores_per_node": nt.get("cores_per_node"),
            "queue": nt.get("queue"),
            "quality_of_service": nt.get("quality_of_service"),
            "max_walltime": nt.get("max_walltime"),
            "cluster_allocation_name": nt.get("cluster_allocation_name"),
            "file_transfer_method_ref": ftm_ref_map.get(nt.get("file_transfer_method_id")),
            "queue_group_ref": agg_ref_map.get(agg_id) if agg_id else None,
        })

    # ── Cluster settings (no id, no node_types, no projects) ─────────────────
    custom_cfg = cluster_dict.get("custom_configuration") or {}
    custom_vault = cluster_dict.get("custom_configuration_vault_toggles") or {}

    export_data = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_cluster_id": cluster_id,
        "cluster": {
            "name": cluster_dict.get("name"),
            "description": cluster_dict.get("description"),
            "master_node_name": cluster_dict.get("master_node_name"),
            "scheduler_type": cluster_dict.get("scheduler_type"),
            "connection_protocol": cluster_dict.get("connection_protocol"),
            "time_zone": cluster_dict.get("time_zone"),
            "port": cluster_dict.get("port"),
            "update_job_state_by_service_account": cluster_dict.get("update_job_state_by_service_account", False),
            "domain_name": cluster_dict.get("domain_name"),
            "custom_configuration": custom_cfg,
            "custom_configuration_vault_toggles": custom_vault,
        },
        "file_transfer_methods": ftm_export,
        "queue_groups": agg_export,
        "queues": queues_export,
    }

    cluster_name_safe = (cluster_dict.get("name") or f"cluster_{cluster_id}").replace(" ", "_")
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"cluster_{cluster_name_safe}_{date_str}.json"

    response = HttpResponse(
        _json.dumps(export_data, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response



@login_required
def cluster_import(request: HttpRequest) -> HttpResponse:
    """Import cluster configuration from a JSON file."""
    if request.method != "POST":
        return redirect("cluster_list")

    uploaded_file = request.FILES.get("config_file")
    if not uploaded_file:
        messages.error(request, "No configuration file uploaded.")
        return redirect("cluster_list")

    import json as _json
    try:
        data = _json.loads(uploaded_file.read().decode("utf-8"))
    except Exception as e:
        messages.error(request, f"Failed to parse JSON file: {e}")
        return redirect("cluster_list")

    # Basic structure validation
    if "version" not in data or "cluster" not in data:
        messages.error(request, "Invalid configuration file format. Missing 'version' or 'cluster' key.")
        return redirect("cluster_list")

    controller = hp.ManagementApi(request.api_instance)
    
    # Check version compatibility
    deployed_version = request.session.get("middleware_deployed_version", "")
    is_v6_4_0_plus = clean_ver(deployed_version) >= [6, 4, 0]
    is_v6_5_0_plus = clean_ver(deployed_version) >= [6, 5, 0]

    # Create the cluster
    cluster_data = data["cluster"]
    payload_data = {
        "Name": cluster_data.get("name"),
        "Description": cluster_data.get("description"),
        "MasterNodeName": cluster_data.get("master_node_name"),
        "SchedulerType": cluster_data.get("scheduler_type"),
        "ConnectionProtocol": cluster_data.get("connection_protocol"),
        "TimeZone": cluster_data.get("time_zone"),
        "Port": cluster_data.get("port"),
        "UpdateJobStateByServiceAccount": cluster_data.get("update_job_state_by_service_account", False),
        "DomainName": cluster_data.get("domain_name"),
    }
    
    if is_v6_4_0_plus and "custom_configuration" in cluster_data:
        payload_data["CustomConfiguration"] = cluster_data["custom_configuration"]
    if is_v6_5_0_plus and "custom_configuration_vault_toggles" in cluster_data:
        payload_data["CustomConfigurationVaultToggles"] = cluster_data["custom_configuration_vault_toggles"]

    try:
        # Create cluster
        payload = _create_payload(request.session_code, payload_data)
        new_cluster = _handle_api_call(
            request,
            lambda: controller.heappe_management_cluster_post(**payload),
            None,
            "Failed to create cluster",
            silent=True
        )
        if not new_cluster or new_cluster == []:
            raise ValueError("API call failed to return cluster data.")
            
        new_cluster_dict = new_cluster.to_dict() if hasattr(new_cluster, "to_dict") else new_cluster
        
        # Determine the new cluster ID
        if isinstance(new_cluster_dict, dict):
            new_cluster_id = new_cluster_dict.get("Id") or new_cluster_dict.get("id")
        else:
            new_cluster_id = getattr(new_cluster, "id", None) or getattr(new_cluster, "Id", None) or new_cluster
            
        if not new_cluster_id:
            raise ValueError("Failed to obtain ID of the newly created cluster.")
    except Exception as e:
        messages.error(request, f"Failed to create cluster: {e}")
        return redirect("cluster_list")

    # ── Import File Transfer Methods ─────────────────────────────────────────
    ftm_ref_map = {} # old _ref -> new id
    ftms = data.get("file_transfer_methods") or []
    for ftm in ftms:
        ftm_payload_data = {
            "ClusterId": new_cluster_id,
            "ServerHostname": ftm.get("server_hostname"),
            "Port": ftm.get("port"),
            "Protocol": ftm.get("protocol"),
        }
        try:
            ftm_payload = _create_payload(request.session_code, ftm_payload_data)
            new_ftm = _handle_api_call(
                request,
                lambda: controller.heappe_management_file_transfer_method_post(**ftm_payload),
                None,
                "Failed to import file transfer method",
                silent=True
            )
            if not new_ftm or new_ftm == []:
                raise ValueError("API call failed to return file transfer method data.")
                
            new_ftm_dict = new_ftm.to_dict() if hasattr(new_ftm, "to_dict") else new_ftm
            if isinstance(new_ftm_dict, dict):
                new_ftm_id = new_ftm_dict.get("Id") or new_ftm_dict.get("id")
            else:
                new_ftm_id = getattr(new_ftm, "id", None) or getattr(new_ftm, "Id", None) or new_ftm
            
            if new_ftm_id and "_ref" in ftm:
                ftm_ref_map[ftm["_ref"]] = new_ftm_id
        except Exception as e:
            messages.warning(request, f"Failed to import file transfer method '{ftm.get('server_hostname')}': {e}")

    # ── Import Queue Groups (ClusterNodeTypeAggregation) ─────────────────────
    agg_ref_map = {} # old _ref -> new id
    queue_groups = data.get("queue_groups") or []
    
    # Fetch existing aggregations to avoid duplicating by name
    existing_aggs = {}
    try:
        all_existing_aggs = controller.heappe_management_cluster_node_type_aggregations_get(SessionCode=request.session_code) or []
        for agg in all_existing_aggs:
            agg_d = agg.to_dict() if hasattr(agg, "to_dict") else agg
            if agg_d.get("name"):
                existing_aggs[agg_d["name"]] = agg_d["id"]
    except Exception:
        pass

    for qg in queue_groups:
        qg_name = qg.get("name")
        if qg_name in existing_aggs:
            # Re-use existing queue group
            agg_ref_map[qg["_ref"]] = existing_aggs[qg_name]
            continue
            
        qg_payload_data = {
            "Name": qg_name,
            "Description": qg.get("description"),
            "AllocationType": qg.get("allocation_type"),
        }
        
        # Parse ISO datetimes
        from .utils import _parse_datetime_local
        validity_from = qg.get("validity_from")
        validity_to = qg.get("validity_to")
        if validity_from:
            qg_payload_data["ValidityFrom"] = _parse_datetime_local(validity_from)
        if validity_to:
            qg_payload_data["ValidityTo"] = _parse_datetime_local(validity_to)

        try:
            qg_payload = _create_payload(request.session_code, qg_payload_data)
            new_qg = _handle_api_call(
                request,
                lambda: controller.heappe_management_cluster_node_type_aggregation_post(**qg_payload),
                None,
                "Failed to import queue group",
                silent=True
            )
            if not new_qg or new_qg == []:
                raise ValueError("API call failed to return queue group data.")
                
            new_qg_dict = new_qg.to_dict() if hasattr(new_qg, "to_dict") else new_qg
            if isinstance(new_qg_dict, dict):
                new_qg_id = new_qg_dict.get("Id") or new_qg_dict.get("id")
            else:
                new_qg_id = getattr(new_qg, "id", None) or getattr(new_qg, "Id", None) or new_qg
                
            if new_qg_id:
                agg_ref_map[qg["_ref"]] = new_qg_id
        except Exception as e:
            messages.warning(request, f"Failed to import queue group '{qg_name}': {e}")

    # ── Import Queues (ClusterNodeType) ──────────────────────────────────────
    queues = data.get("queues") or []
    for q in queues:
        ftm_id = ftm_ref_map.get(q.get("file_transfer_method_ref"))
        qg_id = agg_ref_map.get(q.get("queue_group_ref"))
        
        q_payload_data = {
            "ClusterId": new_cluster_id,
            "Name": q.get("name"),
            "Description": q.get("description"),
            "NumberOfNodes": q.get("number_of_nodes"),
            "CoresPerNode": q.get("cores_per_node"),
            "Queue": q.get("queue"),
            "QualityOfService": q.get("quality_of_service"),
            "MaxWalltime": q.get("max_walltime"),
            "ClusterAllocationName": q.get("cluster_allocation_name"),
            "FileTransferMethodId": ftm_id,
            "ClusterNodeTypeAggregationId": qg_id,
        }
        try:
            q_payload = _create_payload(request.session_code, q_payload_data)
            new_q = _handle_api_call(
                request,
                lambda: controller.heappe_management_cluster_node_type_post(**q_payload),
                None,
                "Failed to import queue",
                silent=True
            )
            if not new_q or new_q == []:
                raise ValueError("API call failed to return queue data.")
        except Exception as e:
            messages.warning(request, f"Failed to import queue '{q.get('name')}': {e}")

    messages.success(request, f"Cluster '{payload_data['Name']}' successfully imported!")
    return redirect("cluster_detail", cluster_id=new_cluster_id)


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


import threading
from django.http import JsonResponse

_slurm_setup_lock = threading.Lock()
_slurm_setup_state = {
    'is_running': False,
    'success': False,
    'error': None,
    'container_name': None,
    'port': None,
}


@login_required
def setup_slurm_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return JsonResponse({'status': 'error', 'message': 'Only POST method is allowed'}, status=405)
    
    with _slurm_setup_lock:
        if _slurm_setup_state['is_running']:
            return JsonResponse({'status': 'error', 'message': 'Slurm setup is already running.'}, status=400)
        
        # Reset state
        _slurm_setup_state['is_running'] = True
        _slurm_setup_state['success'] = False
        _slurm_setup_state['error'] = None
        _slurm_setup_state['container_name'] = None
        _slurm_setup_state['port'] = None

    import uuid
    uid = str(uuid.uuid4())[:8]
    
    # Find free port starting at 2222
    import socket
    def find_free_port(start_port=2222, max_port=3000):
        for p in range(start_port, max_port):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(('', p))
                    return p
                except OSError:
                    continue
        # Fallback to random free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            return s.getsockname()[1]
            
    port = find_free_port()
    container_name = f"slurm-simulator-{uid}"
    _slurm_setup_state['container_name'] = container_name
    _slurm_setup_state['port'] = port
    
    instance_name = request.session.get("chosen_instance")

    thread = threading.Thread(
        target=_run_slurm_setup_thread,
        args=(instance_name, uid, port, container_name),
        daemon=True
    )
    thread.start()
    
    return JsonResponse({
        'status': 'success',
        'message': 'Slurm setup initiated.',
        'container_name': container_name,
        'port': port
    })


@login_required
def setup_slurm_status_view(request: HttpRequest) -> HttpResponse:
    import os
    from django.conf import settings
    
    log_file_path = os.path.join(settings.BASE_DIR, "slurm_setup.log")
    logs = ""
    if os.path.exists(log_file_path):
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                logs = f.read()
        except Exception as e:
            logs = f"Error reading logs: {e}"
            
    with _slurm_setup_lock:
        state = _slurm_setup_state.copy()
        
    return JsonResponse({
        'status': 'success',
        'is_running': state['is_running'],
        'success': state['success'],
        'error': state['error'],
        'container_name': state['container_name'],
        'port': state['port'],
        'logs': logs
    })


def _run_slurm_setup_thread(instance_name, uid, port, container_name):
    import os
    import time
    import json
    import shutil
    import subprocess
    from datetime import datetime, timedelta
    from django.conf import settings
    import py4heappe.heappe_v6.core as hp
    from heappe_ui.auth_backend import patch_api_client
    from heappe_ui.DeployService import get_instance_settings
    
    log_file_path = os.path.join(settings.BASE_DIR, "slurm_setup.log")
    
    def log(message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] {message}\n"
        print(message)
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write(formatted)
            
    # Clean previous log file
    try:
        with open(log_file_path, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass
        
    log("=== STARTING AUTOMATED SLURM SIMULATOR SETUP ===")
    log(f"Unique Build Identifier: {uid}")
    log(f"Dynamic Port Allocation: {port}")
    log(f"Docker Container Name: {container_name}")
    
    temp_dir = os.path.join(settings.BASE_DIR, f"slurm-temp-{uid}")
    acct_name = f"a{uid}"
    slurm_username = f"u{uid}"
    
    try:
        # Step 1: Create temp directory and check disk space
        log("Creating workspace directory for building Docker image...")
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            total_b, used_b, free_b = shutil.disk_usage(temp_dir)
            free_mb = free_b / (1024 * 1024)
            free_gb = free_b / (1024 * 1024 * 1024)
            log(f"Available disk space on host: {free_gb:.2f} GB ({free_mb:.0f} MB)")
            if free_gb < 1.0:
                log("=" * 70)
                log("ERROR: OUT OF DISK SPACE!")
                log(f"The host filesystem has only {free_mb:.0f} MB of free space remaining.")
                log("Building the Slurm simulator requires at least 2.5 GB of free space.")
                log("Please free up disk space on the server before trying again:")
                log("  - docker system prune -a -f --volumes")
                log("  - docker builder prune -a -f")
                log("  - journalctl --vacuum-size=200M")
                log("=" * 70)
                raise RuntimeError(f"Host is out of disk space: only {free_mb:.0f} MB free. Please free up space on the server before retrying.")
            elif free_gb < 2.5:
                log(f"WARNING: Low disk space detected ({free_gb:.2f} GB available). Docker build may run out of space.")
        except RuntimeError:
            raise
        except Exception:
            pass
        
        # 1.1 slurm.conf
        slurm_conf_content = f"""ClusterName=simulator
SlurmctldHost=localhost
SlurmUser=slurm
SlurmdUser=root
SlurmdParameters=config_overrides
ProctrackType=proctrack/pgid
TaskPlugin=task/none
SlurmctldPidFile=/var/run/slurm/slurmctld.pid
SlurmdPidFile=/var/run/slurm/slurmd.pid
StateSaveLocation=/var/spool/slurmctld
SlurmdSpoolDir=/var/spool/slurmd
SlurmctldDebug=info
SlurmctldLogFile=/var/log/slurm/slurmctld.log
SlurmdDebug=info
SlurmdLogFile=/var/log/slurm/slurmd.log
JobAcctGatherType=jobacct_gather/linux
AccountingStorageType=accounting_storage/slurmdbd
AccountingStorageHost=localhost
AccountingStoragePort=6819
AccountingStorageEnforce=associations,limits
SelectType=select/cons_tres
SelectTypeParameters=CR_Core_Memory
GresTypes=gpu
NodeName=localhost NodeAddr=127.0.0.1 State=UNKNOWN CoresPerSocket=2 ThreadsPerCore=1 RealMemory=2000 Gres=gpu:2
PartitionName=test Nodes=localhost Default=YES MaxTime=INFINITE State=UP
"""
        with open(os.path.join(temp_dir, "slurm.conf"), "w") as f:
            f.write(slurm_conf_content)
            
        # 1.2 slurmdbd.conf
        slurmdbd_conf_content = """AuthType=auth/munge
DbdHost=localhost
DbdPort=6819
SlurmUser=slurm
StorageType=accounting_storage/mysql
StorageHost=localhost
StoragePort=3306
StorageUser=slurm
StoragePass=password
StorageLoc=slurm_acct_db
LogFile=/var/log/slurm/slurmdbd.log
PidFile=/var/run/slurm/slurmdbd.pid
"""
        with open(os.path.join(temp_dir, "slurmdbd.conf"), "w") as f:
            f.write(slurmdbd_conf_content)
            
        # 1.3 gres.conf
        gres_conf_content = """Name=gpu File=/var/tmp/gpu0,/var/tmp/gpu1
"""
        with open(os.path.join(temp_dir, "gres.conf"), "w") as f:
            f.write(gres_conf_content)
            
        # 1.4 entrypoint.sh
        entrypoint_content = """#!/bin/bash
set -e

ssh-keygen -A
mkdir -p /var/run/sshd

mkdir -p /var/run/munge /var/log/munge /etc/munge
if [ ! -f /etc/munge/munge.key ]; then
    dd if=/dev/urandom of=/etc/munge/munge.key bs=1 count=1024
fi
chown -R munge:munge /etc/munge /var/run/munge /var/log/munge
chmod 700 /etc/munge
chmod 755 /var/run/munge
chmod 755 /var/log/munge
chmod 400 /etc/munge/munge.key

echo "Starting Munge..."
sudo -u munge munged --force
sleep 2

mkdir -p /var/run/mysqld
chown mysql:mysql /var/run/mysqld
if [ ! -d "/var/lib/mysql/mysql" ]; then
    mysql_install_db --user=mysql --datadir=/var/lib/mysql
fi
/usr/bin/mysqld_safe --user=mysql &

echo "Waiting for MariaDB to start..."
until mysqladmin ping >/dev/null 2>&1; do
    sleep 1
done

mysql -e "CREATE DATABASE IF NOT EXISTS slurm_acct_db;"
mysql -e "CREATE USER IF NOT EXISTS 'slurm'@'localhost' IDENTIFIED BY 'password';"
mysql -e "GRANT ALL PRIVILEGES ON slurm_acct_db.* TO 'slurm'@'localhost';"
mysql -e "FLUSH PRIVILEGES;"

touch /var/tmp/gpu0 /var/tmp/gpu1
chmod 666 /var/tmp/gpu0 /var/tmp/gpu1

mkdir -p /var/spool/slurmctld /var/spool/slurmd /var/log/slurm /var/run/slurm
chown -R slurm:slurm /var/spool/slurmctld /var/spool/slurmd /var/log/slurm /var/run/slurm

chown slurm:slurm /etc/slurm/slurmdbd.conf
chmod 600 /etc/slurm/slurmdbd.conf
chown slurm:slurm /etc/slurm/slurm.conf
chmod 644 /etc/slurm/slurm.conf
chown slurm:slurm /etc/slurm/gres.conf
chmod 644 /etc/slurm/gres.conf

echo "Starting SlurmDBD..."
sudo -u slurm slurmdbd
sleep 3

echo "Configuring Slurm accounts..."
sacctmgr -i add cluster simulator || true
sacctmgr -i add account test Description="Test Project Account" Organization="HEAppE" || true
sacctmgr -i add user heappeslurm Account=test DefaultAccount=test || true

echo "Starting Slurmctld & Slurmd..."
sudo -u slurm slurmctld
sleep 2
if ! pgrep -x slurmctld > /dev/null; then
    echo "ERROR: slurmctld failed to start! /var/log/slurm/slurmctld.log:"
    cat /var/log/slurm/slurmctld.log || true
fi

slurmd -N localhost
sleep 1
if ! pgrep -x slurmd > /dev/null; then
    echo "ERROR: slurmd failed to start! /var/log/slurm/slurmd.log:"
    cat /var/log/slurm/slurmd.log || true
fi

echo "Updating Slurm node state..."
timeout 15 scontrol update nodename=localhost state=idle || true

if [ ! -d "/home/heappeslurm/.local_hpc_scripts" ]; then
    echo "Deploying local HPC helper scripts..."
    mkdir -p /home/heappeslurm/.local_hpc_scripts
    if [ -d "/opt/heappe-scripts/LocalHPC/.local_hpc_scripts" ]; then
        cp -rf /opt/heappe-scripts/LocalHPC/.local_hpc_scripts/* /home/heappeslurm/.local_hpc_scripts/
    else
        git clone --depth 1 --single-branch -b master --quiet https://github.com/It4innovations/HEAppE-scripts.git /tmp/heappe-scripts || true
        if [ -d "/tmp/heappe-scripts/LocalHPC/.local_hpc_scripts" ]; then
            cp -rf /tmp/heappe-scripts/LocalHPC/.local_hpc_scripts/* /home/heappeslurm/.local_hpc_scripts/
            rm -rf /tmp/heappe-scripts
        fi
    fi
    chown -R heappeslurm:heappeslurm /home/heappeslurm/.local_hpc_scripts
    chmod -R 755 /home/heappeslurm/.local_hpc_scripts
fi

echo "Starting HEAppE key scripts watchdog..."
(
while true; do
    if [ -d "/home/heappeslurm/.HEAppE" ]; then
        find /home/heappeslurm/.HEAppE -type d -name ".key_scripts" 2>/dev/null | while read -r dir; do
            if [ ! -f "$dir/run_background_command.sh" ]; then
                echo "Watchdog: Injecting missing run_background_command.sh into $dir"
                cat << 'BG_EOF' > "$dir/run_background_command.sh"
#!/bin/bash
_evalBg() {
    eval "$@" &>/dev/null & disown;
}
BASE64_TEXT=$1
COMMAND=$(echo "${BASE64_TEXT}" | base64 -d)
_evalBg "${COMMAND}";
BG_EOF
                chmod 755 "$dir/run_background_command.sh"
                chown heappeslurm:heappeslurm "$dir/run_background_command.sh"
            fi
        done
    fi
    sleep 1
done
) &

echo "Starting SSH daemon..."
exec /usr/sbin/sshd -D
"""
        entrypoint_content = entrypoint_content.replace("add account test", f"add account {acct_name}").replace("Account=test DefaultAccount=test", f"Account={acct_name} DefaultAccount={acct_name}")
        entrypoint_content = entrypoint_content.replace("heappeslurm", slurm_username)
        with open(os.path.join(temp_dir, "entrypoint.sh"), "w") as f:
            f.write(entrypoint_content)
            
        # 1.5 Dockerfile
        dockerfile_content = """FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    openssh-server \
    sudo \
    munge \
    slurm-wlm \
    slurmdbd \
    mariadb-server \
    mariadb-client \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --single-branch -b master --quiet https://github.com/It4innovations/HEAppE-scripts.git /opt/heappe-scripts || true
RUN useradd -m -s /bin/bash heappeslurm && \
    echo "heappeslurm:pass" | chpasswd && \
    echo "heappeslurm ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
RUN sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
COPY slurm.conf /etc/slurm/slurm.conf
COPY slurmdbd.conf /etc/slurm/slurmdbd.conf
COPY gres.conf /etc/slurm/gres.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 22
ENTRYPOINT ["/entrypoint.sh"]
"""
        dockerfile_content = dockerfile_content.replace("heappeslurm", slurm_username)
        with open(os.path.join(temp_dir, "Dockerfile"), "w") as f:
            f.write(dockerfile_content)

        # Step 2: Build Docker Image
        log("Building Docker image 'slurm-simulator-img:latest' (this might take a few moments)...")
        build_cmd = ["docker", "build", "-t", "slurm-simulator-img:latest", "."]
        
        proc_build = subprocess.run(
            build_cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        if proc_build.returncode != 0:
            is_disk_full = "no space left on device" in (proc_build.stderr + proc_build.stdout).lower()
            if is_disk_full:
                log("=" * 70)
                log("ERROR: OUT OF DISK SPACE!")
                log("The Docker image build failed because the host ran out of disk space ('No space left on device').")
                log("Please free up disk space on the server before trying again:")
                log("  - docker system prune -a -f --volumes")
                log("  - docker builder prune -a -f")
                log("  - journalctl --vacuum-size=200M")
                log("=" * 70)
                raise RuntimeError("Docker build failed: Host ran out of disk space ('No space left on device'). Please free up disk space on the server (e.g. 'docker system prune -a') and try again.")
            
            log("Build output:")
            log(proc_build.stdout)
            log("Build errors:")
            log(proc_build.stderr)
            raise RuntimeError(f"Docker build failed: {proc_build.stderr}")
        log("Docker image built successfully.")

        # Step 3: Run Docker Container
        log(f"Spinning up Docker container '{container_name}' mapping host port {port} -> container port 22...")
        project_label = instance_name or "test"
        run_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--hostname", "localhost",
            "--restart", "unless-stopped",
            "--label", f"com.docker.compose.project={project_label}",
            "--label", "com.docker.compose.service=slurm-simulator",
            "-p", f"{port}:22",
            "slurm-simulator-img:latest"
        ]
        proc_run = subprocess.run(
            run_cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True
        )
        if proc_run.returncode != 0:
            is_disk_full = "no space left on device" in proc_run.stderr.lower()
            if is_disk_full:
                log("=" * 70)
                log("ERROR: OUT OF DISK SPACE!")
                log("Starting Docker container failed: Host is out of disk space ('No space left on device').")
                log("=" * 70)
                raise RuntimeError("Docker run failed: Host is out of disk space ('No space left on device'). Please free up disk space on the server and try again.")
            raise RuntimeError(f"Docker run failed: {proc_run.stderr}")
        log(f"Docker container '{container_name}' started successfully.")

        # Step 4: Wait for services inside container to initialize
        import socket
        log(f"Waiting for SSH daemon inside container to start on port {port} (timeout 90s)...")
        start_time = time.time()
        ssh_ready = False
        timeout = 90
        while time.time() - start_time < timeout:
            s = None
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect(("127.0.0.1", port))
                banner = s.recv(1024)
                if banner and b"SSH-" in banner:
                    ssh_ready = True
                    break
            except Exception:
                pass
            finally:
                if s:
                    try:
                        s.close()
                    except Exception:
                        pass
            time.sleep(1)

        if not ssh_ready:
            container_logs = ""
            try:
                log_proc = subprocess.run(["docker", "logs", "--tail", "100", container_name], capture_output=True, text=True)
                container_logs = (log_proc.stdout + "\n" + log_proc.stderr).strip()
            except Exception:
                pass
            if container_logs:
                log("=" * 70)
                log(f"Docker container '{container_name}' logs:")
                log(container_logs)
                log("=" * 70)
            raise RuntimeError(f"SSH daemon on port {port} did not become ready within {timeout} seconds." + (f"\nContainer logs:\n{container_logs}" if container_logs else ""))
        log("SSH daemon is ready and responding with SSH banner. Waiting an additional 2 seconds to settle...")
        time.sleep(2)
        
        # Step 5: Configure HEAppE
        # Load credentials from DB exactly like HeappeAuthBackend / middleware do.
        log("Loading instance credentials from database...")
        instance_settings = get_instance_settings(instance_name)
        if not instance_settings:
            raise RuntimeError(f"No InstanceCredentials found for instance '{instance_name}'. Cannot connect to HEAppE API.")

        db_host = instance_settings.heappe_host
        db_port = instance_settings.heappe_port
        db_username = instance_settings.heappe_login
        db_password = instance_settings.heappe_password
        full_host = f"{db_host}:{db_port}" if db_port and db_port not in ['80', '443', ''] else db_host
        host_url = 'http://' + full_host if not full_host.startswith('http') else full_host

        log(f"Connecting to HEAppE API at {host_url} as '{db_username}'...")
        config = hp.Configuration()
        config.api_key = {}
        config.api_key_prefix = {}
        config.host = host_url
        config.verify_ssl = True

        session_code = None
        use_api_key = False

        # Try X-API-Key first (same flow as HeappeAuthBackend.authenticate)
        config.api_key = {'X-API-Key': f"{db_username}:{db_password}"}
        api_client = hp.ApiClient(config)
        api_client.set_default_header("X-API-Key", f"{db_username}:{db_password}")
        patch_api_client(api_client)
        ulm = hp.UserAndLimitationManagementApi(api_client)
        try:
            ulm.heappe_user_and_limitation_management_current_user_info_get()
            use_api_key = True
            log("X-API-Key authentication successful.")
            # Best-effort: also get a session code for old HEAppE versions that require it in body
            try:
                r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(
                    _preload_content=False,
                    body={"Credentials": {"Username": db_username, "Password": db_password}}
                )
                session_code = json.loads(r.data)
                log("Also obtained session code for body compatibility.")
            except Exception as e_sc:
                log(f"Note: Could not obtain session code (new API, no fallback needed): {e_sc}")
        except Exception as e_key:
            log(f"X-API-Key auth failed, falling back to session code: {e_key}")
            config.api_key = {}
            api_client.default_headers.pop("X-API-Key", None)
            try:
                r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(
                    _preload_content=False,
                    body={"Credentials": {"Username": db_username, "Password": db_password}}
                )
                session_code = json.loads(r.data)
                log("Session code authentication successful.")
            except Exception as e_fallback:
                raise RuntimeError(f"HEAppE authentication failed entirely: {e_fallback}")

        controller = hp.ManagementApi(api_client)
        
        # 5.1 Create Cluster
        log("Creating Cluster in HEAppE...")
        cluster_payload = {
            "Name": f"Slurm Cluster {uid}",
            "Description": "Automatically generated test Slurm cluster",
            "MasterNodeName": "host.docker.internal",
            "SchedulerType": 4, # Slurm
            "ConnectionProtocol": 2, # SSH
            "TimeZone": "CET",
            "Port": port,
            "UpdateJobStateByServiceAccount": False,
            "DomainName": "",
            "ProxyConnectionId": None,
            "SessionCode": session_code
        }
        cluster_resp = controller.heappe_management_cluster_post(body=cluster_payload)
        cluster_dict = cluster_resp.to_dict() if hasattr(cluster_resp, 'to_dict') else cluster_resp
        cluster_id = cluster_dict.get('id') or cluster_dict.get('Id')
        log(f"Cluster created successfully (ID: {cluster_id}).")
        
        # 5.2 Create File Transfer Method
        log("Creating File Transfer Method (SFTP/SCP) in HEAppE...")
        ftm_payload = {
            "ClusterId": cluster_id,
            "ServerHostname": "host.docker.internal",
            "Protocol": 2, # SFTP/SCP
            "Port": port,
            "SessionCode": session_code
        }
        ftm_resp = controller.heappe_management_file_transfer_method_post(body=ftm_payload)
        ftm_dict = ftm_resp.to_dict() if hasattr(ftm_resp, 'to_dict') else ftm_resp
        ftm_id = ftm_dict.get('id') or ftm_dict.get('Id')
        log(f"File Transfer Method created successfully (ID: {ftm_id}).")
 
        # 5.3 Create Queue Groups (ClusterNodeTypeAggregation)
        log("Creating CPU and GPU Queue Groups (Node Type Aggregations) in HEAppE...")
        now = datetime.now()
        now_aware = now - timedelta(minutes=5)
        valid_to = now + timedelta(days=365)
        
        cpu_group_payload = {
            "Name": f"Slurm CPU Group {uid}",
            "Description": "Automatically generated Slurm CPU Queue Group",
            "AllocationType": "CN",
            "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SessionCode": session_code
        }
        cpu_group_resp = controller.heappe_management_cluster_node_type_aggregation_post(body=cpu_group_payload)
        cpu_group_dict = cpu_group_resp.to_dict() if hasattr(cpu_group_resp, 'to_dict') else cpu_group_resp
        cpu_group_id = cpu_group_dict.get('id') or cpu_group_dict.get('Id')
        log(f"CPU Queue Group created successfully (ID: {cpu_group_id}).")
 
        gpu_group_payload = {
            "Name": f"Slurm GPU Group {uid}",
            "Description": "Automatically generated Slurm GPU Queue Group",
            "AllocationType": "ACN",
            "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SessionCode": session_code
        }
        gpu_group_resp = controller.heappe_management_cluster_node_type_aggregation_post(body=gpu_group_payload)
        gpu_group_dict = gpu_group_resp.to_dict() if hasattr(gpu_group_resp, 'to_dict') else gpu_group_resp
        gpu_group_id = gpu_group_dict.get('id') or gpu_group_dict.get('Id')
        log(f"GPU Queue Group created successfully (ID: {gpu_group_id}).")
 
        # 5.4 Create Accounting Formulas
        log("Creating CPU Accounting Formula in HEAppE...")
        cpu_accounting_payload = {
            "Formula": "NumCPUs * RunTime",
            "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SessionCode": session_code
        }
        cpu_accounting_resp = controller.heappe_management_accounting_post(body=cpu_accounting_payload)
        cpu_accounting_dict = cpu_accounting_resp.to_dict() if hasattr(cpu_accounting_resp, 'to_dict') else cpu_accounting_resp
        cpu_accounting_id = cpu_accounting_dict.get('id') or cpu_accounting_dict.get('Id')
        log(f"CPU Accounting Formula created successfully (ID: {cpu_accounting_id}).")
 
        log("Creating GPU Accounting Formula in HEAppE...")
        gpu_accounting_payload = {
            "Formula": "NumNodes * RunTime * 5",
            "ValidityFrom": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ValidityTo": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SessionCode": session_code
        }
        gpu_accounting_resp = controller.heappe_management_accounting_post(body=gpu_accounting_payload)
        gpu_accounting_dict = gpu_accounting_resp.to_dict() if hasattr(gpu_accounting_resp, 'to_dict') else gpu_accounting_resp
        gpu_accounting_id = gpu_accounting_dict.get('id') or gpu_accounting_dict.get('Id')
        log(f"GPU Accounting Formula created successfully (ID: {gpu_accounting_id}).")
 
        # 5.5 Map Accounting Formulas to Queue Groups
        log("Mapping Accounting Formulas to CPU and GPU Queue Groups...")
        cpu_mapping_payload = {
            "ClusterNodeTypeAggregationId": cpu_group_id,
            "AccountingId": cpu_accounting_id,
            "SessionCode": session_code
        }
        controller.heappe_management_cluster_node_type_aggregation_accounting_post(body=cpu_mapping_payload)
        
        gpu_mapping_payload = {
            "ClusterNodeTypeAggregationId": gpu_group_id,
            "AccountingId": gpu_accounting_id,
            "SessionCode": session_code
        }
        controller.heappe_management_cluster_node_type_aggregation_accounting_post(body=gpu_mapping_payload)
        log("Accounting Formulas mapped successfully to their respective groups.")
 
        # 5.6 Create Queues (ClusterNodeType)
        log("Creating CPU and GPU Queues (Node Types) in HEAppE...")
        cpu_queue_payload = {
            "Name": "cpu",
            "Description": "Slurm CPU partition",
            "NumberOfNodes": 1,
            "CoresPerNode": 2,
            "Queue": "test",
            "QualityOfService": None,
            "MaxWalltime": 999999,
            "ClusterAllocationName": "simulator",  # Must match ClusterName in slurm.conf / sacctmgr cluster name
            "ClusterId": cluster_id,
            "FileTransferMethodId": ftm_id,
            "ClusterNodeTypeAggregationId": cpu_group_id,
            "SessionCode": session_code
        }
        cpu_queue_resp = controller.heappe_management_cluster_node_type_post(body=cpu_queue_payload)
        cpu_queue_dict = cpu_queue_resp.to_dict() if hasattr(cpu_queue_resp, 'to_dict') else cpu_queue_resp
        cpu_queue_id = cpu_queue_dict.get('id') or cpu_queue_dict.get('Id')
        log(f"CPU Queue created successfully (ID: {cpu_queue_id}).")
 
        gpu_queue_payload = {
            "Name": "gpu",
            "Description": "Slurm GPU partition",
            "NumberOfNodes": 1,
            "CoresPerNode": 2,
            "Queue": "test",
            "QualityOfService": None,
            "MaxWalltime": 999999,
            "ClusterAllocationName": "simulator",  # Must match ClusterName in slurm.conf / sacctmgr cluster name
            "ClusterId": cluster_id,
            "FileTransferMethodId": ftm_id,
            "ClusterNodeTypeAggregationId": gpu_group_id,
            "SessionCode": session_code
        }
        gpu_queue_resp = controller.heappe_management_cluster_node_type_post(body=gpu_queue_payload)
        gpu_queue_dict = gpu_queue_resp.to_dict() if hasattr(gpu_queue_resp, 'to_dict') else gpu_queue_resp
        gpu_queue_id = gpu_queue_dict.get('id') or gpu_queue_dict.get('Id')
        log(f"GPU Queue created successfully (ID: {gpu_queue_id}).")
 
        # 5.7 Create Project
        log("Creating Project in HEAppE...")
        project_payload = {
            "Name": f"Slurm Project {uid}",
            "Description": "Automatically generated Slurm test project",
            "AccountingString": acct_name,
            "StartDate": now_aware.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "EndDate": valid_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "UsageType": 1,
            "UseAccountingStringForScheduler": True,
            "IsOneToOneMapping": False,
            "PIEmail": "",
            "SessionCode": session_code
        }
        project_resp = controller.heappe_management_project_post(body=project_payload)
        project_dict = project_resp.to_dict() if hasattr(project_resp, 'to_dict') else project_resp
        project_id = project_dict.get('id') or project_dict.get('Id')
        log(f"Project created successfully (ID: {project_id}).")
 

        # 5.8 Assign Project to Cluster
        log("Assigning Project to Cluster...")
        assign_cluster_payload = {
            "ProjectId": project_id,
            "ClusterId": cluster_id,
            "ScratchStoragePath": f"/home/{slurm_username}",
            "PermanentStoragePath": f"/home/{slurm_username}",
            "ProjectStoragePath": f"/home/{slurm_username}",
            "SessionCode": session_code
        }
        controller.heappe_management_project_assignment_to_cluster_post(body=assign_cluster_payload)
        log("Project assigned to Cluster successfully.")
 
        # 5.9 Assign Project to Queue Groups
        log("Assigning Project to CPU and GPU Queue Groups...")
        assign_cpu_group_payload = {
            "ProjectId": project_id,
            "ClusterNodeTypeAggregationId": cpu_group_id,
            "AllocationAmount": 10000,
            "SessionCode": session_code
        }
        controller.heappe_management_project_cluster_node_type_aggregation_post(body=assign_cpu_group_payload)
        
        assign_gpu_group_payload = {
            "ProjectId": project_id,
            "ClusterNodeTypeAggregationId": gpu_group_id,
            "AllocationAmount": 10000,
            "SessionCode": session_code
        }
        controller.heappe_management_project_cluster_node_type_aggregation_post(body=assign_gpu_group_payload)
        log("Project assigned to CPU and GPU Queue Groups successfully.")
 
        # 5.10 Create Cluster Authentication Credential (SSH Key / Account)
        log(f"Creating SSH Authentication Credentials for '{slurm_username}'...")
        cred_payload = {
            "Credentials": [
                {
                    "Username": slurm_username,
                    "Password": "pass"
                }
            ],
            "ProjectId": project_id,
            "SessionCode": session_code
        }
        controller.heappe_management_generate_secure_shell_key_post(body=cred_payload)
        log("SSH Key authentication credentials generated.")
 
        # 5.11 Initialize the HPC Account
        log("Initializing the HPC Account (deploying key script directories)...")
        init_payload = {
            "ProjectId": project_id,
            "Username": slurm_username,
            "OverwriteExistingProjectRootDirectory": True,
            "SessionCode": session_code
        }
        controller.heappe_management_initialize_cluster_script_directory_post(body=init_payload)
        log("HPC Account initialized successfully.")
 
        log("SUCCESS: Automated Slurm Simulator setup completed successfully!")
        
        with _slurm_setup_lock:
            _slurm_setup_state['is_running'] = False
            _slurm_setup_state['success'] = True
            
    except Exception as ex:
        err_str = str(ex)
        if "no space left on device" in err_str.lower():
            clean_err = "Host is out of disk space ('No space left on device'). Please free up space on the server (e.g. 'docker system prune -a') and try again."
        else:
            clean_err = err_str
        log(f"EXCEPTION: Setup failed: {clean_err}")
        with _slurm_setup_lock:
            _slurm_setup_state['is_running'] = False
            _slurm_setup_state['error'] = clean_err
            
    finally:
        # Clean up temp build folder
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            log(f"Could not clean up temporary build directory: {e}")


@xframe_options_exempt
@login_required
def jaeger_page(request: HttpRequest) -> HttpResponse:
    from heappe_ui.context_processors import get_instance_jaeger_url
    from django.urls import reverse
    instance_name = request.session.get("chosen_instance")
    if not instance_name:
        messages.error(request, "Please choose a HEAppE instance first.")
        return redirect("instance_credentials_list")
        
    jaeger_url, _, otel_disabled = get_instance_jaeger_url(instance_name)
    if otel_disabled:
        messages.warning(request, "Telemetry / Jaeger is not enabled for this instance.")
        return redirect("dashboard_view")
        
    path = request.GET.get('path', '')
    if path:
        iframe_src = reverse('jaeger_proxy', args=[path])
    else:
        iframe_src = reverse('jaeger_proxy_root')
        
    # Forward all other query parameters
    query_params = request.GET.copy()
    if 'path' in query_params:
        del query_params['path']
    if query_params:
        iframe_src += f"?{query_params.urlencode()}"
        
    return render(request, "jaeger.html", {"iframe_src": iframe_src})


@xframe_options_exempt
@login_required
def jaeger_proxy(request: HttpRequest, path: str = "") -> HttpResponse:
    from heappe_ui.context_processors import get_instance_jaeger_url
    instance_name = request.session.get("chosen_instance")
    if not instance_name:
        return HttpResponse("No instance chosen.", status=400)
        
    jaeger_url, _, otel_disabled = get_instance_jaeger_url(instance_name)
    if not jaeger_url:
        return HttpResponse("Jaeger service is not configured.", status=404)
        
    import requests
    url = f"{jaeger_url.rstrip('/')}/{path}"
    if request.META.get('QUERY_STRING'):
        url += f"?{request.META['QUERY_STRING']}"
        
    try:
        headers = {}
        for h in ['Accept', 'Accept-Encoding', 'Accept-Language', 'User-Agent', 'Content-Type']:
            meta_name = f"HTTP_{h.upper().replace('-', '_')}"
            if meta_name in request.META:
                headers[h] = request.META[meta_name]
            elif h == 'Content-Type' and 'CONTENT_TYPE' in request.META:
                headers[h] = request.META['CONTENT_TYPE']
                
        response = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.body,
            stream=True,
            timeout=10
        )
        
        content_type = response.headers.get('Content-Type', '')
        rewrite_content_types = ['text/html', 'application/javascript', 'text/javascript', 'application/json', 'text/css']
        
        if any(ct in content_type.lower() for ct in rewrite_content_types):
            content = response.content
            try:
                text = content.decode('utf-8')
                is_decoded = True
            except UnicodeDecodeError:
                try:
                    text = content.decode('latin-1')
                    is_decoded = True
                except Exception:
                    is_decoded = False
                    
            if is_decoded:
                from django.conf import settings
                script_name = getattr(settings, 'FORCE_SCRIPT_NAME', None) or request.META.get('SCRIPT_NAME', '') or ''
                prefix = f"{script_name.rstrip('/')}/jaeger-proxy"
                
                text = text.replace('<base href="/"', f'<base href="{prefix}/"')
                text = text.replace('<base href=\'/\'', f'<base href=\'{prefix}/\'')
                text = text.replace('"/static/', f'"{prefix}/static/')
                text = text.replace('\'/static/', f"\'{prefix}/static/")
                text = text.replace('"/api/', f'"{prefix}/api/')
                text = text.replace('\'/api/', f"\'{prefix}/api/")
                text = text.replace('"/ui/', f'"{prefix}/ui/')
                text = text.replace('\'/ui/', f"\'{prefix}/ui/")
                content = text.encode('utf-8')
                
            django_response = HttpResponse(content, status=response.status_code, content_type=content_type)
        else:
            django_response = HttpResponse(response.raw, status=response.status_code, content_type=content_type)
            
        for h, v in response.headers.items():
            if h.lower() not in ['transfer-encoding', 'content-length', 'content-encoding', 'x-frame-options', 'content-security-policy']:
                django_response[h] = v
                
        return django_response
        
    except requests.exceptions.RequestException as e:
        return HttpResponse(f"Error connecting to Jaeger service: {e}", status=502)


# ==========================================
# Quantum & QScheduler Management (v6.5.0+)
# ==========================================

@login_required
def cluster_quantum_architecture_api(request: HttpRequest, cluster_id: int) -> JsonResponse:
    """Fetch Quantum Machine Architecture (qubits, topology, basis gates)."""
    try:
        data = request.api_instance.call_api(
            '/heappe/ClusterInformation/MachineArchitecture',
            'GET',
            query_params=[('ClusterId', cluster_id), ('SessionCode', request.session_code)],
            auth_settings=['Bearer', 'ServiceApiKey'],
            response_type='object'
        )
        if isinstance(data, tuple):
            data = data[0]
        if hasattr(data, 'to_dict'):
            data = data.to_dict()
        return JsonResponse({"status": "success", "data": data or {}})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def cluster_quantum_calibration_api(request: HttpRequest, cluster_id: int) -> JsonResponse:
    """Fetch Quantum Machine Calibration (T1, T2, error rates)."""
    try:
        data = request.api_instance.call_api(
            '/heappe/ClusterInformation/MachineCalibration',
            'GET',
            query_params=[('ClusterId', cluster_id), ('SessionCode', request.session_code)],
            auth_settings=['Bearer', 'ServiceApiKey'],
            response_type='object'
        )
        if isinstance(data, tuple):
            data = data[0]
        if hasattr(data, 'to_dict'):
            data = data.to_dict()
        return JsonResponse({"status": "success", "data": data or {}})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def qscheduler_sessions_api(request: HttpRequest, cluster_id: int) -> JsonResponse:
    """List active QScheduler sessions for a cluster."""
    try:
        data = request.api_instance.call_api(
            '/heappe/JobManagement/ListQSchedulerSessions',
            'GET',
            query_params=[('ClusterId', cluster_id), ('SessionCode', request.session_code)],
            auth_settings=['Bearer', 'ServiceApiKey'],
            response_type='list[object]'
        )
        if isinstance(data, tuple):
            data = data[0]
        if isinstance(data, list):
            res = [x.to_dict() if hasattr(x, 'to_dict') else x for x in data]
        else:
            res = []
        return JsonResponse({"status": "success", "data": res})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def qscheduler_open_session_api(request: HttpRequest) -> JsonResponse:
    """Open a new interactive/batch QScheduler session."""
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
    try:
        cluster_id = request.POST.get("ClusterId") or request.POST.get("cluster_id")
        machine_name = request.POST.get("MachineName") or request.POST.get("machine_name", "")
        max_duration_seconds = request.POST.get("MaxDurationSeconds", 3600)
        
        body = {
            "SessionCode": request.session_code,
            "ClusterId": int(cluster_id) if cluster_id else None,
            "MachineName": machine_name,
            "MaxDurationSeconds": int(max_duration_seconds)
        }
        res = request.api_instance.call_api(
            '/heappe/JobManagement/OpenQSchedulerSession',
            'POST',
            body=body,
            auth_settings=['Bearer', 'ServiceApiKey'],
            response_type='object'
        )
        if isinstance(res, tuple):
            res = res[0]
        if hasattr(res, 'to_dict'):
            res = res.to_dict()
        return JsonResponse({"status": "success", "data": res or {}})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def qscheduler_close_session_api(request: HttpRequest, session_id: int) -> JsonResponse:
    """Close an active QScheduler session."""
    if request.method != "POST" and request.method != "DELETE":
        return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
    try:
        body = {
            "SessionCode": request.session_code,
            "QSchedulerSessionId": int(session_id)
        }
        res = request.api_instance.call_api(
            '/heappe/JobManagement/CloseQSchedulerSession',
            'DELETE',
            body=body,
            auth_settings=['Bearer', 'ServiceApiKey'],
            response_type='object'
        )
        return JsonResponse({"status": "success", "message": "Session closed successfully"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def qscheduler_task_result_api(request: HttpRequest, task_id: int) -> JsonResponse:
    """Fetch quantum execution task results."""
    try:
        res = request.api_instance.call_api(
            '/heappe/JobManagement/GetQSchedulerTaskResult',
            'GET',
            query_params=[('SubmittedTaskInfoId', task_id), ('SessionCode', request.session_code)],
            auth_settings=['Bearer', 'ServiceApiKey'],
            response_type='object'
        )
        if isinstance(res, tuple):
            res = res[0]
        if hasattr(res, 'to_dict'):
            res = res.to_dict()
        return JsonResponse({"status": "success", "data": res or {}})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)



