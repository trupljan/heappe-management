import time
from heappe_ui.auth_backend import HeappeAuthBackend
import py4heappe.heappe_v6.core as hp


class HeappeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if any(p in path for p in ["/instances/", "/logout/", "/login/", "/reconnect/"]):
            return self.get_response(request)

        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return self.get_response(request)

        try:
            now = time.time()
            last_auth = request.session.get("heappe_last_auth", 0)
            force_reauth = request.session.get("force_reauth", False)
            session_code = request.session.get("heappe_session_code")
            use_api_key = request.session.get("heappe_use_api_key", False)

            last_failed_auth = request.session.get("heappe_last_failed_auth", 0)
            should_attempt = True
            if not force_reauth and (now - last_failed_auth < 30):
                should_attempt = False

            if not use_api_key:
                if force_reauth or (now - last_auth > 300) or not session_code:
                    if should_attempt:
                        auth_backend = HeappeAuthBackend()
                        auth_user = auth_backend.re_authenticate(request)
                        if not auth_user:
                            # Clear old session code to trigger retry later, but keep configuration intact
                            request.session.pop("heappe_session_code", None)
                            request.session["heappe_last_failed_auth"] = now
                        else:
                            # Reset failed auth timestamp on success
                            request.session["heappe_last_failed_auth"] = 0
                    
                    session_code = request.session.get("heappe_session_code")
                    use_api_key = request.session.get("heappe_use_api_key", False)
                    request.session["force_reauth"] = False
            else:
                if force_reauth:
                    if should_attempt:
                        auth_backend = HeappeAuthBackend()
                        auth_user = auth_backend.re_authenticate(request)
                        if not auth_user:
                            request.session.pop("heappe_session_code", None)
                            request.session["heappe_last_failed_auth"] = now
                        else:
                            request.session["heappe_last_failed_auth"] = 0
                    use_api_key = request.session.get("heappe_use_api_key", False)
                    request.session["force_reauth"] = False

            user_config = hp.Configuration()
            host = request.session.get("heappe_host")

            if host:
                user_config.host = 'http://' + host if not host.startswith('http') else host
                user_config.verify_ssl = True

                if use_api_key:
                    username = request.session.get("heappe_username")
                    password = request.session.get("heappe_password")
                    user_config.api_key['X-API-Key'] = f"{username}:{password}"
                    api_instance = hp.ApiClient(user_config)
                    api_instance.set_default_header("X-API-Key", f"{username}:{password}")
                else:
                    api_instance = hp.ApiClient(user_config)

                from heappe_ui.auth_backend import patch_api_client
                api_instance._request = request
                patch_api_client(api_instance)

                request.api_instance = api_instance
                request.session_code = session_code
                request.host = host

        except Exception as e:
            print(f"[middleware] Error in HeappeSessionMiddleware: {e}")

        # Check if this is a manual cache refresh that should invalidate the session cache
        force_refresh = request.GET.get("refresh") == "1"
        if force_refresh:
            cache_keys = [
                "clusters_cache",
                "node_types_cache",
                "all_adaptor_users_cache",
                "accountings_cache",
                "queue_groups_cache",
                "mappings_cache",
                "projects_list_cache"
            ]
            for key in cache_keys:
                request.session.pop(key, None)
                request.session.pop(f"{key}_time", None)
            
            # Pop all project-specific command templates caches and individual command template detail caches
            for key in list(request.session.keys()):
                if key.startswith("command_templates_cache_") or key.startswith("command_template_detail_cache_"):
                    request.session.pop(key, None)
                    request.session.pop(f"{key}_time", None)
            
            # Also clear the cached middleware version and update-check info
            request.session.pop("last_middleware_check_time", None)
            request.session.pop("last_middleware_checked_instance", None)
            request.session.pop("middleware_update_available", None)
            request.session.pop("middleware_deployed_version", None)
            request.session.pop("middleware_latest_version", None)
            
            from django.http import HttpResponseRedirect
            query_params = request.GET.copy()
            query_params.pop('refresh', None)
            redirect_path = request.path
            if query_params:
                redirect_path += '?' + query_params.urlencode()
            return HttpResponseRedirect(redirect_path)

        # Check if this is a mutating request that should invalidate the metadata cache globally
        if request.method in ["POST", "PUT", "DELETE"]:
            path = request.path
            if any(p in path for p in ["/clusters/", "/queues/", "/projects/", "/command-templates/", "/queue-groups/", "/accounting/"]):
                import os
                from django.conf import settings
                timestamp_file = os.path.join(settings.BASE_DIR, "metadata_last_modified.txt")
                try:
                    with open(timestamp_file, "w") as f:
                        f.write(str(time.time()))
                except Exception as ex:
                    print(f"[middleware] Error updating metadata timestamp: {ex}")

        return self.get_response(request)


class HeappeExceptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from django.conf import settings
        import django.core.exceptions
        import django.http
        from django.shortcuts import render
        import traceback

        # Do not catch Django's internal control exceptions
        if isinstance(exception, (
            django.http.Http404,
            django.core.exceptions.PermissionDenied,
            django.core.exceptions.SuspiciousOperation,
            django.core.exceptions.MiddlewareNotUsed,
        )):
            return None

        error_type = exception.__class__.__name__
        error_message = str(exception)
        error_status = getattr(exception, 'status', None)

        is_heappe_error = False
        if error_status:
            is_heappe_error = True
        else:
            exc_lower = error_type.lower() + " " + error_message.lower()
            if any(term in exc_lower for term in ["timeout", "conn", "unreachable", "refused", "maxretry", "apiexception"]):
                is_heappe_error = True

        # If in debug mode, let Django raise the standard traceback screen unless it's a HEAppE error
        if settings.DEBUG and not is_heappe_error:
            return None

        # Log the exception for tracing in server logs
        print(f"[HeappeExceptionMiddleware] Caught unhandled exception: {exception}")
        traceback.print_exc()
        tb_str = traceback.format_exc()

        error_body = getattr(exception, 'body', None)

        if error_body and isinstance(error_body, str):
            try:
                import json
                body_json = json.loads(error_body)
                if isinstance(body_json, dict):
                    error_message = body_json.get('ErrorMessage') or body_json.get('message') or body_json.get('detail') or error_message
            except Exception:
                pass

        # Determine specific messaging based on exception type and status code
        error_title = "HEAppE Instance Error"
        error_desc = "The application encountered an issue communicating with the HEAppE service."
        error_icon = "bi-cloud-slash-fill"
        error_theme = "danger"

        # Check by status code
        if error_status:
            try:
                status_int = int(error_status)
                if status_int == 404:
                    error_title = "Resource Not Found"
                    error_desc = "The requested resource, object, or page does not exist on the HEAppE server."
                    error_icon = "bi-question-circle-fill"
                    error_theme = "warning"
                elif status_int in (401, 403):
                    # Invalidate session code on auth errors
                    request.session.pop("heappe_session_code", None)
                    request.session["force_reauth"] = True
                    error_title = "Access Denied / Unauthorized"
                    error_desc = "Your session may have expired, credentials might be invalid, or you lack permission for this request."
                    error_icon = "bi-shield-lock-fill"
                    error_theme = "dark"
                elif status_int in (502, 503, 504):
                    error_title = "HEAppE Service Unavailable"
                    error_desc = "The HEAppE server is temporarily offline, overloaded, or undergoing maintenance."
                    error_icon = "bi-hdd-network-fill"
                    error_theme = "danger"
            except (ValueError, TypeError):
                pass
        else:
            # Check by exception type / message
            exc_lower = error_type.lower() + " " + error_message.lower()
            if "timeout" in exc_lower:
                error_title = "Connection Timeout"
                error_desc = "The connection to the HEAppE server timed out. The service might be busy or unreachable."
                error_icon = "bi-hourglass-split"
                error_theme = "danger"
            elif "conn" in exc_lower or "unreachable" in exc_lower or "refused" in exc_lower or "maxretry" in exc_lower:
                error_title = "HEAppE Server Unreachable"
                error_desc = "Could not establish a connection to the HEAppE server host. Please check network settings or server status."
                error_icon = "bi-wifi-off"
                error_theme = "danger"

        # Retrieve active instance info from session
        instance_name = request.session.get("chosen_instance", "N/A")
        host_url = request.session.get("heappe_host_url") or request.session.get("heappe_host", "N/A")

        # Save details to session for error reporting endpoint
        from datetime import datetime
        username = request.user.username if hasattr(request, 'user') and request.user.is_authenticated else 'Anonymous'
        request.session['last_error_report'] = {
            'instance_name': instance_name,
            'host_url': host_url,
            'current_path': request.path,
            'username': username,
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'error_title': error_title,
            'error_desc': error_desc,
            'error_type': error_type,
            'error_status': error_status,
            'error_message': error_message,
            'traceback': tb_str
        }

        context = {
            "error_type": error_type,
            "error_message": error_message,
            "error_status": error_status,
            "instance_name": instance_name,
            "host_url": host_url,
            "current_path": request.path,
            "error_title": error_title,
            "error_desc": error_desc,
            "error_icon": error_icon,
            "error_theme": error_theme,
            "traceback": tb_str,
            "debug_mode": settings.DEBUG,
        }

        # Render custom elegant error page
        response = render(request, "heappe_error.html", context)
        # Set the status code on the response if available, or fallback to 500
        if error_status and isinstance(error_status, int) and 400 <= error_status < 600:
            response.status_code = error_status
        else:
            response.status_code = 500
        return response