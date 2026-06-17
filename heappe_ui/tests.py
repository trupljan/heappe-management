from django.test import TestCase, RequestFactory
from django.http import HttpResponse, Http404
from django.core.exceptions import PermissionDenied
from django.conf import settings
from heappe_ui.middleware import HeappeExceptionMiddleware

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

