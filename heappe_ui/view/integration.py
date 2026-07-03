import inspect
import json
import re
import six
from typing import Dict, Any, List, Optional
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import py4heappe.heappe_v6.core as hp

def generate_default_payload(model_cls, depth=0, visited=None) -> Optional[Dict[str, Any]]:
    """Recursively generates a dictionary representing the default payload of a HEAppE model."""
    if depth > 4:
        return None
    if visited is None:
        visited = set()
        
    cls_name = model_cls.__name__
    if cls_name in visited:
        return None  # Avoid infinite cycles for self-referential models
        
    visited.add(cls_name)
    
    if not hasattr(model_cls, 'swagger_types'):
        return None
        
    res = {}
    for attr, attr_type in model_cls.swagger_types.items():
        json_key = model_cls.attribute_map.get(attr, attr)
        if attr_type == 'str':
            res[json_key] = ""
        elif attr_type in ('int', 'float'):
            res[json_key] = 0
        elif attr_type == 'bool':
            res[json_key] = False
        elif attr_type.startswith('list['):
            elem_type_name = attr_type[5:-1]
            elem_cls = getattr(hp, elem_type_name, None)
            if elem_cls:
                elem_payload = generate_default_payload(elem_cls, depth + 1, set(visited))
                res[json_key] = [elem_payload] if elem_payload is not None else []
            else:
                res[json_key] = []
        elif attr_type.startswith('dict('):
            res[json_key] = {}
        else:
            nested_cls = getattr(hp, attr_type, None)
            if nested_cls:
                res[json_key] = generate_default_payload(nested_cls, depth + 1, set(visited))
            else:
                res[json_key] = None
    return res

def parse_docstring_params(docstring: str) -> List[Dict[str, str]]:
    """Parses Sphinx-style parameters from method docstrings."""
    params = []
    for line in docstring.split('\n'):
        line = line.strip()
        if line.startswith(':param'):
            parts = line.split()
            if len(parts) >= 3:
                param_type = parts[1]
                param_name = parts[2].rstrip(':')
                desc = ' '.join(parts[3:]) if len(parts) > 3 else ''
                
                if param_name == 'async_req' or param_type == 'async_req':
                    continue
                
                params.append({
                    "name": param_name,
                    "type": param_type,
                    "description": desc
                })
    return params

def parse_docstring_return(docstring: str) -> str:
    """Parses Sphinx-style return type from method docstrings."""
    for line in docstring.split('\n'):
        line = line.strip()
        if line.startswith(':return:'):
            return line.replace(':return:', '').strip()
    return 'Any'

def get_api_discovery_data() -> Dict[str, List[Dict[str, Any]]]:
    """Dynamically reflects on all py4heappe *Api classes to build method definitions."""
    api_classes = [
        'ClusterInformationApi',
        'CredentialsApi',
        'DataTransferApi',
        'DictionaryApi',
        'FileTransferApi',
        'HealthApi',
        'JobManagementApi',
        'JobReportingApi',
        'ManagementApi',
        'UserAndLimitationManagementApi'
    ]
    
    discovery = {}
    for cls_name in api_classes:
        cls = getattr(hp, cls_name, None)
        if not cls:
            continue
            
        discovery[cls_name] = []
        methods = sorted([m for m in dir(cls) if not m.startswith('_') and not m.endswith('_with_http_info') and not m.endswith('_async')])
        
        for method_name in methods:
            method = getattr(cls, method_name)
            if not callable(method):
                continue
                
            doc = getattr(method, '__doc__', '') or ''
            doc_lines = [line.strip() for line in doc.split('\n') if line.strip()]
            description = doc_lines[0] if doc_lines else ""
            if description.endswith("  # noqa: E501"):
                description = description.replace("  # noqa: E501", "")
                
            params = parse_docstring_params(doc)
            return_type = parse_docstring_return(doc)
            
            http_method = "GET"
            if method_name.endswith('_post'):
                http_method = "POST"
            elif method_name.endswith('_put'):
                http_method = "PUT"
            elif method_name.endswith('_delete'):
                http_method = "DELETE"
                
            body_param = next((p for p in params if p["name"] == "body"), None)
            payload_template = None
            if body_param:
                model_cls_name = body_param["type"]
                model_cls = getattr(hp, model_cls_name, None)
                if model_cls:
                    payload_template = generate_default_payload(model_cls)
                    
            discovery[cls_name].append({
                "method_name": method_name,
                "http_method": http_method,
                "description": description,
                "params": params,
                "return_type": return_type,
                "payload_template": payload_template
            })
            
    return discovery

@login_required
def api_integration_view(request: HttpRequest) -> HttpResponse:
    """Renders the main integration panel, preloading resources for pre-selection."""
    projects = []
    clusters = []
    queues = []
    templates = []
    
    # Try fetching resource objects safely for pre-selectors
    try:
        mgmt = hp.ManagementApi(request.api_instance)
        projects = mgmt.heappe_management_projects_get(SessionCode=request.session_code) or []
    except Exception as e:
        print(f"Error fetching projects for selectors: {e}")
        
    try:
        mgmt = hp.ManagementApi(request.api_instance)
        clusters = mgmt.heappe_management_clusters_get(SessionCode=request.session_code) or []
    except Exception as e:
        print(f"Error fetching clusters for selectors: {e}")
        
    try:
        mgmt = hp.ManagementApi(request.api_instance)
        queues = mgmt.heappe_management_cluster_node_types_get(SessionCode=request.session_code) or []
    except Exception as e:
        print(f"Error fetching queues for selectors: {e}")
        
    # Command templates must be fetched per ProjectId.
    # We fetch them concurrently using a ThreadPoolExecutor to keep page load fast.
    from concurrent.futures import ThreadPoolExecutor
    
    def fetch_templates_for_project(project_id):
        try:
            mgmt = hp.ManagementApi(request.api_instance)
            return project_id, mgmt.heappe_management_command_templates_get(SessionCode=request.session_code, ProjectId=project_id) or []
        except Exception as ex:
            print(f"Error fetching templates for project {project_id}: {ex}")
            return project_id, []
            
    templates_by_project = {}
    if projects:
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(fetch_templates_for_project, [p.id for p in projects if hasattr(p, "id") and p.id])
            for proj_id, t_list in results:
                templates_by_project[proj_id] = t_list
                
    # Collect all unique templates fetched
    all_unique_templates = {}
    for proj_id, t_list in templates_by_project.items():
        for t in t_list:
            if hasattr(t, "id") and t.id:
                all_unique_templates[t.id] = t
    templates = list(all_unique_templates.values())
        
    discovery_data = get_api_discovery_data()
    
    # Build serialization-friendly mapping for client-side hierarchical filtering
    projects_map = []
    for p in projects:
        cluster_ids = []
        if hasattr(p, "cluster_project_storage_paths") and p.cluster_project_storage_paths:
            cluster_ids = [path.cluster_id for path in p.cluster_project_storage_paths if hasattr(path, "cluster_id") and path.cluster_id]
            
        template_ids = []
        p_templates = templates_by_project.get(getattr(p, "id", None), [])
        for t in p_templates:
            if hasattr(t, "id") and t.id:
                template_ids.append(t.id)
            
        projects_map.append({
            "id": getattr(p, "id", None),
            "name": getattr(p, "name", ""),
            "cluster_ids": cluster_ids,
            "template_ids": template_ids
        })
        
    queues_map = []
    for q in queues:
        queues_map.append({
            "id": getattr(q, "id", None),
            "name": getattr(q, "name", ""),
            "cluster_id": getattr(q, "cluster_id", None)
        })
        
    templates_map = []
    for t in templates:
        templates_map.append({
            "id": getattr(t, "id", None),
            "name": getattr(t, "name", "")
        })
        
    resource_map = {
        "projects": projects_map,
        "queues": queues_map,
        "templates": templates_map
    }
    
    context = {
        "projects": projects,
        "clusters": clusters,
        "queues": queues,
        "templates": templates,
        "discovery_json": json.dumps(discovery_data),
        "discovery_data": discovery_data,
        "resource_map_json": json.dumps(resource_map)
    }
    return render(request, "integration.html", context)

class MockResponse:
    """Mock response class used to pass JSON data strings directly to Client deserializer."""
    def __init__(self, data_str):
        self.data = data_str

@login_required
def execute_api_call(request: HttpRequest) -> JsonResponse:
    """Handles execution of dynamic API calls, capturing request details and response headers/codes."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST method is allowed"}, status=400)
        
    temp_files = []
    try:
        # Resolve request parameters from either multipart/form-data or application/json
        if request.content_type.startswith('multipart/form-data') or request.FILES:
            api_class_name = request.POST.get("api_class")
            method_name = request.POST.get("method_name")
            payload_data = request.POST.get("payload", "")
            param_args = json.loads(request.POST.get("params", "{}"))
            
            # Handle uploaded files by writing them to temporary disk paths
            if request.FILES:
                import tempfile
                import os
                for field_name in request.FILES:
                    uploaded_files = request.FILES.getlist(field_name)
                    paths = []
                    for f in uploaded_files:
                        ext = os.path.splitext(f.name)[1]
                        temp_f = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                        for chunk in f.chunks():
                            temp_f.write(chunk)
                        temp_f.close()
                        temp_files.append(temp_f.name)
                        paths.append(temp_f.name)
                    param_args[field_name] = paths
        else:
            data = json.loads(request.body)
            api_class_name = data.get("api_class")
            method_name = data.get("method_name")
            payload_data = data.get("payload", "")
            param_args = data.get("params", {})
            
        # Resolve API class
        api_class = getattr(hp, api_class_name, None)
        if not api_class:
            return JsonResponse({"error": f"API class '{api_class_name}' not found"}, status=400)
            
        api_instance = api_class(request.api_instance)
        
        # Prefer the http_info method so we get headers and status code
        method_info_name = f"{method_name}_with_http_info"
        method_to_call = getattr(api_instance, method_info_name, None)
        is_http_info = True
        if not method_to_call:
            method_to_call = getattr(api_instance, method_name, None)
            is_http_info = False
            
        if not method_to_call:
            return JsonResponse({"error": f"Method '{method_name}' not found in '{api_class_name}'"}, status=400)
            
        # Parse params from docstring
        docstring = getattr(method_to_call, "__doc__", "") or ""
        params_list = parse_docstring_params(docstring)
        param_names = [p["name"] for p in params_list]
        
        kwargs = {}
        
        # Populate path and query arguments
        for p_name, p_val in param_args.items():
            if p_name in param_names:
                p_type_info = next((p["type"] for p in params_list if p["name"] == p_name), "str")
                if "int" in p_type_info:
                    try:
                        kwargs[p_name] = int(p_val)
                    except (ValueError, TypeError):
                        kwargs[p_name] = p_val
                elif "bool" in p_type_info:
                    kwargs[p_name] = str(p_val).lower() in ("true", "1", "yes")
                else:
                    kwargs[p_name] = p_val
                    
        # Populate body payload
        if "body" in param_names:
            if payload_data:
                if isinstance(payload_data, str):
                    try:
                        kwargs["body"] = json.loads(payload_data)
                    except json.JSONDecodeError:
                        kwargs["body"] = payload_data
                else:
                    kwargs["body"] = payload_data
            else:
                kwargs["body"] = {}
                
        # Populate SessionCode
        if "SessionCode" in param_names and "SessionCode" not in kwargs:
            kwargs["SessionCode"] = request.session_code
            
        # Auto-fill SessionCode in nested body dictionary if present but empty
        if "body" in kwargs and isinstance(kwargs["body"], dict) and "SessionCode" in kwargs["body"] and not kwargs["body"]["SessionCode"]:
            kwargs["body"]["SessionCode"] = request.session_code
            
        # Track start time to measure execution speed
        import time
        start_time = time.time()
        
        if is_http_info:
            response_data, status_code, headers = method_to_call(**kwargs)
            duration = int((time.time() - start_time) * 1000)
            serialized_data = request.api_instance.sanitize_for_serialization(response_data)
            return JsonResponse({
                "status_code": status_code,
                "headers": dict(headers),
                "data": serialized_data,
                "duration_ms": duration
            })
        else:
            response_data = method_to_call(**kwargs)
            duration = int((time.time() - start_time) * 1000)
            serialized_data = request.api_instance.sanitize_for_serialization(response_data)
            return JsonResponse({
                "status_code": 200,
                "headers": {},
                "data": serialized_data,
                "duration_ms": duration
            })
            
    except Exception as e:
        status_code = 500
        headers = {}
        error_msg = str(e)
        
        # Handle ApiException details from py4heappe or underlying client
        if hasattr(e, "status"):
            status_code = getattr(e, "status", 500)
        if hasattr(e, "headers"):
            headers = dict(getattr(e, "headers", {}))
        if hasattr(e, "body"):
            body_val = getattr(e, "body", "")
            if body_val:
                try:
                    if isinstance(body_val, bytes):
                        body_val = body_val.decode("utf-8")
                    error_msg = json.loads(body_val)
                except Exception:
                    error_msg = str(body_val)
                    
        return JsonResponse({
            "status_code": status_code,
            "headers": headers,
            "error": error_msg
        }, status=status_code if status_code >= 400 and status_code < 600 else 500)
        
    finally:
        # Clean up any temporary files created for file upload
        import os
        for path in temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as ex:
                print(f"Error cleaning up temporary upload file {path}: {ex}")
