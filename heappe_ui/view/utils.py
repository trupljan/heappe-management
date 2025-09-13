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
    (3, "Slurm"),
    (4, "HyperQueue")
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

def _handle_api_call(
    request: HttpRequest,
    api_call: callable,
    success_message: str,
    error_message: str,
    redirect_url: Optional[str] = None
) -> HttpResponse:
    """Handle API call with error handling and messaging."""
    try:
        result = api_call()
        messages.success(request, success_message)
        try:
            return result.json()
        except Exception as e:
            return result
    except Exception as e:
        messages.error(request, f"{error_message}: {str(e)}")
        print(f"Error: {error_message}: {e}")


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