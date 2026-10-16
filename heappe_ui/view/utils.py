from .imports import *
from datetime import datetime
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required


PROTOCOL_CHOICES = [
    (1, "network share"),
    (2, "sftp/scp"),
    (4, "local sftp/scp"),
    (8, "http"),
    (16, "https"),
]

SCHEDULER_CHOICES = [
    (1, "Local Simulator"),
    (2, "PBS Pro"),
    (4, "Slurm"),
    (8, "HyperQueue"),
    (16, "FirecREST (Slurm)"),
    (32, "QScheduler")
]

CONNECTION_PROTOCOL_CHOICES = [
    (0, "none"),
    (1, "microsofthpcapi"),
    (2, "ssh"),
    (3, "ssh interactive (legacy)"),
    (4, "ssh interactive"),
    (8, "http"),
    (16, "https")
]

def clean_ver(v: str) -> list[int]:
    if not v:
        return [0, 0, 0]
    import re
    res = [int(n) for n in re.findall(r'\d+', str(v))]
    while len(res) < 3:
        res.append(0)
    return res

ACCOUNTING_OPERATORS = [
    '+',
    '-',
    '*',
    '/',
    '(',
    ')'
]

ACCOUNTING_TIMES = [
    "RunTime",
    "TimeLimit",
    "SubmitTime",
    "StartTime",
    "EndTime"
]

ACCOUNTING_NUMBERS = [
    "JobId",
    "NumNodes",
    "NumCPUs",
    "NumTasks",
    "MinMemoryNode",
    "ExitCode"
]

def _create_payload(session_code: str, data: Dict[str, Any], id_field: Optional[str] = None) -> Dict[str, Any]:
    """Create a standardized payload for API requests.

    SessionCode is always included in the body (as None when not available) so that
    patched_call_api in auth_backend can back-fill it from the session for old HEAppE
    server versions that require it. New servers simply ignore the field.
    """
    body = {**data}
    # Always set SessionCode – even if None. patched_call_api will try to fill in a
    # fallback from the session when it finds a null value, which is needed for old
    # HEAppE server versions that require SessionCode in the request body.
    body["SessionCode"] = session_code or None
    payload = {
        "_preload_content": False,
        "body": body
    }
    if id_field and id_field in data:
        payload["body"]["Id"] = data[id_field]
    return payload


def _parse_datetime_local(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    from django.utils.dateparse import parse_datetime
    from django.utils.timezone import is_aware, make_aware
    dt = parse_datetime(date_str)
    if dt and not is_aware(dt):
        dt = make_aware(dt)
    return dt

def _extract_error_from_json(data):
    if isinstance(data, str):
        return data.strip() if data.strip() else None
    if isinstance(data, list):
        items = [_extract_error_from_json(x) for x in data if x]
        return ", ".join(filter(None, items)) if items else None
    if isinstance(data, dict):
        # 1. Validation errors dict: {"errors": {"Field": ["Error 1", "Error 2"]}}
        errors = data.get('errors') or data.get('Errors')
        errors_str = None
        if isinstance(errors, dict):
            parts = []
            for field, errs in errors.items():
                if isinstance(errs, list):
                    err_text = ", ".join(str(e) for e in errs)
                else:
                    err_text = str(errs)
                parts.append(f"{field}: {err_text}" if field else err_text)
            if parts:
                errors_str = "; ".join(parts)
        elif isinstance(errors, list):
            errors_str = ", ".join(str(e) for e in errors)

        # 2. Direct error message keys commonly returned by HEAppE / ASP.NET
        for key in ['ErrorMessage', 'errorMessage', 'Message', 'message', 'detail', 'Detail', 'error', 'Error', 'description']:
            val = data.get(key)
            if val and isinstance(val, str) and val.strip():
                if errors_str:
                    return f"{val.strip()} ({errors_str})"
                return val.strip()

        title = data.get('title') or data.get('Title')
        if title and isinstance(title, str) and title.strip():
            if errors_str:
                return f"{title.strip()} ({errors_str})"
            return title.strip()

        if errors_str:
            return errors_str

    return None


def extract_heappe_error(exc) -> str:
    """Extract a user-friendly error message from an exception, especially ApiException or HEAppE response."""
    if exc is None:
        return "Unknown error"

    raw_body = getattr(exc, 'body', None)
    if isinstance(raw_body, bytes):
        try:
            raw_body = raw_body.decode('utf-8')
        except Exception:
            raw_body = raw_body.decode('utf-8', errors='replace')

    # If body wasn't an attribute, check if exception string contains response body
    if not raw_body:
        exc_str = str(exc)
        for marker in ["HTTP response body: b'", 'HTTP response body: b"', "HTTP response body: "]:
            if marker in exc_str:
                extracted = exc_str.split(marker, 1)[1]
                if marker.endswith("'") and "'" in extracted:
                    raw_body = extracted.rsplit("'", 1)[0]
                elif marker.endswith('"') and '"' in extracted:
                    raw_body = extracted.rsplit('"', 1)[0]
                else:
                    raw_body = extracted.strip()
                break

    if raw_body:
        # Try JSON parsing
        try:
            import json
            data = json.loads(raw_body)
            msg = _extract_error_from_json(data)
            if msg:
                return msg
        except Exception:
            # Not JSON - check if plain text error
            text = raw_body.strip()
            if text and not text.startswith('<'):
                if len(text) > 300:
                    text = text[:300] + "..."
                return text

    status = getattr(exc, 'status', None)
    reason = getattr(exc, 'reason', None)
    exc_str = str(exc)

    # Check for network/connection errors
    exc_lower = exc_str.lower()
    if any(term in exc_lower for term in ["connection refused", "timeout", "timed out", "max retries", "unreachable", "name resolution", "failed to establish a new connection"]):
        detail = reason or (exc_str.splitlines()[0] if exc_str else "")
        return f"Could not reach the HEAppE service ({detail})"

    if status and reason:
        return f"HEAppE error ({status} {reason})"
    elif reason:
        return str(reason)
    elif status:
        return f"HEAppE error ({status})"

    first_line = exc_str.splitlines()[0] if exc_str else "Unknown error"
    return first_line


def _handle_api_call(request, api_call, success_message, error_message, silent=False):
    try:
        print("DEBUG: Executing api_call...")
        result = api_call()
        print(f"DEBUG: api_call success. Type: {type(result)}")

        if not silent and success_message:
            messages.success(request, success_message)

        # Handling different response types
        if isinstance(result, (list, dict)):
            print("DEBUG: Result is already list/dict.")
            return result

        if hasattr(result, 'json'):
            print("DEBUG: Result has .json() method. Parsing...")
            return result.json()

        if hasattr(result, 'data'):
            print("DEBUG: Result has .data. Parsing JSON...")
            try:
                import json
                raw_data = result.data
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode('utf-8')
                return json.loads(raw_data)
            except Exception as ex:
                print(f"DEBUG: Error parsing response data: {ex}")

        print("DEBUG: Returning result as-is.")
        return result
    except Exception as e:
        print(f"DEBUG: EXCEPTION in _handle_api_call: {str(e)}")
        if not silent:
            messages.error(request, f"{error_message}: {str(e)}")
        return []


def login_view(request):
    if request.method == "POST":
        host = request.POST.get("host")
        username = request.POST.get("username")
        password = request.POST.get("password")

        # prepare host for client
        if not host.startswith("http://") and not host.startswith("https://"):
            host = "http://" + host
        if host.endswith("/"):
            host = host[:-1]

        user = authenticate(request, host=host, username=username, password=password)
        if user:
            login(request, user)
            return redirect("home")
        else:
            return render(request, "login.html", {"error": "Invalid credentials"})
    return render(request, "login.html")


def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        # Authenticate user using Django authentication system
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("home")  # Redirect to home page upon successful login
        else:
            return render(request, "login.html", {"error": "Invalid credentials"})

    return render(request, "login.html")


def get_instance_api_links(instance_name):
    import json
    import os
    from heappe_ui.models import InstanceCredentials

    base_path = "/opt/heappe-deployment/"
    app_settings_path = os.path.join(base_path, instance_name, "app", "confs", "appsettings.json")
    app_settings_data_path = os.path.join(base_path, instance_name, "app", "confs", "appsettings-data.json")

    # Defaults
    heappe_host = ""
    heappe_postfix = ""
    heappe_swagger_path = "swagger"

    datastaging_host = ""
    datastaging_postfix = ""
    datastaging_swagger_path = "swagger"

    # Try reading appsettings.json
    if os.path.exists(app_settings_path):
        try:
            with open(app_settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                deployment_settings = data.get("ApplicationAPISettings", {}).get("DeploymentSettings", {})
                heappe_host = deployment_settings.get("Host", "")
                heappe_postfix = deployment_settings.get("HostPostfix", "")

                swagger_settings = data.get("ApplicationAPISettings", {}).get("SwaggerDocSettings", {})
                heappe_swagger_path = swagger_settings.get("PrefixDocPath", "swagger")
        except Exception as e:
            print(f"Error reading appsettings.json for links: {e}")

    # Try reading appsettings-data.json
    if os.path.exists(app_settings_data_path):
        try:
            with open(app_settings_data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config_settings = data.get("ApplicationAPIConfiguration", {})
                swagger_settings = config_settings.get("SwaggerConfiguration", {})
                datastaging_host = swagger_settings.get("Host", "")
                datastaging_postfix = swagger_settings.get("HostPostfix", "")
                datastaging_swagger_path = swagger_settings.get("PrefixDocPath", "swagger")
        except Exception as e:
            print(f"Error reading appsettings-data.json for links: {e}")

    # Fallbacks from DB if not populated or files not found
    try:
        instance = InstanceCredentials.objects.filter(instance_name=instance_name).first()
    except Exception:
        instance = None

    if instance:
        if not heappe_host:
            host_val = instance.heappe_host
            port_val = instance.heappe_port
            if port_val:
                heappe_host = f"{host_val}:{port_val}"
            else:
                heappe_host = host_val
            heappe_postfix = instance_name if instance_name != "dev" else ""

        if not datastaging_host:
            host_val = instance.heappe_host
            port_val = instance.heappe_port
            if port_val and port_val.isdigit():
                ds_port = int(port_val) + 1
                datastaging_host = f"{host_val}:{ds_port}"
            else:
                datastaging_host = f"{host_val}:5001"
            datastaging_postfix = ""

    # Build clean URLs
    def clean_url(host, postfix=None, path=None):
        if not host:
            return ""
        url = host.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
        if postfix:
            postfix_clean = postfix.strip().strip('/')
            if postfix_clean:
                url = url.rstrip('/') + '/' + postfix_clean
        if path:
            url = url.rstrip('/') + '/' + path.strip().lstrip('/')
        return url

    heappe_api_url = clean_url(heappe_host, heappe_postfix)
    heappe_swagger_url = clean_url(heappe_host, heappe_postfix, heappe_swagger_path + "/index.html")

    datastaging_api_url = clean_url(datastaging_host, datastaging_postfix)
    datastaging_swagger_url = clean_url(datastaging_host, datastaging_postfix, datastaging_swagger_path + "/index.html")

    return {
        "heappe_api_url": heappe_api_url,
        "heappe_swagger_url": heappe_swagger_url,
        "datastaging_api_url": datastaging_api_url,
        "datastaging_swagger_url": datastaging_swagger_url,
    }


def get_dynamic_dictionary(request: HttpRequest, endpoint_name: str) -> list:
    """Fetch dictionary items from HEAppE Dictionary API with fallback support."""
    if not hasattr(request, "api_instance") or not request.api_instance:
        return []
    import requests as req_lib
    base_url = request.api_instance.configuration.host
    endpoint_clean = endpoint_name.lstrip('/')
    if not endpoint_clean.startswith("heappe/Dictionary/"):
        endpoint_clean = f"heappe/Dictionary/{endpoint_clean}"
    try:
        resp = req_lib.get(
            f"{base_url}/{endpoint_clean}",
            verify=False,
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def invalidate_adaptor_users_cache(request=None):
    """Invalidate session and global cache for adaptor users and roles."""
    if request and hasattr(request, "session"):
        request.session.pop("all_adaptor_users_cache", None)
        request.session.pop("all_adaptor_users_cache_time", None)
    try:
        import os
        import time
        from django.conf import settings
        timestamp_file = os.path.join(settings.BASE_DIR, "metadata_last_modified.txt")
        with open(timestamp_file, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass