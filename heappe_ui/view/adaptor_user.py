from .imports import *
from .utils import _create_payload, _handle_api_call, login_required

from django.urls import reverse
from django.contrib import messages

ADAPTOR_USER_STR_TO_INT = {
    "Administrator": 1,
    "Maintainer": 2,
    "Submitter": 3,
    "GroupReporter": 4,
    "Reporter": 5,
    "ManagementAdmin": 6,
    "Manager": 7
}

ADAPTOR_USER_INT_TO_STR = {v: k for k, v in ADAPTOR_USER_STR_TO_INT.items()}


@login_required
def adaptor_user_detail(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    controller = hp.ManagementApi(request.api_instance)

    user_response = controller.heappe_management_adaptor_user_get(
        SessionCode=request.session_code, Username=adaptor_user_username
    )
    adaptor_user = user_response.to_dict() if user_response else {}

    projects_response = controller.heappe_management_projects_get(
        SessionCode=request.session_code
    )

    all_projects = projects_response if projects_response is not None else []

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_adaptor_user":
            return adaptor_user_update(request, adaptor_user_username)
        if action == "adaptor_user_assign_to_project":
            return adaptor_user_assign_to_project(request, adaptor_user_username)
        if action == "adaptor_user_assign_to_user_group":
            return adaptor_user_assign_to_user_group(request, adaptor_user_username)

    return render(request, "adaptor_user.html", {
        "adaptor_user": adaptor_user,
        "projects": all_projects,
    })



@login_required
def adaptor_user_create(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return render(request, "adaptor_user.html", {})
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        payload_data = {
            "Username": request.POST.get("Username"),
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_adaptor_user_post(**payload),
            "Service account created successfully!",
            "Failed to create Service account"
        )
        if result and result.get("ApiKey"):
            messages.info(request, 
                          f'APIKEY/Password: {result.get("ApiKey")}',
                          extra_tags=f"adaptor-user-api-key"
                          )
        if result:
            return redirect("adaptor_user_detail", adaptor_user_username=result['Username'])
        else:
            return redirect("adaptor_user_create")


@login_required
def adaptor_user_update(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "GET":
        return render(request, "adaptor_user.html", {})
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        payload_data = {
            "OldUsername": adaptor_user_username,
            "NewUsername": request.POST.get("Username"),
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_adaptor_user_put(**payload),
            "Service account updated successfully!",
            "Failed to update Service account"
        )
        if result and result.get("ApiKey"):
            messages.info(request, 
                          f'APIKEY/Password: {result.get("ApiKey")}',
                          extra_tags=f"adaptor-user-api-key"
                          )
        if result:
            return redirect("adaptor_user_detail", adaptor_user_username=result['Username'])
        else:
            return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)


from django.http import JsonResponse
from django.shortcuts import redirect


@login_required
def adaptor_user_assign_to_project(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        project_id = request.POST.get("ProjectId")
        role_id = request.POST.get("role")
        role_name_display = request.POST.get("role_name_display", "Unknown Role")

        payload_data = {
            "Username": adaptor_user_username,
            "ProjectId": int(project_id),
            "Role": int(role_id)
        }
        payload = _create_payload(request.session_code, payload_data)

        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_assign_adaptor_user_to_project_post(**payload),
            "Service account assigned successfully!",
            "Failed to assign Service account"
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            if result is not None:
                return JsonResponse({
                    'status': 'success',
                    'role_name': role_name_display,
                    'username': adaptor_user_username
                })
            return JsonResponse({'status': 'error'}, status=400)

        return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)

    return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)

@login_required
def adaptor_user_unassign_from_project(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "GET":
        return render(request, "adaptor_user.html", {})
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        project_id = int(request.POST.get("ProjectId"))
        role = request.POST.get("Role")
        payload_data = {
            "Username": adaptor_user_username,
            "ProjectId": project_id,
            "Role": ADAPTOR_USER_STR_TO_INT.get(role)
        }
        payload = _create_payload(request.session_code, payload_data)
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_remove_adaptor_user_from_project_delete(**payload),
            "Service account role removed from project successfully!",
            "Failed to remove Service account role from project"
        )
        
        return redirect(f"{reverse('project_detail', kwargs={'project_id': project_id})}?tab=adaptor_users")


from django.http import JsonResponse

from django.http import JsonResponse


@login_required
def adaptor_user_assign_to_user_group(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        user_group_id = request.POST.get("UserGroupId")
        role_id = request.POST.get("role")
        project_id = request.POST.get("ProjectId")

        payload_data = {
            "Username": adaptor_user_username,
            "UserGroupId": int(user_group_id) if user_group_id else 0,
            "Role": int(role_id) if role_id and str(role_id).isdigit() else role_id
        }
        payload = _create_payload(request.session_code, payload_data)

        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_assign_adaptor_user_to_user_group_post(**payload),
            "Service account assigned to user group successfully!",
            "Failed to assign Service account to user group"
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            if result is not None:
                return JsonResponse({
                    "status": "success",
                    "role_name": request.POST.get("role_name_display"),
                    "username": adaptor_user_username
                })
            return JsonResponse({"status": "error"}, status=400)

        if project_id:
            return redirect(f"{reverse('project_detail', kwargs={'project_id': int(project_id)})}?tab=adaptor_users")
        return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)

    return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)