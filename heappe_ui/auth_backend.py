import json
import sys
import time
from django.contrib.auth.models import User

# přidání knihovny py4heappe
sys.path.insert(1, '/Users/jakubkonvicka/Documents/GIT/Py4HEAppE/src')
import py4heappe.heappe_v5_1_0.core as hp


class HeappeAuthBackend:
    """
    Django authentication backend pro ověření uživatele přes HEAppE API.
    """

    def authenticate(self, request, host=None, username=None, password=None, reauthenticate=False, **kwargs):
        configuration = hp.Configuration()
        configuration.host = host
        self.api_instance = hp.ApiClient(configuration)
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
                user = User.objects.get(username=username)
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

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None

    def re_authenticate(self, request):
        host = request.POST.get('host') or request.GET.get('host') if request else None  # Podpora override
        if not host:
            host = request.session.get("heappe_host")
        username = request.session.get("heappe_username")
        password = request.session.get("heappe_password")
        if not all([host, username, password]):
            print("[auth_backend] Missing host/username/password in session for reauth.")
            return None
        user = self.authenticate(request, host=host, username=username, password=password, reauthenticate=True)
        return user