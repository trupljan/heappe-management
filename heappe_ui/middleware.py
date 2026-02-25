import time
from heappe_ui.auth_backend import HeappeAuthBackend
import py4heappe.heappe_v6.core as hp


class HeappeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return self.get_response(request)

        try:
            now = time.time()
            last_auth = request.session.get("heappe_last_auth", 0)
            force_reauth = request.session.get("force_reauth", False)
            session_code = request.session.get("heappe_session_code")

            if force_reauth or (now - last_auth > 300) or not session_code:
                auth_backend = HeappeAuthBackend()
                auth_backend.re_authenticate(request)

                session_code = request.session.get("heappe_session_code")

            user_config = hp.Configuration()
            host = request.session.get("heappe_host")

            if host:
                user_config.host = 'http://' + host if not host.startswith('http') else host
                user_config.verify_ssl = True

                request.api_instance = hp.ApiClient(user_config)
                request.session_code = session_code
                request.host = host

        except Exception as e:
            print(f"[middleware] Error in HeappeSessionMiddleware: {e}")

        return self.get_response(request)