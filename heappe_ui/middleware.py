# heappe/middleware.py
import json
import sys
sys.path.insert(1, '/Users/jakubkonvicka/Documents/GIT/Py4HEAppE/src')
import py4heappe.heappe_v5_1_0.core as hp

class HeappeSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.session_code = None
        self.api_instance = None  # zatím žádná instance

    def _init_api(self):
        if self.api_instance is None:
            configuration = hp.Configuration()
            configuration.host = "http://localhost:5005"
            self.api_instance = hp.ApiClient(configuration)
        return self.api_instance

    def _get_session_code(self):
        if self.session_code is None:
            api_instance = self._init_api()
            cred = {
                "_preload_content": False,
                "body": {
                    "Credentials": {
                        "Username": "admin",
                        "Password": "admin"
                    }
                }
            }
            print("Authenticating with credentials")
            ulmEndpoint = hp.UserAndLimitationManagementApi(api_instance)
            r = ulmEndpoint.heappe_user_and_limitation_management_authenticate_user_password_post(**cred)
            self.session_code = json.loads(r.data)
        return self.session_code

    def __call__(self, request):
        request.api_instance = self._init_api()
        request.session_code = self._get_session_code()
        print(f"session code obtained: {request.session_code}, beta")

        response = self.get_response(request)
        return response
