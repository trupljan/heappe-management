from .imports import *
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
    (8, "HyperQueue")
]

CONNECTION_PROTOCOL_CHOICES = [
    (1, "Microsoft HPC Api"),
    (2, "SSH"),
    (3, "SSH Interactive")
]

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
    """Create a standardized payload for API requests."""
    payload = {
        "_preload_content": False,
        "body": {"SessionCode": session_code, **data}
    }
    if id_field and id_field in data:
        payload["body"]["Id"] = data[id_field]
    return payload


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