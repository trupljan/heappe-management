import sys
import json
import time

from heappe_ui.auth_backend import HeappeAuthBackend

sys.path.insert(1, './py4heappe')
import heappe_v6_0_0.core as hp

class HeappeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        auth_backend = HeappeAuthBackend()
        user = auth_backend.re_authenticate(request)
        request.session["heappe_last_auth"] = time.time()
        request.api_instance = hp.ApiClient(HeappeAuthBackend.configuration)
        session_code = request.session.get("heappe_session_code")
        host = request.session.get("heappe_host")
        request.session_code = session_code

        return self.get_response(request)
