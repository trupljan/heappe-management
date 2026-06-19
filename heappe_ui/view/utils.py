from .imports import *
from datetime import datetime
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required


PROTOCOL_CHOICES = [
    (1, "Network Share"),
    (2, "SFTP/SCP"),
    (3, "Local SFTP/SCP"),
]

SCHEDULER_CHOICES = [
    (1, "Local Simulator"),
    (2, "PBS Pro"),
    (4, "Slurm"),
    (8, "HyperQueue"),
    (16, "FirecREST")
]

CONNECTION_PROTOCOL_CHOICES = [
    (1, "Microsoft HPC Api"),
    (2, "SSH"),
    (3, "SSH Interactive (Legacy)"),
    (4, "SSH Interactive"),
    (8, "HTTP"),
    (16, "HTTPS")
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

        # Autentizace uživatele pomocí Django autentizačního systému
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("home")  # Přesměrování na domovskou stránku po úspěšném přihlášení
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