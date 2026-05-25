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
            use_api_key = request.session.get("heappe_use_api_key", False)

            if not use_api_key:
                if force_reauth or (now - last_auth > 300) or not session_code:
                    auth_backend = HeappeAuthBackend()
                    auth_backend.re_authenticate(request)

                    session_code = request.session.get("heappe_session_code")
                    use_api_key = request.session.get("heappe_use_api_key", False)
            else:
                if force_reauth:
                    auth_backend = HeappeAuthBackend()
                    auth_backend.re_authenticate(request)
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
                patch_api_client(api_instance)

                request.api_instance = api_instance
                request.session_code = session_code
                request.host = host

        except Exception as e:
            print(f"[middleware] Error in HeappeSessionMiddleware: {e}")

        # Check if this is a mutating request or a manual cache refresh that should invalidate the metadata cache globally
        force_refresh = request.GET.get("refresh") == "1"
        if request.method in ["POST", "PUT", "DELETE"] or force_refresh:
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