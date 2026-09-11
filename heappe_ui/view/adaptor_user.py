from .imports import *
from .utils import _create_payload, _handle_api_call, login_required, invalidate_adaptor_users_cache

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

    system_roles = []
    all_system_roles = []
    try:
        sys_res = controller.heappe_management_system_role_assignments_get(
            SessionCode=request.session_code
        )
        if sys_res:
            seen_all = set()
            seen_user = set()
            clean_username = adaptor_user_username.strip().lower()
            for item in sys_res:
                u = getattr(item, 'username', None) or (item.get('username') if isinstance(item, dict) else None)
                r = getattr(item, 'role', None) or (item.get('role') if isinstance(item, dict) else None)
                s = getattr(item, 'source', None) or (item.get('source') if isinstance(item, dict) else None) or "Dynamic"
                if not u or not r:
                    continue
                role_display = ADAPTOR_USER_INT_TO_STR.get(r, ADAPTOR_USER_INT_TO_STR.get(int(r) if str(r).isdigit() else None, r))
                u_str = str(u).strip()
                key_all = (u_str.lower(), str(role_display).lower(), str(s).lower())
                if key_all not in seen_all:
                    seen_all.add(key_all)
                    all_system_roles.append({'username': u_str, 'role': role_display, 'source': s})
                if u_str.lower() == clean_username:
                    key_user = (str(role_display).lower(), str(s).lower())
                    if key_user not in seen_user:
                        seen_user.add(key_user)
                        system_roles.append({'username': u_str, 'role': role_display, 'source': s})
    except Exception as e:
        print(f"[adaptor_user_detail] Error fetching system roles: {e}")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_adaptor_user":
            return adaptor_user_update(request, adaptor_user_username)
        if action == "toggle_user_block":
            is_blocked = request.POST.get("is_blocked") in ("true", "True", "1")
            try:
                if hasattr(controller, 'heappe_management_set_adaptor_user_block_status_post'):
                    _handle_api_call(
                        request,
                        lambda: controller.heappe_management_set_adaptor_user_block_status_post(
                            SessionCode=request.session_code,
                            Username=adaptor_user_username,
                            IsBlocked=is_blocked
                        ),
                        f"User block status updated successfully!",
                        "Failed to update block status"
                    )
                else:
                    import requests as req_lib
                    base_url = request.api_instance.configuration.host
                    resp = req_lib.post(
                        f"{base_url}/heappe/Management/SetAdaptorUserBlockStatus",
                        params={"SessionCode": request.session_code},
                        json={"Username": adaptor_user_username, "IsBlocked": is_blocked},
                        verify=False,
                        timeout=15
                    )
                    if resp.status_code == 200:
                        invalidate_adaptor_users_cache(request)
                        messages.success(request, f"User block status updated successfully!")
                    else:
                        messages.error(request, f"Failed to set user block status ({resp.status_code})")
            except Exception as e:
                messages.error(request, f"Error updating block status: {e}")
            invalidate_adaptor_users_cache(request)
            return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)
        if action == "adaptor_user_assign_to_project":
            return adaptor_user_assign_to_project(request, adaptor_user_username)
        if action == "adaptor_user_assign_to_user_group":
            return adaptor_user_assign_to_user_group(request, adaptor_user_username)
        if action == "adaptor_user_assign_system_role":
            return adaptor_user_assign_system_role(request, adaptor_user_username)
        if action == "adaptor_user_remove_system_role":
            return adaptor_user_remove_system_role(request, adaptor_user_username)
        if action == "toggle_block_status":
            return adaptor_user_toggle_block_status(request, adaptor_user_username)

    new_apikey = request.session.pop("new_adaptor_user_apikey", None)
    new_apikey_username = request.session.pop("new_adaptor_user_username", None)

    return render(request, "adaptor_user.html", {
        "adaptor_user": adaptor_user,
        "projects": all_projects,
        "new_apikey": new_apikey,
        "new_apikey_username": new_apikey_username,
        "system_roles": system_roles,
        "all_system_roles": all_system_roles,
        "roles_mapping": ADAPTOR_USER_STR_TO_INT,
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
        invalidate_adaptor_users_cache(request)
        if result and result.get("ApiKey"):
            request.session["new_adaptor_user_apikey"] = result.get("ApiKey")
            request.session["new_adaptor_user_username"] = result.get("Username")
        if result:
            return redirect("adaptor_user_detail", adaptor_user_username=result['Username'])
        else:
            next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("manage_project_adaptor_users_base")
            return redirect(next_url)


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
        invalidate_adaptor_users_cache(request)
        if result and result.get("ApiKey"):
            request.session["new_adaptor_user_apikey"] = result.get("ApiKey")
            request.session["new_adaptor_user_username"] = result.get("Username")
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
        invalidate_adaptor_users_cache(request)

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
        invalidate_adaptor_users_cache(request)
        
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
        invalidate_adaptor_users_cache(request)

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


@login_required
def adaptor_user_assign_system_role(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        role = request.POST.get("role") or request.POST.get("Role")
        role_int = None
        if role:
            if str(role).isdigit():
                role_int = int(role)
            elif role in ADAPTOR_USER_STR_TO_INT:
                role_int = ADAPTOR_USER_STR_TO_INT[role]

        if not role_int or role_int not in ADAPTOR_USER_INT_TO_STR:
            messages.error(request, "Invalid role selected.")
            return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)

        role_name = ADAPTOR_USER_INT_TO_STR[role_int]
        payload = _create_payload(request.session_code, {
            "Username": adaptor_user_username,
            "Role": role_int
        })

        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_assign_system_role_to_user_post(**payload),
            f"System role '{role_name}' successfully assigned to user '{adaptor_user_username}' across all projects!",
            f"Failed to assign system role '{role_name}' to '{adaptor_user_username}'"
        )
        invalidate_adaptor_users_cache(request)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            if result is not None:
                return JsonResponse({
                    'status': 'success',
                    'role_name': role_name,
                    'username': adaptor_user_username
                })
            return JsonResponse({'status': 'error'}, status=400)

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("adaptor_user_detail", kwargs={"adaptor_user_username": adaptor_user_username})
        return redirect(next_url)

    return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)


@login_required
def adaptor_user_remove_system_role(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        role = request.POST.get("role") or request.POST.get("Role")
        role_int = None
        if role:
            if str(role).isdigit():
                role_int = int(role)
            elif role in ADAPTOR_USER_STR_TO_INT:
                role_int = ADAPTOR_USER_STR_TO_INT[role]

        if not role_int or role_int not in ADAPTOR_USER_INT_TO_STR:
            messages.error(request, "Invalid role selected for removal.")
            return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)

        role_name = ADAPTOR_USER_INT_TO_STR[role_int]
        payload = _create_payload(request.session_code, {
            "Username": adaptor_user_username,
            "Role": role_int
        })

        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_remove_system_role_from_user_post(**payload),
            f"System role '{role_name}' removed from '{adaptor_user_username}'!",
            f"Failed to remove system role '{role_name}' from '{adaptor_user_username}'"
        )
        invalidate_adaptor_users_cache(request)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            if result is not None:
                return JsonResponse({
                    'status': 'success',
                    'role_name': role_name,
                    'username': adaptor_user_username
                })
            return JsonResponse({'status': 'error'}, status=400)

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("adaptor_user_detail", kwargs={"adaptor_user_username": adaptor_user_username})
        return redirect(next_url)

    return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)


@login_required
def adaptor_user_toggle_block_status(request: HttpRequest, adaptor_user_username: str) -> HttpResponse:
    if request.method == "POST":
        controller = hp.ManagementApi(request.api_instance)
        is_blocked_param = request.POST.get("is_blocked")
        if is_blocked_param is not None:
            is_blocked = str(is_blocked_param).strip().lower() in ("true", "1", "yes")
        else:
            action = request.POST.get("action")
            is_blocked = (action != "unblock")

        payload = _create_payload(request.session_code, {
            "Username": adaptor_user_username,
            "IsBlocked": is_blocked
        })

        action_word = "blocked" if is_blocked else "unblocked"
        result = _handle_api_call(
            request,
            lambda: controller.heappe_management_set_adaptor_user_block_status_post(**payload),
            f"Service account '{adaptor_user_username}' successfully {action_word}!",
            f"Failed to change block status for '{adaptor_user_username}'"
        )
        invalidate_adaptor_users_cache(request)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            if result is not None:
                return JsonResponse({
                    'status': 'success',
                    'username': adaptor_user_username,
                    'is_blocked': is_blocked
                })
            return JsonResponse({'status': 'error'}, status=400)

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or reverse("adaptor_user_detail", kwargs={"adaptor_user_username": adaptor_user_username})
        return redirect(next_url)


    return redirect("adaptor_user_detail", adaptor_user_username=adaptor_user_username)