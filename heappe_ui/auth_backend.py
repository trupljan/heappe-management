import json
import sys
import time
from django.contrib.auth.models import User
from heappe_ui.DeployService import get_instance_settings
import py4heappe.heappe_v6.core as hp


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

        api_instance = hp.ApiClient(config)
        ulm = hp.UserAndLimitationManagementApi(api_instance)

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
            print(f"[auth_backend] Attempting authentication to {host_url} for user {username}...")
            r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(**cred)
            session_code = json.loads(r.data)
            print(f"[auth_backend] Authentication successful.")
        except Exception as e:
            print(f"[auth_backend] Authentication failed: {e}")
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

        if request and session_code:
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