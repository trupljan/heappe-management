import json
import sys
import time
from django.contrib.auth.models import User

from heappe_ui import DeployService
from heappe_ui.DeployService import get_instance_settings
from py4heappe.heappe_v6_0_0.core import AuthenticateUserPasswordModel, PasswordCredentialsExt

# přidání knihovny py4heappe
sys.path.insert(1, './py4heappe')
import heappe_v6_0_0.core as hp


class HeappeAuthBackend:
    """
    Django authentication backend pro ověření uživatele přes HEAppE API.
    """
    configuration = hp.Configuration()
    def authenticate(self, request, host=None, username=None, password=None, reauthenticate=False, **kwargs):

        self.configuration.host = 'http://' + host if not host.startswith('http') else host
        self.configuration.verify_ssl = True
        self.api_instance = hp.ApiClient(self.configuration)
        self.session_code = None


        ulm = hp.UserAndLimitationManagementApi(self.api_instance)
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
            print(f"[auth_backend] Attempting authentication to {host} for user {username}...")
            r = ulm.heappe_user_and_limitation_management_authenticate_user_password_post(**cred)
            self.session_code = json.loads(r.data)
            print(f"[auth_backend] Authentication successful, session_code obtained.")
        except Exception as e:
            print(f"[auth_backend] Authentication failed: {e}")
            return None

        if reauthenticate:
            try:
                #user = User.objects.get(username=username)
                print(f"[auth_backend] Reauthenticated existing user {username}.")
            except User.DoesNotExist:
                print(f"[auth_backend] User {username} not found during reauth.")
                return None
        else:
            user, created = User.objects.get_or_create(username=username)
            user.set_unusable_password()
            user.save()

        # Uložit do session jen po úspěšné autentizaci
        if request and self.session_code:
            request.session["heappe_session_code"] = self.session_code
            request.session["heappe_last_auth"] = time.time()
            request.session["heappe_host"] = host
            request.session["heappe_username"] = username
            request.session["heappe_password"] = password
            print(f"[auth_backend] Session updated with host: {host}")

        return

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    def re_authenticate(self, request):
        if request.session.get("chosen_instance") is None:
            print("[auth_backend] No chosen_instance in session for reauth.")
            return None
        chosen_instance_name = request.session["chosen_instance"]

        settings = get_instance_settings(instance_name=chosen_instance_name)
        if settings is None:
            return None
        host = settings.heappe_host
        if not host:
            host = settings.heappe_host
        username = settings.heappe_login
        password = settings.heappe_password
        port = settings.heappe_port
        if not all([host, username, password]):
            print("[auth_backend] Missing host/username/password in session for reauth.")
            return None
        user = self.authenticate(request, host=f'{host}:{port}', username=username, password=password, reauthenticate=True)
        return user