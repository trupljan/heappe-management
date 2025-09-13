import sys
import json
import time

from heappe_ui.auth_backend import HeappeAuthBackend

sys.path.insert(1, '/Users/jakubkonvicka/Documents/GIT/Py4HEAppE/src')
import py4heappe.heappe_v5_1_0.core as hp

class HeappeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            session_code = request.session.get("heappe_session_code")
            host = request.session.get("heappe_host")
            username = request.session.get("heappe_username")
            password = request.session.get("heappe_password")
            last_auth = request.session.get("heappe_last_auth", 0)

            if not session_code or (time.time() - last_auth) > 600:
                auth_backend = HeappeAuthBackend()
                user = auth_backend.re_authenticate(request)
                if user:
                    request.session["heappe_last_auth"] = time.time()
                    session_code = request.session.get("heappe_session_code")
                    host = request.session.get("heappe_host")
                else:
                    request.session.flush()
                    return self.get_response(request)

            configuration = hp.Configuration()
            configuration.host = host
            request.api_instance = hp.ApiClient(configuration)
            request.session_code = session_code
        else:
            request.api_instance = None
            request.session_code = None
        return self.get_response(request)
