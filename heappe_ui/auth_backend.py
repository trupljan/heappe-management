import json
import sys
import time
import inspect
from django.contrib.auth.models import User
from heappe_ui.DeployService import get_instance_settings
import py4heappe.heappe_v6.core as hp


def patch_api_client(api_instance):
    original_call_api = api_instance.call_api
    sig = inspect.signature(original_call_api)

    def patched_call_api(*args, **kwargs):
        # Bind the arguments to the signature
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

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
                    new_body = dict(body)
                    new_body.pop('SessionCode', None)
                    bound_args.arguments['body'] = new_body
            elif hasattr(body, 'SessionCode') or hasattr(body, 'session_code'):
                if hasattr(body, 'SessionCode') and (getattr(body, 'SessionCode') is None or getattr(body, 'SessionCode') == ''):
                    body.SessionCode = None
                if hasattr(body, 'session_code') and (getattr(body, 'session_code') is None or getattr(body, 'session_code') == ''):
                    body.session_code = None

        # Outgoing Request Log
        resource_path = bound_args.arguments.get('resource_path', 'unknown')
        print(f"[HEAppE API Request] Outgoing path: {resource_path}")
        if body:
            print(f"[HEAppE API Request] Body payload: {body}")

        try:
            response = original_call_api(*bound_args.args, **bound_args.kwargs)
            # Incoming Response Log
            print(f"[HEAppE API Response] Success on: {resource_path}")
            if hasattr(response, 'data'):
                # Preload content = False -> response is RESTResponse with .data (bytes)
                data = response.data
                if isinstance(data, bytes):
                    try:
                        data = data.decode('utf-8')
                    except Exception:
                        pass
                print(f"[HEAppE API Response Content]: {data}")
            else:
                # Preload content = True -> response is deserialized model
                try:
                    if hasattr(response, 'to_dict'):
                        print(f"[HEAppE API Response Content]: {response.to_dict()}")
                    elif hasattr(response, 'to_str'):
                        print(f"[HEAppE API Response Content]: {response.to_str()}")
                    else:
                        print(f"[HEAppE API Response Content]: {response}")
                except Exception as ex:
                    print(f"[HEAppE API Response Content] Serialization error: {ex}")
            return response
        except Exception as e:
            print(f"[HEAppE API Response] Exception raised on: {resource_path} | Details: {e}")
            raise

    api_instance.call_api = patched_call_api
    return api_instance


class HeappeAuthBackend:
    """
    Django authentication backend.
    """

    def authenticate(self, request, host=None, username=None, password=None, reauthenticate=False, **kwargs):
        if not host:
            return None

        config = hp.Configuration()
        host_url = 'http://' + host if not host.startswith('http') else host
        config.host = host_url
        config.verify_ssl = True

        # Try API Key authentication first
        config.api_key['X-API-Key'] = f"{username}:{password}"
        api_instance = hp.ApiClient(config)
        api_instance.set_default_header("X-API-Key", f"{username}:{password}")
        patch_api_client(api_instance)

        ulm = hp.UserAndLimitationManagementApi(api_instance)

        use_api_key = False
        session_code = None

        try:
            print(f"[auth_backend] Attempting X-API-Key authentication to {host_url} for user {username}...")
            ulm.heappe_user_and_limitation_management_current_user_info_get()
            print(f"[auth_backend] X-API-Key authentication successful.")
            use_api_key = True
        except Exception as e:
            print(f"[auth_backend] X-API-Key authentication failed or unsupported: {e}")
            # Fallback to session code
            config.api_key.clear()
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