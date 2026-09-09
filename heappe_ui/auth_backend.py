import json
import sys
import time
import inspect
from django.contrib.auth.models import User
from heappe_ui.DeployService import get_instance_settings
import py4heappe.heappe_v6.core as hp


def _get_session_code_fallback(api_instance) -> str | None:
    """Return the current session code from the request attached to api_instance, or None.

    Used to back-fill a null/empty SessionCode in request bodies so that old HEAppE server
    versions (which require SessionCode in the body) continue to work even when the management
    app authenticates via X-API-Key (where session_code would otherwise be None).
    """
    if getattr(api_instance, 'custom_auth', False):
        return None
    req = getattr(api_instance, '_request', None)
    if req is None:
        return None
    code = getattr(req, 'session_code', None)
    if code:
        return code
    try:
        return req.session.get('heappe_session_code') or None
    except Exception:
        return None


def patch_api_client(api_instance):
    if getattr(api_instance, '_is_patched', False):
        return api_instance
    original_call_api = api_instance.call_api
    sig = inspect.signature(original_call_api)

    def replace_session_code(bound_args, new_code):
        # Modify query_params
        query_params = bound_args.arguments.get('query_params')
        if query_params:
            new_query_params = []
            for name, val in query_params:
                if name == 'SessionCode':
                    new_query_params.append((name, new_code))
                else:
                    new_query_params.append((name, val))
            bound_args.arguments['query_params'] = new_query_params

        # Modify body
        body = bound_args.arguments.get('body')
        if body:
            if isinstance(body, dict):
                if 'SessionCode' in body:
                    body['SessionCode'] = new_code
            elif hasattr(body, 'SessionCode'):
                try:
                    setattr(body, 'SessionCode', new_code)
                except Exception:
                    pass
            elif hasattr(body, 'session_code'):
                try:
                    setattr(body, 'session_code', new_code)
                except Exception:
                    pass

    def patched_call_api(*args, **kwargs):
        # Bind the arguments to the signature
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        # Fail fast if connection failed recently (within 30 seconds) to avoid blocking threads on offline instance
        request = getattr(api_instance, '_request', None)
        if request:
            last_failed_auth = request.session.get("heappe_last_failed_auth", 0)
            if last_failed_auth and (time.time() - last_failed_auth < 30):
                remaining = max(1, int(30 - (time.time() - last_failed_auth)))
                raise ConnectionError(f"HEAppE connection is offline (cooldown active, auto-retry in {remaining}s).")

        # Inject default _request_timeout if not specified
        if bound_args.arguments.get('_request_timeout') is None:
            resource_path = str(bound_args.arguments.get('resource_path') or '')
            if any(heavy in resource_path for heavy in ['Backup', 'Restore', 'Migration', 'SetupSlurm', 'InitializeClusterScriptDirectory']):
                bound_args.arguments['_request_timeout'] = 300
            else:
                bound_args.arguments['_request_timeout'] = 15

        # Modify query_params
        query_params = bound_args.arguments.get('query_params')
        if query_params:
            new_query_params = []
            for name, val in query_params:
                if name == 'SessionCode' and (val is None or val == ''):
                    continue
                new_query_params.append((name, val))
            bound_args.arguments['query_params'] = new_query_params

        # Modify body
        body = bound_args.arguments.get('body')
        if body:
            if isinstance(body, dict):
                if 'SessionCode' in body and (body['SessionCode'] is None or body['SessionCode'] == ''):
                    # Try to fill SessionCode from session – old HEAppE versions require it in body.
                    # New versions ignore the field, so this is backwards-compatible.
                    # Fall back to sentinel "ignore" when no real session code is available.
                    fallback_code = _get_session_code_fallback(api_instance) or 'ignore'
                    new_body = dict(body)
                    new_body['SessionCode'] = fallback_code
                    bound_args.arguments['body'] = new_body
            elif hasattr(body, 'SessionCode') or hasattr(body, 'session_code'):
                if hasattr(body, 'SessionCode') and (getattr(body, 'SessionCode') is None or getattr(body, 'SessionCode') == ''):
                    body.SessionCode = _get_session_code_fallback(api_instance) or 'ignore'
                if hasattr(body, 'session_code') and (getattr(body, 'session_code') is None or getattr(body, 'session_code') == ''):
                    body.session_code = _get_session_code_fallback(api_instance) or 'ignore'

        def safe_truncate(val, limit=1000):
            if val is None:
                return None
            val_str = str(val)
            if len(val_str) > limit:
                return val_str[:limit] + f"... [Truncated, original length: {len(val_str)}]"
            return val_str

        # Outgoing Request Log
        resource_path = bound_args.arguments.get('resource_path', 'unknown')
        print(f"[HEAppE API Request] Outgoing path: {resource_path}")
        if body:
            single_line_body = body
            try:
                if hasattr(body, 'to_dict'):
                    single_line_body = json.dumps(body.to_dict())
                elif hasattr(body, 'to_str'):
                    single_line_body = body.to_str().replace('\n', ' ').replace('\r', '')
                else:
                    single_line_body = json.dumps(body)
            except Exception:
                single_line_body = str(body).replace('\n', ' ').replace('\r', '')
            print(f"[HEAppE API Request] Body payload: {single_line_body}")

        request = getattr(api_instance, '_request', None)
        if request:
            if not hasattr(request, 'heappe_api_logs'):
                request.heappe_api_logs = []
            
            # Format payload for log
            log_body = None
            if body:
                try:
                    if hasattr(body, 'to_dict'):
                        log_body = body.to_dict()
                    elif hasattr(body, 'to_str'):
                        log_body = body.to_str()
                    else:
                        log_body = body
                except Exception:
                    log_body = str(body)
            
            request.heappe_api_logs.append({
                'type': 'request',
                'path': resource_path,
                'body': safe_truncate(log_body)
            })

        try:
            response = original_call_api(*bound_args.args, **bound_args.kwargs)
            # Incoming Response Log
            print(f"[HEAppE API Response] Success on: {resource_path}")
            
            headers_dict = {}
            if hasattr(response, 'headers'):
                headers_dict = dict(response.headers)
            elif hasattr(response, 'getheaders'):
                headers_dict = dict(response.getheaders())
            
            if headers_dict:
                print(f"[HEAppE API Response Headers]: {json.dumps(headers_dict)}")

            log_content = None
            if hasattr(response, 'data'):
                # Preload content = False -> response is RESTResponse with .data (bytes)
                data = response.data
                if isinstance(data, bytes):
                    try:
                        data = data.decode('utf-8')
                    except Exception:
                        pass
                log_content = data
            else:
                # Preload content = True -> response is deserialized model
                try:
                    if hasattr(response, 'to_dict'):
                        log_content = response.to_dict()
                    elif hasattr(response, 'to_str'):
                        log_content = response.to_str()
                    else:
                        log_content = response
                except Exception as ex:
                    log_content = f"Serialization error: {ex}"
            print(f"[HEAppE API Response Content] Path {resource_path}: {log_content}")
            
            if request:
                request.heappe_api_logs.append({
                    'type': 'response',
                    'path': resource_path,
                    'content': safe_truncate(log_content)
                })
            return response
        except Exception as e:
            print(f"[HEAppE API Response] Exception raised on: {resource_path} | Details: {e}")
            if request:
                if not hasattr(request, 'heappe_api_logs'):
                    request.heappe_api_logs = []
                request.heappe_api_logs.append({
                    'type': 'exception',
                    'path': resource_path,
                    'details': safe_truncate(str(e))
                })
            # Check for 401/403 (unauthorized/expired token) to trigger auto-reauthentication
            status = getattr(e, 'status', None)
            try:
                status_int = int(status)
            except (ValueError, TypeError):
                status_int = None

            if status_int in (401, 403) and not getattr(api_instance, '_is_reauthenticating', False):
                request = getattr(api_instance, '_request', None)
                if request:
                    print(f"[HEAppE API client] Caught {status_int}. Attempting transparent auto-reauthentication...")
                    from heappe_ui.auth_backend import HeappeAuthBackend
                    auth_backend = HeappeAuthBackend()
                    auth_user = auth_backend.re_authenticate(request)
                    if auth_user:
                        new_session_code = request.session.get("heappe_session_code")
                        if new_session_code:
                            print(f"[HEAppE API client] Re-authentication successful. Retrying call with new session code.")
                            request.session_code = new_session_code
                            replace_session_code(bound_args, new_session_code)
                            # Retry the call
                            return original_call_api(*bound_args.args, **bound_args.kwargs)
            raise

    api_instance.call_api = patched_call_api
    api_instance._is_patched = True
    return api_instance


class HeappeAuthBackend:
    """
    Django authentication backend.
    """

    def authenticate(self, request, host=None, username=None, password=None, reauthenticate=False, **kwargs):
        if not host:
            return None

        config = hp.Configuration()
        config.api_key = {}
        config.api_key_prefix = {}
        host_url = 'http://' + host if not host.startswith('http') else host
        config.host = host_url
        config.verify_ssl = True

        # Try API Key authentication first
        config.api_key = {'X-API-Key': f"{username}:{password}"}
        api_instance = hp.ApiClient(config)
        api_instance.set_default_header("X-API-Key", f"{username}:{password}")
        api_instance._is_reauthenticating = True
        api_instance._request = request
        patch_api_client(api_instance)

        ulm = hp.UserAndLimitationManagementApi(api_instance)

        use_api_key = False
        session_code = None

        try:
            print(f"[auth_backend] Attempting X-API-Key authentication to {host_url} for user {username}...")
            ulm.heappe_user_and_limitation_management_current_user_info_get()
            print(f"[auth_backend] X-API-Key authentication successful.")
            use_api_key = True

            # Best-effort: also obtain a session code so that old HEAppE server versions
            # (which require SessionCode in some request bodies) continue to work.
            # New servers ignore the field, so this is backwards-compatible.
            try:
                cred = {
                    "_preload_content": False,
                    "body": {
                        "Credentials": {
                            "Username": username,
                            "Password": password,
                        }
                    }
                }
                r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(**cred)
                session_code = json.loads(r.data)
                print(f"[auth_backend] Also obtained session code for old-API body compatibility.")
            except Exception as e_sc:
                print(f"[auth_backend] Could not obtain session code (new API only, no fallback): {e_sc}")
        except Exception as e:
            print(f"[auth_backend] X-API-Key authentication failed or unsupported: {e}")
            
            # If the failure is due to a network connection/timeout issue, do not attempt fallback
            exc_str = f"{type(e).__name__} {str(e)}".lower()
            if any(term in exc_str for term in ["timeout", "conn", "unreachable", "refused", "maxretry", "socket"]):
                print("[auth_backend] Network error detected. Skipping fallback authentication.")
                return None

            # Fallback to session code
            config.api_key = {}
            api_instance.default_headers.pop("X-API-Key", None)

            cred = {
                "_preload_content": False,
                "body": {
                    "Credentials": {
                        "Username": username,
                        "Password": password,
                    }
                }
            }

            try:
                print(f"[auth_backend] Falling back to session code authentication...")
                r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(**cred)
                session_code = json.loads(r.data)
                print(f"[auth_backend] Session code authentication successful.")
            except Exception as e_fallback:
                print(f"[auth_backend] Fallback authentication failed: {e_fallback}")
                return None

        if reauthenticate:
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                return None
        else:
            user, created = User.objects.get_or_create(username=username)
            user.set_unusable_password()
            user.save()

        if request:
            request.session["heappe_use_api_key"] = use_api_key
            request.session["heappe_session_code"] = session_code
            request.session["heappe_last_auth"] = time.time()
            request.session["heappe_host"] = host
            request.session["heappe_host_url"] = host_url
            request.session["heappe_username"] = username
            request.session["heappe_password"] = password

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    def re_authenticate(self, request):
        chosen_instance_name = request.session.get("chosen_instance")
        if not chosen_instance_name:
            return None

        settings = get_instance_settings(instance_name=chosen_instance_name)
        if not settings:
            return None

        host = settings.heappe_host
        username = settings.heappe_login
        password = settings.heappe_password
        port = settings.heappe_port

        full_host = f"{host}:{port}" if port and port not in ['80', '443', ''] else host

        return self.authenticate(request, host=full_host, username=username, password=password, reauthenticate=True)