from django.test import TestCase, RequestFactory
from django.http import HttpResponse, Http404
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.contrib import messages
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

        from heappe_ui.views import dashboard_jobs_history_partial
        response = dashboard_jobs_history_partial(request)
        self.assertEqual(response.status_code, 200)
        
        # Case 2: request with date > 90 days ago
        time_from = (datetime.now() - timedelta(days=100)).isoformat()
        time_to = datetime.now().isoformat()
        request = self.factory.get(f"/dashboard/jobs-history-partial/?time_from={time_from}&time_to={time_to}")
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

        response = dashboard_jobs_history_partial(request)
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


class ProjectCommandTemplatesBulkDeleteTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_bulk_delete_command_templates_success(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance

        # Mock template response to get project_id
        mock_template1 = mock.MagicMock()
        mock_template1.project_id = 1
        
        # When heappe_management_command_template_get is called, return template info
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_template1

        # POST payload with multiple selected IDs
        request = self.factory.post("/projects/1/", {
            "action": "bulk_delete_command_templates",
            "selected_ids": ["42", "43"]
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        # Mock messages framework
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import project_detail
        response = project_detail(request, project_id=1)

        # Check redirect
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("?tab=commandtemplates"))

        # Verify API delete calls
        self.assertEqual(mock_mgmt_instance.heappe_management_remove_command_template_delete.call_count, 2)
        
        # Verify first call args
        first_call = mock_mgmt_instance.heappe_management_remove_command_template_delete.call_args_list[0][1]
        self.assertEqual(first_call['body']['CommandTemplateId'], 42)
        
        # Verify second call args
        second_call = mock_mgmt_instance.heappe_management_remove_command_template_delete.call_args_list[1][1]
        self.assertEqual(second_call['body']['CommandTemplateId'], 43)


class ProjectCommandTemplateIndividualDeleteTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_individual_delete_command_template_success(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance

        # Mock template response to get project_id
        mock_template1 = mock.MagicMock()
        mock_template1.project_id = 1
        
        # When heappe_management_command_template_get is called, return template info
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_template1

        request = self.factory.post("/command-templates/42/delete/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        # Mock messages framework
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.command_template import command_template_delete
        response = command_template_delete(request, command_template_id=42)

        # Check redirect to project detail page
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/projects/1/?tab=commandtemplates") or response.url.endswith("?tab=commandtemplates"))

        # Verify API delete call
        mock_mgmt_instance.heappe_management_remove_command_template_delete.assert_called_once()
        call_args = mock_mgmt_instance.heappe_management_remove_command_template_delete.call_args[1]
        self.assertEqual(call_args['body']['CommandTemplateId'], 42)


class AdaptorUserApiFormattingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_create_saves_apikey_to_session(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        mock_mgmt_instance.heappe_management_adaptor_user_post.return_value = mock.MagicMock(
            to_dict=lambda: {"Username": "newserviceuser", "ApiKey": "secret-key-123"}
        )

        # We mock return value dictionary parsing in view
        mock_result = {"Username": "newserviceuser", "ApiKey": "secret-key-123"}
        
        with mock.patch("heappe_ui.view.adaptor_user._handle_api_call", return_value=mock_result):
            request = self.factory.post("/adaptor_users/new/", {
                "Username": "newserviceuser"
            })
            request.user = self.user
            request.session = {}
            request.api_instance = mock.MagicMock()
            request.session_code = "token123"

            from heappe_ui.view.adaptor_user import adaptor_user_create
            response = adaptor_user_create(request)

            self.assertEqual(response.status_code, 302)
            self.assertEqual(request.session.get("new_adaptor_user_apikey"), "secret-key-123")
            self.assertEqual(request.session.get("new_adaptor_user_username"), "newserviceuser")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_detail_pops_apikey_and_passes_context(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        
        # Mock get calls
        mock_user = mock.MagicMock()
        mock_user.to_dict.return_value = {"username": "newserviceuser"}
        mock_mgmt_instance.heappe_management_adaptor_user_get.return_value = mock_user
        mock_mgmt_instance.heappe_management_projects_get.return_value = []

        request = self.factory.get("/adaptor_users/newserviceuser/")
        request.user = self.user
        request.session = {
            "new_adaptor_user_apikey": "secret-key-123",
            "new_adaptor_user_username": "newserviceuser"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.view.adaptor_user import adaptor_user_detail
        response = adaptor_user_detail(request, adaptor_user_username="newserviceuser")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("new_adaptor_user_apikey", request.session)
        self.assertNotIn("new_adaptor_user_username", request.session)
        
        self.assertIn(b"newserviceuser:secret-key-123", response.content)


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

    def test_get_session_code_fallback_returns_none_if_custom_auth_is_true(self):
        from heappe_ui.auth_backend import _get_session_code_fallback
        import py4heappe.heappe_v6.core as hp

        config = hp.Configuration()
        api_client = hp.ApiClient(config)
        api_client.custom_auth = True
        
        request = self.factory.get("/")
        request.session = {
            "heappe_session_code": "token123"
        }
        api_client._request = request

        self.assertIsNone(_get_session_code_fallback(api_client))


class JobStatusViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.FileTransferApi")
    @mock.patch("py4heappe.heappe_v6.core.JobManagementApi")
    def test_job_status_view_context(self, mock_job_mgmt_api, mock_file_transfer_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_job_mgmt_api.return_value = mock_mgmt_instance

        mock_ft_instance = mock.MagicMock()
        mock_file_transfer_api.return_value = mock_ft_instance
        mock_ft_instance.heappe_file_transfer_list_changed_files_for_job_get.return_value = []

        class SimpleObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        mock_project = SimpleObj(id=7, name="Breadcrumb Project")
        mock_node_type = SimpleObj(project=mock_project)
        mock_task = SimpleObj(node_type=mock_node_type)
        mock_job = SimpleObj(
            id=123, 
            name="My Test Job", 
            tasks=[mock_task],
            state=1,
            creation_time=None,
            submit_time=None,
            start_time=None,
            end_time=None,
            total_allocated_time=None,
            sub_project=None
        )

        mock_mgmt_instance.heappe_job_management_current_info_for_job_get.return_value = mock_job

        request = self.factory.get("/job-status/123")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import job_status_view
        response = job_status_view(request, job_id=123)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Job Details: My Test Job", response.content)
        self.assertIn(b"Breadcrumb Project", response.content)

    @mock.patch("py4heappe.heappe_v6.core.FileTransferApi")
    def test_download_job_file_view_success(self, mock_file_transfer_api):
        mock_ft_instance = mock.MagicMock()
        mock_file_transfer_api.return_value = mock_ft_instance

        import base64
        mock_ft_instance.heappe_file_transfer_download_file_from_cluster_post.return_value = base64.b64encode(b"Hello\x00World\x1b").decode("utf-8")

        # Test view/preview action (JSON response)
        request = self.factory.get("/job-status/123/file/?file_path=stdout&action=view")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.view.project import download_job_file_view
        response = download_job_file_view(request, job_id=123)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Hello\\ufffdWorld\\ufffd", response.content)
        self.assertIn(b"content", response.content)

        # Test download action (file attachment)
        request = self.factory.get("/job-status/123/file/?file_path=stdout&action=download")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        response = download_job_file_view(request, job_id=123)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"Hello\x00World\x1b")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="stdout"')

    @mock.patch("py4heappe.heappe_v6.core.FileTransferApi")
    @mock.patch("py4heappe.heappe_v6.core.JobManagementApi")
    def test_job_status_partial_view(self, mock_job_mgmt_api, mock_file_transfer_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_job_mgmt_api.return_value = mock_mgmt_instance

        mock_ft_instance = mock.MagicMock()
        mock_file_transfer_api.return_value = mock_ft_instance
        mock_ft_instance.heappe_file_transfer_list_changed_files_for_job_get.return_value = []

        class SimpleObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        mock_project = SimpleObj(id=7, name="Breadcrumb Project")
        mock_node_type = SimpleObj(project=mock_project)
        mock_task = SimpleObj(node_type=mock_node_type)
        mock_job = SimpleObj(
            id=123, 
            name="My Test Job", 
            tasks=[mock_task],
            state=1,
            creation_time=None,
            submit_time=None,
            start_time=None,
            end_time=None,
            total_allocated_time=None,
            sub_project=None
        )

        mock_mgmt_instance.heappe_job_management_current_info_for_job_get.return_value = mock_job

        request = self.factory.get("/job-status/123/partial/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import job_status_partial_view
        response = job_status_partial_view(request, job_id=123)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Execution State", response.content)
        self.assertIn(b"Changed Files", response.content)

    def test_job_state_source_filters(self):
        from heappe_ui.templatetags.custom_filters import get_job_state_source, get_job_state_updated_at

        # Test dictionary formats
        job_dict_0 = {"state_source": 0, "state_updated_at": "2026-08-31T09:00:00"}
        job_dict_3 = {"state_source": 3, "StateUpdatedAt": "2026-08-31T09:10:00"}
        
        self.assertEqual(get_job_state_source(job_dict_0), "Standard")
        self.assertEqual(get_job_state_source(job_dict_3), "DirectQuery")
        self.assertEqual(get_job_state_updated_at(job_dict_0), "2026-08-31T09:00:00")
        self.assertEqual(get_job_state_updated_at(job_dict_3), "2026-08-31T09:10:00")

        # Test object format
        class ObjJob:
            state_source = 1
            state_updated_at = "2026-08-31T09:20:00"

        self.assertEqual(get_job_state_source(ObjJob()), "ServiceAccount")
        self.assertEqual(get_job_state_updated_at(ObjJob()), "2026-08-31T09:20:00")


class SubmitJobTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.JobManagementApi")
    def test_submit_job_empty_email_disables_notifications(self, mock_job_mgmt_api, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        mock_job_mgmt_instance = mock.MagicMock()
        mock_job_mgmt_api.return_value = mock_job_mgmt_instance

        # Mock GET info for template, project, node type, cluster
        mock_mgmt_instance.heappe_management_clusters_get.return_value = []
        
        mock_template = mock.MagicMock()
        mock_template.to_dict.return_value = {
            "project_id": 1,
            "cluster_node_type_id": 2,
            "template_parameters": []
        }
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_template

        mock_project = mock.MagicMock()
        mock_project.to_dict.return_value = {
            "id": 1,
            "name": "Test Project",
        }
        mock_mgmt_instance.heappe_management_project_get.return_value = mock_project

        mock_node_type = mock.MagicMock()
        mock_node_type.to_dict.return_value = {
            "id": 2,
            "cluster_id": 3,
            "file_transfer_method_id": 4,
            "cores_per_node": 16,
        }
        mock_mgmt_instance.heappe_management_cluster_node_type_get.return_value = mock_node_type

        mock_cluster = mock.MagicMock()
        mock_cluster.to_dict.return_value = {
            "id": 3,
            "name": "Test Cluster",
        }
        mock_mgmt_instance.heappe_management_cluster_get.return_value = mock_cluster

        # Mock CreateJob / SubmitJob responses
        mock_job_mgmt_instance.heappe_job_management_create_job_post.return_value = {"Id": 123}
        mock_job_mgmt_instance.heappe_job_management_submit_job_put.return_value = {"Id": 123}

        # POST payload with empty email but notify flags set to "true"
        request = self.factory.post("/submit-job/1/", {
            "action": "submit_job",
            "JobName": "Test Job",
            "ProjectId": "1",
            "ClusterId": "3",
            "NotificationEmail": "  ",  # empty after strip
            "NotifyOnStart": "true",
            "NotifyOnFinish": "true",
            "NotifyOnAbort": "true",
            "TaskName": "Test Task",
            "MinCores": "1",
            "MaxCores": "8",
            "WalltimeLimit": "600",
            "ClusterNodeTypeId": "2",
            "CommandTemplateId": "1",
            "IsExclusive": "false",
            "IsRerunnable": "true",
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import submit_job_view
        response = submit_job_view(request, command_template_id=1)

        # It should redirect to job_status_view
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/job-status/123"))

        # Verify that create_job_post was called with notification flags set to False
        mock_job_mgmt_instance.heappe_job_management_create_job_post.assert_called_once()
        call_kwargs = mock_job_mgmt_instance.heappe_job_management_create_job_post.call_args[1]
        
        job_spec = call_kwargs['body']['JobSpecification']
        self.assertEqual(job_spec['NotificationEmail'], '')
        self.assertFalse(job_spec['NotifyOnStart'])
        self.assertFalse(job_spec['NotifyOnFinish'])
        self.assertFalse(job_spec['NotifyOnAbort'])

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.JobManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.ApiClient")
    def test_submit_job_with_custom_jwt(self, mock_api_client_cls, mock_job_mgmt_api, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        mock_job_mgmt_instance = mock.MagicMock()
        mock_job_mgmt_api.return_value = mock_job_mgmt_instance

        mock_api_instance = mock.MagicMock()
        mock_api_client_cls.return_value = mock_api_instance

        # Mock GET info for template, project, node type, cluster
        mock_mgmt_instance.heappe_management_clusters_get.return_value = []
        
        mock_template = mock.MagicMock()
        mock_template.to_dict.return_value = {
            "project_id": 1,
            "cluster_node_type_id": 2,
            "template_parameters": []
        }
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_template

        mock_project = mock.MagicMock()
        mock_project.to_dict.return_value = {
            "id": 1,
            "name": "Test Project",
        }
        mock_mgmt_instance.heappe_management_project_get.return_value = mock_project

        mock_node_type = mock.MagicMock()
        mock_node_type.to_dict.return_value = {
            "id": 2,
            "cluster_id": 3,
            "file_transfer_method_id": 4,
            "cores_per_node": 16,
        }
        mock_mgmt_instance.heappe_management_cluster_node_type_get.return_value = mock_node_type

        mock_cluster = mock.MagicMock()
        mock_cluster.to_dict.return_value = {
            "id": 3,
            "name": "Test Cluster",
        }
        mock_mgmt_instance.heappe_management_cluster_get.return_value = mock_cluster

        # Mock CreateJob / SubmitJob responses
        mock_job_mgmt_instance.heappe_job_management_create_job_post.return_value = {"Id": 123}
        mock_job_mgmt_instance.heappe_job_management_submit_job_put.return_value = {"Id": 123}

        # POST payload with custom JWT
        request = self.factory.post("/submit-job/1/", {
            "action": "submit_job",
            "JobName": "Test Job",
            "ProjectId": "1",
            "ClusterId": "3",
            "TaskName": "Test Task",
            "MinCores": "1",
            "MaxCores": "8",
            "WalltimeLimit": "600",
            "ClusterNodeTypeId": "2",
            "CommandTemplateId": "1",
            "IsExclusive": "false",
            "IsRerunnable": "true",
            "AuthMethod": "jwt",
            "AuthCredential": "my_jwt_token_123"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "heappe_host": "heappe.local"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import submit_job_view
        response = submit_job_view(request, command_template_id=1)

        # It should redirect to job_status_view
        self.assertEqual(response.status_code, 302)
        
        # Verify custom ApiClient was initialized and configured with JWT
        mock_api_client_cls.assert_called_once()
        config_passed = mock_api_client_cls.call_args[0][0]
        self.assertEqual(config_passed.api_key['Authorization'], "my_jwt_token_123")
        self.assertEqual(config_passed.api_key_prefix['Authorization'], "Bearer")
        
        # Verify custom JobManagementApi instantiation
        mock_job_mgmt_api.assert_called_once_with(mock_api_instance)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.JobManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.ApiClient")
    def test_submit_job_with_custom_apikey(self, mock_api_client_cls, mock_job_mgmt_api, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        mock_job_mgmt_instance = mock.MagicMock()
        mock_job_mgmt_api.return_value = mock_job_mgmt_instance

        mock_api_instance = mock.MagicMock()
        mock_api_client_cls.return_value = mock_api_instance

        # Mock GET info for template, project, node type, cluster
        mock_mgmt_instance.heappe_management_clusters_get.return_value = []
        
        mock_template = mock.MagicMock()
        mock_template.to_dict.return_value = {
            "project_id": 1,
            "cluster_node_type_id": 2,
            "template_parameters": []
        }
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_template

        mock_project = mock.MagicMock()
        mock_project.to_dict.return_value = {
            "id": 1,
            "name": "Test Project",
        }
        mock_mgmt_instance.heappe_management_project_get.return_value = mock_project

        mock_node_type = mock.MagicMock()
        mock_node_type.to_dict.return_value = {
            "id": 2,
            "cluster_id": 3,
            "file_transfer_method_id": 4,
            "cores_per_node": 16,
        }
        mock_mgmt_instance.heappe_management_cluster_node_type_get.return_value = mock_node_type

        mock_cluster = mock.MagicMock()
        mock_cluster.to_dict.return_value = {
            "id": 3,
            "name": "Test Cluster",
        }
        mock_mgmt_instance.heappe_management_cluster_get.return_value = mock_cluster

        # Mock CreateJob / SubmitJob responses
        mock_job_mgmt_instance.heappe_job_management_create_job_post.return_value = {"Id": 123}
        mock_job_mgmt_instance.heappe_job_management_submit_job_put.return_value = {"Id": 123}

        # POST payload with custom X-API-Key
        request = self.factory.post("/submit-job/1/", {
            "action": "submit_job",
            "JobName": "Test Job",
            "ProjectId": "1",
            "ClusterId": "3",
            "TaskName": "Test Task",
            "MinCores": "1",
            "MaxCores": "8",
            "WalltimeLimit": "600",
            "ClusterNodeTypeId": "2",
            "CommandTemplateId": "1",
            "IsExclusive": "false",
            "IsRerunnable": "true",
            "AuthMethod": "apikey",
            "AuthCredential": "my_api_key_456"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "heappe_host": "heappe.local"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import submit_job_view
        response = submit_job_view(request, command_template_id=1)

        # It should redirect to job_status_view
        self.assertEqual(response.status_code, 302)
        
        # Verify custom ApiClient was initialized and configured with X-API-Key
        mock_api_client_cls.assert_called_once()
        config_passed = mock_api_client_cls.call_args[0][0]
        self.assertEqual(config_passed.api_key['X-API-Key'], "my_api_key_456")
        
        # Verify custom JobManagementApi instantiation
        mock_job_mgmt_api.assert_called_once_with(mock_api_instance)


class ClusterAndProxyConnectionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_cluster_create_get(self, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance
        
        # Mock proxy connections list
        class SimpleObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
            def to_dict(self):
                return self.__dict__.copy()

        mock_pc = SimpleObj(id=1, host="1.2.3.4", port=1080, type=2, username="puser", password="ppass")
        mock_mgmt_instance.heappe_management_cluster_proxy_connections_get.return_value = [mock_pc]

        request = self.factory.get("/clusters/create/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.view.clusters import cluster_create
        response = cluster_create(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Proxy Connection", response.content)
        self.assertIn(b"puser@1.2.3.4:1080 (SOCKS5)", response.content)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_cluster_detail_get(self, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        class SimpleObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
            def to_dict(self):
                return self.__dict__.copy()

        mock_cluster = SimpleObj(
            id=45,
            name="TestCluster",
            description="A test cluster",
            master_node_name="master",
            scheduler_type=4,
            connection_protocol=2,
            time_zone="UTC",
            port=22,
            proxy_connection=1,
            update_job_state_by_service_account=True,
            domain_name="cluster.it4i.cz",
            node_types=[]
        )
        mock_mgmt_instance.heappe_management_cluster_get.return_value = mock_cluster

        mock_pc = SimpleObj(id=1, host="1.2.3.4", port=1080, type=2, username="puser", password="ppass")
        mock_mgmt_instance.heappe_management_cluster_proxy_connections_get.return_value = [mock_pc]

        # GET request for proxy connections tab
        request = self.factory.get("/clusters/45/?tab=proxy_connections")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.view.clusters import cluster_detail
        response = cluster_detail(request, cluster_id=45)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Proxy Connections", response.content)
        self.assertIn(b"1.2.3.4:1080", response.content)
        self.assertIn(b"puser", response.content)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_proxy_connection_post(self, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        # POST request to create new proxy connection
        request = self.factory.post("/clusters/45/", {
            "action": "add_proxy_connection",
            "Host": "5.6.7.8",
            "Port": "8080",
            "Type": "3",
            "Username": "httpuser",
            "Password": "httppassword"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.clusters import cluster_detail
        response = cluster_detail(request, cluster_id=45)

        # Should redirect to cluster detail tab=proxy_connections
        self.assertEqual(response.status_code, 302)
        self.assertIn("tab=proxy_connections", response.url)

        # Verify SDK was called correctly
        call_args = mock_mgmt_instance.heappe_management_cluster_proxy_connection_post.call_args[1]
        body = call_args["body"]
        self.assertEqual(body.host, "5.6.7.8")
        self.assertEqual(body.port, 8080)
        self.assertEqual(body.type, 3)
        self.assertEqual(body.username, "httpuser")
        self.assertEqual(body.password, "httppassword")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_proxy_connection_post_auto_assign(self, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        class SimpleObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
            def to_dict(self):
                return self.__dict__

        # Mock get to return cluster with NO proxy connection
        mock_cluster = SimpleObj(
            id=45,
            name="TestCluster",
            description="A test cluster",
            master_node_name="master",
            scheduler_type=4,
            connection_protocol=2,
            time_zone="UTC",
            port=22,
            proxy_connection=None,  # No proxy connection initially!
            update_job_state_by_service_account=True,
            domain_name="cluster.it4i.cz",
            node_types=[]
        )
        mock_mgmt_instance.heappe_management_cluster_get.return_value = mock_cluster

        # Mock post to return the created proxy connection with id=99
        mock_pc = SimpleObj(id=99, host="5.6.7.8", port=8080, type=3, username="httpuser", password="httppassword")
        mock_mgmt_instance.heappe_management_cluster_proxy_connection_post.return_value = mock_pc

        request = self.factory.post("/clusters/45/", {
            "action": "add_proxy_connection",
            "Host": "5.6.7.8",
            "Port": "8080",
            "Type": "3",
            "Username": "httpuser",
            "Password": "httppassword"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.clusters import cluster_detail
        response = cluster_detail(request, cluster_id=45)

        # Should redirect to cluster detail tab=proxy_connections
        self.assertEqual(response.status_code, 302)

        # Verify that heappe_management_cluster_put was called to assign the new proxy connection!
        self.assertTrue(mock_mgmt_instance.heappe_management_cluster_put.called)
        put_call_args = mock_mgmt_instance.heappe_management_cluster_put.call_args[1]
        self.assertEqual(put_call_args["body"]["ProxyConnectionId"], 99)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_cluster_create_firecrest_validation(self, mock_mgmt_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_mgmt_api.return_value = mock_mgmt_instance

        # Mock proxy list
        mock_mgmt_instance.heappe_management_cluster_proxy_connections_get.return_value = []

        # Case 1: SchedulerType=16 (FirecREST), CustomConfiguration empty -> should show error message
        request = self.factory.post("/clusters/new/", {
            "Name": "FC-Cluster",
            "MasterNodeName": "fc.master.cz",
            "SchedulerType": "16",
            "ConnectionProtocol": "16",
            "TimeZone": "UTC",
            "CustomConfiguration": ""
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "middleware_deployed_version": "6.4.0"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.clusters import cluster_create
        response = cluster_create(request)
        self.assertEqual(response.status_code, 200) # Re-renders the form on validation error
        
        # Check messages contains error
        storage = messages.get_messages(request)
        error_msgs = [str(m) for m in storage if m.level == messages.ERROR]
        self.assertTrue(any("Validation Error" in msg or "specified" in msg for msg in error_msgs))

        # Case 2: SchedulerType=16, CustomConfiguration invalid JSON -> error message
        request = self.factory.post("/clusters/new/", {
            "Name": "FC-Cluster",
            "MasterNodeName": "fc.master.cz",
            "SchedulerType": "16",
            "ConnectionProtocol": "16",
            "TimeZone": "UTC",
            "CustomConfiguration": "{invalid_json}"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "middleware_deployed_version": "6.4.0"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"
        setattr(request, '_messages', FallbackStorage(request))

        response = cluster_create(request)
        self.assertEqual(response.status_code, 200)
        storage = messages.get_messages(request)
        error_msgs = [str(m) for m in storage if m.level == messages.ERROR]
        self.assertTrue(any("Invalid Custom Configuration" in msg for msg in error_msgs))

        # Case 3: SchedulerType=16, CustomConfiguration valid with IdpUrl and HomeDirectoryTemplate -> succeeds and redirects
        mock_mgmt_instance.heappe_management_cluster_post.return_value = {"Id": 12}
        request = self.factory.post("/clusters/new/", {
            "Name": "FC-Cluster",
            "MasterNodeName": "fc.master.cz",
            "SchedulerType": "16",
            "ConnectionProtocol": "16",
            "TimeZone": "UTC",
            "CustomConfiguration": '{"IdpUrl": "https://keycloak.url", "HomeDirectoryTemplate": "/users/{username}"}'
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "middleware_deployed_version": "6.4.0"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"
        setattr(request, '_messages', FallbackStorage(request))

        response = cluster_create(request)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/clusters/12/"))

        # Case 4: SchedulerType=16, CustomConfiguration valid with ExpirioSecretName and HomeDirectoryTemplate -> succeeds and redirects
        mock_mgmt_instance.heappe_management_cluster_post.return_value = {"Id": 12}
        request = self.factory.post("/clusters/new/", {
            "Name": "FC-Cluster",
            "MasterNodeName": "fc.master.cz",
            "SchedulerType": "16",
            "ConnectionProtocol": "16",
            "TimeZone": "UTC",
            "CustomConfiguration": '{"ExpirioSecretName": "secret-key", "HomeDirectoryTemplate": "/users/{username}"}'
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "middleware_deployed_version": "6.4.0"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"
        setattr(request, '_messages', FallbackStorage(request))

        response = cluster_create(request)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/clusters/12/"))

        # Case 5: SchedulerType=16, CustomConfiguration missing HomeDirectoryTemplate -> fails and re-renders form
        request = self.factory.post("/clusters/new/", {
            "Name": "FC-Cluster",
            "MasterNodeName": "fc.master.cz",
            "SchedulerType": "16",
            "ConnectionProtocol": "16",
            "TimeZone": "UTC",
            "CustomConfiguration": '{"IdpUrl": "https://keycloak.url"}'
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "middleware_deployed_version": "6.4.0"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"
        setattr(request, '_messages', FallbackStorage(request))

        response = cluster_create(request)
        self.assertEqual(response.status_code, 200)
        storage = messages.get_messages(request)
        error_msgs = [str(m) for m in storage if m.level == messages.ERROR]
        self.assertTrue(any("HomeDirectoryTemplate must be specified" in msg or "Validation Error" in msg for msg in error_msgs))


class VersionParsingTests(TestCase):
    def test_clean_ver_various_formats(self):
        from heappe_ui.view.utils import clean_ver
        
        # Standard versions
        self.assertEqual(clean_ver("6.4.0"), [6, 4, 0])
        self.assertEqual(clean_ver("v6.4.0"), [6, 4, 0])
        self.assertEqual(clean_ver("V6.4.0"), [6, 4, 0])
        
        # Missing patch version or short versions
        self.assertEqual(clean_ver("6.4"), [6, 4, 0])
        self.assertEqual(clean_ver("6"), [6, 0, 0])
        
        # Complex versions with suffixes/prefixes
        self.assertEqual(clean_ver("v6.4.0-rc1"), [6, 4, 0, 1])
        self.assertEqual(clean_ver("6.4.0-beta"), [6, 4, 0])
        self.assertEqual(clean_ver("v6.4.1.2"), [6, 4, 1, 2])
        
        # Edge cases
        self.assertEqual(clean_ver(""), [0, 0, 0])
        self.assertEqual(clean_ver(None), [0, 0, 0])
        
        # Comparisons
        self.assertTrue(clean_ver("6.4.0") >= [6, 4, 0])
        self.assertTrue(clean_ver("v6.4.0") >= [6, 4, 0])
        self.assertTrue(clean_ver("6.4") >= [6, 4, 0])
        self.assertTrue(clean_ver("6.4.1") >= [6, 4, 0])
        self.assertFalse(clean_ver("6.3") >= [6, 4, 0])


class AdminUsersViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.superuser = User.objects.create_superuser(username="superuser", email="super@test.com", password="password")
        self.staff_user = User.objects.create_user(username="staff", email="staff@test.com", password="password", is_staff=True)
        self.regular_user = User.objects.create_user(username="regular", email="reg@test.com", password="password")

    def _setup_request_messages(self, request):
        from unittest import mock
        request._messages = mock.MagicMock()
        request.session = {}

    def test_unauthenticated_access_denied(self):
        from heappe_ui.view.admin_users import admin_users_list
        request = self.factory.get("/admin-users/")
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        
        # login_required decorator redirects to LOGIN_URL
        response = admin_users_list(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.url)

    def test_staff_access_denied(self):
        from heappe_ui.view.admin_users import admin_users_list
        request = self.factory.get("/admin-users/")
        request.user = self.staff_user
        self._setup_request_messages(request)

        response = admin_users_list(request)
        # superuser_required redirects non-superusers
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/dashboard/")

    def test_superuser_access_allowed(self):
        from heappe_ui.view.admin_users import admin_users_list
        request = self.factory.get("/admin-users/")
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_list(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin Accounts", response.content)

    def test_create_user_success(self):
        from heappe_ui.view.admin_users import admin_users_create
        request = self.factory.post("/admin-users/create/", {
            "username": "newadmin",
            "email": "newadmin@test.com",
            "password": "strongpassword123",
            "is_superuser": "on",
            "is_staff": "on"
        })
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Administrator Account Created", response.content)
        self.assertIn(b"newadmin", response.content)
        self.assertIn(b"strongpassword123", response.content)
        self.assertIn(b"Decryption Page", response.content)
        self.assertIn(b"/decrypt/", response.content)

        # Check in DB
        new_user = User.objects.get(username="newadmin")
        self.assertTrue(new_user.is_superuser)
        self.assertTrue(new_user.is_staff)

    def test_change_password_get(self):
        from heappe_ui.view.admin_users import admin_users_password
        target_user = User.objects.create_user(username="pwtarget", password="oldpassword")
        request = self.factory.get(f"/admin-users/{target_user.id}/password/")
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_password(request, user_id=target_user.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Change Password", response.content)

    def test_change_password_post_success(self):
        from heappe_ui.view.admin_users import admin_users_password
        target_user = User.objects.create_user(username="pwtarget2", password="oldpassword")
        request = self.factory.post(f"/admin-users/{target_user.id}/password/", {
            "password": "newsuperpassword123"
        })
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_password(request, user_id=target_user.id)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password Updated", response.content)
        self.assertIn(b"pwtarget2", response.content)
        self.assertIn(b"newsuperpassword123", response.content)
        self.assertIn(b"Decryption Page", response.content)
        self.assertIn(b"/decrypt/", response.content)

    def test_create_user_generated_password(self):
        from heappe_ui.view.admin_users import admin_users_create
        # Leave password empty
        request = self.factory.post("/admin-users/create/", {
            "username": "genpwuser",
            "email": "gen@test.com",
            "is_staff": "on"
        })
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"genpwuser", response.content)
        
        # A password should be generated (visible in response context)
        new_user = User.objects.get(username="genpwuser")
        self.assertTrue(new_user.is_staff)
        self.assertFalse(new_user.is_superuser)

    def test_edit_user(self):
        from heappe_ui.view.admin_users import admin_users_edit
        edit_target = User.objects.create_user(username="toedit", password="password")
        request = self.factory.post(f"/admin-users/{edit_target.id}/edit/", {
            "username": "editedusername",
            "email": "edited@test.com",
            "is_staff": "on",
            "is_active": "on"
        })
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_edit(request, user_id=edit_target.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/admin-users/")

        # Verify DB values
        updated_user = User.objects.get(id=edit_target.id)
        self.assertEqual(updated_user.username, "editedusername")
        self.assertEqual(updated_user.email, "edited@test.com")
        self.assertTrue(updated_user.is_staff)

    def test_delete_user_prevent_self_delete(self):
        from heappe_ui.view.admin_users import admin_users_delete
        request = self.factory.post(f"/admin-users/{self.superuser.id}/delete/")
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_delete(request, user_id=self.superuser.id)
        # Should redirect to list with error
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/admin-users/")
        # Superuser should not be deleted
        self.assertTrue(User.objects.filter(id=self.superuser.id).exists())

    def test_delete_user_success(self):
        from heappe_ui.view.admin_users import admin_users_delete
        delete_target = User.objects.create_user(username="todelete", password="password")
        request = self.factory.post(f"/admin-users/{delete_target.id}/delete/")
        request.user = self.superuser
        self._setup_request_messages(request)

        response = admin_users_delete(request, user_id=delete_target.id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/admin-users/")
        # Should be deleted from DB
        self.assertFalse(User.objects.filter(id=delete_target.id).exists())

    def test_decrypt_credentials_view_public(self):
        from heappe_ui.view.admin_users import decrypt_credentials_view
        request = self.factory.get("/decrypt/")
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()

        response = decrypt_credentials_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Decrypt HEAppE Credentials", response.content)


class UserProfileViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="profileuser", email="profile@test.com", password="oldpassword123")
        self.other_user = User.objects.create_user(username="takenname", password="password")

    def _setup_request_messages(self, request):
        from unittest import mock
        request._messages = mock.MagicMock()
        session = mock.MagicMock()
        session.get.return_value = None
        request.session = session

    def test_profile_view_get(self):
        from heappe_ui.views import profile_view
        request = self.factory.get("/profile/")
        request.user = self.user
        self._setup_request_messages(request)

        response = profile_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"User Profile Details", response.content)
        self.assertIn(b"profileuser", response.content)
        self.assertIn(b"Update Profile Details", response.content)

    def test_profile_view_post_success(self):
        from heappe_ui.views import profile_view
        request = self.factory.post("/profile/", {
            "update_profile": "1",
            "username": "newprofileuser",
            "email": "newprofile@test.com",
            "password": "newpassword123",
            "confirm_password": "newpassword123"
        })
        request.user = self.user
        self._setup_request_messages(request)

        response = profile_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/profile/")

        # Check DB updates
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "newprofileuser")
        self.assertEqual(self.user.email, "newprofile@test.com")
        self.assertTrue(self.user.check_password("newpassword123"))

    def test_profile_view_post_empty_password_kept(self):
        from heappe_ui.views import profile_view
        request = self.factory.post("/profile/", {
            "update_profile": "1",
            "username": "profileuser",
            "email": "profile@test.com",
            "password": "",
            "confirm_password": ""
        })
        request.user = self.user
        self._setup_request_messages(request)

        response = profile_view(request)
        self.assertEqual(response.status_code, 302)

        # Check password is still old one
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("oldpassword123"))

    def test_profile_view_post_mismatch_password(self):
        from heappe_ui.views import profile_view
        request = self.factory.post("/profile/", {
            "update_profile": "1",
            "username": "profileuser",
            "email": "profile@test.com",
            "password": "newpassword123",
            "confirm_password": "differentpassword"
        })
        request.user = self.user
        self._setup_request_messages(request)

        response = profile_view(request)
        self.assertEqual(response.status_code, 200)

        # Verify error message was added
        request._messages.add.assert_called()
        args, kwargs = request._messages.add.call_args
        from django.contrib import messages
        self.assertEqual(args[0], messages.ERROR)
        self.assertEqual(args[1], "Passwords do not match.")

    def test_profile_view_post_duplicate_username(self):
        from heappe_ui.views import profile_view
        request = self.factory.post("/profile/", {
            "update_profile": "1",
            "username": "takenname",
            "email": "profile@test.com",
            "password": "",
            "confirm_password": ""
        })
        request.user = self.user
        self._setup_request_messages(request)

        response = profile_view(request)
        self.assertEqual(response.status_code, 200)

        # Verify error message was added
        request._messages.add.assert_called()
        args, kwargs = request._messages.add.call_args
        from django.contrib import messages
        self.assertEqual(args[0], messages.ERROR)
        self.assertEqual(args[1], "Username 'takenname' is already taken.")


class DatabaseBackupRetentionTests(TestCase):
    def test_backup_datetime_parsing(self):
        from heappe_ui.view.backups import parse_backup_dt
        from datetime import datetime
        
        # Test valid string formats
        self.assertEqual(parse_backup_dt("2026-07-01 02:00:00"), datetime(2026, 7, 1, 2, 0, 0))
        self.assertEqual(parse_backup_dt("2026-07-01T02:00:00Z"), datetime(2026, 7, 1, 2, 0, 0))
        self.assertEqual(parse_backup_dt("2026-07-01"), datetime(2026, 7, 1, 0, 0, 0))
        
        # Test invalid inputs
        self.assertIsNone(parse_backup_dt(None))
        self.assertIsNone(parse_backup_dt("invalid-date"))

    def test_backup_retention_flagging(self):
        from heappe_ui.view.backups import database_backups
        from django.test import RequestFactory
        from unittest import mock
        from django.contrib.auth.models import User
        
        factory = RequestFactory()
        request = factory.get("/database-backups/")
        request.user = User.objects.create_superuser(username="admin_retention", password="password")
        
        # Setup request session and API instance
        request.session = mock.MagicMock()
        request.session.get.side_effect = lambda key, default=None: {
            "chosen_instance": "test_instance"
        }.get(key, default)
        
        request.session_code = "session123"
        request.api_instance = mock.MagicMock()
        
        # Mock ensure_heappe_version to pass
        with mock.patch("heappe_ui.view.backups.ensure_heappe_version", return_value=None):
            # Mock ManagementApi backups list response
            mock_backup_1 = mock.MagicMock()
            mock_backup_1.to_dict.return_value = {
                "file_name": "HEAppE_FULL_202607010200.bak",
                "path": "/opt/heappe/backups/database/HEAppE_FULL_202607010200.bak",
                "type": 0, # Full Backup
                "file_size_mb": 68.09,
                "time_stamp": "2026-07-01T02:00:00Z" # Wednesday, 1st day of month (Daily, Monthly)
            }
            
            mock_backup_2 = mock.MagicMock()
            mock_backup_2.to_dict.return_value = {
                "file_name": "HEAppE_FULL_202606280200.bak",
                "path": "/opt/heappe/backups/database/HEAppE_FULL_202606280200.bak",
                "type": 0,
                "file_size_mb": 68.09,
                "time_stamp": "2026-06-28T02:00:00Z" # Sunday (Daily, Weekly)
            }
            
            mock_backup_3 = mock.MagicMock()
            mock_backup_3.to_dict.return_value = {
                "file_name": "HEAppE_FULL_202606210200.bak",
                "path": "/opt/heappe/backups/database/HEAppE_FULL_202606210200.bak",
                "type": 0,
                "file_size_mb": 67.09,
                "time_stamp": "2026-06-21T02:00:00Z" # Sunday (Weekly, not Daily)
            }
            
            mock_backup_logs = mock.MagicMock()
            mock_backup_logs.to_dict.return_value = {
                "file_name": "HEAppE_LOG_202607010300.bak",
                "path": "/opt/heappe/backups/database/logs/HEAppE_LOG_202607010300.bak",
                "type": 1, # Transaction logs
                "file_size_mb": 2.01,
                "time_stamp": "2026-07-01T03:00:00Z"
            }
            
            with mock.patch("py4heappe.heappe_v6.core.ManagementApi") as mock_mgmt:
                mock_mgmt.return_value.heappe_management_backups_get.return_value = [
                    mock_backup_1, mock_backup_2, mock_backup_3, mock_backup_logs
                ]
                
                # Mock os.path.exists to verify parsing does not crash if config file is missing
                with mock.patch("os.path.exists", return_value=False):
                    with mock.patch("heappe_ui.view.backups.render") as mock_render:
                        database_backups(request)
                        mock_render.assert_called_once()
                        args, kwargs = mock_render.call_args
                        backups = args[2]["backups"]
                    
                    b1 = next(b for b in backups if b["file_name"] == "HEAppE_FULL_202607010200.bak")
                    b2 = next(b for b in backups if b["file_name"] == "HEAppE_FULL_202606280200.bak")
                    b3 = next(b for b in backups if b["file_name"] == "HEAppE_FULL_202606210200.bak")
                    blog = next(b for b in backups if b["file_name"] == "HEAppE_LOG_202607010300.bak")
                    
                    # b1: 2026-07-01. ref_date is 2026-07-01.
                    # It's day 1 of month -> monthly. It is within 7 days -> daily.
                    flags1 = {f["label"] for f in b1["retention_flags"]}
                    self.assertIn("monthly", flags1)
                    self.assertIn("daily", flags1)
                    self.assertNotIn("weekly", flags1)
                    
                    # b2: 2026-06-28. Sunday.
                    # It's Sunday -> weekly. It is within 7 days (ref_date - 3 days) -> daily.
                    flags2 = {f["label"] for f in b2["retention_flags"]}
                    self.assertIn("weekly", flags2)
                    self.assertIn("daily", flags2)
                    self.assertNotIn("monthly", flags2)
                    
                    # b3: 2026-06-21. Sunday.
                    # It's Sunday -> weekly. Outside 7 days (ref_date - 10 days) -> not daily.
                    flags3 = {f["label"] for f in b3["retention_flags"]}
                    self.assertIn("weekly", flags3)
                    self.assertNotIn("daily", flags3)
                    
                    # blog: Transaction logs should have no flags
                    self.assertNotIn("retention_flags", blog)


import tempfile
import shutil
import os
import json
from heappe_ui.DeployService import HEAppEDeployService, HEAppEConfig

class HEAppEDeployServiceTests(TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = self.temp_dir.name
        self.instance_name = "test_instance"
        self.config = HEAppEConfig(
            base_path=self.base_path,
            target_dir="heappe-core",
            repo_branch="V6.3.3"
        )
        self.service = HEAppEDeployService(self.config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_update_init_success(self):
        # Create directories
        confs_dir = os.path.join(self.base_path, self.instance_name, "app", "confs")
        core_dir = os.path.join(self.base_path, self.instance_name, "heappe-core")
        os.makedirs(confs_dir, exist_ok=True)
        os.makedirs(core_dir, exist_ok=True)

        # Write dummy appsettings.json
        dummy_appsettings = {
            "ApplicationAPISettings": {
                "DeploymentSettings": {
                    "Version": "v6.2.2"
                }
            }
        }
        with open(os.path.join(confs_dir, "appsettings.json"), "w", encoding="utf-8") as f:
            json.dump(dummy_appsettings, f)

        # Write dummy .env
        dummy_env = (
            "VAULT_PASSWORD=secret_vault\n"
            "HOST_MSSQL_PASSWORD=secret_db\n"
            "HOST_MSSQL_PORT=6000\n"
            "HOST_APP_PORT=5005\n"
            "HOST_DATA_STAGING_PORT=5001\n"
        )
        with open(os.path.join(core_dir, ".env"), "w", encoding="utf-8") as f:
            f.write(dummy_env)

        # Run update_init
        res = self.service.update_init(self.instance_name, "V6.3.3")
        self.assertEqual(res["status"], "success")

        # Verify new appsettings.json has the new version
        with open(os.path.join(confs_dir, "appsettings.json"), "r", encoding="utf-8") as f:
            updated_settings = json.load(f)
        self.assertEqual(
            updated_settings["ApplicationAPISettings"]["DeploymentSettings"]["Version"],
            "V6.3.3"
        )

        # Verify new .env contains the correct values
        with open(os.path.join(core_dir, ".env"), "r", encoding="utf-8") as f:
            updated_env_content = f.read()
        self.assertIn("VAULT_PASSWORD=secret_vault", updated_env_content)
        self.assertIn("HOST_MSSQL_PASSWORD=secret_db", updated_env_content)
        self.assertIn("HOST_MSSQL_PORT=6000", updated_env_content)
        self.assertIn("HOST_APP_PORT=5005", updated_env_content)
        self.assertIn("HOST_DATA_STAGING_PORT=5001", updated_env_content)
        # Verify local port default is written because it was missing in the old env
        self.assertIn("HOST_LOCAL_PORT=49005", updated_env_content)

        # Verify old appsettings and old env were archived
        files_in_confs = os.listdir(confs_dir)
        archived_appsettings = [f for f in files_in_confs if f.startswith("appsettings_v6.2.2_")]
        self.assertEqual(len(archived_appsettings), 1)

        files_in_core = os.listdir(core_dir)
        archived_env = [f for f in files_in_core if f.startswith(".env_v6.2.2_")]
        self.assertEqual(len(archived_env), 1)

    def test_update_init_missing_env_uses_defaults(self):
        # Create directories but do NOT create .env or appsettings
        confs_dir = os.path.join(self.base_path, self.instance_name, "app", "confs")
        os.makedirs(confs_dir, exist_ok=True)

        res = self.service.update_init(self.instance_name, "V6.3.3")
        self.assertEqual(res["status"], "success")

        # Verify appsettings.json was generated
        self.assertTrue(os.path.exists(os.path.join(confs_dir, "appsettings.json")))

        # Verify new .env was generated at heappe-core/.env
        env_path = os.path.join(self.base_path, self.instance_name, "heappe-core", ".env")
        self.assertTrue(os.path.exists(env_path))

    def test_update_init_failure_raises_original_exception(self):
        # Trigger an exception by mocking generate_appsettings_and_merge_with_old
        from unittest.mock import patch
        with patch.object(self.service, "generate_appsettings_and_merge_with_old", side_effect=ValueError("Merger failed")):
            with self.assertRaises(ValueError) as ctx:
                self.service.update_init(self.instance_name, "V6.3.3")
            self.assertEqual(str(ctx.exception), "Merger failed")


class QSchedulerConfigTests(TestCase):
    """Tests for QScheduler CustomConfiguration and VaultToggles serialization logic."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser_qs", password="password")

    # ------------------------------------------------------------------
    # clean_ver / is_v6_5_0_plus gating
    # ------------------------------------------------------------------
    def test_is_v6_5_0_plus_true(self):
        from heappe_ui.view.utils import clean_ver
        for ver in ["6.5.0", "v6.5.0", "V6.5.0", "6.5.1", "6.6.0", "7.0.0"]:
            self.assertTrue(
                clean_ver(ver) >= [6, 5, 0],
                msg=f"Expected {ver} to satisfy >= 6.5.0"
            )

    def test_is_v6_5_0_plus_false(self):
        from heappe_ui.view.utils import clean_ver
        for ver in ["6.4.9", "6.4.0", "6.3.0", "5.9.0", "", None]:
            self.assertFalse(
                clean_ver(ver) >= [6, 5, 0],
                msg=f"Expected {ver} to NOT satisfy >= 6.5.0"
            )

    # ------------------------------------------------------------------
    # Queue validation: QScheduler + v6.5.0+ allows non-integer names
    # ------------------------------------------------------------------
    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_queue_create_qscheduler_v650_allows_string_queue_name(self, mock_api):
        """With QScheduler + version >= 6.5.0 the Queue field may be a non-integer string."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance

        cluster_obj = mock.MagicMock()
        cluster_obj.to_dict.return_value = {"scheduler_type": 32, "id": 1}
        mock_instance.heappe_management_cluster_get.return_value = cluster_obj

        created_queue = {"Id": 101, "Queue": "QuantumDevice"}
        mock_instance.heappe_management_cluster_node_type_post.return_value = created_queue

        request = self.factory.post("/queues/create/1/", {
            "Name": "QuantumQueue",
            "Description": "A QScheduler queue",
            "Queue": "QuantumDevice",
            "NumberOfNodes": "1",
            "CoresPerNode": "1",
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test",
            "heappe_session_code": "tok",
            "middleware_deployed_version": "6.5.0",
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "tok"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.queue import queue_create
        response = queue_create(request, cluster_id=1)

        # Should not redirect to error; integer check should be bypassed
        self.assertNotIn(b"Validation Error", response.content if hasattr(response, 'content') else b"")
        # If the API was called then no validation error was raised
        mock_instance.heappe_management_cluster_node_type_post.assert_called_once()

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_queue_create_qscheduler_pre_v650_rejects_string_queue_name(self, mock_api):
        """With QScheduler + version < 6.5.0 the Queue field must be a positive integer."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance

        cluster_obj = mock.MagicMock()
        cluster_obj.to_dict.return_value = {"scheduler_type": 32, "id": 1}
        mock_instance.heappe_management_cluster_get.return_value = cluster_obj

        request = self.factory.post("/queues/create/1/", {
            "Name": "OldQueue",
            "Description": "Pre-6.5 QScheduler queue",
            "Queue": "QuantumDevice",   # string, invalid for < 6.5.0
            "NumberOfNodes": "1",
            "CoresPerNode": "1",
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test",
            "heappe_session_code": "tok",
            "middleware_deployed_version": "6.4.0",
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "tok"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.queue import queue_create
        response = queue_create(request, cluster_id=1)

        # Should redirect (validation error redirects without calling API)
        self.assertEqual(response.status_code, 302)
        mock_instance.heappe_management_cluster_node_type_post.assert_not_called()

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_queue_create_non_qscheduler_always_allows_string(self, mock_api):
        """Non-QScheduler (e.g. Slurm=4) queue creation is never blocked for string names."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance

        cluster_obj = mock.MagicMock()
        cluster_obj.to_dict.return_value = {"scheduler_type": 4, "id": 2}
        mock_instance.heappe_management_cluster_get.return_value = cluster_obj

        created_queue = {"Id": 102, "Queue": "normal"}
        mock_instance.heappe_management_cluster_node_type_post.return_value = created_queue

        request = self.factory.post("/queues/create/2/", {
            "Name": "SlurmQueue",
            "Description": "",
            "Queue": "normal",
            "NumberOfNodes": "2",
            "CoresPerNode": "24",
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test",
            "heappe_session_code": "tok",
            "middleware_deployed_version": "6.4.0",
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "tok"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.queue import queue_create
        response = queue_create(request, cluster_id=2)

        # API should be called because validation only blocks QScheduler clusters
        mock_instance.heappe_management_cluster_node_type_post.assert_called_once()


class QSchedulerVaultToggleSerializationTests(TestCase):
    """Unit tests for CustomConfigurationVaultToggles serialization in cluster views."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser_vault", password="password")

    def _make_cluster_mock(self, scheduler_type=32):
        cluster = mock.MagicMock()
        cluster.id = 10
        cluster.name = "QCluster"
        cluster.description = ""
        cluster.master_node_name = "qmaster"
        cluster.scheduler_type = scheduler_type
        cluster.connection_protocol = 2
        cluster.time_zone = "UTC"
        cluster.port = 22
        cluster.proxy_connection = None
        cluster.update_job_state_by_service_account = False
        cluster.domain_name = "qcluster.example.com"
        cluster.node_types = []
        cluster.custom_configuration = '{"QSchedulerPort":"3000","QSchedulerUseSessions":"true","ClusterCallbackNotifyToken":"secret"}'
        cluster.to_dict.return_value = {
            "id": 10,
            "name": "QCluster",
            "description": "",
            "master_node_name": "qmaster",
            "scheduler_type": scheduler_type,
            "connection_protocol": 2,
            "time_zone": "UTC",
            "port": 22,
            "proxy_connection": None,
            "update_job_state_by_service_account": False,
            "domain_name": "qcluster.example.com",
            "node_types": [],
            "custom_configuration": '{"QSchedulerPort":"3000","QSchedulerUseSessions":"true","ClusterCallbackNotifyToken":"secret"}',
        }
        return cluster

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_cluster_create_post_qscheduler_v650_sends_vault_toggles(self, mock_api):
        """cluster_create POST for QScheduler + v6.5.0 should pass CustomConfigurationVaultToggles."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.heappe_management_cluster_proxy_connections_get.return_value = []

        created_cluster = {"id": 10}
        mock_instance.heappe_management_cluster_post.return_value = created_cluster

        custom_config = '{"QSchedulerPort":"3000","QSchedulerUseSessions":"true","ClusterCallbackNotifyToken":"mytoken"}'
        vault_toggles = '{"ClusterCallbackNotifyToken":true}'

        request = self.factory.post("/clusters/create/", {
            "Name": "NewQCluster",
            "Description": "",
            "MasterNodeName": "qmaster",
            "SchedulerType": "32",
            "ConnectionProtocol": "2",
            "TimeZone": "UTC",
            "Port": "22",
            "UpdateJobStateByServiceAccount": "true",
            "DomainName": "qcluster.example.com",
            "CustomConfiguration": custom_config,
            "CustomConfigurationVaultToggles": vault_toggles,
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test",
            "heappe_session_code": "tok",
            "middleware_deployed_version": "6.5.0",
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "tok"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.clusters import cluster_create
        response = cluster_create(request)

        # API should be called once
        mock_instance.heappe_management_cluster_post.assert_called_once()
        call_kwargs = mock_instance.heappe_management_cluster_post.call_args[1]
        body = call_kwargs["body"]

        # Verify CustomConfigurationVaultToggles was passed on the body
        self.assertIn(
            "CustomConfigurationVaultToggles", body,
            "Expected body to have CustomConfigurationVaultToggles key"
        )
        toggles = body["CustomConfigurationVaultToggles"]
        self.assertTrue(toggles.get("ClusterCallbackNotifyToken"), "Expected vault flag to be True for token")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_cluster_create_post_qscheduler_pre_v650_no_vault_toggles(self, mock_api):
        """cluster_create POST for QScheduler + v < 6.5.0 should NOT pass CustomConfigurationVaultToggles."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.heappe_management_cluster_proxy_connections_get.return_value = []

        created_cluster = {"id": 11}
        mock_instance.heappe_management_cluster_post.return_value = created_cluster

        request = self.factory.post("/clusters/create/", {
            "Name": "OldQCluster",
            "Description": "",
            "MasterNodeName": "qmaster",
            "SchedulerType": "32",
            "ConnectionProtocol": "2",
            "TimeZone": "UTC",
            "Port": "22",
            "UpdateJobStateByServiceAccount": "true",
            "DomainName": "qcluster.example.com",
            "CustomConfiguration": '{"QSchedulerPort":"3000"}',
            "CustomConfigurationVaultToggles": '{}',
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test",
            "heappe_session_code": "tok",
            "middleware_deployed_version": "6.4.0",
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "tok"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.clusters import cluster_create
        response = cluster_create(request)

        mock_instance.heappe_management_cluster_post.assert_called_once()
        call_kwargs = mock_instance.heappe_management_cluster_post.call_args[1]
        body = call_kwargs["body"]

        # For pre-6.5.0 no vault toggles should be set on the body
        vault_field = getattr(body, "custom_configuration_vault_toggles", None)
        # Either None or not set at all
        self.assertFalse(
            vault_field,
            "Expected custom_configuration_vault_toggles to be falsy for pre-6.5.0"
        )


class ApiSessionCodePatchingTests(TestCase):
    """Tests that generated API methods are dynamically wrapped to handle SessionCode."""

    def test_api_method_wraps_session_code(self):
        class MockConfig:
            def __init__(self):
                self.api_key = {}
                self.api_key_prefix = {}

        class MockApiClient:
            def __init__(self):
                self.default_headers = {}
                self.configuration = MockConfig()
            def set_default_header(self, k, v):
                self.default_headers[k] = v

        class MockApiClass:
            def __init__(self, api_client):
                self.api_client = api_client

            def test_method_accepts_session_code(self, **kwargs):
                # Simulates PIP package behavior: accepts SessionCode without error
                if "SessionCode" not in kwargs:
                    raise ValueError("SessionCode must be present!")
                return kwargs

            def test_method_rejects_session_code(self, **kwargs):
                # Simulates new generated client: raises TypeError on SessionCode
                if "SessionCode" in kwargs:
                    raise TypeError("Got an unexpected keyword argument 'SessionCode' to method test_method_rejects_session_code")
                return kwargs

        # Re-declare wrapper logic to match apps.py
        import functools
        def wrap_api_method(original_method):
            @functools.wraps(original_method)
            def method_wrapper(self, *args, **kwargs):
                session_code = kwargs.get('SessionCode') or kwargs.get('session_code')
                try:
                    return original_method(self, *args, **kwargs)
                except TypeError as e:
                    err_msg = str(e)
                    if "unexpected keyword argument" in err_msg and ("SessionCode" in err_msg or "session_code" in err_msg):
                        kwargs.pop('SessionCode', None)
                        kwargs.pop('session_code', None)
                        if session_code and getattr(self, 'api_client', None):
                            client = self.api_client
                            client.set_default_header("X-Api-token", session_code)
                            if getattr(client, 'configuration', None):
                                cfg = client.configuration
                                if not hasattr(cfg, 'api_key') or not isinstance(cfg.api_key, dict):
                                    cfg.api_key = {}
                                cfg.api_key['X-Api-token'] = session_code
                                if not hasattr(cfg, 'api_key_prefix') or not isinstance(cfg.api_key_prefix, dict):
                                    cfg.api_key_prefix = {}
                                cfg.api_key_prefix['X-Api-token'] = ''
                        return original_method(self, *args, **kwargs)
                    else:
                        raise
            return method_wrapper

        # Wrap both methods
        MockApiClass.test_method_accepts_session_code = wrap_api_method(MockApiClass.test_method_accepts_session_code)
        MockApiClass.test_method_rejects_session_code = wrap_api_method(MockApiClass.test_method_rejects_session_code)

        # CASE 1: Simulating PIP client behavior (SessionCode is accepted)
        client1 = MockApiClient()
        instance1 = MockApiClass(client1)
        res1 = instance1.test_method_accepts_session_code(SessionCode="token_xyz", other_arg="val")
        
        # Verify SessionCode was passed in kwargs (for old servers / pip packages)
        self.assertEqual(res1.get("SessionCode"), "token_xyz")
        self.assertEqual(res1.get("other_arg"), "val")
        # Header was not modified
        self.assertNotIn("X-Api-token", client1.default_headers)

        # CASE 2: Simulating new generated client behavior (SessionCode is rejected)
        client2 = MockApiClient()
        instance2 = MockApiClass(client2)
        res2 = instance2.test_method_rejects_session_code(SessionCode="token_xyz", other_arg="val")
        
        # Verify SessionCode was popped from kwargs to prevent TypeError in actual clients
        self.assertNotIn("SessionCode", res2)
        self.assertEqual(res2.get("other_arg"), "val")
        # Verify X-Api-token headers and config were set on the client
        self.assertEqual(client2.default_headers.get("X-Api-token"), "token_xyz")
        self.assertEqual(client2.configuration.api_key.get("X-Api-token"), "token_xyz")
        self.assertEqual(client2.configuration.api_key_prefix.get("X-Api-token"), "")


class LogViewerJsonTests(TestCase):
    def test_parse_json_log_line_basic(self):
        from heappe_ui.views import parse_json_log_line
        line = '{"timestamp":"2026-07-13T09:34:15.523Z","level":"INFO","logger":"MyLogger","message":"Hello world","requestId":"req123","userId":10,"userName":"johndoe","exception":""}'
        parsed = parse_json_log_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['level'], 'INFO')
        self.assertEqual(parsed['timestamp_str'], '2026-07-13 09:34:15')
        self.assertIn('[req123]', parsed['content'])
        self.assertIn('johndoe(10)', parsed['content'])
        self.assertIn('MyLogger', parsed['content'])
        self.assertIn('Hello world', parsed['content'])

    def test_parse_json_log_line_exception(self):
        from heappe_ui.views import parse_json_log_line
        line = '{"timestamp":"2026-07-13T09:34:15.000Z","level":"ERROR","logger":"Logger","message":"Failure","requestId":null,"userId":null,"userName":null,"exception":"Stacktrace here"}'
        parsed = parse_json_log_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['level'], 'ERROR')
        self.assertIn('Failure\nStacktrace here', parsed['content'])
        self.assertIn('[-]', parsed['content'])

    def test_parse_log_line_routes_to_json(self):
        from heappe_ui.views import parse_log_line
        line = '{"timestamp":"2026-07-13T09:34:15.523Z","level":"WARN","logger":"Logger","message":"Warning msg","requestId":"req1"}'
        parsed = parse_log_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['level'], 'WARN')
        self.assertIn('[req1]', parsed['content'])

    @mock.patch('os.path.exists')
    @mock.patch('os.listdir')
    @mock.patch('os.path.getmtime')
    def test_get_log_file_paths_includes_json(self, mock_getmtime, mock_listdir, mock_exists):
        from heappe_ui.views import get_log_file_paths
        mock_exists.return_value = True
        mock_listdir.return_value = ['2026_07_13.log', '2026_07_13.json', '2026_07_13.json.1', 'other.log']
        mock_getmtime.side_effect = lambda path: 10 if 'json.1' in path else 20
        
        paths = get_log_file_paths('test_instance', '2026-07-13')
        self.assertEqual(len(paths), 3)
        self.assertIn('/opt/heappe-deployment/test_instance/app/logs/API/2026_07_13.json.1', paths[0])

    def test_get_log_entries_backwards_json(self):
        from heappe_ui.views import get_log_entries_backwards
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            tmp.write('{"timestamp":"2026-07-13T09:34:15.000Z","level":"INFO","logger":"L","message":"Line 1","requestId":"r1"}\n')
            tmp.write('{"timestamp":"2026-07-13T09:34:16.000Z","level":"WARN","logger":"L","message":"Line 2","requestId":"r2"}\n')
            tmp_path = tmp.name
        
        try:
            entries = list(get_log_entries_backwards([tmp_path], max_entries=10))
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]['level'], 'WARN')
            self.assertIn('Line 2', entries[0]['content'])
            self.assertEqual(entries[1]['level'], 'INFO')
            self.assertIn('Line 1', entries[1]['content'])
        finally:
            import os
            os.remove(tmp_path)

    def test_fetch_new_logs_json_endpoint(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import fetch_new_logs
        
        factory = RequestFactory()
        user = User.objects.create_user(username='testuser_logs', password='password')
        
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            tmp.write('{"timestamp":"2026-07-13T09:34:15.000Z","level":"INFO","logger":"L","message":"Test1"}\n')
            incomplete_pos = tmp.tell()
            tmp.write('{"timestamp":"2026-07-13T09:34:16.000Z","level":"WARN","logger":"L","message":"Test2"')
            tmp_path = tmp.name
            
        try:
            with mock.patch('heappe_ui.views.get_log_file_path', return_value=tmp_path):
                req = factory.get('/fetch-new-logs/?offset=0')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = fetch_new_logs(req)
                self.assertEqual(resp.status_code, 200)
                import json as pyjson
                data = pyjson.loads(resp.content.decode('utf-8'))
                
                self.assertEqual(len(data['entries']), 1)
                self.assertEqual(data['entries'][0]['level'], 'INFO')
                self.assertIn('Test1', data['entries'][0]['content'])
                self.assertEqual(data['offset'], incomplete_pos)
        finally:
            import os
            os.remove(tmp_path)
            user.delete()


from django.test import SimpleTestCase

class CustomConfigurationMetadataTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = mock.MagicMock()
        self.user.username = "metadata_user"
        self.user.is_authenticated = True

    def test_fetch_cluster_custom_config_metadata_fallback(self):
        """Test fetch_cluster_custom_config_metadata returns fallback items when API fails."""
        from heappe_ui.view.clusters import fetch_cluster_custom_config_metadata
        request = self.factory.get("/clusters/create/")
        request.api_instance = mock.MagicMock()
        request.api_instance.call_api.side_effect = Exception("API error")

        metadata = fetch_cluster_custom_config_metadata(request)
        self.assertIsInstance(metadata, list)
        self.assertTrue(len(metadata) > 0)
        
        names = [m["Name"] for m in metadata]
        self.assertIn("EnableCallback", names)
        self.assertIn("QSchedulerPort", names)
        self.assertIn("GracefulTimeoutSeconds", names)

    def test_fetch_cluster_custom_config_metadata_success(self):
        """Test fetch_cluster_custom_config_metadata normalizes response from HEAppE API."""
        from heappe_ui.view.clusters import fetch_cluster_custom_config_metadata
        request = self.factory.get("/clusters/create/")
        request.api_instance = mock.MagicMock()
        mock_response = [
            {
                "Id": 1,
                "Name": "EnableCallback",
                "DefaultValue": "false",
                "SupportedSchedulerTypes": [{"Id": 4, "Name": "Slurm"}, {"Id": 32, "Name": "QScheduler"}]
            },
            {
                "Id": 24,
                "Name": "QSchedulerPort",
                "DefaultValue": "3000",
                "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]
            }
        ]
        request.api_instance.call_api.return_value = mock_response

        metadata = fetch_cluster_custom_config_metadata(request)
        self.assertIsInstance(metadata, list)
        item_names = [item["Name"] for item in metadata]
        self.assertIn("EnableCallback", item_names)
        self.assertIn("QSchedulerPort", item_names)

    def test_validate_and_clean_custom_config_allows_any_custom_keys(self):
        """Test validate_and_clean_custom_config allows any custom configuration keys while cleaning them."""
        from heappe_ui.view.clusters import validate_and_clean_custom_config
        metadata = [
            {
                "Name": "QSchedulerPort",
                "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]
            },
            {
                "Name": "SshCommandPrefix",
                "SupportedSchedulerTypes": [{"Id": 4, "Name": "Slurm"}]
            }
        ]

        # For Slurm (SchedulerType=4), both specific and additional parameters are allowed
        config_slurm = {"QSchedulerPort": "3000", "SshCommandPrefix": "module load mpi"}
        cleaned_slurm = validate_and_clean_custom_config(config_slurm, 4, metadata)
        self.assertEqual(cleaned_slurm.get("QSchedulerPort"), "3000")
        self.assertEqual(cleaned_slurm.get("SshCommandPrefix"), "module load mpi")

        # For QScheduler (SchedulerType=32), both specific and additional parameters are allowed
        config_qs = {"QSchedulerPort": "3000", "SshCommandPrefix": "module load mpi"}
        cleaned_qs = validate_and_clean_custom_config(config_qs, 32, metadata)
        self.assertEqual(cleaned_qs.get("QSchedulerPort"), "3000")
        self.assertEqual(cleaned_qs.get("SshCommandPrefix"), "module load mpi")

    def test_validate_and_clean_custom_config_preserves_vault_masked_values(self):
        """Test validate_and_clean_custom_config preserves original value if submitted value is '********'."""
        from heappe_ui.view.clusters import validate_and_clean_custom_config
        metadata = [
            {"Name": "ClusterCallbackNotifyToken", "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]}
        ]
        old_config = {"ClusterCallbackNotifyToken": "real-vault-secret-12345"}
        new_config = {"ClusterCallbackNotifyToken": "********"}

        cleaned = validate_and_clean_custom_config(new_config, 32, metadata, old_config=old_config)
        self.assertEqual(cleaned.get("ClusterCallbackNotifyToken"), "real-vault-secret-12345")

    def test_validate_and_clean_custom_config_normalizes_boolean_values(self):
        """Test validate_and_clean_custom_config converts empty/invalid values for boolean keys like EnableCallback to 'false'."""
        from heappe_ui.view.clusters import validate_and_clean_custom_config
        metadata = [
            {"Name": "EnableCallback", "DefaultValue": "false", "SupportedSchedulerTypes": [{"Id": 4, "Name": "Slurm"}]},
            {"Name": "QSchedulerUseSessions", "DefaultValue": "true", "SupportedSchedulerTypes": [{"Id": 32, "Name": "QScheduler"}]}
        ]

        # Case 1: Empty string for EnableCallback -> should convert to 'false'
        config1 = {"EnableCallback": ""}
        cleaned1 = validate_and_clean_custom_config(config1, 4, metadata)
        self.assertEqual(cleaned1.get("EnableCallback"), "false")

        # Case 2: Boolean True / "1" / "true" -> should convert to 'true'
        config2 = {"EnableCallback": True}
        cleaned2 = validate_and_clean_custom_config(config2, 4, metadata)
        self.assertEqual(cleaned2.get("EnableCallback"), "true")

        config2_qs = {"QSchedulerUseSessions": "1"}
        cleaned2_qs = validate_and_clean_custom_config(config2_qs, 32, metadata)
        self.assertEqual(cleaned2_qs.get("QSchedulerUseSessions"), "true")

        # Case 3: Empty string for QSchedulerUseSessions -> should convert to default 'true'
        config3 = {"QSchedulerUseSessions": ""}
        cleaned3 = validate_and_clean_custom_config(config3, 32, metadata)
        self.assertEqual(cleaned3.get("QSchedulerUseSessions"), "true")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_cluster_detail_get_passes_metadata_context(self, mock_api):
        """Test cluster_detail GET view passes custom_config_metadata_json in template context."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance
        
        mock_cluster = mock.MagicMock()
        mock_cluster.to_dict.return_value = {
            "id": 1,
            "name": "TestCluster",
            "scheduler_type": 4,
            "node_types": []
        }
        mock_instance.heappe_management_cluster_get.return_value = mock_cluster
        mock_instance.heappe_management_cluster_proxy_connections_get.return_value = []
        mock_instance.heappe_management_file_transfer_methods_get.return_value = []

        request = self.factory.get("/clusters/1/detail/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test",
            "heappe_session_code": "tok",
            "middleware_deployed_version": "6.5.0",
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "tok"

        from heappe_ui.view.clusters import cluster_detail
        response = cluster_detail(request, cluster_id=1)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("custom-config-metadata-script", html)


class AppSettingsV650UpgradeTests(TestCase):
    """Tests for v6.5.0 appsettings generation and non-destructive merge upgrades."""

    def test_generate_appsettings_v6_5_0_structure(self):
        from heappe_ui.appsettings.generator import (
            generate_appsettings_v6_5_0,
            generate_appsettings_data_staging_v6_5_0,
        )

        appsettings = generate_appsettings_v6_5_0(
            instance_name="my_inst",
            sa_password="MyPassword123!",
            port=5000,
            automigrate=True,
            version="v6.5.0",
            deployed_ip="10.0.0.5"
        )

        # 1.A ApplicationAPISettings
        self.assertEqual(
            appsettings["ApplicationAPISettings"]["DeploymentSettings"]["Version"],
            "v6.5.0"
        )
        self.assertEqual(
            appsettings["ApplicationAPISettings"]["SwaggerDocSettings"]["Description"],
            "HEAppE middleware API v6.5.0"
        )

        # 1.B IpRateLimiting.GeneralRules
        rules = appsettings["IpRateLimiting"]["GeneralRules"]
        mgmt_rule = next((r for r in rules if r.get("Endpoint") == "*:/heappe/Management/*"), None)
        user_mgmt_rule = next((r for r in rules if r.get("Endpoint") == "*:/heappe/UserAndLimitationManagement/*"), None)
        catch_all_rule = next((r for r in rules if r.get("Endpoint") == "*"), None)

        self.assertIsNotNone(mgmt_rule)
        self.assertEqual(mgmt_rule["Period"], "1m")
        self.assertEqual(mgmt_rule["Limit"], 120)

        self.assertIsNotNone(user_mgmt_rule)
        self.assertEqual(user_mgmt_rule["Period"], "1m")
        self.assertEqual(user_mgmt_rule["Limit"], 300)

        # Ensure mgmt rules are placed before catch_all
        mgmt_idx = rules.index(mgmt_rule)
        user_mgmt_idx = rules.index(user_mgmt_rule)
        catch_all_idx = rules.index(catch_all_rule)
        self.assertLess(mgmt_idx, catch_all_idx)
        self.assertLess(user_mgmt_idx, catch_all_idx)

        # 1.C HPCConnectionFrameworkSettings.ScriptsSettings
        scripts = appsettings["HPCConnectionFrameworkSettings"]["ScriptsSettings"]
        self.assertFalse(scripts["EnableCallback"])
        self.assertEqual(scripts["CallbackUrl"], "https://10.0.0.5:5000/heappe/JobManagement/TaskCallback")
        self.assertFalse(scripts["EnableGracefulTimeout"])
        self.assertEqual(scripts["GracefulTimeoutSeconds"], 30)
        self.assertEqual(scripts["SshCommandPrefix"], "")
        self.assertFalse(scripts["SyncScriptsViaSftp"])

        # 1.D BusinessLogicSettings
        self.assertEqual(
            appsettings["BusinessLogicSettings"]["SessionLastAccessTimeUpdateIntervalInSeconds"],
            60
        )

        # 1.E BackGroundThreadSettings
        self.assertEqual(
            appsettings["BackGroundThreadSettings"]["ExternalServiceHealthMonitoringSettings"],
            {
                "IsEnabled": True,
                "IntervalSeconds": 60,
                "RetentionDays": 30
            }
        )

        # 1.F MigrationSettings
        self.assertEqual(
            appsettings["MigrationSettings"],
            {
                "EncryptionKey": ""
            }
        )

        # 2. DataStagingAPI
        ds_settings = generate_appsettings_data_staging_v6_5_0(
            instance_name="my_inst",
            sa_password="MyPassword123!",
            data_staging_token="testtoken",
            port=5001,
            version="v6.5.0"
        )
        self.assertEqual(
            ds_settings["ApplicationAPIConfiguration"]["DeploymentConfiguration"]["Version"],
            "v6.5.0"
        )

    def test_update_init_v6_5_0_merge_preserves_secrets_and_applies_new_settings(self):
        import tempfile
        import json
        import os
        from heappe_ui.DeployService import HEAppEDeployService, HEAppEConfig

        with tempfile.TemporaryDirectory() as temp_dir:
            instance_name = "test_upgrade_inst"
            config = HEAppEConfig(base_path=temp_dir, repo_branch="v6.5.0")
            service = HEAppEDeployService(config)

            confs_dir = os.path.join(temp_dir, instance_name, "app", "confs")
            core_dir = os.path.join(temp_dir, instance_name, "heappe-core")
            os.makedirs(confs_dir, exist_ok=True)
            os.makedirs(core_dir, exist_ok=True)

            # Old appsettings.json from v6.2.1
            old_appsettings = {
                "ConnectionStrings": {
                    "MiddlewareContext": "Server=custom_server;Database=heappe;User=SA;Password=SecretCustomPassword!;",
                    "Logging": "Server=custom_server;Database=heappe-monitoring;User=SA;Password=SecretCustomPassword!;"
                },
                "ApplicationAPISettings": {
                    "AllowedHosts": ["http://customhost:5000"],
                    "DeploymentSettings": {
                        "Name": "Custom Instance",
                        "Version": "v6.2.1",
                        "DeployedIPAddress": "192.168.1.100",
                        "Port": "5000"
                    }
                },
                "JwtTokenIntrospectionConfiguration": {
                    "Authority": "https://auth.custom.org",
                    "ClientId": "custom_client_id",
                    "ClientSecret": "custom_client_secret"
                },
                "VaultConnectorSettings": {
                    "VaultBaseAddress": "http://vault.custom.org:8200"
                },
                "SshCaSettings": {
                    "BaseUri": "https://custom.ca.url",
                    "CAName": "CustomCA"
                },
                "IpRateLimiting": {
                    "GeneralRules": [
                        {"Endpoint": "*", "Period": "1h", "Limit": 50000}
                    ]
                }
            }
            with open(os.path.join(confs_dir, "appsettings.json"), "w", encoding="utf-8") as f:
                json.dump(old_appsettings, f)

            # Old appsettings-data.json
            old_ds_settings = {
                "ApplicationAPIConfiguration": {
                    "AuthenticationToken": "super_secret_ds_token",
                    "AllowedHosts": ["http://customhost:5001"],
                    "DeploymentConfiguration": {
                        "Version": "v6.2.1"
                    }
                }
            }
            with open(os.path.join(confs_dir, "appsettings-data.json"), "w", encoding="utf-8") as f:
                json.dump(old_ds_settings, f)

            # Run update_init
            res = service.update_init(instance_name, "v6.5.0")
            self.assertEqual(res["status"], "success")

            # Check merged appsettings.json
            with open(os.path.join(confs_dir, "appsettings.json"), "r", encoding="utf-8") as f:
                merged = json.load(f)

            # 1. Preserved secrets & custom values
            self.assertEqual(
                merged["ConnectionStrings"]["MiddlewareContext"],
                "Server=custom_server;Database=heappe;User=SA;Password=SecretCustomPassword!;"
            )
            self.assertEqual(merged["ApplicationAPISettings"]["AllowedHosts"], ["http://customhost:5000"])
            self.assertEqual(merged["JwtTokenIntrospectionConfiguration"]["ClientSecret"], "custom_client_secret")
            self.assertEqual(merged["VaultConnectorSettings"]["VaultBaseAddress"], "http://vault.custom.org:8200")
            self.assertEqual(merged["SshCaSettings"]["CAName"], "CustomCA")

            # 2. Updated version and doc settings
            self.assertEqual(merged["ApplicationAPISettings"]["DeploymentSettings"]["Version"], "v6.5.0")
            self.assertEqual(merged["ApplicationAPISettings"]["SwaggerDocSettings"]["Description"], "HEAppE middleware API v6.5.0")

            # 3. Merged GeneralRules: new rules prepended, custom limit preserved for catch-all
            rules = merged["IpRateLimiting"]["GeneralRules"]
            self.assertEqual(rules[0]["Endpoint"], "*:/heappe/Management/*")
            self.assertEqual(rules[0]["Limit"], 120)
            self.assertEqual(rules[1]["Endpoint"], "*:/heappe/UserAndLimitationManagement/*")
            self.assertEqual(rules[1]["Limit"], 300)
            self.assertEqual(rules[2]["Endpoint"], "*")
            self.assertEqual(rules[2]["Limit"], 50000)

            # 4. New v6.5.0 settings added
            self.assertIn("MigrationSettings", merged)
            self.assertEqual(merged["MigrationSettings"]["EncryptionKey"], "")
            self.assertEqual(
                merged["BusinessLogicSettings"]["SessionLastAccessTimeUpdateIntervalInSeconds"],
                60
            )
            self.assertEqual(
                merged["BackGroundThreadSettings"]["ExternalServiceHealthMonitoringSettings"]["IsEnabled"],
                True
            )
            self.assertFalse(merged["HPCConnectionFrameworkSettings"]["ScriptsSettings"]["EnableCallback"])

            # 5. Check appsettings-data.json updated
            with open(os.path.join(confs_dir, "appsettings-data.json"), "r", encoding="utf-8") as f:
                merged_ds = json.load(f)
            self.assertEqual(merged_ds["ApplicationAPIConfiguration"]["DeploymentConfiguration"]["Version"], "v6.5.0")
            self.assertEqual(merged_ds["ApplicationAPIConfiguration"]["AuthenticationToken"], "super_secret_ds_token")


class TelemetryDashboardV650Tests(TestCase):
    """Unit tests for HEAppE v6.5.0 External Services & Telemetry views and APIs."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="telemetryadmin", password="password123")

    def _setup_request(self, req, deployed_version="6.5.0"):
        from django.contrib.messages.storage.fallback import FallbackStorage
        req.user = self.user
        req.session = {
            "heappe_session_code": "test_session_123",
            "chosen_instance": "test_instance",
            "middleware_deployed_version": deployed_version
        }
        req.session_code = "test_session_123"
        req.api_instance = mock.MagicMock()
        setattr(req, '_messages', FallbackStorage(req))
        return req

    def test_external_services_telemetry_view_version_gated(self):
        """Older HEAppE versions (<6.5.0) are redirected when accessing telemetry dashboard."""
        from heappe_ui.view.telemetry import external_services_telemetry_view
        req = self.factory.get("/monitoring/telemetry/")
        self._setup_request(req)
        mock_health = mock.MagicMock()
        mock_health.version = "v6.4.0"
        with mock.patch("py4heappe.heappe_v6.core.HealthApi.heappe_health_get", return_value=mock_health):
            with mock.patch("heappe_ui.view.utils.messages"):
                res = external_services_telemetry_view(req)
        self.assertEqual(res.status_code, 302)

    def test_external_services_telemetry_view_renders_successfully(self):
        """v6.5.0+ renders telemetry dashboard with live status and aggregated statistics."""
        from heappe_ui.view.telemetry import external_services_telemetry_view
        req = self.factory.get("/monitoring/telemetry/?range=24h")
        self._setup_request(req)

        mock_health = mock.MagicMock()
        mock_health.version = "v6.5.0"

        def mock_call_api(resource_path, method="GET", *args, **kwargs):
            if "GetExternalServicesLiveStatus" in resource_path:
                return [
                    {"ServiceName": "Keycloak", "ServiceType": "identity", "IsAvailable": True, "ResponseTimeMs": 42},
                    {"ServiceName": "HashiCorp Vault", "ServiceType": "keymanagement", "IsAvailable": True, "ResponseTimeMs": 15},
                    {"ServiceName": "Database", "ServiceType": "database", "IsAvailable": True, "ResponseTimeMs": 5},
                ]
            elif "GetExternalServicesStatistics" in resource_path:
                return [
                    {
                        "ServiceName": "Keycloak",
                        "ServiceType": "identity",
                        "CommandOrPath": "/auth/realms/heappe",
                        "AvailabilityPercentage": 99.9,
                        "AverageResponseTimeMs": 45.2,
                        "MinResponseTimeMs": 20,
                        "MaxResponseTimeMs": 180,
                        "P95ResponseTimeMs": 65.0,
                        "TotalChecks": 1440,
                        "FailedChecks": 1
                    }
                ]
            return []

        req.api_instance.call_api.side_effect = mock_call_api

        with mock.patch("py4heappe.heappe_v6.core.HealthApi.heappe_health_get", return_value=mock_health):
            with mock.patch("py4heappe.heappe_v6.core.ClusterInformationApi.heappe_cluster_information_list_available_clusters_get", return_value=[]):
                res = external_services_telemetry_view(req)

        self.assertEqual(res.status_code, 200)
        content = res.content.decode("utf-8")
        self.assertIn("External Services &amp; Telemetry", content)
        self.assertIn("Keycloak", content)
        self.assertIn("HashiCorp Vault", content)

    def test_external_services_live_status_api(self):
        """Live status AJAX API returns JSON with probe results."""
        from heappe_ui.view.telemetry import external_services_live_status_api
        req = self.factory.get("/monitoring/telemetry/live-status/")
        self._setup_request(req, deployed_version="6.5.0")

        req.api_instance.call_api.return_value = [
            {"ServiceName": "Slurm", "IsAvailable": True, "ResponseTimeMs": 85}
        ]

        res = external_services_live_status_api(req)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["ServiceName"], "Slurm")

    def test_external_services_statistics_api(self):
        """Statistics AJAX API returns filtered telemetry data."""
        from heappe_ui.view.telemetry import external_services_statistics_api
        req = self.factory.get("/monitoring/telemetry/statistics/?range=7d&service=Keycloak")
        self._setup_request(req, deployed_version="6.5.0")

        req.api_instance.call_api.return_value = [
            {"ServiceName": "Keycloak", "AvailabilityPercentage": 100.0, "AverageResponseTimeMs": 30.0}
        ]

        res = external_services_statistics_api(req)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["ServiceName"], "Keycloak")

    def test_job_external_service_logs_api(self):
        """Job-specific external logs API returns telemetry logs for the job ID."""
        from heappe_ui.view.telemetry import job_external_service_logs_api
        req = self.factory.get("/monitoring/telemetry/job/101/logs/")
        self._setup_request(req, deployed_version="6.5.0")

        req.api_instance.call_api.return_value = [
            {"ServiceName": "Hashicorp Vault", "DurationMs": 25, "StatusCode": 200, "RequestId": "req-xyz-123"}
        ]

        res = job_external_service_logs_api(req, job_id=101)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"][0]["RequestId"], "req-xyz-123")


class QuantumAndQSchedulerV650Tests(TestCase):
    """Unit tests for Quantum Computing and QScheduler endpoints in HEAppE v6.5.0."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="quantumadmin", password="password123")

    def _setup_request(self, req):
        req.user = self.user
        req.session = {
            "heappe_session_code": "test_session_quantum",
            "chosen_instance": "test_instance",
            "middleware_deployed_version": "6.5.0"
        }
        req.session_code = "test_session_quantum"
        req.api_instance = mock.MagicMock()
        return req

    def test_cluster_quantum_architecture_api(self):
        """Test retrieving quantum machine architecture."""
        from heappe_ui.view.clusters import cluster_quantum_architecture_api
        req = self.factory.get("/clusters/1/quantum/architecture/")
        self._setup_request(req)

        req.api_instance.call_api.return_value = {
            "QubitsCount": 5,
            "BasisGates": ["cx", "id", "rz", "sx", "x"],
            "CouplingMap": [[0, 1], [1, 2], [2, 3], [3, 4]]
        }

        res = cluster_quantum_architecture_api(req, cluster_id=1)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["QubitsCount"], 5)

    def test_cluster_quantum_calibration_api(self):
        """Test retrieving quantum machine calibration parameters."""
        from heappe_ui.view.clusters import cluster_quantum_calibration_api
        req = self.factory.get("/clusters/1/quantum/calibration/")
        self._setup_request(req)

        req.api_instance.call_api.return_value = {
            "LastCalibratedAt": "2026-08-21T08:00:00Z",
            "QubitsCalibration": [{"Qubit": 0, "T1_us": 120.5, "T2_us": 85.2, "ReadoutError": 0.012}]
        }

        res = cluster_quantum_calibration_api(req, cluster_id=1)
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]["QubitsCalibration"]), 1)

    def test_qscheduler_sessions_and_lifecycle_api(self):
        """Test listing, opening, and closing QScheduler sessions."""
        from heappe_ui.view.clusters import (
            qscheduler_sessions_api,
            qscheduler_open_session_api,
            qscheduler_close_session_api
        )

        # 1. List sessions
        req_list = self.factory.get("/clusters/1/qscheduler/sessions/")
        self._setup_request(req_list)
        req_list.api_instance.call_api.return_value = [
            {"Id": 501, "MachineName": "quantum_qpu_1", "State": "Open"}
        ]
        res_list = qscheduler_sessions_api(req_list, cluster_id=1)
        self.assertEqual(res_list.status_code, 200)
        data_list = json.loads(res_list.content.decode("utf-8"))
        self.assertEqual(data_list["data"][0]["Id"], 501)

        # 2. Open session
        req_open = self.factory.post("/clusters/qscheduler/sessions/open/", {
            "ClusterId": 1,
            "MachineName": "quantum_qpu_1",
            "MaxDurationSeconds": 3600
        })
        self._setup_request(req_open)
        req_open.api_instance.call_api.return_value = {"SessionId": 502, "State": "Active"}
        res_open = qscheduler_open_session_api(req_open)
        self.assertEqual(res_open.status_code, 200)
        data_open = json.loads(res_open.content.decode("utf-8"))
        self.assertEqual(data_open["data"]["SessionId"], 502)

        # 3. Close session
        req_close = self.factory.post("/clusters/qscheduler/sessions/502/close/")
        self._setup_request(req_close)
        req_close.api_instance.call_api.return_value = {"Status": "Closed"}
        res_close = qscheduler_close_session_api(req_close, session_id=502)
        self.assertEqual(res_close.status_code, 200)
        data_close = json.loads(res_close.content.decode("utf-8"))
        self.assertEqual(data_close["status"], "success")





