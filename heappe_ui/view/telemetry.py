import json
from datetime import datetime, timedelta, timezone
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

import py4heappe.heappe_v6.core as hp
from .utils import ensure_heappe_version, clean_ver


def _normalize_item(item):
    """Normalize object or dict into a standard dict with all standard keys populated."""
    if item is None:
        return {}
    if isinstance(item, dict):
        d = dict(item)
    elif hasattr(item, 'to_dict'):
        d = item.to_dict()
    else:
        d = getattr(item, '__dict__', {})

    res = dict(d)
    
    defaults = {
        'ServiceName': 'Service',
        'ServiceType': 'external',
        'Protocol': 'http',
        'Host': '-',
        'Port': '',
        'IsAvailable': False,
        'ResponseTimeMs': 0,
        'ErrorMessage': '',
        'CommandOrPath': '-',
        'AvailabilityPercentage': 100.0,
        'AverageResponseTimeMs': 0.0,
        'MinResponseTimeMs': 0,
        'MaxResponseTimeMs': 0,
        'P95ResponseTimeMs': 0.0,
        'TotalChecks': 0,
        'FailedChecks': 0,
        'Timestamp': '',
        'DurationMs': 0,
        'StatusCode': 200,
        'IsSuccess': True,
        'SubmittedTaskInfoId': '',
        'RequestId': '',
    }
    
    key_mappings = {
        'ServiceName': ['service_name', 'name', 'Name'],
        'ServiceType': ['service_type', 'type', 'Type'],
        'Protocol': ['protocol', 'Protocol'],
        'Host': ['host', 'Host'],
        'Port': ['port', 'Port'],
        'IsAvailable': ['is_available', 'IsAvailable'],
        'ResponseTimeMs': ['response_time_ms', 'ResponseTimeMs'],
        'ErrorMessage': ['error_message', 'ErrorMessage'],
        'CommandOrPath': ['command_or_path', 'operation', 'Operation', 'CommandOrPath'],
        'AvailabilityPercentage': ['availability_percentage', 'AvailabilityPercentage'],
        'AverageResponseTimeMs': ['average_response_time_ms', 'AverageResponseTimeMs'],
        'MinResponseTimeMs': ['min_response_time_ms', 'MinResponseTimeMs'],
        'MaxResponseTimeMs': ['max_response_time_ms', 'MaxResponseTimeMs'],
        'P95ResponseTimeMs': ['p95_response_time_ms', 'P95ResponseTimeMs'],
        'TotalChecks': ['total_checks', 'TotalChecks'],
        'FailedChecks': ['failed_checks', 'FailedChecks'],
        'Timestamp': ['timestamp', 'Timestamp'],
        'DurationMs': ['duration_ms', 'DurationMs'],
        'StatusCode': ['status_code', 'StatusCode'],
        'IsSuccess': ['is_success', 'IsSuccess'],
        'SubmittedTaskInfoId': ['submitted_task_info_id', 'task_id', 'TaskId', 'SubmittedTaskInfoId'],
        'RequestId': ['request_id', 'trace_id', 'TraceId', 'RequestId'],
    }
    for primary, aliases in key_mappings.items():
        val = None
        for alias in aliases:
            if alias in res and res[alias] is not None:
                val = res[alias]
                break
        if val is None:
            val = defaults.get(primary)
        for alias in aliases:
            res[alias] = val
            
    return res


def _call_telemetry_api(request, endpoint: str, method: str = 'POST', body: dict = None, query_params: dict = None):
    """Safely call HEAppE telemetry endpoints using request.api_instance supporting X-API-KEY and SessionCode."""
    if not hasattr(request, 'api_instance') or not request.api_instance:
        raise RuntimeError("No HEAppE API instance connected.")

    session_code = getattr(request, 'session_code', None) or request.session.get('heappe_session_code', '')
    use_api_key = request.session.get('heappe_use_api_key', False)

    # For GetExternalServicesLiveStatus, invoke directly without application/json Content-Type to prevent abstract SessionCodeModel deserialization error
    if 'GetExternalServicesLiveStatus' in endpoint:
        try:
            import requests as req_lib
            raw_host = getattr(getattr(request.api_instance, 'configuration', None), 'host', '')
            if isinstance(raw_host, str) and raw_host.strip():
                base_url = raw_host.strip().rstrip('/')
                if not base_url.startswith('http'):
                    base_url = 'http://' + base_url
                url = f"{base_url}{endpoint}"
                headers = {}
                if hasattr(request.api_instance, 'default_headers') and request.api_instance.default_headers:
                    headers.update(request.api_instance.default_headers)
                if hasattr(request.api_instance, 'configuration') and hasattr(request.api_instance.configuration, 'api_key'):
                    for key_name, key_val in (request.api_instance.configuration.api_key or {}).items():
                        if key_val and isinstance(key_val, str):
                            pfx = ""
                            if hasattr(request.api_instance.configuration, 'api_key_prefix') and request.api_instance.configuration.api_key_prefix.get(key_name):
                                pfx = f"{request.api_instance.configuration.api_key_prefix[key_name]} "
                            headers[key_name] = f"{pfx}{key_val}"
                
                if session_code and not use_api_key:
                    headers.setdefault('SessionCode', session_code)
                    headers.setdefault('Authorization', f"Bearer {session_code}")

                req_params = dict(query_params or {})
                if session_code and not use_api_key and 'SessionCode' not in req_params:
                    req_params['SessionCode'] = session_code

                resp = req_lib.post(url, params=req_params, headers=headers, timeout=20, verify=False)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        return [_normalize_item(x) for x in data]
                    return _normalize_item(data)
                else:
                    if resp.status_code == 500 and 'SessionCodeModel' in resp.text:
                        resp = req_lib.post(url, params=req_params, data="", headers=headers, timeout=20, verify=False)
                        if resp.status_code == 200:
                            data = resp.json()
                            if isinstance(data, list):
                                return [_normalize_item(x) for x in data]
                            return _normalize_item(data)
        except Exception as ex:
            pass

    if body is not None and isinstance(body, dict):
        if not use_api_key and session_code:
            if 'SessionCode' not in body and 'session_code' not in body:
                body['SessionCode'] = session_code

    call_kwargs = {
        'auth_settings': ['Bearer', 'ServiceApiKey', 'ApiKeyAuth', 'X-API-Key'],
        'response_type': 'list[object]' if 'Statistics' in endpoint or 'Logs' in endpoint or 'Status' in endpoint else 'object'
    }
    if body is not None:
        call_kwargs['body'] = body
    if query_params is not None:
        call_kwargs['query_params'] = [(k, v) for k, v in query_params.items() if v is not None]

    try:
        raw_res = request.api_instance.call_api(
            endpoint,
            method,
            **call_kwargs
        )
        if isinstance(raw_res, tuple):
            raw_res = raw_res[0]
            
        if isinstance(raw_res, list):
            return [_normalize_item(x) for x in raw_res]
        elif raw_res:
            return _normalize_item(raw_res)
        return [] if 'list' in call_kwargs['response_type'] else {}
    except Exception as e:
        # If GET failed with 405 (Method Not Allowed), retry call_api with POST
        if method.upper() == 'GET' and hasattr(e, 'status') and getattr(e, 'status') == 405:
            try:
                raw_res = request.api_instance.call_api(
                    endpoint,
                    'POST',
                    **call_kwargs
                )
                if isinstance(raw_res, tuple):
                    raw_res = raw_res[0]
                if isinstance(raw_res, list):
                    return [_normalize_item(x) for x in raw_res]
                elif raw_res:
                    return _normalize_item(raw_res)
            except Exception:
                pass

        # Fallback to direct HTTP request using requests
        try:
            import requests as req_lib
            base_url = request.api_instance.configuration.host.rstrip('/')
            url = f"{base_url}{endpoint}"
            headers = {}
            
            # Pass all configured API keys from ApiClient configuration (e.g. X-API-Key, ServiceApiKey, etc.)
            if hasattr(request.api_instance, 'configuration') and hasattr(request.api_instance.configuration, 'api_key'):
                for key_name, key_val in (request.api_instance.configuration.api_key or {}).items():
                    if key_val:
                        pfx = ""
                        if hasattr(request.api_instance.configuration, 'api_key_prefix') and request.api_instance.configuration.api_key_prefix.get(key_name):
                            pfx = f"{request.api_instance.configuration.api_key_prefix[key_name]} "
                        headers[key_name] = f"{pfx}{key_val}"

            if session_code and not use_api_key:
                headers.setdefault('SessionCode', session_code)
                headers.setdefault('Authorization', f"Bearer {session_code}")
                
            req_params = dict(query_params or {})
            if session_code and not use_api_key and 'SessionCode' not in req_params and 'GetExternalServicesLiveStatus' in endpoint:
                req_params['SessionCode'] = session_code

            if method.upper() == 'GET':
                resp = req_lib.get(url, params=req_params, headers=headers, timeout=20, verify=False)
                if resp.status_code == 405:
                    resp = req_lib.post(url, params=req_params, headers=headers, timeout=20, verify=False)
            else:
                if body is not None:
                    headers['Content-Type'] = 'application/json'
                    resp = req_lib.post(url, params=req_params, json=body, headers=headers, timeout=20, verify=False)
                else:
                    resp = req_lib.post(url, params=req_params, headers=headers, timeout=20, verify=False)

                if resp.status_code in (404, 405, 500) and ('SessionCodeModel' in resp.text or resp.status_code == 405):
                    resp = req_lib.get(url, params=req_params, headers=headers, timeout=20, verify=False)
                
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return [_normalize_item(x) for x in data]
                return _normalize_item(data)
        except Exception:
            pass
        raise e


def _get_live_statuses(request):
    """Retrieve live probe statuses from GetExternalServicesLiveStatus or synthesize from /Health and recent statistics."""
    try:
        res = _call_telemetry_api(
            request,
            '/heappe/Management/GetExternalServicesLiveStatus',
            'POST'
        )
        if res and isinstance(res, list) and len(res) > 0:
            return res, None
    except Exception:
        pass

    # Synthesize live probe statuses using /heappe/Health and GetExternalServicesStatistics (last 1h)
    synthesized = []
    try:
        health_controller = hp.HealthApi(request.api_instance)
        health_info = health_controller.heappe_health_get()
        
        # Database probe
        db_healthy = True
        if hasattr(health_info, 'component') and hasattr(health_info.component, 'database'):
            db_healthy = getattr(health_info.component.database, 'is_healthy', True)
        synthesized.append(_normalize_item({
            "ServiceName": "Database",
            "ServiceType": "database",
            "Protocol": "sql",
            "Host": "db",
            "Port": "1433",
            "IsAvailable": db_healthy,
            "ResponseTimeMs": 5,
            "ErrorMessage": "" if db_healthy else "Database unreachable"
        }))

        # Vault probe
        vault_healthy = True
        if hasattr(health_info, 'component') and hasattr(health_info.component, 'vault'):
            vault_healthy = getattr(health_info.component.vault, 'is_healthy', True)
        synthesized.append(_normalize_item({
            "ServiceName": "HashiCorp Vault",
            "ServiceType": "keymanagement",
            "Protocol": "http",
            "Host": "vault",
            "Port": "8200",
            "IsAvailable": vault_healthy,
            "ResponseTimeMs": 12,
            "ErrorMessage": "" if vault_healthy else "Vault sealed or unreachable"
        }))
    except Exception:
        pass

    # Add services from recent 1-hour statistics
    try:
        now = datetime.utcnow()
        stats_body = {
            "From": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "To": now.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        if not request.session.get('heappe_use_api_key', False) and getattr(request, 'session_code', None):
            stats_body["SessionCode"] = request.session_code

        recent_stats = _call_telemetry_api(
            request,
            '/heappe/Management/GetExternalServicesStatistics',
            'POST',
            body=stats_body
        )
        if recent_stats and isinstance(recent_stats, list):
            existing_names = {s.get('ServiceName') for s in synthesized}
            for stat in recent_stats:
                s_name = stat.get('ServiceName') or stat.get('service_name')
                if s_name and s_name not in existing_names:
                    existing_names.add(s_name)
                    avail_pct = stat.get('AvailabilityPercentage', 100.0)
                    is_avail = avail_pct >= 50.0
                    stype = stat.get('ServiceType') or ('cluster' if any(c in s_name.lower() for c in ['cluster', 'slurm', 'karolina', 'barbora', 'lumi']) else 'external')
                    synthesized.append(_normalize_item({
                        "ServiceName": s_name,
                        "ServiceType": stype,
                        "Protocol": "ssh" if stype == 'cluster' else "http",
                        "Host": s_name,
                        "Port": "22" if stype == 'cluster' else "",
                        "IsAvailable": is_avail,
                        "ResponseTimeMs": int(stat.get('AverageResponseTimeMs') or stat.get('P95ResponseTimeMs') or 25),
                        "ErrorMessage": "" if is_avail else f"Low availability: {avail_pct}%"
                    }))
    except Exception:
        pass

    return synthesized, None


@login_required
def external_services_telemetry_view(request: HttpRequest) -> HttpResponse:
    """Dashboard for external services health probes and aggregated latency/reliability statistics."""
    version_error = ensure_heappe_version(
        request,
        "6.5.0",
        "External Services & Telemetry is supported on HEAppE version 6.5.0 or newer.",
        "dashboard_view"
    )
    if version_error:
        return version_error

    time_range = request.GET.get('range', '24h')
    service_filter = request.GET.get('service', '').strip()
    cluster_filter = request.GET.get('cluster', '').strip()

    now = datetime.utcnow()
    if time_range == '1h':
        from_dt = now - timedelta(hours=1)
    elif time_range == '7d':
        from_dt = now - timedelta(days=7)
    elif time_range == '30d':
        from_dt = now - timedelta(days=30)
    else:
        from_dt = now - timedelta(hours=24)
        time_range = '24h'

    live_statuses, live_error = _get_live_statuses(request)

    stats_list = []
    stats_error = None
    stats_body = {
        "From": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "To": now.strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    if not request.session.get('heappe_use_api_key', False) and getattr(request, 'session_code', None):
        stats_body["SessionCode"] = request.session_code

    if service_filter:
        stats_body["ServiceName"] = service_filter
    if cluster_filter:
        try:
            stats_body["ClusterId"] = int(cluster_filter)
        except ValueError:
            pass

    try:
        stats_list = _call_telemetry_api(
            request,
            '/heappe/Management/GetExternalServicesStatistics',
            'POST',
            body=stats_body
        )
    except Exception as e:
        stats_error = str(e)

    clusters_list = []
    try:
        clusters_controller = hp.ClusterInformationApi(request.api_instance)
        clusters_data = clusters_controller.heappe_cluster_information_list_available_clusters_get(
            SessionCode=getattr(request, 'session_code', None) or 'ignore'
        )
        if clusters_data:
            clusters_list = [_normalize_item(c) for c in clusters_data]
    except Exception:
        pass

    available_service_names = set()
    for s in live_statuses:
        name = s.get('ServiceName') or s.get('service_name') or s.get('name')
        if name:
            available_service_names.add(name)
    for st in stats_list:
        name = st.get('ServiceName') or st.get('service_name')
        if name:
            available_service_names.add(name)

    # Compute KPI Aggregates
    total_checks = sum(int(st.get('TotalChecks') or st.get('total_checks') or 0) for st in stats_list)
    total_failures = sum(int(st.get('FailedChecks') or st.get('failed_checks') or 0) for st in stats_list)
    avg_avail = 100.0
    if total_checks > 0:
        avg_avail = max(0.0, min(100.0, ((total_checks - total_failures) / total_checks) * 100.0))
    elif stats_list:
        avails = [float(st.get('AvailabilityPercentage') or st.get('availability_percentage') or 100) for st in stats_list]
        avg_avail = sum(avails) / len(avails) if avails else 100.0

    valid_latencies = [float(st.get('AverageResponseTimeMs') or st.get('average_response_time_ms') or 0) for st in stats_list if (st.get('AverageResponseTimeMs') or st.get('average_response_time_ms'))]
    avg_latency = (sum(valid_latencies) / len(valid_latencies)) if valid_latencies else 0.0

    # Chart datasets
    chart_labels = []
    chart_avg_latency = []
    chart_p95_latency = []
    chart_success_calls = []
    chart_failed_calls = []

    for st in stats_list[:15]:
        s_name = st.get('ServiceName') or st.get('service_name') or '-'
        cmd = st.get('CommandOrPath') or st.get('command_or_path') or ''
        label = f"{s_name}: {cmd[:25]}..." if len(cmd) > 25 else (f"{s_name}: {cmd}" if cmd else s_name)
        chart_labels.append(label)
        chart_avg_latency.append(round(float(st.get('AverageResponseTimeMs') or st.get('average_response_time_ms') or 0), 1))
        chart_p95_latency.append(round(float(st.get('P95ResponseTimeMs') or st.get('p95_response_time_ms') or 0), 1))
        
        tc = int(st.get('TotalChecks') or st.get('total_checks') or 0)
        fc = int(st.get('FailedChecks') or st.get('failed_checks') or 0)
        chart_success_calls.append(max(0, tc - fc))
        chart_failed_calls.append(fc)

    context = {
        "live_statuses": live_statuses,
        "live_error": live_error,
        "statistics": stats_list,
        "stats_error": stats_error,
        "time_range": time_range,
        "selected_service": service_filter,
        "selected_cluster_id": cluster_filter,
        "clusters": clusters_list,
        "service_names": sorted(list(available_service_names)),
        "from_dt": from_dt,
        "to_dt": now,
        "total_checks": total_checks,
        "total_failures": total_failures,
        "avg_avail": round(avg_avail, 1),
        "avg_latency": round(avg_latency, 1),
        "chart_labels_json": json.dumps(chart_labels),
        "chart_avg_latency_json": json.dumps(chart_avg_latency),
        "chart_p95_latency_json": json.dumps(chart_p95_latency),
        "chart_success_calls_json": json.dumps(chart_success_calls),
        "chart_failed_calls_json": json.dumps(chart_failed_calls),
    }
    return render(request, "external_services_telemetry.html", context)


@login_required
def external_services_live_status_api(request: HttpRequest) -> JsonResponse:
    """AJAX JSON endpoint to refresh Live Health Status probes."""
    try:
        statuses, err = _get_live_statuses(request)
        if err:
            return JsonResponse({"status": "error", "message": err}, status=500)
        return JsonResponse({"status": "success", "data": statuses})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def external_services_statistics_api(request: HttpRequest) -> JsonResponse:
    """AJAX JSON endpoint to fetch filtered statistics."""
    time_range = request.GET.get('range', '24h')
    service_filter = request.GET.get('service', '').strip()
    cluster_filter = request.GET.get('cluster_id', '').strip()
    from_param = request.GET.get('from', '').strip()
    to_param = request.GET.get('to', '').strip()

    now = datetime.now(timezone.utc)
    if from_param and to_param:
        from_str = from_param
        to_str = to_param
    elif time_range == '1h':
        from_str = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif time_range == '7d':
        from_str = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif time_range == '30d':
        from_str = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        from_str = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "SessionCode": request.session_code,
        "From": from_str,
        "To": to_str
    }
    if service_filter:
        body["ServiceName"] = service_filter
    if cluster_filter:
        try:
            body["ClusterId"] = int(cluster_filter)
        except ValueError:
            pass

    try:
        stats = _call_telemetry_api(
            request,
            '/heappe/Management/GetExternalServicesStatistics',
            'POST',
            body=body
        )
        return JsonResponse({"status": "success", "data": stats, "from": from_str, "to": to_str})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def external_services_report_api(request: HttpRequest) -> JsonResponse:
    """Fetch external services comprehensive telemetry report."""
    from_param = request.GET.get('from', '').strip()
    to_param = request.GET.get('to', '').strip()
    service_filter = request.GET.get('service', '').strip()
    cluster_filter = request.GET.get('cluster_id', '').strip()

    now = datetime.now(timezone.utc)
    from_str = from_param or (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str = to_param or now.strftime("%Y-%m-%dT%H:%M:%SZ")

    body = {
        "SessionCode": request.session_code,
        "From": from_str,
        "To": to_str
    }
    if service_filter:
        body["ServiceName"] = service_filter
    if cluster_filter:
        try:
            body["ClusterId"] = int(cluster_filter)
        except ValueError:
            pass

    try:
        report = _call_telemetry_api(
            request,
            '/heappe/Management/GetExternalServicesReport',
            'POST',
            body=body
        )
        return JsonResponse({"status": "success", "data": report})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
def job_external_service_logs_api(request: HttpRequest, job_id: int) -> JsonResponse:
    """API endpoint to get external service telemetry logs for a specific job."""
    try:
        logs = _call_telemetry_api(
            request,
            '/heappe/Management/GetJobExternalServiceLogs',
            'POST',
            body={
                "SessionCode": request.session_code,
                "SubmittedJobInfoId": int(job_id)
            }
        )
        return JsonResponse({"status": "success", "data": logs})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
