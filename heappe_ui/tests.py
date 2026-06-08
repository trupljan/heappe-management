from django.test import TestCase, RequestFactory
from django.http import HttpResponse, Http404
from django.core.exceptions import PermissionDenied
from django.conf import settings
from heappe_ui.middleware import HeappeExceptionMiddleware
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User

class HeappeExceptionMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = HeappeExceptionMiddleware(get_response=lambda req: HttpResponse("OK"))

    def _create_request(self, path="/", authenticated=True):
        request = self.factory.get(path)
        if authenticated:
            user = User(username="testuser")
            request.user = user
        else:
            request.user = AnonymousUser()
        request.session = {}
        return request

    def test_no_exception(self):
        request = self._create_request()
        response = self.middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_process_exception_debug_true(self):
        request = self._create_request()
        request.session["chosen_instance"] = "test_instance"
        
        # Temporarily set DEBUG to True
        old_debug = settings.DEBUG
        try:
            settings.DEBUG = True
            response = self.middleware.process_exception(request, ValueError("Test Error"))
            # In DEBUG mode, it should return None to let Django handle it
            self.assertIsNone(response)
        finally:
            settings.DEBUG = old_debug

    def test_process_exception_debug_false(self):
        request = self._create_request()
        request.session["chosen_instance"] = "test_instance"
        request.session["heappe_host"] = "http://heappe.local"
        
        # Temporarily set DEBUG to False
        old_debug = settings.DEBUG
        try:
            settings.DEBUG = False
            response = self.middleware.process_exception(request, ValueError("Test Error"))
            # It should render the template and return a 500 response
            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 500)
            self.assertIn(b"HEAppE Instance Error", response.content)
            self.assertIn(b"ValueError", response.content)
            self.assertIn(b"Test Error", response.content)
        finally:
            settings.DEBUG = old_debug

    def test_process_exception_connection_timeout(self):
        request = self._create_request()
        request.session["chosen_instance"] = "test_instance"
        request.session["heappe_host"] = "http://heappe.local"
        
        old_debug = settings.DEBUG
        try:
            settings.DEBUG = False
            response = self.middleware.process_exception(request, TimeoutError("Connection timed out"))
            self.assertIsNotNone(response)
            self.assertEqual(response.status_code, 500)
            self.assertIn(b"Connection Timeout", response.content)
            self.assertIn(b"Connection timed out", response.content)
        finally:
            settings.DEBUG = old_debug

    def test_process_exception_django_control_exceptions(self):
        request = self._create_request()
        
        old_debug = settings.DEBUG
        try:
            settings.DEBUG = False
            # Http404 should return None so Django handles it
            response = self.middleware.process_exception(request, Http404("Not Found"))
            self.assertIsNone(response)

            # PermissionDenied should return None
            response = self.middleware.process_exception(request, PermissionDenied("Denied"))
            self.assertIsNone(response)
        finally:
            settings.DEBUG = old_debug

    def test_process_exception_with_status_code(self):
        request = self._create_request()
        request.session["chosen_instance"] = "test_instance"
        request.session["heappe_host"] = "http://heappe.local"
        
        class MockApiException(Exception):
            def __init__(self, message, status):
                super().__init__(message)
                self.status = status
                self.body = '{"ErrorMessage": "Specific API Failure Details"}'
        
        old_debug = settings.DEBUG
        try:
            settings.DEBUG = False
            exc = MockApiException("API Error", 404)
            response = self.middleware.process_exception(request, exc)
            self.assertIsNotNone(response)
            # The status code should be 404
            self.assertEqual(response.status_code, 404)
            self.assertIn(b"Resource Not Found", response.content)
            self.assertIn(b"Specific API Failure Details", response.content)
        finally:
            settings.DEBUG = old_debug

    def test_process_exception_saves_error_report_to_session(self):
        request = self._create_request()
        request.session["chosen_instance"] = "test_instance"
        request.session["heappe_host"] = "http://heappe.local"
        
        old_debug = settings.DEBUG
        try:
            settings.DEBUG = False
            self.middleware.process_exception(request, ValueError("Database Connection Failure"))
            
            self.assertIn("last_error_report", request.session)
            report = request.session["last_error_report"]
            self.assertEqual(report["instance_name"], "test_instance")
            self.assertEqual(report["error_type"], "ValueError")
            self.assertEqual(report["error_message"], "Database Connection Failure")
            self.assertIn("traceback", report)
        finally:
            settings.DEBUG = old_debug

    def test_report_error_view_manual_generation_success(self):
        import json
        from heappe_ui.views import report_error_view
        
        request = self._create_request()
        request.session["middleware_deployed_version"] = "v6.1.2"
        request.session["chosen_instance"] = "test_instance"
        request.session["last_error_report"] = {
            "instance_name": "test_instance",
            "host_url": "http://heappe.local",
            "current_path": "/dashboard/",
            "username": "testuser",
            "timestamp": "2026-06-04 12:00:00",
            "error_title": "HEAppE Instance Error",
            "error_desc": "Desc",
            "error_type": "ValueError",
            "error_status": 500,
            "error_message": "Failure details",
            "traceback": "Traceback info here"
        }
        request.method = "POST"
        request.POST = {
            "screenshot": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUAAAAFCAYAAACNbyblAAAAHElEQVQI12P4//8/w38GIAXDIBKE0DHxgljNBAAO9TXL0Y4OHwAAAABJRU5ErkJggg==",
            "contact_email": "tester@example.com",
            "summary": "Test issue summary",
            "description": "Detailed test description of the problem.",
            "category": "heappe_error",
            "affected_url": "/dashboard/",
        }

        response = report_error_view(request)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["status"], "manual")
        self.assertEqual(data["to_email"], "support.heappe@it4i.cz")
        self.assertIn("[HEAppE Support]", data["subject"])
        self.assertIn("Test issue summary", data["subject"])
        self.assertIn("Detailed test description of the problem.", data["body"])
        self.assertIn("Traceback info here", data["body"])
        self.assertEqual(data["heappe_version"], "v6.1.2")
        self.assertEqual(data["chosen_instance"], "test_instance")
        self.assertIn("admin_version", data)
        self.assertIn("python_version", data)
        self.assertIn("server_os", data)
        self.assertNotIn("last_error_report", request.session)




    def test_generate_session_code_missing_credentials(self):
        request = self._create_request()
        # No credentials in session
        from heappe_ui.views import generate_session_code_view
        response = generate_session_code_view(request)
        self.assertEqual(response.status_code, 400)
        import json
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["status"], "error")
        self.assertIn("Missing credentials", data["message"])

    from unittest import mock
    @mock.patch("py4heappe.heappe_v6.core.UserAndLimitationManagementApi")
    def test_generate_session_code_success(self, mock_ulm_class):
        from unittest.mock import MagicMock
        import json
        
        # Setup mock instance and return value
        mock_ulm = MagicMock()
        mock_response = MagicMock()
        mock_response.data = b'"generated_session_token_12345"'
        mock_ulm.heappe_user_and_limitation_management_authenticate_user_password_post.return_value = mock_response
        mock_ulm_class.return_value = mock_ulm
        
        request = self._create_request()
        request.session["heappe_username"] = "user"
        request.session["heappe_password"] = "pass"
        request.session["heappe_host"] = "heappe.local"
        
        # Call the view
        from heappe_ui.views import generate_session_code_view
        response = generate_session_code_view(request)
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["session_code"], "generated_session_token_12345")
        self.assertEqual(request.session["heappe_session_code"], "generated_session_token_12345")

    def test_custom_error_templates_exist(self):
        from django.template import loader
        try:
            loader.get_template("404.html")
            loader.get_template("500.html")
            templates_ok = True
        except Exception:
            templates_ok = False
        self.assertTrue(templates_ok, "Templates 404.html and 500.html must be discoverable by loader")


from unittest import mock
from datetime import datetime, timedelta

class DashboardReportingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.JobReportingApi")
    @mock.patch("py4heappe.heappe_v6.core.HealthApi")
    def test_dashboard_view_date_bounds(self, mock_health_api, mock_job_reporting_api, mock_management_api):
        # Setup mocks
        mock_health_instance = mock.MagicMock()
        mock_health_api.return_value = mock_health_instance
        
        mock_management_instance = mock.MagicMock()
        mock_management_api.return_value = mock_management_instance
        
        mock_jr_instance = mock.MagicMock()
        mock_jr_instance.heappe_job_reporting_jobs_detailed_report_get.return_value = []
        mock_jr_instance.heappe_job_reporting_jobs_state_agregation_report_get.return_value = []
        mock_job_reporting_api.return_value = mock_jr_instance

        # Create user
        user = User.objects.create_user(username="testuser", password="password")

        # Case 1: normal request (default timedelta 1 day)
        request = self.factory.get("/dashboard/")
        request.user = user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.views import dashboard_view
        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)
        
        # Case 2: request with date > 90 days ago
        time_from = (datetime.now() - timedelta(days=100)).isoformat()
        time_to = datetime.now().isoformat()
        request = self.factory.get(f"/dashboard/?time_from={time_from}&time_to={time_to}")
        request.user = user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"
        
        # We need to support django messages since we show warning
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        response = dashboard_view(request)
        self.assertEqual(response.status_code, 200)
        
        # Check that TimeFrom passed to heappe_job_reporting_jobs_detailed_report_get is limited to 90 days
        args, kwargs = mock_jr_instance.heappe_job_reporting_jobs_detailed_report_get.call_args
        called_time_from = kwargs.get("TimeFrom")
        now = datetime.now()
        min_allowed_date = now - timedelta(days=90)
        # It should be very close to min_allowed_date (within a few seconds)
        self.assertAlmostEqual(called_time_from.timestamp(), min_allowed_date.timestamp(), delta=10)


class ProjectPresetTemplateTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_preset_template_success(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        
        # Mock responses
        mock_project = mock.MagicMock()
        mock_project.to_dict.return_value = {
            "id": 1,
            "name": "Test Project",
            "key_scripts_directory_path": "/path/to/keyscripts/"
        }
        mock_mgmt_instance.heappe_management_project_get.return_value = mock_project
        mock_mgmt_instance.heappe_management_command_template_post.return_value = {"Id": 42}
        mock_mgmt_instance.heappe_management_command_template_parameter_post.return_value = {"Id": 100}

        # Build request
        request = self.factory.post("/projects/1/", {
            "action": "create_preset_template",
            "preset_name": "test",
            "ClusterNodeTypeId": "5"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "command_templates_cache_1": [],
            "command_templates_cache_1_time": 0
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        # Mock messages framework
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import project_detail
        response = project_detail(request, project_id=1)

        # Check redirections and API calls
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("?tab=commandtemplates"))
        
        # Verify cache invalidation
        self.assertNotIn("command_templates_cache_1", request.session)
        self.assertNotIn("command_templates_cache_1_time", request.session)

        # Verify command template creation payload
        mock_mgmt_instance.heappe_management_command_template_post.assert_called_once()
        call_args = mock_mgmt_instance.heappe_management_command_template_post.call_args[1]
        self.assertEqual(call_args['body']['ProjectId'], 1)
        self.assertEqual(call_args['body']['Name'], "TestTemplate")
        self.assertEqual(call_args['body']['Description'], "Predefined test command template")
        self.assertEqual(call_args['body']['ExtendedAllocationCommand'], "")
        self.assertEqual(call_args['body']['ExecutableFile'], "/path/to/keyscripts/test.sh")
        self.assertEqual(call_args['body']['PreparationScript'], "")
        self.assertEqual(call_args['body']['ClusterNodeTypeId'], 5)
        self.assertEqual(call_args['body']['IsEnabled'], True)
        self.assertEqual(call_args['body']['TemplateParameters'], [])

        # Verify parameter creation payload
        mock_mgmt_instance.heappe_management_command_template_parameter_post.assert_called_once()
        param_call_args = mock_mgmt_instance.heappe_management_command_template_parameter_post.call_args[1]
        self.assertEqual(param_call_args['body']['CommandTemplateId'], 42)
        self.assertEqual(param_call_args['body']['Identifier'], "inputParam")


class SelfHealingSessionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("heappe_ui.auth_backend.HeappeAuthBackend.re_authenticate")
    def test_session_middleware_does_not_purge_config_on_auth_failure(self, mock_re_auth):
        mock_re_auth.return_value = None  # Auth failed

        from heappe_ui.middleware import HeappeSessionMiddleware
        middleware = HeappeSessionMiddleware(get_response=lambda req: HttpResponse("OK"))

        request = self.factory.get("/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_host": "heappe.local",
            "heappe_host_url": "http://heappe.local",
            "heappe_session_code": "old_token",
            "heappe_use_api_key": False,
            "heappe_last_auth": 0
        }

        # Run middleware
        response = middleware(request)

        # Host config should still remain
        self.assertEqual(request.session.get("heappe_host"), "heappe.local")
        self.assertEqual(request.session.get("heappe_host_url"), "http://heappe.local")
        # Session token should be popped
        self.assertNotIn("heappe_session_code", request.session)
        # Failed auth timestamp must be set
        self.assertGreater(request.session.get("heappe_last_failed_auth", 0), 0)

    @mock.patch("heappe_ui.auth_backend.HeappeAuthBackend.re_authenticate")
    def test_session_middleware_cooldown_behavior(self, mock_re_auth):
        from heappe_ui.middleware import HeappeSessionMiddleware
        import time
        middleware = HeappeSessionMiddleware(get_response=lambda req: HttpResponse("OK"))

        request = self.factory.get("/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_host": "heappe.local",
            "heappe_session_code": "old_token",
            "heappe_last_auth": 0,
            "heappe_last_failed_auth": time.time() - 10,  # 10s ago, within 30s cooldown
            "force_reauth": False
        }

        response = middleware(request)

        # Re-authenticate should NOT be called due to cooldown
        mock_re_auth.assert_not_called()

    @mock.patch("heappe_ui.auth_backend.HeappeAuthBackend.re_authenticate")
    def test_api_client_transparent_auto_reauth_success(self, mock_re_auth):
        from heappe_ui.auth_backend import patch_api_client
        import py4heappe.heappe_v6.core as hp

        class MockApiException(Exception):
            def __init__(self, status):
                self.status = status

        called_query_params = []
        def mock_call_api(resource_path, method, path_params=None, query_params=None, **kwargs):
            called_query_params.append(query_params)
            if len(called_query_params) == 1:
                raise MockApiException(401)
            return "Success response"

        config = hp.Configuration()
        api_client = hp.ApiClient(config)
        api_client.call_api = mock_call_api

        request = self.factory.get("/")
        request.session = {
            "heappe_session_code": "old_token"
        }
        
        # Configure client with request reference and force re-patching
        api_client._request = request
        api_client._is_patched = False
        patch_api_client(api_client)

        # Re-authenticate mock behavior
        def side_effect_reauth(req):
            req.session["heappe_session_code"] = "new_token"
            return self.user
        mock_re_auth.side_effect = side_effect_reauth

        # Call with session code parameter in query params
        result = api_client.call_api(
            resource_path="/test", method="GET",
            query_params=[("SessionCode", "old_token")]
        )

        # Should successfully retry and return success response
        self.assertEqual(result, "Success response")
        # Re-auth should be called once
        mock_re_auth.assert_called_once_with(request)
        # Session code updated in request
        self.assertEqual(request.session_code, "new_token")
        
        # Verify call_api was called twice (first fail, second retry)
        self.assertEqual(len(called_query_params), 2)
        # Check that the second call received 'new_token'
        self.assertIn(("SessionCode", "new_token"), called_query_params[1])


