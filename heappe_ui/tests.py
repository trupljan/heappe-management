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


class CommandTemplateCopyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_command_template_copy_get(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance

        mock_template = mock.MagicMock()
        mock_template.to_dict.return_value = {
            "id": 10,
            "name": "Original MPI Template",
            "description": "Original description",
            "extended_allocation_command": "--mem=8G",
            "executable_file": "/usr/bin/mpirun",
            "preparation_script": "module load mpi",
            "cluster_node_type_id": 3,
            "is_enabled": True,
            "project_id": 1,
            "template_parameters": [
                {"id": 101, "identifier": "CORES", "description": "Num cores", "query": "1..64"}
            ]
        }
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_template

        mock_p1 = mock.MagicMock()
        mock_p1.to_dict.return_value = {"id": 1, "name": "Source Project"}
        mock_p2 = mock.MagicMock()
        mock_p2.to_dict.return_value = {"id": 2, "name": "Target Project"}
        mock_mgmt_instance.heappe_management_projects_get.return_value = [mock_p1, mock_p2]

        mock_cluster = mock.MagicMock()
        mock_cluster.to_dict.return_value = {
            "id": 1,
            "name": "Cluster A",
            "node_types": [{"id": 3, "name": "Default Queue"}]
        }
        mock_mgmt_instance.heappe_management_clusters_get.return_value = [mock_cluster]

        request = self.factory.get("/command-templates/10/copy/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.command_template import command_template_copy
        response = command_template_copy(request, command_template_id=10)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Copy of Original MPI Template", content)
        self.assertIn("Target Project", content)
        self.assertIn("CORES", content)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_command_template_copy_post_success(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance

        mock_mgmt_instance.heappe_management_command_template_post.return_value = {"Id": 99}
        mock_mgmt_instance.heappe_management_command_template_parameter_post.return_value = {"Id": 201}

        mock_src_template = mock.MagicMock()
        mock_src_template.to_dict.return_value = {
            "id": 10,
            "name": "Original Template",
            "template_parameters": [
                {"id": 101, "identifier": "PARAM1", "description": "Param 1 desc", "query": "1..10"}
            ]
        }
        mock_mgmt_instance.heappe_management_command_template_get.return_value = mock_src_template

        request = self.factory.post("/command-templates/10/copy/", {
            "ProjectId": "2",
            "Name": "Cloned Template",
            "Description": "Cloned desc",
            "ExtendedAllocationCommand": "--mem=16G",
            "ExecutableFile": "/usr/bin/python3",
            "PreparationScript": "module load python3",
            "ClusterNodeTypeId": "3",
            "IsEnabled": "on"
        })
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123",
            "command_templates_cache_2": [],
            "command_templates_cache_2_time": 0
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.command_template import command_template_copy
        response = command_template_copy(request, command_template_id=10)

        # Verify redirect to new command template detail
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/command-templates/99/"))

        # Verify command template creation call
        mock_mgmt_instance.heappe_management_command_template_post.assert_called_once()
        post_kwargs = mock_mgmt_instance.heappe_management_command_template_post.call_args[1]
        self.assertEqual(post_kwargs['body']['ProjectId'], 2)
        self.assertEqual(post_kwargs['body']['Name'], "Cloned Template")
        self.assertEqual(post_kwargs['body']['ExecutableFile'], "/usr/bin/python3")
        self.assertEqual(post_kwargs['body']['ClusterNodeTypeId'], 3)
        self.assertEqual(post_kwargs['body']['IsEnabled'], True)
        self.assertEqual(post_kwargs['body']['TemplateParameters'], [])

        # Verify parameter duplication
        mock_mgmt_instance.heappe_management_command_template_parameter_post.assert_called_once()
        param_kwargs = mock_mgmt_instance.heappe_management_command_template_parameter_post.call_args[1]
        self.assertEqual(param_kwargs['body']['CommandTemplateId'], 99)
        self.assertEqual(param_kwargs['body']['Identifier'], "PARAM1")

        # Verify cache invalidation for target project
        self.assertNotIn("command_templates_cache_2", request.session)
        self.assertNotIn("command_templates_cache_2_time", request.session)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_command_template_copy_post_missing_project(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance

        request = self.factory.post("/command-templates/10/copy/", {
            "ProjectId": "",
            "Name": "Cloned Template",
            "ExecutableFile": "/usr/bin/python3",
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

        from heappe_ui.view.command_template import command_template_copy
        response = command_template_copy(request, command_template_id=10)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.endswith("/command-templates/10/copy/"))


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

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_assign_system_role_success(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        mock_mgmt_instance.heappe_management_assign_system_role_to_user_post.return_value = True

        from django.contrib.messages.storage.fallback import FallbackStorage
        from heappe_ui.view.adaptor_user import adaptor_user_assign_system_role
        request = self.factory.post("/adaptor_users/assign-system-role/testsvc/", {
            "role": "1"
        })
        request.user = self.user
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        response = adaptor_user_assign_system_role(request, adaptor_user_username="testsvc")
        self.assertEqual(response.status_code, 302)
        mock_mgmt_instance.heappe_management_assign_system_role_to_user_post.assert_called_once()
        call_args = mock_mgmt_instance.heappe_management_assign_system_role_to_user_post.call_args[1]
        payload = call_args.get("body") or call_args
        self.assertEqual(payload["Username"], "testsvc")
        self.assertEqual(payload["Role"], 1)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_remove_system_role_success(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        mock_mgmt_instance.heappe_management_remove_system_role_from_user_post.return_value = True

        from django.contrib.messages.storage.fallback import FallbackStorage
        from heappe_ui.view.adaptor_user import adaptor_user_remove_system_role
        request = self.factory.post("/adaptor_users/remove-system-role/testsvc/", {
            "role": "Administrator"
        })
        request.user = self.user
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        response = adaptor_user_remove_system_role(request, adaptor_user_username="testsvc")
        self.assertEqual(response.status_code, 302)
        mock_mgmt_instance.heappe_management_remove_system_role_from_user_post.assert_called_once()
        call_args = mock_mgmt_instance.heappe_management_remove_system_role_from_user_post.call_args[1]
        payload = call_args.get("body") or call_args
        self.assertEqual(payload["Username"], "testsvc")
        self.assertEqual(payload["Role"], 1)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_detail_renders_system_roles(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        
        mock_user = mock.MagicMock()
        mock_user.to_dict.return_value = {"username": "newserviceuser", "adaptor_user_groups": []}
        mock_mgmt_instance.heappe_management_adaptor_user_get.return_value = mock_user
        mock_mgmt_instance.heappe_management_projects_get.return_value = []
        mock_mgmt_instance.heappe_management_system_role_assignments_get.return_value = [
            mock.MagicMock(username="newserviceuser", role="Administrator", source="Dynamic")
        ]

        request = self.factory.get("/adaptor_users/newserviceuser/")
        request.user = self.user
        request.session = {}
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.view.adaptor_user import adaptor_user_detail
        response = adaptor_user_detail(request, adaptor_user_username="newserviceuser")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"System Roles (Global Permissions)", response.content)
        self.assertIn(b"Administrator", response.content)
        self.assertIn(b"Dynamic", response.content)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_toggle_block_status_block(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        mock_mgmt_instance.heappe_management_set_adaptor_user_block_status_post.return_value = True

        from django.contrib.messages.storage.fallback import FallbackStorage
        from heappe_ui.view.adaptor_user import adaptor_user_toggle_block_status
        request = self.factory.post("/adaptor_users/toggle-block/testsvc/", {
            "is_blocked": "true"
        })
        request.user = self.user
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        response = adaptor_user_toggle_block_status(request, adaptor_user_username="testsvc")
        self.assertEqual(response.status_code, 302)
        mock_mgmt_instance.heappe_management_set_adaptor_user_block_status_post.assert_called_once()
        call_args = mock_mgmt_instance.heappe_management_set_adaptor_user_block_status_post.call_args[1]
        payload = call_args.get("body") or call_args
        self.assertEqual(payload["Username"], "testsvc")
        self.assertTrue(payload["IsBlocked"])

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_toggle_block_status_unblock(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        mock_mgmt_instance.heappe_management_set_adaptor_user_block_status_post.return_value = True

        from django.contrib.messages.storage.fallback import FallbackStorage
        from heappe_ui.view.adaptor_user import adaptor_user_toggle_block_status
        request = self.factory.post("/adaptor_users/toggle-block/testsvc/", {
            "is_blocked": "false"
        })
        request.user = self.user
        request.session = {}
        setattr(request, '_messages', FallbackStorage(request))
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        response = adaptor_user_toggle_block_status(request, adaptor_user_username="testsvc")
        self.assertEqual(response.status_code, 302)
        mock_mgmt_instance.heappe_management_set_adaptor_user_block_status_post.assert_called_once()
        call_args = mock_mgmt_instance.heappe_management_set_adaptor_user_block_status_post.call_args[1]
        payload = call_args.get("body") or call_args
        self.assertEqual(payload["Username"], "testsvc")
        self.assertFalse(payload["IsBlocked"])

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_detail_renders_blocked_badge(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        
        mock_user = mock.MagicMock()
        mock_user.to_dict.return_value = {"username": "testsvc", "is_blocked": True, "adaptor_user_groups": []}
        mock_mgmt_instance.heappe_management_adaptor_user_get.return_value = mock_user
        mock_mgmt_instance.heappe_management_projects_get.return_value = []
        mock_mgmt_instance.heappe_management_system_role_assignments_get.return_value = []

        request = self.factory.get("/adaptor_users/testsvc/")
        request.user = self.user
        request.session = {}
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from heappe_ui.view.adaptor_user import adaptor_user_detail
        response = adaptor_user_detail(request, adaptor_user_username="testsvc")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Blocked", response.content)
        self.assertIn(b"Unblock Account", response.content)

    def test_get_user_system_roles_filter(self):
        from heappe_ui.templatetags.custom_filters import get_user_system_roles

        system_role_user_map = {
            "test_user": [{"role": "Administrator", "source": "Dynamic"}],
            "admin_user": [{"role": "ManagementAdmin", "source": "Appsettings"}]
        }

        # 1. Direct attachment in dict
        user_with_direct = {"username": "other", "system_roles": [{"role": "Manager", "source": "Dynamic"}]}
        res = get_user_system_roles(user_with_direct, system_role_user_map)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["role"], "Manager")

        # 2. Case insensitive lookup
        user_upper = {"username": "TEST_USER"}
        res = get_user_system_roles(user_upper, system_role_user_map)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["role"], "Administrator")

        # 3. Stripped whitespace lookup
        user_whitespace = {"username": "  admin_user  "}
        res = get_user_system_roles(user_whitespace, system_role_user_map)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["role"], "ManagementAdmin")

        # 4. Plain username string
        res = get_user_system_roles("test_user", system_role_user_map)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["role"], "Administrator")

        # 5. Non-existent user
        res = get_user_system_roles("unknown_user", system_role_user_map)
        self.assertEqual(res, [])

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_adaptor_user_assign_system_role_invalidates_cache(self, mock_management_api):
        mock_mgmt_instance = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt_instance
        mock_mgmt_instance.heappe_management_assign_system_role_to_user_post.return_value = True

        from django.contrib.messages.storage.fallback import FallbackStorage
        from heappe_ui.view.adaptor_user import adaptor_user_assign_system_role
        request = self.factory.post("/adaptor_users/assign-system-role/testsvc/", {
            "role": "1"
        })
        request.user = self.user
        request.session = {
            "all_adaptor_users_cache": [{"username": "testsvc"}],
            "all_adaptor_users_cache_time": 12345
        }
        setattr(request, '_messages', FallbackStorage(request))
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        response = adaptor_user_assign_system_role(request, adaptor_user_username="testsvc")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("all_adaptor_users_cache", request.session)
        self.assertNotIn("all_adaptor_users_cache_time", request.session)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    @mock.patch("py4heappe.heappe_v6.core.HealthApi")
    def test_project_detail_get_renders_with_roles_mapping(self, mock_health_api, mock_management_api):
        mock_mgmt = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt
        mock_health = mock.MagicMock()
        mock_health_api.return_value = mock_health

        mock_health.heappe_health_get.return_value = mock.MagicMock(version="6.5.0")
        mock_project = mock.MagicMock()
        mock_project.to_dict.return_value = {
            "id": 1,
            "name": "Test Project",
            "description": "Test Project Desc",
            "start_date": "2026-01-01T00:00:00",
            "end_date": "2027-01-01T00:00:00",
        }
        mock_mgmt.heappe_management_project_get.return_value = mock_project
        mock_mgmt.heappe_management_clusters_get.return_value = []
        mock_mgmt.heappe_management_clusters_in_project_get.return_value = []
        mock_mgmt.heappe_management_command_templates_get.return_value = []
        mock_mgmt.heappe_management_adaptor_users_in_project_get.return_value = []
        mock_mgmt.heappe_management_adaptor_users_get.return_value = []
        mock_mgmt.heappe_management_system_role_assignments_get.return_value = []
        mock_mgmt.heappe_management_cluster_accounts_in_project_get.return_value = []

        request = self.factory.get("/projects/1/")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import project_detail
        response = project_detail(request, project_id=1)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Test Project", response.content)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_admin_jobs_monitoring_view_success(self, mock_management_api):
        mock_mgmt = mock.MagicMock()
        mock_management_api.return_value = mock_mgmt

        mock_job = mock.MagicMock()
        mock_job.to_dict.return_value = {
            "id": 101,
            "name": "MonitoringJob",
            "state": "Running",
            "submitted_by": "testuser",
            "cluster": "Karolina",
            "creation_time": "2026-09-10T10:00:00",
            "start_time": "2026-09-10T10:05:00",
        }
        mock_page = mock.MagicMock()
        mock_page.jobs = [mock_job]
        mock_page.next_cursor_id = 101
        mock_page.count = 1
        mock_mgmt.heappe_management_get_jobs_monitoring_post.return_value = mock_page

        request = self.factory.get("/monitoring/jobs/?page_size=20")
        request.user = self.user
        request.session = {
            "chosen_instance": "test_instance",
            "heappe_session_code": "token123"
        }
        request.api_instance = mock.MagicMock()
        request.session_code = "token123"

        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(request, '_messages', FallbackStorage(request))

        from heappe_ui.view.project import admin_jobs_monitoring_view
        response = admin_jobs_monitoring_view(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"MonitoringJob", response.content)
        self.assertIn(b"Karolina", response.content)
        self.assertIn(b"RUNNING", response.content)
        mock_mgmt.heappe_management_get_jobs_monitoring_post.assert_called_once()
        call_kwargs = mock_mgmt.heappe_management_get_jobs_monitoring_post.call_args[1]
        self.assertIn("body", call_kwargs)



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

    def test_session_middleware_allows_admin_update_paths_without_chosen_instance(self):
        from heappe_ui.middleware import HeappeSessionMiddleware
        middleware = HeappeSessionMiddleware(get_response=lambda req: HttpResponse("OK"))

        paths = [
            "/api/check-updates/",
            "/api/deploy-direct/",
            "/fetch-branches/",
        ]
        for path in paths:
            request = self.factory.get(path)
            request.user = self.user
            request.session = {}  # No chosen_instance
            response = middleware(request)
            self.assertEqual(
                response.status_code, 200,
                f"Path {path} should be accessible without chosen_instance"
            )
            self.assertEqual(response.content, b"OK")

        # Non-whitelisted path should still redirect to instance list
        req_redirect = self.factory.get("/dashboard/")
        req_redirect.user = self.user
        req_redirect.session = {}
        resp_redirect = middleware(req_redirect)
        self.assertEqual(resp_redirect.status_code, 302)
        self.assertEqual(resp_redirect.url, "/instances/")

    @mock.patch("py4heappe.heappe_v6.core.HealthApi.heappe_health_get")
    def test_instance_health_check_api_version_stripped(self, mock_health_get):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.views import instance_health_check_api
        import json

        instance = InstanceCredentials.objects.create(
            instance_name="test_deucalion",
            heappe_host="localhost",
            heappe_port=8080,
            heappe_login="user",
            heappe_password="password",
        )
        mock_resp = mock.MagicMock()
        mock_resp.version = "V6.5.1"
        mock_resp.component = None
        mock_resp.instance_identifier = "deucalion"
        mock_health_get.return_value = mock_resp

        request = self.factory.get(f"/instances/{instance.pk}/health/")
        request.user = self.user
        request.session = {}

        response = instance_health_check_api(request, instance.pk)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content.decode("utf-8"))
        self.assertEqual(data["version"], "6.5.1")
        self.assertEqual(data["status"], "online")


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
        
        self.assertEqual(get_job_state_source(job_dict_0), "Unknown")
        self.assertEqual(get_job_state_source(job_dict_3), "Background Poll")
        self.assertEqual(get_job_state_updated_at(job_dict_0), "2026-08-31T09:00:00")
        self.assertEqual(get_job_state_updated_at(job_dict_3), "2026-08-31T09:10:00")

        # Test object format
        class ObjJob:
            state_source = 1
            state_updated_at = "2026-08-31T09:20:00"

        self.assertEqual(get_job_state_source(ObjJob()), "Callback")
        self.assertEqual(get_job_state_updated_at(ObjJob()), "2026-08-31T09:20:00")

    def test_cluster_auth_type_and_task_priority_filters(self):
        from heappe_ui.templatetags.custom_filters import format_cluster_auth_type, format_task_priority

        self.assertEqual(format_cluster_auth_type(None), "N/A")
        self.assertEqual(format_cluster_auth_type(1), "Password")
        self.assertEqual(format_cluster_auth_type(4), "SSH Private Key")
        self.assertEqual(format_cluster_auth_type("4"), "SSH Private Key")
        self.assertEqual(format_cluster_auth_type(999), "999")

        self.assertEqual(format_task_priority(None), "N/A")
        self.assertEqual(format_task_priority(0), "Lowest")
        self.assertEqual(format_task_priority(4), "Average")
        self.assertEqual(format_task_priority(8), "Critical")
        self.assertEqual(format_task_priority("6"), "High")
        self.assertEqual(format_task_priority(999), "999")

    def test_format_datetime_filter(self):
        from datetime import datetime
        from heappe_ui.templatetags.custom_filters import format_datetime

        # None / empty
        self.assertEqual(format_datetime(None), "")
        self.assertEqual(format_datetime(""), "")

        # datetime object with subseconds
        dt = datetime(2026, 10, 8, 22, 28, 35, 123456)
        self.assertEqual(format_datetime(dt), "08.10.2026 22:28:35.123")

        # ISO string with 7 decimal places (nanoseconds / datetime2)
        iso_str = "2026-10-08T22:28:35.1234567Z"
        self.assertEqual(format_datetime(iso_str), "08.10.2026 22:28:35.123")

        # ISO string without subseconds
        iso_no_sub = "2026-10-08T22:28:35Z"
        self.assertEqual(format_datetime(iso_no_sub), "08.10.2026 22:28:35.000")

        # Custom format without ms
        self.assertEqual(format_datetime(dt, "%Y-%m-%d %H:%M"), "2026-10-08 22:28")
        self.assertEqual(format_datetime(iso_str, "%Y-%m-%dT%H:%M"), "2026-10-08T22:28")

        # Date only string
        self.assertEqual(format_datetime("2026-10-08"), "08.10.2026")

    def test_dashboard_jobs_history_template_null_safe(self):
        from django.template.loader import render_to_string

        class SimpleObj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        task_null_node = SimpleObj(id=1, name='Task 1', state=2, node_type=None, command_template_id=10)
        task_null_project = SimpleObj(id=2, name='Task 2', state=2, node_type=SimpleObj(id=5, name='CPU', description='CPU Node', project=None))
        task_null_template = SimpleObj(id=3, name='Task 3', state=2, node_type=SimpleObj(id=6, name='GPU', description=None, project=SimpleObj(id=8, name='Prj', accounting_string='acc', description=None, command_template=None)))
        task_full = SimpleObj(id=4, name='Task 4', state=2, node_type=SimpleObj(id=7, name='MEM', description='Mem', project=SimpleObj(id=9, name='Prj2', accounting_string='acc2', description='desc', command_template=SimpleObj(id=12, name='CT', description='Command Temp'))))

        job1 = SimpleObj(
            id=101,
            name='Test Job 1',
            state=2,
            submitter=SimpleObj(username='john', email='john@example.com', id=42),
            tasks=[task_null_node, task_null_project, task_null_template, task_full],
            cluster_username='johnhpc',
            project_name='Demo',
            sub_project_identifier='sub1',
            total_nodes=1,
            total_cores=4,
            total_allocated_cores=4
        )
        job2 = SimpleObj(
            id=102,
            name='Test Job 2',
            state=16,
            submitter='str_user',
            tasks=[],
            cluster_username=None,
            project_name=None,
            sub_project_identifier=None
        )

        rendered = render_to_string('partials/dashboard_jobs_history.html', {
            'job_details': [job1, job2],
            'total_count': 2,
            'total_pages': 1,
            'page': 1,
            'page_range': [1],
            'is_admin_api': True,
            'request': SimpleObj(GET={})
        })
        self.assertIn("Test Job 1", rendered)
        self.assertIn("Test Job 2", rendered)
        self.assertIn("CLUSTER NODE TYPE", rendered)


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
import unittest
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
    def test_cluster_create_post_qscheduler_v660_sends_vault_toggles(self, mock_api):
        """cluster_create POST for QScheduler + v6.6.0 should pass CustomConfigurationVaultToggles."""
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
            "middleware_deployed_version": "6.6.0",
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
    def test_cluster_create_post_qscheduler_pre_v660_refused(self, mock_api):
        """QScheduler clusters need HEAppE 6.6.0+: cluster_create refuses them on older versions."""
        mock_instance = mock.MagicMock()
        mock_api.return_value = mock_instance
        mock_instance.heappe_management_cluster_proxy_connections_get.return_value = []

        for version in ("6.4.0", "6.5.0", ""):
            request = self.factory.post("/clusters/create/", {
                "Name": "OldQCluster", "Description": "", "MasterNodeName": "qmaster", "SchedulerType": "32",
                "ConnectionProtocol": "2", "TimeZone": "UTC", "Port": "22",
                "UpdateJobStateByServiceAccount": "true", "DomainName": "qcluster.example.com",
                "CustomConfiguration": '{"QSchedulerPort":"3000"}', "CustomConfigurationVaultToggles": '{}',
            })
            request.user = self.user
            request.session = {"chosen_instance": "test", "heappe_session_code": "tok",
                               "middleware_deployed_version": version}
            request.api_instance = mock.MagicMock()
            request.session_code = "tok"
            from django.contrib.messages.storage.fallback import FallbackStorage
            setattr(request, '_messages', FallbackStorage(request))

            from heappe_ui.view.clusters import cluster_create
            response = cluster_create(request)

            self.assertEqual(response.status_code, 302, version)
            mock_instance.heappe_management_cluster_post.assert_not_called()
            self.assertIn("6.6.0", " ".join(str(m) for m in request._messages))


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
    @mock.patch('os.path.isdir')
    @mock.patch('os.listdir')
    @mock.patch('os.path.getmtime')
    def test_get_log_file_paths_includes_json(self, mock_getmtime, mock_listdir, mock_isdir, mock_exists):
        from heappe_ui.views import get_log_file_paths
        mock_exists.return_value = True
        mock_isdir.return_value = False
        mock_listdir.side_effect = lambda d: ['2026_07_13.log', '2026_07_13.json', '2026_07_13.json.1', 'other.log'] if str(d).endswith('/API') else []
        mock_getmtime.side_effect = lambda path: 10 if 'json.1' in path else 20
        
        paths = get_log_file_paths('test_instance', '2026-07-13', service='API')
        self.assertEqual(len(paths), 3)
        self.assertIn('/opt/heappe-deployment/test_instance/app/logs/API/2026_07_13.json.1', paths[0][0] if isinstance(paths[0], tuple) else paths[0])

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
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
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

    def test_fetch_new_logs_with_dict_offset_and_date(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import fetch_new_logs
        import json as pyjson

        factory = RequestFactory()
        user = User.objects.create_user(username='testuser_logs2', password='password')

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            tmp.write('{"timestamp":"2026-10-05T09:34:15.000Z","level":"INFO","logger":"L","message":"LineA"}\n')
            offset_a = tmp.tell()
            tmp.write('{"timestamp":"2026-10-05T09:34:16.000Z","level":"WARN","logger":"L","message":"LineB"}\n')
            offset_b = tmp.tell()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                dict_offset = pyjson.dumps({tmp_path: offset_a})
                req = factory.get(f'/fetch-new-logs/?offset={dict_offset}&date=2026-10-05')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = fetch_new_logs(req)
                self.assertEqual(resp.status_code, 200)
                data = pyjson.loads(resp.content.decode('utf-8'))

                self.assertEqual(len(data['entries']), 1)
                self.assertEqual(data['entries'][0]['level'], 'WARN')
                self.assertIn('LineB', data['entries'][0]['content'])
                self.assertIsInstance(data['offset'], dict)
                self.assertEqual(data['offset'][tmp_path], offset_b)
        finally:
            import os
            os.remove(tmp_path)
            user.delete()

    def test_fetch_new_logs_initial_tail_minus_one(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import fetch_new_logs
        import json as pyjson

        factory = RequestFactory()
        user = User.objects.create_user(username='testuser_logs3', password='password')

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            tmp.write('{"timestamp":"2026-10-05T09:34:15.000Z","level":"INFO","logger":"L","message":"PriorLine"}\n')
            end_pos = tmp.tell()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                req = factory.get('/fetch-new-logs/?offset=-1')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = fetch_new_logs(req)
                self.assertEqual(resp.status_code, 200)
                data = pyjson.loads(resp.content.decode('utf-8'))

                # Should return no entries, and single-file integer offset should match end of file
                self.assertEqual(len(data['entries']), 0)
                self.assertEqual(data['offset'], end_pos)
        finally:
            import os
            os.remove(tmp_path)
    def test_is_rotated_log_file(self):
        from heappe_ui.views import is_rotated_log_file
        self.assertTrue(is_rotated_log_file("/path/to/2026_10_19.json.1"))
        self.assertTrue(is_rotated_log_file("/path/to/heappe_2026_10_19.log.2"))
        self.assertTrue(is_rotated_log_file("/path/to/heappe_2026_10_19.log.3.gz"))
        self.assertFalse(is_rotated_log_file("/path/to/2026_10_19.json"))
        self.assertFalse(is_rotated_log_file("/path/to/heappe_2026_10_19.log"))
        self.assertFalse(is_rotated_log_file("/path/to/heappe_2026_10_19_001.log"))

    def test_fetch_new_logs_caps_max_entries(self):
        import os
        import json as pyjson
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import fetch_new_logs, MAX_LOG_ENTRIES_PER_PULL

        factory = RequestFactory()
        user = User.objects.create_user(username='testuser_logs_cap', password='password')

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            for i in range(400):
                tmp.write(f'{{"timestamp":"2026-10-05T09:{i//60:02d}:{i%60:02d}.000Z","level":"INFO","logger":"L","message":"Line_{i}"}}\n')
            tmp.flush()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                # First pull: should cap at MAX_LOG_ENTRIES_PER_PULL (300)
                req = factory.get('/fetch-new-logs/?offset=0')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = fetch_new_logs(req)
                self.assertEqual(resp.status_code, 200)
                data = pyjson.loads(resp.content.decode('utf-8'))
                self.assertEqual(len(data['entries']), MAX_LOG_ENTRIES_PER_PULL)
                self.assertEqual(data['entries'][0]['content'], 'INFO  2026-10-05 09:00:00  [-]  -  L - Line_0')
                next_offset = data['offset']

                # Second pull: should get the remaining 100 entries
                req2 = factory.get(f'/fetch-new-logs/?offset={next_offset}')
                req2.user = user
                req2.session = {'chosen_instance': 'test'}
                resp2 = fetch_new_logs(req2)
                self.assertEqual(resp2.status_code, 200)
                data2 = pyjson.loads(resp2.content.decode('utf-8'))
                self.assertEqual(len(data2['entries']), 100)
                self.assertEqual(data2['entries'][-1]['content'], 'INFO  2026-10-05 09:06:39  [-]  -  L - Line_399')
        finally:
            os.remove(tmp_path)
            user.delete()

    def test_fetch_new_logs_chronological_sort_across_files(self):
        import os
        import json as pyjson
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import fetch_new_logs

        factory = RequestFactory()
        user = User.objects.create_user(username='testuser_logs_sort', password='password')

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp_api, \
             tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp_ds:
            tmp_api.write('{"timestamp":"2026-10-05T09:00:02.000Z","level":"INFO","logger":"L","message":"API_02"}\n')
            tmp_api.write('{"timestamp":"2026-10-05T09:00:04.000Z","level":"INFO","logger":"L","message":"API_04"}\n')
            tmp_api.flush()

            tmp_ds.write('{"timestamp":"2026-10-05T09:00:01.000Z","level":"INFO","logger":"L","message":"DS_01"}\n')
            tmp_ds.write('{"timestamp":"2026-10-05T09:00:03.000Z","level":"INFO","logger":"L","message":"DS_03"}\n')
            tmp_ds.flush()

            api_path = tmp_api.name
            ds_path = tmp_ds.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(api_path, 'API'), (ds_path, 'DATASTAGING')]):
                req = factory.get('/fetch-new-logs/?offset={}')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = fetch_new_logs(req)
                self.assertEqual(resp.status_code, 200)
                data = pyjson.loads(resp.content.decode('utf-8'))

                self.assertEqual(len(data['entries']), 4)
                timestamps = [e['timestamp_str'] for e in data['entries']]
                self.assertEqual(timestamps, [
                    '2026-10-05 09:00:01',
                    '2026-10-05 09:00:02',
                    '2026-10-05 09:00:03',
                    '2026-10-05 09:00:04',
                ])
        finally:
            os.remove(api_path)
            os.remove(ds_path)
            user.delete()

    def test_fetch_new_logs_rotated_file_not_read_from_zero(self):
        import os
        import json as pyjson
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import fetch_new_logs

        factory = RequestFactory()
        user = User.objects.create_user(username='testuser_logs_rot', password='password')

        with tempfile.NamedTemporaryFile(suffix='.json.1', mode='w+', delete=False) as tmp_rot, \
             tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp_act:
            tmp_rot.write('{"timestamp":"2026-10-05T08:00:00.000Z","level":"WARN","logger":"L","message":"OldRotatedMsg"}\n')
            tmp_rot.flush()
            rot_path = tmp_rot.name

            tmp_act.write('{"timestamp":"2026-10-05T09:00:00.000Z","level":"INFO","logger":"L","message":"NewActiveMsg"}\n')
            tmp_act.flush()
            act_path = tmp_act.name

        try:
            # Client only tracked active_path previously, but now rot_path exists too (rotation occurred)
            dict_offset = pyjson.dumps({act_path: 0})
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(rot_path, 'API'), (act_path, 'API')]):
                req = factory.get(f'/fetch-new-logs/?offset={dict_offset}')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = fetch_new_logs(req)
                self.assertEqual(resp.status_code, 200)
                data = pyjson.loads(resp.content.decode('utf-8'))

                # Should only return the new active message, NOT the old rotated message!
                self.assertEqual(len(data['entries']), 1)
                self.assertIn('NewActiveMsg', data['entries'][0]['content'])
                self.assertNotIn('OldRotatedMsg', [e['content'] for e in data['entries']])
                # The rotated file offset should be recorded as its full size
                self.assertEqual(data['offset'][rot_path], os.path.getsize(rot_path))
        finally:
            os.remove(rot_path)
            os.remove(act_path)
            user.delete()

    def test_matches_filters_time_filtering(self):
        from heappe_ui.views import matches_filters
        entry_night = {'timestamp_str': '2026-10-15 23:56:15', 'level': 'INFO', 'content': 'Night log'}
        entry_iso_night = {'timestamp_str': '2026-10-15T23:56:15.127Z', 'level': 'INFO', 'content': 'ISO Night log'}
        entry_noon = {'timestamp_str': '2026-10-15 12:15:00', 'level': 'INFO', 'content': 'Noon log'}
        entry_time_only = {'timestamp_str': '12:20:00', 'level': 'INFO', 'content': 'Time only log'}
        entry_no_ts = {'timestamp_str': None, 'level': 'INFO', 'content': 'No timestamp log'}

        # Filter: 12:03 to 12:30
        self.assertFalse(matches_filters(entry_night, "", "", "12:03", "12:30"))
        self.assertFalse(matches_filters(entry_iso_night, "", "", "12:03", "12:30"))
        self.assertTrue(matches_filters(entry_noon, "", "", "12:03", "12:30"))
        self.assertTrue(matches_filters(entry_time_only, "", "", "12:03", "12:30"))
        self.assertFalse(matches_filters(entry_no_ts, "", "", "12:03", "12:30"))

        # Exact boundaries
        entry_boundary_start = {'timestamp_str': '2026-10-15 12:03:00', 'level': 'INFO', 'content': 'Start boundary'}
        entry_boundary_end = {'timestamp_str': '2026-10-15 12:30:59', 'level': 'INFO', 'content': 'End boundary'}
        entry_outside_end = {'timestamp_str': '2026-10-15 12:31:00', 'level': 'INFO', 'content': 'Outside end'}
        self.assertTrue(matches_filters(entry_boundary_start, "", "", "12:03", "12:30"))
        self.assertTrue(matches_filters(entry_boundary_end, "", "", "12:03", "12:30"))
        self.assertFalse(matches_filters(entry_outside_end, "", "", "12:03", "12:30"))

    def test_parse_json_log_line_serilog_pascalcase(self):
        from heappe_ui.views import parse_json_log_line
        serilog_json = (
            '{"Timestamp":"2026-10-15T23:56:15.1272345+00:00","Level":"Information",'
            '"MessageTemplate":"User {UserName} logged in","Properties":{"UserName":"johndoe","RequestId":"req789"},'
            '"SourceContext":"HEAppE.Controllers.AuthController"}'
        )
        parsed = parse_json_log_line(serilog_json)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['level'], 'INFO')
        self.assertEqual(parsed['timestamp_str'], '2026-10-15 23:56:15')
        self.assertEqual(parsed['conn'], '[req789]')
        self.assertEqual(parsed['logger'], 'HEAppE.Controllers.AuthController')
        self.assertIn('User {UserName} logged in', parsed['content'])

    def test_parse_log_line_time_only(self):
        from heappe_ui.views import parse_log_line
        line = "INFO  23:56:15 [7ce0d92b6028f1334700c96bfd41f5eb] AuthMiddleware: Anonymous endpoint detected."
        parsed = parse_log_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['level'], 'INFO')
        self.assertEqual(parsed['timestamp_str'], '23:56:15')
        self.assertEqual(parsed['conn'], '[7ce0d92b6028f1334700c96bfd41f5eb]')

    def test_log_viewer_view_limit_parameter(self):
        from django.contrib.auth.models import User
        import json as pyjson

        user = User.objects.create_user(username='test_limit_user', password='password')
        self.client.force_login(user)
        session = self.client.session
        session['chosen_instance'] = 'develop'
        session.save()

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            for i in range(1200):
                tmp.write(f'{{"timestamp":"2026-10-15T12:{i//60:02d}:{i%60:02d}.000Z","level":"INFO","logger":"L","message":"Msg_{i}"}}\n')
            tmp.flush()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                # Test default limit (1000)
                resp = self.client.get('/logs/?date=2026-10-15')
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.context['limit'], 1000)
                self.assertEqual(resp.context['logs_count'], 1000)

                # Test explicit limit (500)
                resp500 = self.client.get('/logs/?date=2026-10-15&limit=500')
                self.assertEqual(resp500.status_code, 200)
                self.assertEqual(resp500.context['limit'], 500)
                self.assertEqual(resp500.context['logs_count'], 500)
        finally:
            os.remove(tmp_path)
            user.delete()


class VaultUnsealApiTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="test_vault_user", password="password")

    def test_unseal_vault_api_get_rejected(self):
        from heappe_ui.view.deploy import unseal_vault_api
        req = self.factory.get("/vault/unseal/")
        req.user = self.user
        req.session = {"chosen_instance": "develop"}
        resp = unseal_vault_api(req)
        self.assertEqual(resp.status_code, 405)

    @mock.patch("heappe_ui.view.deploy.os.path.exists", return_value=True)
    @mock.patch("heappe_ui.view.deploy.execute_docker_compose")
    @mock.patch("heappe_ui.view.deploy._kick_vaultagent")
    @mock.patch("heappe_ui.view.deploy._check_vault_sealed", return_value=False)
    @mock.patch("time.sleep", return_value=None)
    def test_unseal_vault_api_auto_success(self, mock_sleep, mock_check_sealed, mock_kick, mock_compose, mock_exists):
        from heappe_ui.view.deploy import unseal_vault_api
        mock_compose_res = mock.MagicMock()
        mock_compose_res.returncode = 0
        mock_compose_res.stdout = "initVault unsealed successfully"
        mock_compose.return_value = mock_compose_res

        req = self.factory.post("/vault/unseal/", {"instance_name": "develop"})
        req.user = self.user
        req.session = {"chosen_instance": "develop"}

        resp = unseal_vault_api(req)
        self.assertEqual(resp.status_code, 200)
        import json as pyjson
        data = pyjson.loads(resp.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["sealed"])
        mock_compose.assert_called_once()
        mock_kick.assert_called_once_with("develop")

    @mock.patch("heappe_ui.view.deploy.os.path.exists", return_value=True)
    @mock.patch("heappe_ui.view.deploy.execute_docker_compose")
    @mock.patch("heappe_ui.view.deploy._kick_vaultagent")
    @mock.patch("heappe_ui.view.deploy._check_vault_sealed", return_value=True)
    @mock.patch("time.sleep", return_value=None)
    def test_unseal_vault_api_auto_failure(self, mock_sleep, mock_check_sealed, mock_kick, mock_compose, mock_exists):
        from heappe_ui.view.deploy import unseal_vault_api
        mock_compose_res = mock.MagicMock()
        mock_compose_res.returncode = 1
        mock_compose_res.stderr = "Failed to run container"
        mock_compose.return_value = mock_compose_res

        req = self.factory.post("/vault/unseal/", {"instance_name": "develop"})
        req.user = self.user
        req.session = {"chosen_instance": "develop"}

        resp = unseal_vault_api(req)
        self.assertEqual(resp.status_code, 200)
        import json as pyjson
        data = pyjson.loads(resp.content.decode("utf-8"))
        self.assertEqual(data["status"], "warning")
        self.assertTrue(data["sealed"])

    @mock.patch("urllib.request.urlopen")
    @mock.patch("heappe_ui.view.deploy._kick_vaultagent")
    def test_unseal_vault_api_manual_key(self, mock_kick, mock_urlopen):
        from heappe_ui.view.deploy import unseal_vault_api
        import json as pyjson

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = pyjson.dumps({"sealed": False, "t": 1, "n": 1, "progress": 0}).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        req = self.factory.post("/vault/unseal/", {
            "instance_name": "develop",
            "unseal_key": "s.dummykey123"
        })
        req.user = self.user
        req.session = {"chosen_instance": "develop"}

        resp = unseal_vault_api(req)
        self.assertEqual(resp.status_code, 200)
        data = pyjson.loads(resp.content.decode("utf-8"))
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["sealed"])
        mock_kick.assert_called_once_with("develop")


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

    def test_generate_appsettings_v6_4_17_structure(self):
        from heappe_ui.appsettings.generator import (
            generate_appsettings_v6_4_17,
            generate_appsettings_data_staging_v6_4_17,
        )
        from heappe_ui.DeployService import HEAppEDeployService, HEAppEConfig

        appsettings = generate_appsettings_v6_4_17(
            instance_name="v6417_inst",
            sa_password="Password123!",
            port=5000,
            automigrate=True,
            version="v6.4.17",
            deployed_ip="127.0.0.1"
        )

        self.assertEqual(appsettings["ApplicationAPISettings"]["DeploymentSettings"]["Version"], "v6.4.17")
        self.assertEqual(appsettings["ApplicationAPISettings"]["SwaggerDocSettings"]["DictionaryTitle"], "Dictionary API")
        self.assertEqual(appsettings["BackGroundThreadSettings"]["ClusterProjectCredentialsCheckConfiguration"], {"IsEnabled": False, "IntervalMinutes": 60})
        self.assertEqual(appsettings["BackGroundThreadSettings"]["ExternalServiceHealthMonitoringSettings"], {"IsEnabled": True, "IntervalSeconds": 60, "RetentionDays": 30})
        self.assertEqual(appsettings["HPCConnectionFrameworkSettings"]["ClustersConnectionPoolSettings"]["ConnectionPoolMaxUnusedInterval"], 1800)
        self.assertEqual(appsettings["HPCConnectionFrameworkSettings"]["SshClientSettings"]["ConnectionTimeout"], 30000)
        self.assertEqual(appsettings["ExternalAuthenticationSettings"]["LexisAuthenticationConfiguration"]["ApiVersion"], "auto")
        self.assertEqual(appsettings["ExternalAuthenticationSettings"]["LexisAuthenticationConfiguration"]["ExtendedUserInfoV2Endpoint"], "/api/v2/UserInfo/Extended")
        self.assertEqual(appsettings["ExternalAuthenticationSettings"]["LexisAuthenticationConfiguration"]["CommandTemplatePermissionsV2Endpoint"], "/api/Heappe/CommandTemplatePermissions/")
        self.assertEqual(appsettings["SshCaSettings"]["BaseUri"], "https://ssh.ca.api.heappe.eu")

        # Test DeployService version matching for 6.4.17
        service = HEAppEDeployService(HEAppEConfig(base_path="/tmp", repo_branch="v6.4.17"))
        gen, ds_gen = service._get_generators_for_version("6.4.17")
        self.assertEqual(gen, generate_appsettings_v6_4_17)
        self.assertEqual(ds_gen, generate_appsettings_data_staging_v6_4_17)

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

    def test_generate_appsettings_v6_6_0_structure_and_efp_template(self):
        from heappe_ui.appsettings.generator import (
            generate_appsettings_v6_6_0,
            generate_appsettings_efp_v6_6_0,
            generate_appsettings_data_staging_v6_6_0,
            get_default_token_exchange_targets,
            get_efp_token_exchange_targets,
            SUPPORTED_TOKEN_EXCHANGE_STRATEGIES,
        )
        from heappe_ui.DeployService import HEAppEDeployService, HEAppEConfig

        # 1. Default v6.6.0 deployment
        appsettings = generate_appsettings_v6_6_0(
            instance_name="v660_inst",
            sa_password="Password123!",
            port=5000,
            automigrate=True,
            version="v6.6.0",
            deployed_ip="127.0.0.1"
        )

        # Version & Swagger description
        self.assertEqual(appsettings["ApplicationAPISettings"]["DeploymentSettings"]["Version"], "v6.6.0")
        self.assertEqual(appsettings["ApplicationAPISettings"]["SwaggerDocSettings"]["Description"], "HEAppE middleware API v6.6.0")

        # UserOrg V1 & V2 Endpoints in LexisAuthenticationConfiguration
        lexis_auth = appsettings["ExternalAuthenticationSettings"]["LexisAuthenticationConfiguration"]
        self.assertEqual(lexis_auth["ExtendedUserInfoEndpoint"], "/api/UserInfo/Extended")
        self.assertEqual(lexis_auth["ExtendedUserInfoV2Endpoint"], "/api/v2/UserInfo/Extended")
        self.assertEqual(lexis_auth["CommandTemplatePermissions"], "/api/Heappe/CommandTemplatePermissions/")
        self.assertEqual(lexis_auth["CommandTemplatePermissionsV2Endpoint"], "/api/Heappe/CommandTemplatePermissions/")

        # MigrationSettings root section next to DatabaseMigrationSettings
        root_keys = list(appsettings.keys())
        self.assertIn("MigrationSettings", appsettings)
        self.assertEqual(appsettings["MigrationSettings"], {"EncryptionKey": ""})
        self.assertEqual(
            root_keys.index("MigrationSettings"),
            root_keys.index("DatabaseMigrationSettings") + 1
        )

        # LexisTokenFlowConfiguration pre-exchange introspection defaults
        lexis_flow = appsettings["JwtTokenIntrospectionConfiguration"]["LexisTokenFlowConfiguration"]
        self.assertFalse(lexis_flow["IsEnabled"])
        self.assertTrue(lexis_flow["UseExpirioServiceForTokenExchange"])
        self.assertFalse(lexis_flow["IntrospectLexisToken"])
        self.assertEqual(lexis_flow["Authority"], "")
        self.assertEqual(lexis_flow["IntrospectionEndpoint"], "")
        self.assertEqual(lexis_flow["ConnectionTimeoutInSeconds"], 15)

        # Default TokenExchangeTargets root section next to JwtTokenIntrospectionConfiguration
        self.assertIn("TokenExchangeTargets", appsettings)
        self.assertEqual(
            root_keys.index("TokenExchangeTargets"),
            root_keys.index("JwtTokenIntrospectionConfiguration") + 1
        )
        self.assertEqual(appsettings["TokenExchangeTargets"], get_default_token_exchange_targets())
        self.assertEqual(len(appsettings["TokenExchangeTargets"]), 3)
        self.assertEqual([t["Name"] for t in appsettings["TokenExchangeTargets"]], ["idp", "sshca", "userorg"])
        for target in appsettings["TokenExchangeTargets"]:
            self.assertFalse(target["IsEnabled"])
            self.assertIn(target["Strategy"], SUPPORTED_TOKEN_EXCHANGE_STRATEGIES)

        # 2. EFP v6.6.0 template
        efp_settings = generate_appsettings_efp_v6_6_0(
            instance_name="discoverer",
            sa_password="Password123!",
            port=5000,
            automigrate=True,
            version="v6.6.0",
            deployed_ip="localhost"
        )
        efp_flow = efp_settings["JwtTokenIntrospectionConfiguration"]["LexisTokenFlowConfiguration"]
        self.assertTrue(efp_flow["IsEnabled"])
        self.assertTrue(efp_flow["UseExpirioServiceForTokenExchange"])
        self.assertTrue(efp_flow["IntrospectLexisToken"])
        self.assertEqual(efp_flow["BaseUrl"], "https://lexis/auth")
        self.assertEqual(efp_flow["Realm"], "LEXIS_AAI")
        self.assertEqual(efp_flow["Broker"], "EFP")
        self.assertEqual(efp_flow["Scope"], "openid profile email audience")
        self.assertEqual(efp_flow["ClientId"], "<LEXIS_KEYCLOAK_CLIENT_ID>")
        self.assertEqual(efp_flow["ClientSecret"], "<LEXIS_KEYCLOAK_CLIENT_SECRET>")
        self.assertEqual(efp_flow["ConnectionTimeoutInSeconds"], 15)

        self.assertEqual(efp_settings["TokenExchangeTargets"], get_efp_token_exchange_targets())
        self.assertTrue(efp_settings["TokenExchangeTargets"][0]["IsEnabled"])
        self.assertEqual(efp_settings["TokenExchangeTargets"][0]["Strategy"], "Expirio")
        self.assertTrue(efp_settings["TokenExchangeTargets"][0]["IntrospectSubjectToken"])
        self.assertTrue(efp_settings["TokenExchangeTargets"][1]["IsEnabled"])
        self.assertEqual(efp_settings["TokenExchangeTargets"][1]["Strategy"], "Rfc8693")
        self.assertFalse(efp_settings["TokenExchangeTargets"][2]["IsEnabled"])

        # 3. DataStaging v6.6.0
        ds_settings = generate_appsettings_data_staging_v6_6_0(
            instance_name="v660_inst",
            sa_password="Password123!",
            data_staging_token="token",
            port=5001,
            version="v6.6.0"
        )
        self.assertEqual(ds_settings["ApplicationAPIConfiguration"]["DeploymentConfiguration"]["Version"], "v6.6.0")

        # 4. DeployService version dispatch
        service = HEAppEDeployService(HEAppEConfig(base_path="/tmp", repo_branch="v6.6.0"))
        gen_66, ds_gen_66 = service._get_generators_for_version("v6.6.0")
        self.assertEqual(gen_66, generate_appsettings_v6_6_0)
        self.assertEqual(ds_gen_66, generate_appsettings_data_staging_v6_6_0)

        gen_master, ds_gen_master = service._get_generators_for_version("master")
        self.assertEqual(gen_master, generate_appsettings_v6_6_0)
        self.assertEqual(ds_gen_master, generate_appsettings_data_staging_v6_6_0)

    def test_update_init_v6_6_0_merge_adds_token_exchange_targets_and_fixes_v2_endpoints(self):
        import tempfile
        import json
        import os
        from heappe_ui.DeployService import HEAppEDeployService, HEAppEConfig

        with tempfile.TemporaryDirectory() as temp_dir:
            instance_name = "test_upgrade_v660"
            config = HEAppEConfig(base_path=temp_dir, repo_branch="v6.6.0")
            service = HEAppEDeployService(config)

            confs_dir = os.path.join(temp_dir, instance_name, "app", "confs")
            core_dir = os.path.join(temp_dir, instance_name, "heappe-core")
            os.makedirs(confs_dir, exist_ok=True)
            os.makedirs(core_dir, exist_ok=True)

            old_appsettings = {
                "ApplicationAPISettings": {
                    "DeploymentSettings": {"Version": "v6.5.0"},
                    "SwaggerDocSettings": {"Description": "HEAppE middleware API v6.5.0"}
                },
                "ExternalAuthenticationSettings": {
                    "LexisAuthenticationConfiguration": {
                        "BaseAddress": "https://api.workflows.my-eurohpc.eu",
                        "ExtendedUserInfoV2Endpoint": "/api/v2/users/me/extended",
                        "CommandTemplatePermissionsV2Endpoint": "/api/v2/heappe/command-template-permissions/"
                    }
                },
                "JwtTokenIntrospectionConfiguration": {
                    "LexisTokenFlowConfiguration": {
                        "IsEnabled": True,
                        "BaseUrl": "https://lexis/auth",
                        "Realm": "LEXIS_AAI",
                        "Broker": "EFP",
                        "ClientId": "existing_client",
                        "ClientSecret": "existing_secret"
                    }
                }
            }
            with open(os.path.join(confs_dir, "appsettings.json"), "w", encoding="utf-8") as f:
                json.dump(old_appsettings, f)

            res = service.update_init(instance_name, "v6.6.0")
            self.assertEqual(res["status"], "success")

            with open(os.path.join(confs_dir, "appsettings.json"), "r", encoding="utf-8") as f:
                merged = json.load(f)

            self.assertEqual(merged["ApplicationAPISettings"]["DeploymentSettings"]["Version"], "v6.6.0")
            self.assertEqual(merged["ApplicationAPISettings"]["SwaggerDocSettings"]["Description"], "HEAppE middleware API v6.6.0")

            # Deprecated V2 routes replaced with actual UserOrg V2 routes
            lexis_auth = merged["ExternalAuthenticationSettings"]["LexisAuthenticationConfiguration"]
            self.assertEqual(lexis_auth["BaseAddress"], "https://api.workflows.my-eurohpc.eu")
            self.assertEqual(lexis_auth["ExtendedUserInfoV2Endpoint"], "/api/v2/UserInfo/Extended")
            self.assertEqual(lexis_auth["CommandTemplatePermissionsV2Endpoint"], "/api/Heappe/CommandTemplatePermissions/")

            # LexisTokenFlowConfiguration preserves existing secrets and adds new introspection fields
            lexis_flow = merged["JwtTokenIntrospectionConfiguration"]["LexisTokenFlowConfiguration"]
            self.assertTrue(lexis_flow["IsEnabled"])
            self.assertEqual(lexis_flow["ClientId"], "existing_client")
            self.assertEqual(lexis_flow["ClientSecret"], "existing_secret")
            self.assertIn("IntrospectLexisToken", lexis_flow)
            self.assertIn("Authority", lexis_flow)
            self.assertIn("IntrospectionEndpoint", lexis_flow)

            # TokenExchangeTargets and MigrationSettings added
            self.assertIn("MigrationSettings", merged)
            self.assertIn("TokenExchangeTargets", merged)
            self.assertEqual(len(merged["TokenExchangeTargets"]), 3)


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


class HpcAccountAccessTestErrorHandlingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="admin", email="admin@test.com", password="password", is_superuser=True)

    def test_extract_heappe_error_from_dict_error_message(self):
        from heappe_ui.view.utils import extract_heappe_error
        class FakeApiException(Exception):
            def __init__(self):
                self.status = 400
                self.reason = "Bad Request"
                self.body = b'{"ErrorMessage": "Account atr-26-4-01 not configured on cluster Karolina"}'
        
        err = extract_heappe_error(FakeApiException())
        self.assertEqual(err, "Account atr-26-4-01 not configured on cluster Karolina")

    def test_extract_heappe_error_from_validation_errors(self):
        from heappe_ui.view.utils import extract_heappe_error
        class FakeApiException(Exception):
            def __init__(self):
                self.status = 400
                self.reason = "Bad Request"
                self.body = b'{"title": "Validation failed", "errors": {"Username": ["Account not found"]}}'
        
        err = extract_heappe_error(FakeApiException())
        self.assertEqual(err, "Validation failed (Username: Account not found)")

    def test_extract_heappe_error_plain_text(self):
        from heappe_ui.view.utils import extract_heappe_error
        class FakeApiException(Exception):
            def __init__(self):
                self.status = 500
                self.reason = "Internal Server Error"
                self.body = b'SSH connection timed out on cluster node'
        
        err = extract_heappe_error(FakeApiException())
        self.assertEqual(err, "SSH connection timed out on cluster node")

    def test_extract_heappe_error_connection_failure(self):
        from heappe_ui.view.utils import extract_heappe_error
        exc = Exception("Failed to establish a new connection: [Errno 61] Connection refused")
        err = extract_heappe_error(exc)
        self.assertIn("Could not reach the HEAppE service", err)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_access_test_failed_displays_heappe_error(self, mock_mgmt_api_class):
        from heappe_ui.view.project import test_cluster_authentication_credential_HPC_access
        mock_controller = mock.MagicMock()
        mock_mgmt_api_class.return_value = mock_controller

        class FakeApiException(Exception):
            def __init__(self):
                self.status = 400
                self.reason = "Bad Request"
                self.body = b'{"ErrorMessage": "Account atr-26-4-01 not found on cluster"}'

        mock_controller.heappe_management_test_cluster_access_for_account_get.side_effect = FakeApiException()

        req = self.factory.post("/projects/test_access/", {
            "ProjectId": "10",
            "username": "atr-26-4-01"
        })
        req.user = self.user
        req.session_code = "dummy_session"
        req.api_instance = mock.MagicMock()
        req.session = {}
        req._messages = mock.MagicMock()

        response = test_cluster_authentication_credential_HPC_access(req)
        self.assertEqual(response.status_code, 302)

        # Ensure messages.error was called with the specific message from HEAppE
        req._messages.add.assert_called()
        error_calls = [call for call in req._messages.add.call_args_list if call[0][0] == messages.ERROR]
        self.assertTrue(len(error_calls) > 0)
        msg_text = error_calls[0][0][1]
        self.assertIn("Account atr-26-4-01 not found on cluster", msg_text)
        self.assertNotIn("Could not reach the HEAppE service", msg_text)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_access_test_denied_with_cluster_error(self, mock_mgmt_api_class):
        from heappe_ui.view.project import test_cluster_authentication_credential_HPC_access
        mock_controller = mock.MagicMock()
        mock_mgmt_api_class.return_value = mock_controller

        fake_resp = mock.MagicMock()
        fake_resp.data = json.dumps([{
            "ClusterName": "Karolina",
            "IsClusterAccessible": False,
            "ErrorMessage": "SSH key rejected by host"
        }]).encode('utf-8')
        mock_controller.heappe_management_test_cluster_access_for_account_get.return_value = fake_resp

        req = self.factory.post("/projects/test_access/", {
            "ProjectId": "10",
            "username": "atr-26-4-01"
        })
        req.user = self.user
        req.session_code = "dummy_session"
        req.api_instance = mock.MagicMock()
        req.session = {}
        req._messages = mock.MagicMock()

        response = test_cluster_authentication_credential_HPC_access(req)
        self.assertEqual(response.status_code, 302)

        req._messages.add.assert_called()
        warning_calls = [call for call in req._messages.add.call_args_list if call[0][0] == messages.WARNING]
        self.assertTrue(len(warning_calls) > 0)
        msg_text = warning_calls[0][0][1]
        self.assertIn("Access denied for 'atr-26-4-01'", msg_text)

class SshKeysAndCredentialsVersionGatingTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    def test_obsolete_model_and_api_method(self):
        from py4heappe.heappe_v6.core.models.create_secure_shell_key_model_obsolete import CreateSecureShellKeyModelObsolete
        model = CreateSecureShellKeyModelObsolete(
            session_code="sess",
            username="user1",
            password="pwd",
            project_id=42
        )
        self.assertEqual(model.username, "user1")
        self.assertEqual(model.project_id, 42)
        d = model.to_dict()
        self.assertEqual(d["username"], "user1")
        self.assertEqual(d["project_id"], 42)

        import py4heappe.heappe_v6.core as hp
        self.assertTrue(hasattr(hp.ManagementApi, "heappe_management_secure_shell_key_post"))

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_new_hpc_account_success_generate(self, mock_mgmt_api):
        from heappe_ui.view.project import create_new_hpc_account
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller

        req = self.factory.post("/projects/create_account/", {
            "ProjectId": "10",
            "username": "new_user",
            "password": "secret_password"
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {}
        req._messages = mock.MagicMock()

        response = create_new_hpc_account(req)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_generate_secure_shell_key_post.assert_called_once()
        mock_controller.heappe_management_secure_shell_key_post.assert_not_called()

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_new_hpc_account_fallback_to_obsolete(self, mock_mgmt_api):
        from heappe_ui.view.project import create_new_hpc_account
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller

        # Simulate GenerateSecureShellKey failing (e.g. 404 endpoint not found on older server)
        mock_controller.heappe_management_generate_secure_shell_key_post.side_effect = Exception("404 Not Found")

        req = self.factory.post("/projects/create_account/", {
            "ProjectId": "10",
            "username": "old_user",
            "password": "old_password"
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {}
        req._messages = mock.MagicMock()

        response = create_new_hpc_account(req)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_generate_secure_shell_key_post.assert_called_once()
        mock_controller.heappe_management_secure_shell_key_post.assert_called_once()

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_new_hpc_account_fallback_to_direct_api_call(self, mock_mgmt_api):
        from heappe_ui.view.project import create_new_hpc_account
        mock_controller = mock.MagicMock(spec=["heappe_management_generate_secure_shell_key_post", "api_client"])
        mock_mgmt_api.return_value = mock_controller

        mock_controller.heappe_management_generate_secure_shell_key_post.side_effect = Exception("404 Not Found")
        mock_controller.api_client = mock.MagicMock()

        req = self.factory.post("/projects/create_account/", {
            "ProjectId": "10",
            "username": "direct_user",
            "password": "direct_password"
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {}
        req._messages = mock.MagicMock()

        response = create_new_hpc_account(req)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_generate_secure_shell_key_post.assert_called_once()
        mock_controller.api_client.call_api.assert_called_once()
        call_args = mock_controller.api_client.call_api.call_args
        self.assertEqual(call_args[0][0], '/heappe/Management/SecureShellKey')
        self.assertEqual(call_args[0][1], 'POST')

    @mock.patch("heappe_ui.view.project.render")
    @mock.patch("py4heappe.heappe_v6.core.CredentialsApi")
    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_project_detail_credentials_gated_at_v650(self, mock_mgmt_api, mock_cred_api, mock_render):
        from heappe_ui.view.project import project_detail
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller
        mock_cred_ctrl = mock.MagicMock()
        mock_cred_api.return_value = mock_cred_ctrl

        proj_obj = mock.MagicMock()
        proj_obj.to_dict.return_value = {"id": 1, "name": "Proj1"}
        mock_controller.heappe_management_project_get.return_value = proj_obj

        # 1. Test version 6.4.0: CredentialsApi should NOT be called
        req_640 = self.factory.get("/projects/1/?tab=accounts")
        req_640.user = self.user
        req_640.session_code = "sess_123"
        req_640.api_instance = mock.MagicMock()
        req_640.session = {"middleware_deployed_version": "6.4.0"}
        req_640._messages = mock.MagicMock()

        project_detail(req_640, project_id=1)
        mock_cred_ctrl.heappe_credentials_get_credentials_get.assert_not_called()
        render_context = mock_render.call_args[0][2]
        self.assertFalse(render_context["is_v6_5_0_plus"])
        self.assertTrue(render_context["is_v6_4_0_plus"])

        # 2. Test version 6.5.0: CredentialsApi should be called
        mock_cred_ctrl.reset_mock()
        mock_cred_ctrl.heappe_credentials_get_credentials_get.return_value = []
        req_650 = self.factory.get("/projects/1/?tab=accounts")
        req_650.user = self.user
        req_650.session_code = "sess_123"
        req_650.api_instance = mock.MagicMock()
        req_650.session = {"middleware_deployed_version": "6.5.0"}
        req_650._messages = mock.MagicMock()

        project_detail(req_650, project_id=1)
        self.assertEqual(mock_cred_ctrl.heappe_credentials_get_credentials_get.call_count, 2)
        render_context = mock_render.call_args[0][2]
        self.assertTrue(render_context["is_v6_5_0_plus"])


class CleanVersionResolutionTests(SimpleTestCase):
    """Test suite for resolve_clean_version and branch-to-clean-version handling."""

    def test_resolve_clean_version_direct_semver(self):
        from heappe_ui.DeployService import resolve_clean_version
        self.assertEqual(resolve_clean_version("v6.5.0"), "v6.5.0")
        self.assertEqual(resolve_clean_version("6.4.17"), "6.4.17")
        self.assertEqual(resolve_clean_version("V6.3.3"), "V6.3.3")
        self.assertEqual(resolve_clean_version("v6.0.0"), "v6.0.0")

    def test_resolve_clean_version_embedded_branch_version(self):
        from heappe_ui.DeployService import resolve_clean_version
        self.assertEqual(resolve_clean_version("release/v6.5.0"), "v6.5.0")
        self.assertEqual(resolve_clean_version("release/6.4.17"), "v6.4.17")
        self.assertEqual(resolve_clean_version("tags/v6.2.1"), "v6.2.1")

    def test_resolve_clean_version_feature_branch_with_old_version(self):
        from heappe_ui.DeployService import resolve_clean_version
        resolved = resolve_clean_version(
            version_or_ref="feature/qsheduler_machine_info_endpoint",
            old_version="v6.4.17"
        )
        self.assertEqual(resolved, "v6.4.17")

    def test_resolve_clean_version_feature_branch_fallback(self):
        from heappe_ui.DeployService import resolve_clean_version
        resolved = resolve_clean_version("feature/qsheduler_machine_info_endpoint")
        self.assertEqual(resolved, "v6.5.0")

    def test_extract_version_from_changelog_formats(self):
        from heappe_ui.DeployService import extract_version_from_changelog
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            # Test Keep a Changelog with [Unreleased] and bracketed versions
            cl_path = os.path.join(temp_dir, "CHANGELOG.md")
            with open(cl_path, "w", encoding="utf-8") as f:
                f.write("""# Changelog
All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- WIP feature

## [6.5.2] - 2024-05-10
### Added
- New endpoint

## [6.4.17] - 2024-01-15
### Fixed
- Bugfix
""")
            self.assertEqual(extract_version_from_changelog(temp_dir), "v6.5.2")
            self.assertEqual(extract_version_from_changelog(cl_path), "v6.5.2")

            # Test simple header format '## v6.6.0'
            with open(cl_path, "w", encoding="utf-8") as f:
                f.write("""# Changes
## v6.6.0 (2024-06-01)
- Released version 6.6.0
""")
            self.assertEqual(extract_version_from_changelog(temp_dir), "v6.6.0")

            # Test '### Version 7.0.1'
            with open(cl_path, "w", encoding="utf-8") as f:
                f.write("""# Project Changelog
### Version 7.0.1
- Major upgrade
""")
            self.assertEqual(extract_version_from_changelog(temp_dir), "v7.0.1")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resolve_clean_version_from_changelog_on_develop_branch(self):
        from heappe_ui.DeployService import resolve_clean_version
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp()
        try:
            cl_path = os.path.join(temp_dir, "CHANGELOG.md")
            with open(cl_path, "w", encoding="utf-8") as f:
                f.write("""# Changelog
## [Unreleased]
## [6.5.3] - 2024-07-20
""")
            # For develop branch with CHANGELOG present in compose_dir
            resolved = resolve_clean_version(
                version_or_ref="develop",
                compose_dir=temp_dir
            )
            self.assertEqual(resolved, "v6.5.3")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_resolve_clean_version_git_describe(self):
        from heappe_ui.DeployService import resolve_clean_version
        import subprocess

        # Using current repo directory which has tags
        resolved = resolve_clean_version(
            version_or_ref="feature/new_feature",
            compose_dir="."
        )
        # Should resolve to git tag reachable or highest tag, never feature/...
        self.assertNotIn("/", resolved)
        self.assertNotIn("feature", resolved)

    def test_update_init_with_branch_name_sanitizes_appsettings_and_swagger(self):
        import tempfile
        import shutil
        from heappe_ui.DeployService import HEAppEDeployService, HEAppEConfig

        temp_dir = tempfile.mkdtemp()
        try:
            instance_name = "test_branch_inst"
            confs_dir = os.path.join(temp_dir, instance_name, "app", "confs")
            core_dir = os.path.join(temp_dir, instance_name, "heappe-core")
            os.makedirs(confs_dir, exist_ok=True)
            os.makedirs(core_dir, exist_ok=True)

            # Create existing appsettings with valid version
            existing_appsettings = {
                "ApplicationAPISettings": {
                    "DeploymentSettings": {
                        "Version": "v6.4.17"
                    },
                    "SwaggerDocSettings": {
                        "Description": "HEAppE middleware API v6.4.17"
                    }
                }
            }
            with open(os.path.join(confs_dir, "appsettings.json"), "w", encoding="utf-8") as f:
                json.dump(existing_appsettings, f)

            existing_ds = {
                "ApplicationAPIConfiguration": {
                    "DeploymentConfiguration": {
                        "Version": "v6.4.17"
                    }
                }
            }
            with open(os.path.join(confs_dir, "appsettings-data.json"), "w", encoding="utf-8") as f:
                json.dump(existing_ds, f)

            service = HEAppEDeployService(HEAppEConfig(base_path=temp_dir))
            # Call update_init with a branch name containing slashes
            res = service.update_init(instance_name, "feature/qsheduler_machine_info_endpoint")
            self.assertEqual(res["status"], "success")

            # Check appsettings.json
            with open(os.path.join(confs_dir, "appsettings.json"), "r", encoding="utf-8") as f:
                updated_settings = json.load(f)

            app_ver = updated_settings["ApplicationAPISettings"]["DeploymentSettings"]["Version"]
            # Must NOT contain slashes or the branch name
            self.assertNotIn("/", app_ver)
            self.assertNotIn("feature", app_ver)
            self.assertEqual(app_ver, "v6.4.17")

            swagger_desc = updated_settings["ApplicationAPISettings"]["SwaggerDocSettings"]["Description"]
            self.assertNotIn("feature/", swagger_desc)
            self.assertIn("v6.4.17", swagger_desc)

            # Check appsettings-data.json
            with open(os.path.join(confs_dir, "appsettings-data.json"), "r", encoding="utf-8") as f:
                updated_ds = json.load(f)
            ds_ver = updated_ds["ApplicationAPIConfiguration"]["DeploymentConfiguration"]["Version"]
            self.assertNotIn("/", ds_ver)
            self.assertEqual(ds_ver, "v6.4.17")

            # Now test when old_version itself had slashes (e.g. from prior buggy version)
            updated_settings["ApplicationAPISettings"]["DeploymentSettings"]["Version"] = "feature/old_buggy_branch"
            with open(os.path.join(confs_dir, "appsettings.json"), "w", encoding="utf-8") as f:
                json.dump(updated_settings, f)

            # update_init should archive safely without crashing on file paths with slashes
            res2 = service.update_init(instance_name, "v6.5.0")
            self.assertEqual(res2["status"], "success")

            with open(os.path.join(confs_dir, "appsettings.json"), "r", encoding="utf-8") as f:
                final_settings = json.load(f)
            self.assertEqual(final_settings["ApplicationAPISettings"]["DeploymentSettings"]["Version"], "v6.5.0")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class ProjectSubProjectTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testuser", password="password")

    @mock.patch("heappe_ui.view.project.render")
    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_project_detail_subprojects_tab_renders(self, mock_mgmt_api, mock_render):
        from heappe_ui.view.project import project_detail
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller

        proj_obj = mock.MagicMock()
        proj_obj.to_dict.return_value = {"id": 1, "name": "Proj1"}
        mock_controller.heappe_management_project_get.return_value = proj_obj

        sp_mock = mock.MagicMock()
        sp_mock.to_dict.return_value = {
            "id": 10,
            "identifier": "SUB-01",
            "description": "Test subproject",
            "start_date": "2026-01-01T00:00:00",
            "end_date": "2026-12-31T23:59:59",
            "project_id": 1
        }
        mock_controller.heappe_management_sub_projects_get.return_value = [sp_mock]

        req = self.factory.get("/projects/1/?tab=subprojects")
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {"middleware_deployed_version": "6.5.0"}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        project_detail(req, project_id=1)
        mock_controller.heappe_management_sub_projects_get.assert_called_once()
        render_context = mock_render.call_args[0][2]
        self.assertEqual(render_context["active_tab"], "subprojects")
        self.assertEqual(len(render_context["sub_projects"]), 1)
        self.assertEqual(render_context["sub_projects"][0]["identifier"], "SUB-01")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_create_subproject_success(self, mock_mgmt_api):
        from heappe_ui.view.project import create_subproject
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller
        mock_controller.heappe_management_sub_project_post.return_value = {"Id": 11}

        req = self.factory.post("/projects/1/subprojects/create/", {
            "Identifier": "SUB-NEW",
            "Description": "New description",
            "StartDate": "2026-10-05T12:00",
            "EndDate": "2027-10-05T12:00",
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {"middleware_deployed_version": "6.5.0"}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        response = create_subproject(req, project_id=1)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_sub_project_post.assert_called_once()
        call_kwargs = mock_controller.heappe_management_sub_project_post.call_args[1]
        self.assertIn("body", call_kwargs)
        self.assertEqual(call_kwargs["body"]["Identifier"], "SUB-NEW")
        self.assertEqual(call_kwargs["body"]["ProjectId"], 1)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_modify_subproject_success(self, mock_mgmt_api):
        from heappe_ui.view.project import modify_subproject
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller
        mock_controller.heappe_management_sub_project_put.return_value = {"Id": 11}

        req = self.factory.post("/projects/1/subprojects/11/modify/", {
            "subproject_id": "11",
            "Identifier": "SUB-MODIFIED",
            "Description": "Updated desc",
            "StartDate": "2026-10-05T12:00",
            "EndDate": "",
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {"middleware_deployed_version": "6.5.0"}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        response = modify_subproject(req, project_id=1, subproject_id=11)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_sub_project_put.assert_called_once()
        call_kwargs = mock_controller.heappe_management_sub_project_put.call_args[1]
        self.assertEqual(call_kwargs["body"]["Id"], 11)
        self.assertEqual(call_kwargs["body"]["Identifier"], "SUB-MODIFIED")

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_delete_subproject_success(self, mock_mgmt_api):
        from heappe_ui.view.project import delete_subproject
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller
        mock_controller.heappe_management_sub_project_delete.return_value = "true"

        req = self.factory.post("/projects/1/subprojects/11/delete/", {
            "subproject_id": "11",
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {"middleware_deployed_version": "6.5.0"}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        response = delete_subproject(req, project_id=1, subproject_id=11)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_sub_project_delete.assert_called_once()
        call_kwargs = mock_controller.heappe_management_sub_project_delete.call_args[1]
        self.assertEqual(call_kwargs["body"]["Id"], 11)

    @mock.patch("py4heappe.heappe_v6.core.ManagementApi")
    def test_project_detail_post_action_subproject(self, mock_mgmt_api):
        from heappe_ui.view.project import project_detail
        mock_controller = mock.MagicMock()
        mock_mgmt_api.return_value = mock_controller
        mock_controller.heappe_management_sub_project_post.return_value = {"Id": 15}

        req = self.factory.post("/projects/1/", {
            "action": "create_subproject",
            "Identifier": "SUB-DISPATCH",
            "Description": "Via project detail post",
            "StartDate": "2026-10-05T12:00",
        })
        req.user = self.user
        req.session_code = "sess_123"
        req.api_instance = mock.MagicMock()
        req.session = {"middleware_deployed_version": "6.5.0"}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        response = project_detail(req, project_id=1)
        self.assertEqual(response.status_code, 302)
        mock_controller.heappe_management_sub_project_post.assert_called_once()


class InstanceTeardownAndDeploymentFailureTests(TestCase):
    """Tests for teardown_instance, instance deletion with shutdown, and deployment failure handling."""

    def setUp(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="testadmin", password="password")

    @mock.patch("heappe_ui.view.deploy.docker.from_env")
    @mock.patch("heappe_ui.view.deploy.execute_docker_compose")
    def test_teardown_instance_docker_and_files(self, mock_exec_compose, mock_docker_env):
        import tempfile
        from heappe_ui.view.deploy import teardown_instance
        import subprocess

        mock_exec_compose.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        mock_container = mock.MagicMock()
        mock_container.name = "heappe-test_inst"
        mock_container.status = "running"
        mock_container.labels = {"com.docker.compose.project": "test_inst"}

        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_docker_env.return_value = mock_client

        with tempfile.TemporaryDirectory() as temp_dir:
            inst_dir = os.path.join(temp_dir, "test_inst")
            core_dir = os.path.join(inst_dir, "heappe-core")
            os.makedirs(core_dir, exist_ok=True)

            res = teardown_instance("test_inst", base_path=temp_dir, stop_containers=True, delete_files=True)
            self.assertTrue(res["compose_down_success"])
            self.assertEqual(res["containers_stopped"], 1)
            self.assertEqual(res["containers_removed"], 1)
            self.assertTrue(res["files_removed"])
            self.assertFalse(os.path.exists(inst_dir))
            mock_container.stop.assert_called_once()
            mock_container.remove.assert_called_once()

    @mock.patch("heappe_ui.view.deploy.docker.from_env")
    @mock.patch("heappe_ui.view.deploy.execute_docker_compose")
    def test_teardown_instance_keep_files(self, mock_exec_compose, mock_docker_env):
        import tempfile
        from heappe_ui.view.deploy import teardown_instance
        import subprocess

        mock_exec_compose.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        mock_container = mock.MagicMock()
        mock_container.name = "heappe-test_inst"
        mock_container.status = "running"
        mock_container.labels = {"com.docker.compose.project": "test_inst"}
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_docker_env.return_value = mock_client

        with tempfile.TemporaryDirectory() as temp_dir:
            inst_dir = os.path.join(temp_dir, "test_inst")
            os.makedirs(inst_dir, exist_ok=True)

            res = teardown_instance("test_inst", base_path=temp_dir, stop_containers=True, delete_files=False)
            self.assertFalse(res["files_removed"])
            self.assertTrue(os.path.exists(inst_dir))

    @mock.patch("heappe_ui.views.teardown_instance")
    def test_instance_credentials_delete_calls_teardown(self, mock_teardown):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.views import instance_credentials_delete
        from django.contrib.messages.storage.fallback import FallbackStorage

        inst = InstanceCredentials.objects.create(
            instance_name="inst_to_del",
            heappe_host="localhost",
            heappe_login="admin",
            heappe_password="pwd",
            heappe_port="5000",
            log_db_host="localhost",
            log_db_port="6000",
            log_db_user="SA",
            log_db_password="pwd",
            log_db_database="db"
        )
        mock_teardown.return_value = {"files_removed": True}

        req = self.factory.post(f"/instances/{inst.pk}/delete/", {
            "stop_containers": "true",
            "delete_files": "true"
        })
        req.user = self.user
        req.session = {"chosen_instance": "inst_to_del", "heappe_session_code": "code123"}
        setattr(req, '_messages', FallbackStorage(req))

        resp = instance_credentials_delete(req, pk=inst.pk)
        self.assertEqual(resp.status_code, 302)
        mock_teardown.assert_called_once_with(instance_name="inst_to_del", stop_containers=True, delete_files=True)
        self.assertFalse(InstanceCredentials.objects.filter(pk=inst.pk).exists())
        self.assertNotIn("chosen_instance", req.session)

    @mock.patch("heappe_ui.views.teardown_instance")
    def test_instance_credentials_bulk_delete_calls_teardown(self, mock_teardown):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.views import instance_credentials_list
        from django.contrib.messages.storage.fallback import FallbackStorage

        inst1 = InstanceCredentials.objects.create(instance_name="inst_b1", heappe_host="h1", heappe_login="u", heappe_password="p", heappe_port="5000")
        inst2 = InstanceCredentials.objects.create(instance_name="inst_b2", heappe_host="h2", heappe_login="u", heappe_password="p", heappe_port="5001")

        req = self.factory.post("/instances/", {
            "action": "bulk_delete",
            "selected_ids": [inst1.pk, inst2.pk],
            "stop_containers": "true",
            "delete_files": "true"
        })
        req.user = self.user
        req.session = {}
        setattr(req, '_messages', FallbackStorage(req))

        resp = instance_credentials_list(req)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(mock_teardown.call_count, 2)
        self.assertFalse(InstanceCredentials.objects.filter(instance_name__in=["inst_b1", "inst_b2"]).exists())

    @mock.patch("heappe_ui.view.deploy.teardown_instance")
    def test_deploy_delete_instance_endpoint(self, mock_teardown):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.view.deploy import deploy_delete_instance
        from django.contrib.messages.storage.fallback import FallbackStorage

        InstanceCredentials.objects.create(instance_name="deploy_del_test", heappe_host="h", heappe_login="u", heappe_password="p", heappe_port="5000")

        req = self.factory.post("/deploy/deploy_del_test/delete/", {
            "stop_containers": "true",
            "delete_files": "true"
        })
        req.user = self.user
        req.session = {"chosen_instance": "deploy_del_test"}
        setattr(req, '_messages', FallbackStorage(req))

        resp = deploy_delete_instance(req, instance_name="deploy_del_test")
        self.assertEqual(resp.status_code, 302)
        mock_teardown.assert_called_once_with(instance_name="deploy_del_test", stop_containers=True, delete_files=True)
        self.assertFalse(InstanceCredentials.objects.filter(instance_name="deploy_del_test").exists())
        self.assertNotIn("chosen_instance", req.session)

    @mock.patch("heappe_ui.view.deploy.teardown_instance")
    def test_deploy_delete_instance_ajax(self, mock_teardown):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.view.deploy import deploy_delete_instance
        import json

        InstanceCredentials.objects.create(instance_name="ajax_del_test", heappe_host="h", heappe_login="u", heappe_password="p", heappe_port="5000")

        req = self.factory.post("/deploy/ajax_del_test/delete/", {
            "stop_containers": "true",
            "delete_files": "true"
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        req.user = self.user
        req.session = {}

        resp = deploy_delete_instance(req, instance_name="ajax_del_test")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["status"], "success")

    @mock.patch("heappe_ui.view.deploy.render")
    @mock.patch("heappe_ui.view.deploy.docker.from_env")
    def test_deploy_view_detects_deployment_failed(self, mock_docker_env, mock_render):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.view.deploy import deploy_view
        from django.http import HttpResponse

        mock_render.return_value = HttpResponse("OK")
        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = []
        mock_docker_env.return_value = mock_client

        inst = InstanceCredentials.objects.create(
            instance_name="failed_inst",
            heappe_host="localhost",
            heappe_login="admin",
            heappe_password="pwd",
            heappe_port="5000",
            is_deployed=False,
            is_updating=False
        )

        log_content = "[2026-10-19] Starting deploy...\nEXCEPTION: Docker compose build failed: Error in Dockerfile\n"

        orig_exists = os.path.exists
        def mock_exists(p):
            if "deploy.log" in str(p):
                return True
            return orig_exists(p)

        from unittest.mock import mock_open
        m_open = mock_open(read_data=log_content)

        with mock.patch("os.path.exists", side_effect=mock_exists):
            with mock.patch("builtins.open", m_open):
                req = self.factory.get("/deploy/failed_inst/")
                req.user = self.user
                req.session = {}

                deploy_view(req, instance_name="failed_inst")
                mock_render.assert_called_once()
                ctx = mock_render.call_args[0][2]
                self.assertTrue(ctx["deployment_failed"])
                self.assertIn("Docker compose build failed", ctx["deployment_error"])
                self.assertIn("EXCEPTION:", ctx["deploy_logs"])

    def test_maintenance_pane_template_rendering(self):
        from django.template.loader import render_to_string
        from django.test import RequestFactory
        factory = RequestFactory()
        req = factory.get("/deploy/develop/")
        req.user = self.user
        req.session = {"chosen_instance": "develop"}

        context = {
            "request": req,
            "instance_name": "develop",
            "is_deployed": True,
            "containers": [{"name": "heappe", "status": "running"}],
            "repo_url": "https://github.com/IT4Innovations/HEAppE.git",
            "repo_branch": "develop",
            "branches": ["develop", "main", "release/v6.6.0"],
            "branch_list": ["develop", "main"],
            "tag_list": ["v6.6.0", "v6.5.0"],
            "current_git_ref": {"branch": "develop", "commit": "48767517", "description": "develop (48767517)"},
            "deployed_version": "6.6.0",
            "latest_version": "6.6.0",
            "update_available": False,
        }

        rendered = render_to_string("deploy.html", context, request=req)

        # Check tab header exists
        self.assertIn('id="maintenance-tab"', rendered)
        self.assertIn('Maintenance &amp; Setup', rendered)

        # Check tab pane exists
        self.assertIn('id="maintenance-pane"', rendered)

        # Check all 4 panels exist
        self.assertIn('Switch Branch &amp; Build', rendered)
        self.assertIn('Regenerate Configs', rendered)
        self.assertIn('Deploy New Instance', rendered)
        self.assertIn('Delete &amp; Teardown Instance', rendered)

        # Check forms exist without mt-auto pushing them down
        self.assertIn('id="update-form"', rendered)
        self.assertIn('id="regenerate-configs-form"', rendered)
        self.assertIn('id="deploy-form"', rendered)
        self.assertNotIn('class="instance-action-form mt-auto"', rendered)

        # Check modal triggers exist
        self.assertIn('id="deleteTeardownModal"', rendered)
        self.assertIn('id="switchBranchModal"', rendered)












def _cli_target(t):
    """
    Mock QScheduler target without the admin API (< 0.2.1): its machine / notifier operations run the real CLI code
    path, so the tests can check the qscheduler commands in t.cli.call_args_list.
    """
    from heappe_ui.view.qscheduler_core import QsTarget
    t.uses_admin_api.return_value = False
    for name in ("add_machine", "remove_machine", "add_notifier", "remove_notifier", "_cli_write"):
        setattr(t, name, getattr(QsTarget, name).__get__(t))
    return t


class QSchedulerHelperTests(TestCase):
    """Pure helpers: CLI arguments, parsing, redaction, cluster configuration."""

    def test_machine_options_defaults(self):
        from heappe_ui.view.qscheduler_machines import parse_machine_options
        opts, errors = parse_machine_options({"qscheduler_id": "3"}, "abcd1234")
        self.assertEqual(errors, [])
        self.assertEqual(opts['machine_mode'], 'new')
        self.assertEqual(opts['machine_name'], 'SimulatorMachine')
        self.assertEqual(opts['cluster_name'], 'SimulatorMachine')
        self.assertEqual(opts['project_name'], 'qs-abcd1234')

    def test_machine_options_require_instance_and_iqm_fields(self):
        from heappe_ui.view.qscheduler_machines import parse_machine_options
        _, errors = parse_machine_options({"backend": "iqm", "machine_name": "VLQ", "iqm_poll_interval": "500"}, "x")
        joined = " ".join(errors)
        for text in ("QScheduler instance", "IQM server URL", "device", "IQM token", "unit suffix"):
            self.assertIn(text, joined)

    def test_machine_options_existing_machine_skips_backend_validation(self):
        from heappe_ui.view.qscheduler_machines import parse_machine_options
        opts, errors = parse_machine_options({"qscheduler_id": "1", "machine_mode": "existing", "machine_name": "Shared",
                                              "backend": "iqm", "create_project": False}, "x")
        self.assertEqual(errors, [])
        self.assertIsNone(opts['project_name'])

    def test_machine_args_new_cli(self):
        from heappe_ui.view.qscheduler_machines import parse_machine_options
        from heappe_ui.view.qscheduler_core import machine_args
        opts, _ = parse_machine_options({"qscheduler_id": "1", "machine_name": "Sim"}, "x")
        args = machine_args(opts)
        self.assertEqual(args[:3], ["machine", "add", "Sim"])
        self.assertEqual(args[-1], "test")
        self.assertLess(args.index("--limit-check-interval"), args.index("test"))
        self.assertNotIn("--notify-url", args)       # notifications are not part of a machine any more
        opts, errors = parse_machine_options({"qscheduler_id": "1", "backend": "iqm", "machine_name": "VLQ",
                                              "iqm_url": "https://vlq.it4i.cz", "iqm_device": "star24",
                                              "iqm_token": "secret"}, "x")
        self.assertEqual(errors, [])
        args = machine_args(opts)
        i = args.index("iqm")
        self.assertIn("--poll-interval", args[i:])
        self.assertNotIn("--check-interval", args)
        self.assertIn("--machine-name", args[i:])

    def test_notifier_args_and_list_parsing(self):
        from heappe_ui.view.qscheduler_core import notifier_add_args, parse_notifier_list, redact_args
        args = notifier_add_args("heappe-dev", "http://h/heappe/JobManagement/TaskCallback", "tok")
        self.assertEqual(args[:3], ["notifier", "add", "heappe-dev"])
        self.assertEqual(redact_args(args)[-2:], ["--token", "********"])
        out = "NAME        TOKEN  URL\nheappe-dev  yes    http://h/cb\nother       no     http://x/cb\n"
        self.assertEqual(parse_notifier_list(out), [
            {"name": "heappe-dev", "has_token": True, "url": "http://h/cb"},
            {"name": "other", "has_token": False, "url": "http://x/cb"}])
        self.assertEqual(parse_notifier_list("No notifiers registered.\n"), [])

    def test_redact_and_serve_port(self):
        from heappe_ui.view.qscheduler_core import redact_args, parse_serve_port
        joined = " ".join(redact_args(["-e", "DATABASE_URL=postgres://u:pw@h/db", "--token", "abc", "-e", "POSTGRES_PASSWORD=x"]))
        self.assertNotIn("pw@", joined)
        self.assertNotIn("abc", joined)
        self.assertNotIn("PASSWORD=x", joined)
        self.assertEqual(parse_serve_port(["serve", "--port", "4305"]), 4305)
        self.assertEqual(parse_serve_port(["serve"]), 4300)

    def test_cluster_configuration_with_own_notifier(self):
        from heappe_ui.view.qscheduler_core import build_cluster_custom_configuration, cluster_notifier_name
        inst = mock.Mock(service_host="qs-1", port=4301)
        name = cluster_notifier_name("heappe-dev", "Sim")
        self.assertEqual(name, "heappe-dev.Sim")
        cfg, toggles = build_cluster_custom_configuration(inst, (name, "tok"))
        self.assertEqual(cfg, {"QSchedulerHost": "qs-1", "QSchedulerPort": "4301", "QSchedulerUseSessions": "true",
                               "EnableCallback": "true", "QSchedulerNotifier": "heappe-dev.Sim", "QSchedulerNotifyToken": "tok"})
        self.assertEqual(toggles, {"QSchedulerNotifyToken": True})        # token always in Vault
        cfg, toggles = build_cluster_custom_configuration(inst, None, use_sessions=False)
        self.assertEqual(cfg["EnableCallback"], "false")
        self.assertNotIn("QSchedulerNotifier", cfg)
        self.assertNotIn("QSchedulerNotifyToken", cfg)
        self.assertEqual(toggles, {})

    def test_update_cluster_notifications_keeps_other_settings(self):
        from heappe_ui.view.qscheduler_core import update_cluster_notifications
        controller = mock.Mock()
        cluster = {"id": 7, "name": "Sim", "description": "d", "master_node_name": "qs-1", "scheduler_type": 32,
                   "connection_protocol": 8, "time_zone": "UTC", "port": 4300, "domain_name": None,
                   "proxy_connection": None,
                   "custom_configuration": {"QSchedulerHost": "qs-1", "QSchedulerPort": "4300", "EnableCallback": "true",
                                            "QSchedulerNotifier": "old", "QSchedulerNotifyToken": "********",
                                            "ClusterCallbackNotifyToken": "********"},
                   "custom_configuration_vault_toggles": {"QSchedulerNotifyToken": True, "ClusterCallbackNotifyToken": True}}
        update_cluster_notifications(controller, "sc", cluster, None, lambda *_: None)
        body = controller.heappe_management_cluster_put.call_args.kwargs["body"]
        self.assertEqual(body["Id"], 7)
        # disabled: notifier removed; empty Vault-toggled token makes HEAppE delete it from Vault
        self.assertEqual(body["CustomConfiguration"], {"QSchedulerHost": "qs-1", "QSchedulerPort": "4300",
                                                       "EnableCallback": "false", "QSchedulerNotifyToken": "",
                                                       "ClusterCallbackNotifyToken": "********"})
        self.assertEqual(body["CustomConfigurationVaultToggles"], {"QSchedulerNotifyToken": True, "ClusterCallbackNotifyToken": True})
        update_cluster_notifications(controller, "sc", cluster, ("heappe-dev.Sim", "new"), lambda *_: None)
        body = controller.heappe_management_cluster_put.call_args.kwargs["body"]
        self.assertEqual(body["CustomConfiguration"]["QSchedulerNotifier"], "heappe-dev.Sim")
        self.assertEqual(body["CustomConfiguration"]["QSchedulerNotifyToken"], "new")
        self.assertTrue(body["CustomConfigurationVaultToggles"]["QSchedulerNotifyToken"])

    def test_qscheduler_clusters_match_host_and_port(self):
        from heappe_ui.view.qscheduler_core import qscheduler_clusters, cluster_machine
        inst = mock.Mock(service_host="qs-1", port=4300, hosts=["qs-1", "vlq.machine.qscheduler.it4i.cz"])
        mk = lambda **kw: mock.Mock(to_dict=mock.Mock(return_value=kw))
        controller = mock.Mock()
        controller.heappe_management_clusters_get.return_value = [
            mk(id=1, scheduler_type=32, master_node_name="qs-1", port=4300, custom_configuration={},
               node_types=[{"queue": "Sim"}]),
            mk(id=2, scheduler_type=32, master_node_name="x", custom_configuration={"QSchedulerHost": "qs-1", "QSchedulerPort": "4300"}),
            mk(id=3, scheduler_type=32, master_node_name="qs-1", port=4301, custom_configuration={}),
            mk(id=4, scheduler_type=4, master_node_name="qs-1", port=4300),
            mk(id=5, scheduler_type=32, master_node_name="vlq.machine.qscheduler.it4i.cz", port=4300,
               custom_configuration={}),                                                 # alias of the instance
        ]
        found = qscheduler_clusters(controller, "sc", inst)
        self.assertEqual([c["id"] for c in found], [1, 2, 5])
        self.assertEqual(cluster_machine(found[0]), "Sim")

    def test_container_shell_target_exports_database_url(self):
        from heappe_ui.view.qscheduler_core import ContainerShellTarget, CommandResult
        ssh = mock.Mock(host="h", port=2222)
        ssh.run.return_value = CommandResult(0, "ok", "")
        target = ContainerShellTarget(ssh, 4300, "postgres://u:p@db/q")
        target.cli(["notifier", "list"], lambda *_: None)
        cmd = ssh.run.call_args.args[0]
        self.assertTrue(cmd.startswith("export DATABASE_URL="))
        self.assertTrue(cmd.endswith("qscheduler notifier list"))
        ContainerShellTarget(ssh, 4300).cli(["notifier", "list"], lambda *_: None)
        self.assertIn("/proc/1/environ", ssh.run.call_args.args[0])

    def test_recreate_args_keep_configuration(self):
        from heappe_ui.view import qscheduler_deploy as q
        info = {"Id": "abcdef1234567890", "Name": "/qs-1",
                "Config": {"Image": "qscheduler:latest", "Cmd": ["serve", "--port", "4301"],
                           "Env": ["DATABASE_URL=postgres://u:pw@qs-1-pgsql:5432/db", "PATH=/usr/bin"],
                           "Labels": {"com.docker.compose.service": "qscheduler"}},
                "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"},
                               "PortBindings": {"4301/tcp": [{"HostIp": "127.0.0.1", "HostPort": "14301"}]}},
                "NetworkSettings": {"Networks": {"qs-1_db_net": {"Aliases": ["qs-1", "abcdef123456"]},
                                                 "inst_external_network": {"Aliases": ["qs-1"]}}}}
        internal = {"qs-1_db_net": True, "inst_external_network": False}
        with mock.patch.object(q, "_network_is_internal", side_effect=lambda n, d=None: internal[n]):
            args, nets, port = q.recreate_args_from_inspect(info, "qscheduler:new", {"qscheduler.branch": "v2"})
        self.assertEqual(port, 4301)
        self.assertEqual(nets[0][0], "inst_external_network")
        self.assertIn("127.0.0.1:14301:4301", args)
        self.assertIn("DATABASE_URL=postgres://u:pw@qs-1-pgsql:5432/db", args)
        self.assertFalse(any(a.startswith("PATH=") for a in args))
        self.assertIn("qscheduler.branch=v2", args)
        self.assertIn("--health-cmd", args)
        self.assertEqual(args[-4:], ["qscheduler:new", "serve", "--port", "4301"])


class QSchedulerOptionParsingTests(TestCase):
    def test_deploy_defaults_and_source(self):
        from heappe_ui.view.qscheduler_deploy import parse_deploy_options
        opts, errors = parse_deploy_options({}, "abcd1234")
        self.assertEqual(errors, [])
        self.assertEqual(opts['name'], "qscheduler-abcd1234")
        opts, errors = parse_deploy_options({"name": "mydev"}, "5190156f")
        self.assertEqual((opts['name'], errors), ("mydev-5190156f", []))           # custom prefix + random id
        self.assertEqual(parse_deploy_options({"name": "dev-"}, "5190156f")[0]['name'], "dev-5190156f")
        self.assertTrue(parse_deploy_options({"name": "-bad"}, "x")[1])
        self.assertTrue(parse_deploy_options({"name": "a" * 55}, "x")[1])
        self.assertEqual(parse_deploy_options({"name": "a" * 54}, "5190156f")[0]['name'], "a" * 54 + "-5190156f")
        self.assertEqual(opts['source'], "git")
        self.assertIsNone(opts['host_port'])
        _, errors = parse_deploy_options({"source": "git", "repo": "file:///etc", "ref": "bad ref"}, "x")
        self.assertEqual(len(errors), 2)
        opts, errors = parse_deploy_options({"source": "image", "image": "registry.example.org/qscheduler:v0.2"}, "x")
        self.assertEqual(errors, [])

    def test_register_local_and_ssh(self):
        from heappe_ui.view.qscheduler_deploy import parse_register_options
        opts, errors = parse_register_options({"kind": "local", "container_name": "qs-ext"})
        self.assertEqual(errors, [])
        self.assertEqual((opts['name'], opts['service_host']), ("qs-ext", "qs-ext"))
        _, errors = parse_register_options({"kind": "ssh_host", "container_name": "qs", "ssh_host": "vm.example.org"})
        self.assertTrue(any("SSH user" in e for e in errors))
        self.assertTrue(any("private key" in e for e in errors))
        key = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"
        opts, errors = parse_register_options({"kind": "ssh_container", "ssh_host": "vm.example.org", "ssh_port": "2222",
                                               "ssh_user": "root", "ssh_private_key": key})
        self.assertEqual(errors, [])
        self.assertEqual((opts['ssh_port'], opts['service_host'], opts['restart_command']), (2222, "vm.example.org", "kill -TERM 1"))
        _, errors = parse_register_options({"kind": "ssh_host", "container_name": "qs", "ssh_host": "vm", "ssh_user": "u",
                                            "ssh_private_key": key, "docker_command": "rm -rf /; docker"})
        self.assertTrue(any("Docker command" in e for e in errors))

    def test_assignment_options(self):
        from heappe_ui.view.qscheduler_deploy import parse_assignment_options
        opts, errors = parse_assignment_options({"heappe_instance_id": "2", "notifications_enabled": True})
        self.assertEqual(errors, [])
        self.assertTrue(opts['notifications_enabled'])
        _, errors = parse_assignment_options({"heappe_instance_id": "", "callback_url": "ftp://x"})
        self.assertEqual(len(errors), 2)


class QSchedulerWorkflowTests(TestCase):
    """Assignment / machine workflows with QScheduler, Docker and HEAppE mocked."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)
        self.log = lambda *_: None

    def _target(self, notifiers=None, machines=None):
        from heappe_ui.view.qscheduler_core import CommandResult
        target = mock.Mock()
        target.list_notifiers.return_value = notifiers or []
        target.list_machines.return_value = machines
        target.cli.return_value = CommandResult(0, "ok", "")
        target.docker.networks_of.return_value = []
        return _cli_target(target)

    def _patches(self, target, version="6.6.0", clusters=None):
        from heappe_ui.view import qscheduler_core as core
        controller = mock.Mock()
        return [
            mock.patch.object(core, "target_for", return_value=target),
            mock.patch.object(core, "heappe_identity", return_value=(version, "heappe-dev")),
            mock.patch.object(core, "resolve_heappe_service_network", return_value=("dev_heappe", "dev_external")),
            mock.patch.object(core, "restart_heappe"),
            mock.patch.object(core, "check_from_heappe"),
            mock.patch.object(core, "find_heappe_api_container", return_value="dev_heappe"),
            mock.patch.object(core, "qscheduler_clusters", return_value=clusters or []),
            mock.patch.object(core, "update_cluster_notifications"),
            mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)),
        ], controller

    def _run(self, patches, fn, *args):
        for p in patches:
            p.start()
        try:
            result = {}
            fn(self.log, result, *args)
            return result
        finally:
            for p in patches:
                p.stop()

    @staticmethod
    def _cluster(cid, machine, notifier=None):
        cfg = {"QSchedulerHost": "qs-1", "QSchedulerPort": "4300",
               "EnableCallback": "true" if notifier else "false"}
        if notifier:
            cfg.update({"QSchedulerNotifier": notifier, "QSchedulerNotifyToken": "********"})
        return {"id": cid, "name": machine, "node_types": [{"queue": machine}], "custom_configuration": cfg}

    def _added(self, target):
        return [c.args[0] for c in target.cli.call_args_list if c.args[0][:2] == ["notifier", "add"]]

    def _removed(self, target):
        return [c.args[0][2] for c in target.cli.call_args_list if c.args[0][:2] == ["notifier", "remove"]]

    def test_assign_without_clusters_creates_no_notifier(self):
        from heappe_ui.view.qscheduler_deploy import assign_worker
        from heappe_ui.models import QSchedulerAssignment
        target = self._target()
        patches, _ = self._patches(target)
        opts = {"heappe_instance_id": str(self.cred.id), "notifications_enabled": True, "callback_url": ""}
        self._run(patches, assign_worker, self.inst.id, opts)
        asg = QSchedulerAssignment.objects.get(qscheduler=self.inst, heappe_instance=self.cred)
        self.assertTrue(asg.notifications_enabled)
        self.assertEqual(asg.heappe_identifier, "heappe-dev")
        self.assertEqual(asg.network, "dev_external")
        self.assertEqual(asg.callback_url, "http://dev_heappe:80/heappe/JobManagement/TaskCallback")
        self.assertEqual(self._added(target), [])    # notifiers are created per cluster on the Clusters page
        target.restart.assert_not_called()
        target.docker.run.assert_called()           # joined the HEAppE network

    def test_enabling_notifications_creates_one_notifier_per_cluster(self):
        from heappe_ui.view.qscheduler_deploy import assign_worker
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred, heappe_identifier="heappe-dev")
        target = self._target()
        patches, _ = self._patches(target, clusters=[self._cluster(5, "Sim"), self._cluster(6, "VLQ")])
        opts = {"heappe_instance_id": str(self.cred.id), "notifications_enabled": True, "callback_url": "http://h/cb"}
        for p in patches:
            p.start()
        try:
            result = {}
            assign_worker(self.log, result, self.inst.id, opts)
            calls = core.update_cluster_notifications.call_args_list
        finally:
            for p in patches:
                p.stop()
        added = self._added(target)
        self.assertEqual(sorted(a[2] for a in added), ["heappe-dev.Sim", "heappe-dev.VLQ"])
        tokens = {a[2]: a[-1] for a in added}
        self.assertNotEqual(tokens["heappe-dev.Sim"], tokens["heappe-dev.VLQ"])      # own token per cluster
        target.restart.assert_called_once()                                        # one restart for all
        notifiers = {c.args[2]["id"]: c.args[3] for c in calls}
        self.assertEqual(notifiers[5], ("heappe-dev.Sim", tokens["heappe-dev.Sim"]))
        self.assertEqual(result['updated_clusters'], [5, 6])

    def test_disabling_notifications_removes_cluster_notifiers(self):
        from heappe_ui.view.qscheduler_deploy import assign_worker
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred, heappe_identifier="heappe-dev",
                                            notifications_enabled=True, callback_url="http://h/cb")
        target = self._target(notifiers=[{"name": "heappe-dev.Sim", "has_token": True, "url": "http://h/cb"},
                                         {"name": "other.Sim", "has_token": True, "url": "http://o/cb"}])
        patches, _ = self._patches(target, clusters=[self._cluster(5, "Sim", "heappe-dev.Sim")])
        opts = {"heappe_instance_id": str(self.cred.id), "notifications_enabled": False}
        for p in patches:
            p.start()
        try:
            assign_worker(self.log, {}, self.inst.id, opts)
            calls = core.update_cluster_notifications.call_args_list
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(self._removed(target), ["heappe-dev.Sim"])     # the other HEAppE's notifier is untouched
        self.assertEqual(self._added(target), [])
        self.assertIsNone(calls[0].args[3])

    def test_unchanged_settings_keep_notifiers(self):
        from heappe_ui.view.qscheduler_deploy import assign_worker
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred, heappe_identifier="heappe-dev",
                                            notifications_enabled=True, callback_url="http://h/cb")
        target = self._target()
        patches, _ = self._patches(target, clusters=[self._cluster(5, "Sim", "heappe-dev.Sim")])
        opts = {"heappe_instance_id": str(self.cred.id), "notifications_enabled": True, "callback_url": "http://h/cb"}
        self._run(patches, assign_worker, self.inst.id, opts)
        target.cli.assert_not_called()
        target.restart.assert_not_called()

    def test_assign_refuses_duplicate_identifier(self):
        from heappe_ui.view.qscheduler_deploy import assign_worker
        from heappe_ui.models import InstanceCredentials, QSchedulerAssignment
        other = InstanceCredentials.objects.create(instance_name="other", heappe_host="h2", heappe_login="u",
                                                   heappe_password="p", heappe_port="5001")
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=other, heappe_identifier="heappe-dev")
        patches, _ = self._patches(self._target())
        opts = {"heappe_instance_id": str(self.cred.id), "notifications_enabled": True}
        with self.assertRaisesRegex(RuntimeError, "same instance identifier"):
            self._run(patches, assign_worker, self.inst.id, opts)

    def test_assign_rejects_heappe_older_than_660(self):
        from heappe_ui.view.qscheduler_deploy import assign_worker
        from heappe_ui.models import QSchedulerAssignment
        for version, notify in (("6.5.2", True), ("6.5.2", False), ("", False)):
            target = self._target()
            patches, _ = self._patches(target, version=version)
            opts = {"heappe_instance_id": str(self.cred.id), "notifications_enabled": notify}
            with self.assertRaisesRegex(RuntimeError, "6.6.0"):
                self._run(patches, assign_worker, self.inst.id, opts)
            target.cli.assert_not_called()
        self.assertFalse(QSchedulerAssignment.objects.filter(qscheduler=self.inst, heappe_instance=self.cred).exists())

    def test_supports_qscheduler_versions(self):
        from heappe_ui.view import qscheduler_core as core
        for v in ("6.6.0", "v6.6.0", "6.6.1", "7.0.0"):
            self.assertTrue(core.supports_qscheduler(v), v)
        for v in ("", None, "6.5.0", "v6.5.9", "6.4.0"):
            self.assertFalse(core.supports_qscheduler(v), v)

    def test_unassign_blocked_while_clusters_exist(self):
        from heappe_ui.view.qscheduler_deploy import unassign_worker
        from heappe_ui.models import QSchedulerAssignment
        asg = QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred)
        patches, _ = self._patches(self._target(), clusters=[self._cluster(5, "Sim")])
        with self.assertRaisesRegex(RuntimeError, "still has clusters"):
            self._run(patches, unassign_worker, asg.id, False)
        self.assertTrue(QSchedulerAssignment.objects.filter(pk=asg.pk).exists())

    def test_unassign_removes_leftover_notifiers(self):
        from heappe_ui.view.qscheduler_deploy import unassign_worker
        from heappe_ui.models import QSchedulerAssignment
        asg = QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred,
                                                  heappe_identifier="heappe-dev", notifications_enabled=True)
        target = self._target(notifiers=[{"name": "heappe-dev.Old", "has_token": True, "url": "http://x"},
                                         {"name": "other.Sim", "has_token": True, "url": "http://o"}])
        patches, _ = self._patches(target)
        self._run(patches, unassign_worker, asg.id, False)
        self.assertEqual(self._removed(target), ["heappe-dev.Old"])
        self.assertFalse(QSchedulerAssignment.objects.filter(pk=asg.pk).exists())

    def test_add_new_machine_that_exists_is_refused(self):
        from heappe_ui.view.qscheduler_machines import add_machine_worker, parse_machine_options
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred)
        opts, _ = parse_machine_options({"qscheduler_id": str(self.inst.id), "machine_name": "Sim"}, "x")
        patches, _ = self._patches(self._target(machines=[{"name": "Sim", "backend": "test"}]))
        with self.assertRaisesRegex(RuntimeError, "Use existing machine"):
            self._run(patches, add_machine_worker, "dev", opts, "x")

    def test_add_new_machine_creates_machine_and_notifier_with_one_restart(self):
        from heappe_ui.view.qscheduler_machines import add_machine_worker, parse_machine_options
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred, heappe_identifier="heappe-dev",
                                            notifications_enabled=True, callback_url="http://h/cb")
        opts, _ = parse_machine_options({"qscheduler_id": str(self.inst.id), "machine_name": "Sim", "create_project": False}, "x")
        target = self._target(machines=[])
        patches, controller = self._patches(target)
        controller.heappe_management_cluster_post.return_value = {"id": 12}
        result = self._run(patches, add_machine_worker, "dev", opts, "x")
        commands = [c.args[0][:2] for c in target.cli.call_args_list]
        self.assertEqual(commands, [["machine", "add"], ["notifier", "add"]])
        target.restart.assert_called_once()
        added = self._added(target)[0]
        self.assertEqual(added[2:5], ["heappe-dev.Sim", "--url", "http://h/cb"])
        body = controller.heappe_management_cluster_post.call_args.kwargs["body"]
        self.assertEqual(body["CustomConfiguration"]["QSchedulerNotifyToken"], added[-1])
        self.assertEqual(body["CustomConfigurationVaultToggles"], {"QSchedulerNotifyToken": True})
        self.assertEqual(result['notifier'], "heappe-dev.Sim")

    def test_add_existing_machine_gets_own_notifier(self):
        from heappe_ui.view.qscheduler_machines import add_machine_worker, parse_machine_options
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred, heappe_identifier="heappe-dev",
                                            notifications_enabled=True, callback_url="http://h/cb")
        opts, _ = parse_machine_options({"qscheduler_id": str(self.inst.id), "machine_mode": "existing",
                                         "machine_name": "Sim", "create_project": False}, "x")
        # machine shared with another HEAppE, which has its own notifier for it
        target = self._target(machines=[{"name": "Sim", "backend": "test"}],
                              notifiers=[{"name": "other.Sim", "has_token": True, "url": "http://o/cb"}])
        patches, controller = self._patches(target)
        controller.heappe_management_cluster_post.return_value = {"id": 11}
        result = self._run(patches, add_machine_worker, "dev", opts, "x")
        self.assertEqual([c.args[0][:2] for c in target.cli.call_args_list], [["notifier", "add"]])   # no machine add
        self.assertEqual(self._removed(target), [])
        target.restart.assert_called_once()
        body = controller.heappe_management_cluster_post.call_args.kwargs["body"]
        self.assertEqual(body["MasterNodeName"], "qs-1")
        self.assertEqual(body["CustomConfiguration"]["QSchedulerNotifier"], "heappe-dev.Sim")
        self.assertEqual(body["CustomConfiguration"]["EnableCallback"], "true")
        self.assertTrue(body["CustomConfigurationVaultToggles"]["QSchedulerNotifyToken"])
        self.assertEqual(result['cluster_id'], 11)
        controller.heappe_management_project_post.assert_not_called()

    def test_add_machine_without_notifications(self):
        from heappe_ui.view.qscheduler_machines import add_machine_worker, parse_machine_options
        from heappe_ui.models import QSchedulerAssignment
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred)
        opts, _ = parse_machine_options({"qscheduler_id": str(self.inst.id), "machine_mode": "existing",
                                         "machine_name": "Sim", "create_project": False}, "x")
        target = self._target(machines=[{"name": "Sim", "backend": "test"}])
        patches, controller = self._patches(target)
        controller.heappe_management_cluster_post.return_value = {"id": 11}
        self._run(patches, add_machine_worker, "dev", opts, "x")
        target.cli.assert_not_called()
        target.restart.assert_not_called()
        body = controller.heappe_management_cluster_post.call_args.kwargs["body"]
        self.assertEqual(body["CustomConfiguration"]["EnableCallback"], "false")
        self.assertNotIn("QSchedulerNotifyToken", body["CustomConfiguration"])

    def test_remove_machine_removes_cluster_notifier(self):
        from heappe_ui.view.qscheduler_machines import remove_machine_worker
        target = self._target(notifiers=[{"name": "heappe-dev.Sim", "has_token": True, "url": "http://h/cb"}])
        patches, controller = self._patches(target)
        cluster = dict(self._cluster(5, "Sim", "heappe-dev.Sim"), scheduler_type=32, master_node_name="qs-1", port=4300)
        controller.heappe_management_cluster_get.return_value = cluster
        result = self._run(patches, remove_machine_worker, "dev",
                           {"cluster_id": 5, "remove_from_qscheduler": False, "force": False})
        self.assertEqual(self._removed(target), ["heappe-dev.Sim"])
        self.assertFalse(any(c.args[0][:2] == ["machine", "remove"] for c in target.cli.call_args_list))
        target.restart.assert_called_once()
        controller.heappe_management_cluster_delete.assert_called_once()
        self.assertEqual(result['removed_notifier'], "heappe-dev.Sim")


class QSchedulerClusterDetailTemplateTests(TestCase):
    """Cluster detail: QScheduler badge and notifier fields in the Webhook & Callback section."""

    def _render(self, scheduler_type):
        import json as _json
        import re
        from django.template.loader import get_template
        request = RequestFactory().get("/")
        request.session = {}
        request.user = AnonymousUser()
        html = get_template("cluster_detail.html").render({
            'cluster': {'id': 7, 'name': 'Sim', 'scheduler_type': scheduler_type, 'connection_protocol': 8},
            'active_tab': 'detail', 'proxy_connections': [], 'is_v6_4_0_plus': True, 'is_v6_5_0_plus': True,
            'custom_configuration_json': _json.dumps({"EnableCallback": "true", "QSchedulerNotifier": "heappe-dev.Sim",
                                                      "QSchedulerNotifyToken": "********"}),
            'custom_configuration_vault_toggles_json': _json.dumps({"QSchedulerNotifyToken": True}),
            'custom_config_metadata_json': '[]'}, request)
        badge = re.search(r'id="qs-cluster-badge" class="([^"]*)"', html).group(1)
        return html, badge

    def test_qscheduler_cluster_has_badge_and_notifier_fields(self):
        html, badge = self._render(32)
        self.assertNotIn("d-none", badge)
        self.assertIn("QScheduler cluster", html)
        self.assertIn('id="cb-QSchedulerNotifier"', html)
        self.assertIn('id="cb-QSchedulerNotifyToken"', html)
        # notifier keys are handled by the callback section, not listed as additional parameters
        self.assertIn("'QSchedulerNotifier', 'QSchedulerNotifyToken'];", html)

    def test_other_clusters_hide_badge(self):
        _, badge = self._render(4)
        self.assertIn("d-none", badge)


class QSchedulerViewTests(TestCase):
    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        self.user = User.objects.create_user(username="qs_admin", password="p")
        self.client.force_login(self.user)
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred)
        session = self.client.session
        session["chosen_instance"] = "dev"
        session["middleware_deployed_version"] = "6.6.0"
        session.save()

    @mock.patch("heappe_ui.view.qscheduler_core.start_operation")
    def test_undeploy_blocked_while_assigned(self, start):
        response = self.client.post(f"/qscheduler/{self.inst.id}/undeploy/", data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("dev", response.json()["message"])
        start.assert_not_called()

    @mock.patch("heappe_ui.view.qscheduler_core.start_operation")
    def test_machine_add_requires_assignment(self, start):
        from heappe_ui.models import QSchedulerInstance
        other = QSchedulerInstance.objects.create(name="qs-2", kind="managed", container_name="qs-2", service_host="qs-2")
        response = self.client.post("/clusters/qscheduler/machine-add/", data=json.dumps({"qscheduler_id": other.id}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)
        start.assert_not_called()
        start.return_value = (True, "started")
        response = self.client.post("/clusters/qscheduler/machine-add/", data=json.dumps({"qscheduler_id": self.inst.id}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        start.assert_called_once()

    @mock.patch("heappe_ui.view.qscheduler_core.start_operation")
    def test_machine_add_requires_heappe_660(self, start):
        for version in ("6.5.0", ""):
            session = self.client.session
            session["middleware_deployed_version"] = version
            session.save()
            response = self.client.post("/clusters/qscheduler/machine-add/",
                                        data=json.dumps({"qscheduler_id": self.inst.id}), content_type="application/json")
            self.assertEqual(response.status_code, 400, version)
            self.assertIn("6.6.0", response.json()["message"])
        start.assert_not_called()

    @mock.patch("heappe_ui.view.qscheduler_core.start_operation")
    @mock.patch("heappe_ui.view.qscheduler_core.heappe_identity", return_value=("6.5.0", "heappe-dev"))
    def test_assign_api_refuses_old_heappe(self, _identity, start):
        response = self.client.post(f"/qscheduler/{self.inst.id}/assign/",
                                    data=json.dumps({"heappe_instance_id": str(self.cred.id)}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("6.6.0", response.json()["message"])
        start.assert_not_called()

    def test_clusters_page_hides_qscheduler_menu_before_660(self):
        from django.template.loader import render_to_string
        html_old = render_to_string("clusters.html", {"clusters": [], "is_v6_6_0_plus": False})
        html_new = render_to_string("clusters.html", {"clusters": [], "is_v6_6_0_plus": True})
        self.assertNotIn('id="qschedulerMenuBtnEmpty"', html_old)
        self.assertIn('id="qschedulerMenuBtnEmpty"', html_new)
        self.assertIn('id="qs-add-machine_select"', html_new)        # existing machine: dropdown ...
        self.assertIn('id="qs-add-machine_name" name="machine_name"', html_new)   # ... with the text field as fallback

    @mock.patch("heappe_ui.view.qscheduler_deploy.import_legacy_instances")
    def test_page_lists_instances_and_assignments(self, _import):
        response = self.client.get("/qscheduler/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "qs-1")
        self.assertContains(response, "Assigned HEAppE instances")

    @mock.patch("heappe_ui.view.qscheduler_deploy.import_legacy_instances")
    def test_ssh_container_instance_shows_limited_management_warning(self, _import):
        from heappe_ui.models import QSchedulerInstance
        response = self.client.get("/qscheduler/")
        self.assertNotContains(response, "Limited management: no Docker control")
        QSchedulerInstance.objects.create(name="qs-remote", kind="ssh_container", service_host="vm", ssh_host="vm",
                                          ssh_user="root", restart_command="")
        response = self.client.get("/qscheduler/")
        self.assertContains(response, "Limited management: no Docker control")   # card badge
        self.assertContains(response, "qs-sshc-warning")                         # modal reminders
        self.assertContains(response, "Confirm manual restart")

    def test_manual_restart_confirmation_only_checks_health(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_deploy import restart_worker
        inst = QSchedulerInstance.objects.create(name="qs-remote", kind="ssh_container", service_host="vm",
                                                 restart_command="", restart_pending=True)
        target = mock.Mock()
        with mock.patch.object(core, "target_for", return_value=target):
            restart_worker(lambda *_: None, {}, inst.id)
        target.restart.assert_not_called()
        target.wait_healthy.assert_called_once()
        inst.refresh_from_db()
        self.assertFalse(inst.restart_pending)

    @mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", side_effect=RuntimeError("down"))
    def test_machine_defaults_lists_assigned_instances(self, _conn):
        response = self.client.get("/clusters/qscheduler/machine-defaults/")
        data = response.json()
        self.assertEqual([i["name"] for i in data["instances"]], ["qs-1"])
        self.assertIn("down", data["clusters_error"])


class InstanceConfigOidcActionTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        from heappe_ui.models import InstanceCredentials
        self.user = User.objects.create_user(username="admin_user", password="password123")
        self.client.force_login(self.user)
        self.instance = InstanceCredentials.objects.create(
            instance_name="test_inst",
            heappe_host="127.0.0.1",
            heappe_login="admin",
            heappe_password="secret_password",
            heappe_port="5000",
            log_db_host="127.0.0.1",
            log_db_port="1433",
            log_db_user="sa",
            log_db_password="sa_password",
            log_db_database="log_db"
        )
        session = self.client.session
        session["chosen_instance"] = "test_inst"
        session.save()

    @mock.patch("heappe_ui.view.deploy.docker.from_env")
    def test_oidc_action_empty_authority(self, mock_docker):
        mock_container = mock.MagicMock()
        mock_container.labels = {'com.docker.compose.project': 'test_inst', 'com.docker.compose.service': 'heappe'}
        mock_container.name = 'test_inst_heappe'
        mock_docker.return_value.containers.list.return_value = [mock_container]

        response = self.client.post(f"/deploy/test_inst/config/", {
            "action": "test_oidc",
            "authority": ""
        })
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "danger")
        self.assertIn("cannot be empty", data["message"])

    @mock.patch("heappe_ui.view.deploy.docker.from_env")
    @mock.patch("urllib.request.urlopen")
    def test_oidc_action_successful_discovery(self, mock_urlopen, mock_docker):
        mock_container = mock.MagicMock()
        mock_container.labels = {'com.docker.compose.project': 'test_inst', 'com.docker.compose.service': 'heappe'}
        mock_container.name = 'test_inst_heappe'
        mock_docker.return_value.containers.list.return_value = [mock_container]

        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = (
            b'{"issuer": "https://kc.example.com/realms/demo", '
            b'"token_endpoint": "https://kc.example.com/realms/demo/protocol/openid-connect/token", '
            b'"userinfo_endpoint": "https://kc.example.com/realms/demo/protocol/openid-connect/userinfo"}'
        )
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        response = self.client.post(f"/deploy/test_inst/config/", {
            "action": "test_oidc",
            "authority": "https://kc.example.com/realms/demo"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["details"]["issuer"], "https://kc.example.com/realms/demo")
        self.assertEqual(data["details"]["token_endpoint"], "https://kc.example.com/realms/demo/protocol/openid-connect/token")


class SystemUpdateStatusApiTests(TestCase):
    def test_status_endpoint_no_logs_and_no_process(self):
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("subprocess.check_output", side_effect=Exception("not running")):
            response = self.client.get("/api/system-update-status/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["is_running"])
            self.assertFalse(data["is_success"])
            self.assertFalse(data["is_failed"])
            self.assertEqual(data["logs"], "")

    def test_status_endpoint_process_running(self):
        mock_log = "[2026-10-19 15:00:00] === START DEPLOYMENT: main ===\nFetching origin...\n"
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=mock_log)), \
             mock.patch("subprocess.check_output", return_value=b"1234\n"):
            response = self.client.get("/api/system-update-status/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertTrue(data["is_running"])
            self.assertFalse(data["is_success"])
            self.assertFalse(data["is_failed"])
            self.assertIn("Fetching origin", data["logs"])

    def test_status_endpoint_deployment_succeeded(self):
        mock_log = (
            "[2026-10-19 15:00:00] === START DEPLOYMENT: main ===\n"
            "Migrating...\n"
            "[2026-10-19 15:00:20] === SUCCESS ===\n"
        )
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=mock_log)), \
             mock.patch("subprocess.check_output", side_effect=Exception("not running")):
            response = self.client.get("/api/system-update-status/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["is_running"])
            self.assertTrue(data["is_success"])
            self.assertFalse(data["is_failed"])
            self.assertIn("=== SUCCESS ===", data["logs"])

    def test_status_endpoint_deployment_failed(self):
        mock_log = (
            "[2026-10-19 15:00:00] === START DEPLOYMENT: main ===\n"
            "ERROR: Step failed. Exiting.\n"
        )
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=mock_log)), \
             mock.patch("subprocess.check_output", side_effect=Exception("not running")):
            response = self.client.get("/api/system-update-status/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["is_running"])
            self.assertFalse(data["is_success"])
            self.assertTrue(data["is_failed"])
            self.assertIn("ERROR: Step failed", data["logs"])

    def test_status_endpoint_isolates_current_deployment_slice(self):
        mock_log = (
            "[2026-10-18 10:00:00] === START DEPLOYMENT: v1 ===\n"
            "Old output\n"
            "=== SUCCESS ===\n"
            "[2026-10-19 15:00:00] === START DEPLOYMENT: v2 ===\n"
            "New output in progress\n"
        )
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=mock_log)), \
             mock.patch("subprocess.check_output", return_value=b"5678\n"):
            response = self.client.get("/api/system-update-status/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["is_running"])
            self.assertFalse(data["is_success"])
            self.assertNotIn("Old output", data["logs"])
            self.assertIn("New output in progress", data["logs"])

    def test_status_endpoint_deployment_succeeded_without_explicit_success_marker(self):
        mock_log = (
            "[2026-10-20 13:00:00] === START DEPLOYMENT: main ===\n"
            "Migrating...\n"
            "129 static files copied to '/opt/heappe/heappe-admin-app/branches/main/static'.\n"
        )
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=mock_log)), \
             mock.patch("subprocess.check_output", side_effect=Exception("not running")):
            response = self.client.get("/api/system-update-status/")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertFalse(data["is_running"])
            self.assertTrue(data["is_success"])
            self.assertFalse(data["is_failed"])
            self.assertIn("static files copied", data["logs"])



class TestHeappeIdentifierFormulaAndPropagation(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin_ident",
            password="adminpassword123",
            email="admin_ident@example.com"
        )
        self.client.force_login(self.user)

    def test_build_heappe_identifier_standard(self):
        from heappe_ui.appsettings.generator import build_heappe_identifier
        ident = build_heappe_identifier("core", "dev", "it4i", "develop")
        self.assertEqual(ident, "core_dev_it4i_develop")

        ident2 = build_heappe_identifier("efp", "prod", "it4i", "inference")
        self.assertEqual(ident2, "efp_prod_it4i_inference")

    def test_build_heappe_identifier_stripping_and_fallback(self):
        from heappe_ui.appsettings.generator import build_heappe_identifier
        ident = build_heappe_identifier(" core ", " DEV ", " it4i ", " My Instance ")
        self.assertEqual(ident, "core_dev_it4i_my_instance")

        # Fallback when parts are missing
        self.assertEqual(build_heappe_identifier("", "", "", "custom_name"), "custom_name")

    def test_parse_heappe_identifier(self):
        from heappe_ui.appsettings.generator import parse_heappe_identifier
        d = parse_heappe_identifier("core_dev_it4i_develop")
        self.assertEqual(d["scope"], "core")
        self.assertEqual(d["environment"], "dev")
        self.assertEqual(d["provider"], "it4i")
        self.assertEqual(d["instance_name"], "develop")

        # Multi-underscore instance name
        d = parse_heappe_identifier("core_dev_it4i_deep_learning_v2")
        self.assertEqual(d["scope"], "core")
        self.assertEqual(d["environment"], "dev")
        self.assertEqual(d["provider"], "it4i")
        self.assertEqual(d["instance_name"], "deep_learning_v2")

        # Non-formula identifier
        d = parse_heappe_identifier("legacy-instance")
        self.assertEqual(d["scope"], "")
        self.assertEqual(d["instance_name"], "legacy-instance")

        # None input
        d = parse_heappe_identifier(None)
        self.assertEqual(d["scope"], "")
        self.assertEqual(d["instance_name"], "")

    def test_generate_appsettings_v6_6_0_with_identifier(self):
        from heappe_ui.appsettings.generator import generate_appsettings_v6_6_0
        cfg = generate_appsettings_v6_6_0(
            instance_name="my_inst",
            sa_password="MySecretPassword123!",
            instance_identifier="core_dev_it4i_develop"
        )
        self.assertEqual(
            cfg["HPCConnectionFrameworkSettings"]["ScriptsSettings"]["InstanceIdentifierPath"],
            "core_dev_it4i_develop"
        )
        self.assertEqual(
            cfg["ApplicationAPISettings"]["DeploymentSettings"]["Name"],
            "core_dev_it4i_develop instance"
        )

    def test_generate_appsettings_v6_6_0_fallback_without_identifier(self):
        from heappe_ui.appsettings.generator import generate_appsettings_v6_6_0
        cfg = generate_appsettings_v6_6_0(
            instance_name="fallback_inst",
            sa_password="MySecretPassword123!"
        )
        self.assertEqual(
            cfg["HPCConnectionFrameworkSettings"]["ScriptsSettings"]["InstanceIdentifierPath"],
            "fallback_inst"
        )
        self.assertEqual(
            cfg["ApplicationAPISettings"]["DeploymentSettings"]["Name"],
            "fallback_inst instance"
        )

    def test_generate_appsettings_efp_v6_6_0_with_identifier(self):
        from heappe_ui.appsettings.generator import generate_appsettings_efp_v6_6_0
        cfg = generate_appsettings_efp_v6_6_0(
            instance_name="efp_inst",
            sa_password="MySecretPassword123!",
            instance_identifier="efp_prod_it4i_cluster"
        )
        self.assertEqual(
            cfg["HPCConnectionFrameworkSettings"]["ScriptsSettings"]["InstanceIdentifierPath"],
            "efp_prod_it4i_cluster"
        )

    def test_deploy_view_renders_identifier_builder_card(self):
        response = self.client.get("/deploy/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("heappe-identifier-builder-card", content)
        self.assertIn("InstanceIdentifier", content)
        self.assertIn("ident-f-scope", content)
        self.assertIn("core_dev_it4i_develop", content)
        self.assertIn("NEXUS &amp; AAI Registration Workflow", content)

    def test_instance_health_check_api_fallback_reads_identifier(self):
        from heappe_ui.models import InstanceCredentials
        from django.urls import reverse
        cred = InstanceCredentials.objects.create(
            instance_name="test_ident_inst",
            heappe_host="http://invalid.local",
            heappe_port="8080",
            heappe_login="user",
            heappe_password="password"
        )
        mock_json_content = json.dumps({
            "HPCConnectionFrameworkSettings": {
                "ScriptsSettings": {
                    "InstanceIdentifierPath": "core_stage_it4i_inference"
                }
            }
        })
        with mock.patch("os.path.exists", return_value=True), \
             mock.patch("builtins.open", mock.mock_open(read_data=mock_json_content)):
            url = reverse("instance_health_check_api", args=[cred.pk])
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["instance_identifier"], "core_stage_it4i_inference")



class QSchedulerGitRefsTests(TestCase):
    """Branch / tag picker of the deploy and update forms."""

    def setUp(self):
        from heappe_ui.view import qscheduler_core as core
        core._git_refs_cache.clear()

    @staticmethod
    def _resp(data):
        r = mock.Mock()
        r.json.return_value = data
        r.raise_for_status.return_value = None
        return r

    def test_github_api(self):
        from heappe_ui.view import qscheduler_core as core
        def get(url, **kw):
            if url.endswith("/branches"):
                return self._resp([{"name": "feature"}, {"name": "main"}])
            if url.endswith("/tags"):
                return self._resp([{"name": "v0.2.0"}, {"name": "v0.10.0"}])
            return self._resp({"default_branch": "main"})
        with mock.patch("requests.get", side_effect=get) as g:
            r = core.list_git_refs("https://github.com/It4innovations/qscheduler.git")
        self.assertEqual(r["source"], "github")
        self.assertEqual(r["branches"], ["main", "feature"])      # default branch first
        self.assertEqual(r["tags"], ["v0.10.0", "v0.2.0"])         # newest version first
        self.assertTrue(g.call_args_list[0][0][0].startswith("https://api.github.com/repos/It4innovations/qscheduler"))
        with mock.patch("requests.get") as g2:                     # cached
            core.list_git_refs("https://github.com/It4innovations/qscheduler.git")
            g2.assert_not_called()

    def test_gitlab_api_for_other_hosts(self):
        from heappe_ui.view import qscheduler_core as core
        def get(url, **kw):
            if url.endswith("/repository/branches"):
                return self._resp([{"name": "master"}])
            if url.endswith("/repository/tags"):
                return self._resp([{"name": "1.0"}])
            return self._resp({"default_branch": "master"})
        with mock.patch("requests.get", side_effect=get) as g:
            r = core.list_git_refs("https://gitlab.example.org/group/sub/qscheduler.git")
        self.assertEqual((r["source"], r["branches"], r["tags"]), ("gitlab", ["master"], ["1.0"]))
        self.assertIn("/api/v4/projects/group%2Fsub%2Fqscheduler", g.call_args_list[0][0][0])

    def test_falls_back_to_ls_remote(self):
        from heappe_ui.view import qscheduler_core as core
        out = ("ref: refs/heads/dev\tHEAD\nabc\tHEAD\nabc\trefs/heads/dev\nabd\trefs/heads/main\n"
               "abe\trefs/tags/v1.0\nabf\trefs/tags/v1.0^{}\n")
        with mock.patch("requests.get", side_effect=OSError("no API")), \
             mock.patch.object(core.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=out, stderr="")) as run:
            r = core.list_git_refs("https://git.example.org/qscheduler.git")
        self.assertEqual((r["source"], r["branches"], r["tags"], r["default_branch"]), ("git", ["dev", "main"], ["v1.0"], "dev"))
        self.assertEqual(run.call_args[1]["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_ssh_url_uses_ls_remote_only(self):
        from heappe_ui.view import qscheduler_core as core
        with mock.patch("requests.get") as g, \
             mock.patch.object(core.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="a\trefs/heads/main\n", stderr="")):
            r = core.list_git_refs("git@github.com:It4innovations/qscheduler.git")
        g.assert_not_called()
        self.assertEqual(r["branches"], ["main"])

    def test_invalid_and_unreachable(self):
        from heappe_ui.view import qscheduler_core as core
        for bad in ("", "ftp://x/y", "-uhttps://x", "https://x/y z"):
            with self.assertRaises(ValueError):
                core.list_git_refs(bad)
        with mock.patch("requests.get", side_effect=OSError("down")), \
             mock.patch.object(core.subprocess, "run", return_value=mock.Mock(returncode=128, stdout="", stderr="fatal: nope")):
            with self.assertRaisesRegex(RuntimeError, "nope"):
                core.list_git_refs("https://git.example.org/x.git")

    def test_view(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user(username="refs_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        with mock.patch("heappe_ui.view.qscheduler_core.list_git_refs",
                        return_value={"branches": ["main"], "tags": [], "default_branch": "main", "source": "github"}):
            d = self.client.get("/qscheduler/git-refs/", {"repo": "https://github.com/a/b.git"}).json()
        self.assertEqual((d["status"], d["branches"]), ("success", ["main"]))
        with mock.patch("heappe_ui.view.qscheduler_core.list_git_refs", side_effect=RuntimeError("down")):
            d = self.client.get("/qscheduler/git-refs/", {"repo": "https://github.com/a/b.git"}).json()
        self.assertEqual(d["status"], "error")
        self.assertIn("down", d["message"])
        self.assertEqual(self.client.get("/qscheduler/git-refs/", {"repo": "ftp://x"}).status_code, 400)


class CoverageReportDataTests(TestCase):
    """`manage.py qscheduler_coverage` input: runs without coverage.py (not named QScheduler*, so not measured)."""

    def test_feature_code_references_exist(self):
        import tomllib
        from pathlib import Path
        from django.conf import settings
        from heappe_ui.management.commands import qscheduler_coverage as qc
        cfg = tomllib.loads(qc.DATA_FILE.read_text())
        indexes = {k: qc.code_index(Path(settings.BASE_DIR) / p) for k, p in cfg["files"].items()}
        qc.Command().validate_refs(cfg, indexes)      # raises CommandError on a renamed / removed function
        for section in cfg["sections"]:
            for f in section["features"]:
                self.assertTrue(f.get("code") or f.get("status") in qc.STATUSES, f["name"])

    def test_code_index_and_counting(self):
        import tempfile
        from pathlib import Path
        from heappe_ui.management.commands import qscheduler_coverage as qc
        src = "import os\n\n\n@decorator\ndef f(x):\n    if x:\n        return 1\n    return 2\n\n\nclass C:\n    A = 1\n\n    def m(self):\n        return 3\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.py"
            path.write_text(src)
            index = qc.code_index(path)
        self.assertEqual(index["f"], [(6, 8)])           # body only: decorator and def run at import time
        self.assertEqual(index["C.m"], [(15, 15)])
        self.assertEqual(index["C"], [(15, 15)])         # class = its methods
        measured = qc.Measured({"executed_lines": [1, 5, 6, 7, 11, 12, 14], "missing_lines": [8, 15],
                                "executed_branches": [[6, 7]], "missing_branches": [[6, 8]]})
        self.assertEqual(measured.count(index["f"]), {'lines': 3, 'covered': 2, 'branches': 2, 'covered_branches': 1})
        self.assertEqual(measured.count(index["C"])["covered"], 0)

    def test_unmapped_lists_whole_classes_once(self):
        from heappe_ui.management.commands import qscheduler_coverage as qc
        indexes = {"core": {"f": [(1, 1)], "g": [(2, 2)], "C": [(3, 3)], "C.a": [(3, 3)], "D": [(4, 5)], "D.a": [(4, 4)],
                            "D.b": [(5, 5)]}}
        cfg = {"unmapped": {"ignore": ["core:g"]}}
        rows = qc.Command().unmapped(cfg, indexes, {("core", "f"), ("core", "D.a")})
        self.assertEqual([r["ref"] for r in rows], ["core:C", "core:D.b"])


class QSchedulerRecoveryTests(TestCase):
    """QScheduler service removed without HEAppE Management: presence, archive, cascade deletion, restore."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300, source="git",
                                                      repo="https://github.com/It4innovations/qscheduler.git", ref="main",
                                                      image="qscheduler:latest")
        self.asg = QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred,
                                                       heappe_identifier="heappe-dev", notifications_enabled=True,
                                                       callback_url="http://h/cb")
        self.log = lambda *_: None

    @staticmethod
    def _cluster(cid, machine, project=None, group=None, token=True):
        cfg = {"QSchedulerHost": "qs-1", "QSchedulerPort": "4300", "EnableCallback": "true",
               "QSchedulerNotifier": f"heappe-dev.{machine}"}
        if token:
            cfg["QSchedulerNotifyToken"] = "********"
        nt = {"queue": machine, "projects": [project] if project else [],
              "cluster_node_type_aggregation": group}
        return {"id": cid, "name": machine, "scheduler_type": 32, "master_node_name": "qs-1", "port": 4300,
                "node_types": [nt], "custom_configuration": cfg,
                "custom_configuration_vault_toggles": {"QSchedulerNotifyToken": True}, "file_transfer_method_ids": [cid * 10]}

    def _heappe(self, clusters, all_clusters=None):
        controller = mock.Mock()
        controller.heappe_management_clusters_get.return_value = all_clusters if all_clusters is not None else clusters
        controller.heappe_management_project_cluster_node_type_aggregations_get.return_value = []
        controller.heappe_management_cluster_node_type_aggregation_accountings_get.return_value = []
        return controller

    # ---- presence ----

    def test_presence(self):
        from heappe_ui.view import qscheduler_core as core
        with mock.patch.object(core.DockerCli, "inspect", return_value=None):
            self.assertEqual(core.presence(self.inst)[0], core.MISSING)
        with mock.patch.object(core.DockerCli, "inspect", return_value={"State": {"Status": "exited"}}):
            self.assertEqual(core.presence(self.inst), (core.PRESENT, "container 'qs-1' is exited"))
        with mock.patch.object(core.DockerCli, "inspect", side_effect=RuntimeError("Docker CLI not found")):
            self.assertEqual(core.presence(self.inst), (core.UNREACHABLE, "Docker CLI not found"))
        self.inst.kind, self.inst.ssh_host = "ssh_container", "vm"
        session = mock.Mock()
        with mock.patch.object(core, "ssh_session_for", return_value=session):
            self.assertEqual(core.presence(self.inst)[0], core.PRESENT)          # SSH login into the container works
            session.connect.side_effect = RuntimeError("SSH connection to vm:22 failed")
            self.assertEqual(core.presence(self.inst)[0], core.UNREACHABLE)      # down and removed look the same
        session.close.assert_called()

    def test_live_marks_existing_but_not_responding_as_restartable(self):
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="rec_admin5", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        target = mock.Mock()
        target.health.return_value = None
        target.list_notifiers.side_effect = RuntimeError("container is not running")
        target.list_machines.return_value = None
        target.version.return_value = "0.3.0"
        with mock.patch.object(core, "target_for", return_value=target):
            with mock.patch.object(core, "presence", return_value=(core.PRESENT, "container 'qs-1' is exited")):
                d = self.client.get(f"/qscheduler/{self.inst.id}/live/").json()
            self.assertEqual((d["presence"], d["restartable"]), ("present", True))
            with mock.patch.object(core, "presence", return_value=(core.MISSING, "gone")):
                self.assertFalse(self.client.get(f"/qscheduler/{self.inst.id}/live/").json()["restartable"])
            target.health.return_value = 200
            self.assertFalse(self.client.get(f"/qscheduler/{self.inst.id}/live/").json()["restartable"])
        with mock.patch("heappe_ui.view.qscheduler_deploy.import_legacy_instances"):
            html = self.client.get("/qscheduler/").content.decode()
        self.assertIn("qs-try-restart-btn", html)
        self.assertIn("Try restart", html)

    # ---- archive ----

    def test_archive_refuses_running_and_archives_missing(self):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_recovery import archive_instance, unarchive_instance
        with mock.patch.object(core, "presence", return_value=(core.PRESENT, "")):
            with self.assertRaisesRegex(RuntimeError, "running"):
                archive_instance(self.inst, "x")
        with mock.patch.object(core, "presence", return_value=(core.MISSING, "container 'qs-1' not found")):
            archive_instance(self.inst, "")
            with self.assertRaisesRegex(RuntimeError, "still not available"):
                unarchive_instance(self.inst)
        self.inst.refresh_from_db()
        self.assertTrue(self.inst.is_archived)
        self.assertEqual(self.inst.archived_reason, "container 'qs-1' not found")
        self.assertTrue(self.inst.assignments.exists())                      # assignments kept
        with mock.patch.object(core, "presence", return_value=(core.PRESENT, "")):
            unarchive_instance(self.inst)
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.is_archived)

    def test_archive_and_unarchive_api(self):
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="rec_admin4", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        post = lambda path, data=None: self.client.post(path, data=json.dumps(data or {}), content_type="application/json")
        with mock.patch.object(core, "presence", return_value=(core.MISSING, "gone")):
            self.assertEqual(post(f"/qscheduler/{self.inst.id}/archive/", {"reason": "removed by hand"}).status_code, 200)
            self.assertEqual(post(f"/qscheduler/{self.inst.id}/archive/").status_code, 400)     # already archived
            self.assertEqual(post(f"/qscheduler/{self.inst.id}/unarchive/").status_code, 400)   # still gone
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.archived_reason, "removed by hand")
        with mock.patch.object(core, "presence", return_value=(core.PRESENT, "")):
            self.assertEqual(post(f"/qscheduler/{self.inst.id}/unarchive/").status_code, 200)
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.is_archived)

    def test_archived_instance_is_not_managed(self):
        from datetime import datetime, timezone
        from heappe_ui.view.qscheduler_machines import add_machine_worker, remove_machine_worker, parse_machine_options
        from heappe_ui.view import qscheduler_core as core
        self.inst.archived_at = datetime.now(timezone.utc)
        self.inst.save()
        opts, _ = parse_machine_options({"qscheduler_id": str(self.inst.id), "create_project": False}, "x")
        with self.assertRaisesRegex(RuntimeError, "archived"):
            add_machine_worker(self.log, {}, "dev", opts, "x")
        controller = self._heappe([])
        controller.heappe_management_cluster_get.return_value = dict(self._cluster(5, "Sim"), scheduler_type=32,
                                                                     master_node_name="qs-1", port=4300)
        with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)), \
             mock.patch.object(core, "target_for") as target_for:
            remove_machine_worker(self.log, {}, "dev", {'cluster_id': 5, 'remove_from_qscheduler': False, 'force': False})
            with self.assertRaisesRegex(RuntimeError, "archived"):
                remove_machine_worker(self.log, {}, "dev", {'cluster_id': 5, 'remove_from_qscheduler': True, 'force': False})
        target_for.assert_not_called()                                        # QScheduler is never contacted
        controller.heappe_management_cluster_delete.assert_called_once()

    def test_views_refuse_archived_and_live_reports_presence(self):
        from datetime import datetime, timezone
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="rec_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        self.inst.archived_at = datetime.now(timezone.utc)
        self.inst.save()
        for path in (f"/qscheduler/{self.inst.id}/restart/", f"/qscheduler/{self.inst.id}/undeploy/",
                     f"/qscheduler/{self.inst.id}/assign/", f"/qscheduler/assignment/{self.asg.id}/unassign/"):
            response = self.client.post(path, data="{}", content_type="application/json")
            self.assertEqual(response.status_code, 400, path)
            self.assertIn("archived", response.json()["message"])
        with mock.patch.object(core, "presence", return_value=(core.PRESENT, "")):
            d = self.client.get(f"/qscheduler/{self.inst.id}/live/").json()
        self.assertEqual((d["archived"], d["presence"]), (True, "present"))

    # ---- cascade deletion ----

    def test_cluster_dependents_only_exclusive(self):
        from heappe_ui.view.qscheduler_recovery import cluster_dependents
        p1, p2 = {"id": 1, "name": "own"}, {"id": 2, "name": "shared"}
        g1, g2 = {"id": 7, "name": "QPU own"}, {"id": 8, "name": "QPU shared"}
        mine = [self._cluster(5, "Sim", p1, g1), self._cluster(6, "VLQ", p2, g2)]
        other = {"id": 9, "name": "slurm", "node_types": [{"projects": [p2], "cluster_node_type_aggregation": g2}]}
        projects, groups = cluster_dependents(mine, mine + [other])
        self.assertEqual((projects, groups), ({1: "own"}, {7: "QPU own"}))

    def _cascade(self, controller, opts=None, connect_error=None):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_recovery import cascade_delete_worker, parse_cascade_options
        options, _ = parse_cascade_options(dict({"confirm_name": "qs-1"}, **(opts or {})))
        docker = mock.Mock()
        docker.exists.return_value = True
        docker.json.return_value = [{}]
        connect = (mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", side_effect=connect_error)
                   if connect_error else
                   mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)))
        result = {}
        with connect, mock.patch.object(core, "presence", return_value=(core.MISSING, "gone")), \
             mock.patch("heappe_ui.view.qscheduler_recovery.DockerCli", return_value=docker), \
             mock.patch.object(core, "update_cluster_notifications") as upd:
            cascade_delete_worker(self.log, result, self.inst.id, options)
        return result, docker, upd

    def test_cascade_deletes_clusters_and_selected_entities(self):
        from heappe_ui.models import QSchedulerInstance
        p1, g1 = {"id": 1, "name": "qs-abc"}, {"id": 7, "name": "QPU Group abc"}
        clusters = [self._cluster(5, "Sim", p1, g1)]
        controller = self._heappe(clusters)
        controller.heappe_management_cluster_node_type_aggregation_accountings_get.return_value = [
            {"cluster_node_type_aggregation_id": 7, "accounting_id": 70}]
        controller.heappe_management_project_cluster_node_type_aggregations_get.return_value = [
            {"cluster_node_type_aggregation_id": 7, "project_id": 1}]
        result, docker, upd = self._cascade(controller, {"delete_projects": True, "delete_queue_groups": True,
                                                          "remove_db_volume": True})
        self.assertEqual(upd.call_args.args[3], None)                         # token removed from Vault first
        controller.heappe_management_cluster_delete.assert_called_once_with(body={"Id": 5, "SessionCode": "sc"})
        controller.heappe_management_project_delete.assert_called_once_with(body={"Id": 1, "SessionCode": "sc"})
        controller.heappe_management_accounting_delete.assert_called_once_with(body={"Id": 70, "SessionCode": "sc"})
        controller.heappe_management_cluster_node_type_aggregation_delete.assert_called_once_with(body={"Id": 7, "SessionCode": "sc"})
        commands = [c.args[0] for c in docker.run.call_args_list]
        self.assertIn(["rm", "-f", "qs-1-pgsql"], commands)
        self.assertIn(["volume", "rm", "qs-1-pgdata"], commands)
        self.assertFalse(QSchedulerInstance.objects.filter(pk=self.inst.pk).exists())
        self.assertEqual(result['deleted_projects'], ["dev: qs-abc"])

    def test_cascade_keeps_projects_and_volume_by_default(self):
        controller = self._heappe([self._cluster(5, "Sim", {"id": 1, "name": "p"}, {"id": 7, "name": "g"})])
        _, docker, _ = self._cascade(controller)
        controller.heappe_management_project_delete.assert_not_called()
        controller.heappe_management_cluster_node_type_aggregation_delete.assert_not_called()
        self.assertNotIn(["volume", "rm", "qs-1-pgdata"], [c.args[0] for c in docker.run.call_args_list])

    def test_cascade_without_clusters_does_not_contact_heappe(self):
        from heappe_ui.models import QSchedulerInstance
        self._cascade(None, {"delete_clusters": False, "delete_projects": True},
                      connect_error=AssertionError("HEAppE must not be contacted"))
        self.assertFalse(QSchedulerInstance.objects.filter(pk=self.inst.pk).exists())

    def test_cascade_unreachable_heappe_aborts_or_is_skipped(self):
        from heappe_ui.models import QSchedulerInstance
        with self.assertRaisesRegex(RuntimeError, "Nothing was changed"):
            self._cascade(None, connect_error=OSError("down"))
        self.assertTrue(QSchedulerInstance.objects.filter(pk=self.inst.pk).exists())
        result, _, _ = self._cascade(None, {"skip_unreachable": True}, connect_error=OSError("down"))
        self.assertEqual(result['skipped_heappe'], ["dev"])
        self.assertFalse(QSchedulerInstance.objects.filter(pk=self.inst.pk).exists())

    def test_cascade_failure_keeps_instance(self):
        from heappe_ui.models import QSchedulerInstance
        controller = self._heappe([self._cluster(5, "Sim")])
        controller.heappe_management_cluster_delete.side_effect = RuntimeError("cluster has jobs")
        with self.assertRaisesRegex(RuntimeError, "cluster has jobs"):
            self._cascade(controller)
        self.assertTrue(QSchedulerInstance.objects.filter(pk=self.inst.pk).exists())

    def test_cascade_api_needs_confirmation(self):
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="rec_admin2", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        with mock.patch.object(core, "start_operation") as start:
            response = self.client.post(f"/qscheduler/{self.inst.id}/cascade-delete/",
                                        data=json.dumps({"confirm_name": "wrong"}), content_type="application/json")
            self.assertEqual(response.status_code, 400)
            start.assert_not_called()

    # ---- restore ----

    def test_restore_options(self):
        from heappe_ui.view.qscheduler_recovery import parse_restore_options
        opts, errors = parse_restore_options({}, self.inst)
        self.assertEqual(errors, [])
        self.assertEqual((opts['name'], opts['port'], opts['source'], opts['ref'], opts['db_mode']),
                         ("qs-1", 4300, "git", "main", "new"))
        _, errors = parse_restore_options({"name": "qs-2", "db_mode": "reuse"}, self.inst)
        self.assertTrue(any("reused only" in e for e in errors))
        opts, errors = parse_restore_options({"machines": [
            {"name": "Sim", "backend": "test"}, {"name": "Q5", "backend": "iqm", "iqm_url": "https://iqm"},
            {"name": "Old", "mode": "skip"}]}, self.inst)
        self.assertTrue(any("Machine 'Q5'" in e and "token" in e for e in errors))
        self.assertEqual(sorted(opts['machines']), ["Q5", "Sim"])

    def _restore(self, opts, clusters, machines_in_db=None, cli=None):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_core import CommandResult
        from heappe_ui.view.qscheduler_recovery import parse_restore_options, restore_worker
        options, errors = parse_restore_options(opts, self.inst)
        self.assertEqual(errors, [])
        controller = self._heappe(clusters)
        docker = mock.Mock()
        docker.exists.return_value = False
        docker.networks_of.return_value = []
        target = _cli_target(mock.Mock())
        target.list_machines.return_value = [{"name": m, "backend": "test"} for m in machines_in_db or []]
        target.list_notifiers.return_value = []
        target.cli.return_value = CommandResult(0, "ok", "")
        if cli:
            target.cli.side_effect = cli
        result = {}
        with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)), \
             mock.patch.object(core, "presence", return_value=(core.MISSING, "gone")), \
             mock.patch.object(core, "heappe_identity", return_value=("6.6.0", "heappe-dev")), \
             mock.patch.object(core, "resolve_heappe_service_network", return_value=("dev_heappe", "dev_external")), \
             mock.patch.object(core, "restart_heappe"), mock.patch.object(core, "check_from_heappe"), \
             mock.patch.object(core, "find_heappe_api_container", return_value="dev_heappe"), \
             mock.patch.object(core, "update_cluster_notifications") as upd, \
             mock.patch.object(core, "repoint_file_transfer_methods") as ftm, \
             mock.patch("heappe_ui.view.qscheduler_recovery.DockerCli", return_value=docker), \
             mock.patch("heappe_ui.view.qscheduler_recovery.DockerTarget", return_value=target), \
             mock.patch("heappe_ui.view.qscheduler_recovery.deploy_service",
                        return_value={'database_url': "postgres://qscheduler:pw@qs-2-pgsql:5432/qscheduler",
                                      'version': "0.3.0"}) as deploy:
            try:
                restore_worker(self.log, result, self.inst.id, options)
            finally:
                self.calls = {'upd': upd, 'ftm': ftm, 'deploy': deploy, 'target': target, 'docker': docker}
        return result

    def test_restore_new_endpoint_reassigns_clusters_with_new_tokens(self):
        from heappe_ui.models import QSchedulerInstance, QSchedulerMachine
        self.inst.archived_at = datetime.now()
        self.inst.save()
        clusters = [self._cluster(5, "Sim"), self._cluster(6, "VLQ")]
        result = self._restore({"name": "qs-2", "port": "4400", "ref": "v0.3.0", "machines": [
            {"name": "Sim", "backend": "test"}, {"name": "VLQ", "backend": "test", "queue_size": "8"}]}, clusters)
        c = self.calls
        self.assertEqual(c['deploy'].call_args.args[1]['ref'], "v0.3.0")
        added = [x.args[0] for x in c['target'].cli.call_args_list]
        self.assertEqual([a[:3] for a in added if a[0] == "machine"], [["machine", "add", "Sim"], ["machine", "add", "VLQ"]])
        notifiers = {a[2]: a[a.index("--token") + 1] for a in added if a[:2] == ["notifier", "add"]}
        self.assertEqual(sorted(notifiers), ["heappe-dev.Sim", "heappe-dev.VLQ"])
        self.assertNotEqual(notifiers["heappe-dev.Sim"], notifiers["heappe-dev.VLQ"])
        c['target'].restart.assert_called_once()                              # one restart for all
        for call in c['upd'].call_args_list:
            self.assertEqual(call.kwargs['location'], ("qs-2", 4400))
            name, token = call.args[3]
            self.assertEqual(notifiers[name], token)                          # cluster gets the new token
        self.assertEqual(c['ftm'].call_count, 2)
        inst = QSchedulerInstance.objects.get(pk=self.inst.pk)
        self.assertEqual((inst.name, inst.service_host, inst.port, inst.ref, inst.is_archived), ("qs-2", "qs-2", 4400, "v0.3.0", False))
        self.assertEqual(QSchedulerMachine.objects.get(qscheduler=inst, name="VLQ").options["queue_size"], 8)
        self.assertEqual(len(result['updated_clusters']), 2)

    def test_restore_same_endpoint_and_reused_machines(self):
        clusters = [self._cluster(5, "Sim")]
        with mock.patch("heappe_ui.view.qscheduler_recovery._prepare_reused_database",
                        return_value=("postgres://qscheduler:pw@qs-1-pgsql:5432/qscheduler", "qs-1_db_net")):
            self._restore({"db_mode": "reuse", "machines": [{"name": "Sim", "mode": "skip"}]}, clusters,
                          machines_in_db=["Sim"])
        c = self.calls
        self.assertEqual(c['deploy'].call_args.args[1]['db_mode'], "existing")
        self.assertFalse(any(x.args[0][0] == "machine" for x in c['target'].cli.call_args_list))
        self.assertIsNone(c['upd'].call_args.kwargs['location'])            # same host and port
        c['ftm'].assert_not_called()

    def test_restore_without_machine_definition_changes_nothing(self):
        from heappe_ui.models import QSchedulerInstance
        with self.assertRaisesRegex(RuntimeError, "Define the backend of machine.*Sim"):
            self._restore({}, [self._cluster(5, "Sim")])
        self.calls['deploy'].assert_not_called()
        self.assertEqual(QSchedulerInstance.objects.get(pk=self.inst.pk).name, "qs-1")

    def test_restore_reports_failed_machine(self):
        from heappe_ui.view.qscheduler_core import CommandResult
        clusters = [self._cluster(5, "Sim"), self._cluster(6, "VLQ")]
        cli = lambda args, log, check=True, timeout=None: (CommandResult(1, "", "boom") if args[:3] == ["machine", "add", "VLQ"]
                                                           else CommandResult(0, "ok", ""))
        with self.assertRaisesRegex(RuntimeError, "running again, but"):
            self._restore({"machines": [{"name": "Sim", "backend": "test"}, {"name": "VLQ", "backend": "test"}]},
                          clusters, cli=cli)
        self.assertEqual([c.args[2]['name'] for c in self.calls['upd'].call_args_list], ["Sim"])   # VLQ not reassigned
        self.assertFalse(_qs_is_archived(self.inst.pk))                                           # restored anyway

    def test_reuse_old_database(self):
        from heappe_ui.view.qscheduler_recovery import reusable_database, _prepare_reused_database
        docker = mock.Mock()
        docker.exists.side_effect = lambda kind, name: name == "qs-1-pgsql"
        docker.json.return_value = [{}]
        docker.inspect.return_value = {"Config": {"Env": ["POSTGRES_PASSWORD=secret", "PATH=/bin"]}, "State": {"Running": False}}
        docker.run.return_value = mock.Mock(returncode=0)
        self.assertIn("qs-1-pgsql", reusable_database(docker, self.inst))
        url, net = _prepare_reused_database(docker, self.inst, self.log)
        self.assertEqual((url, net), ("postgres://qscheduler:secret@qs-1-pgsql:5432/qscheduler", "qs-1_db_net"))
        self.assertIn(["start", "qs-1-pgsql"], [c.args[0] for c in docker.run.call_args_list])
        # Only the volume is left: recreated with the stored password
        docker.reset_mock()
        docker.inspect.return_value = None
        docker.exists.side_effect = lambda kind, name: False
        self.inst.database_url = "postgres://qscheduler:stored@qs-1-pgsql:5432/qscheduler"
        self.assertIn("volume", reusable_database(docker, self.inst))
        url, _ = _prepare_reused_database(docker, self.inst, self.log)
        self.assertIn("stored", url)
        self.assertTrue(any("POSTGRES_PASSWORD=stored" in c.args[0] for c in docker.run.call_args_list))
        self.inst.kind = "ssh_host"
        self.assertIsNone(reusable_database(docker, self.inst))

    def test_page_shows_archived_and_recovery_actions(self):
        from datetime import datetime, timezone
        self.client.force_login(User.objects.create_user(username="rec_admin3", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        with mock.patch("heappe_ui.view.qscheduler_deploy.import_legacy_instances"):
            html = self.client.get("/qscheduler/").content.decode()
            self.assertIn('data-action="resolve"', html)          # hidden until the live check reports it missing
            self.assertNotIn("Delete with entities...", html)
            self.inst.archived_at = datetime.now(timezone.utc)
            self.inst.archived_reason = "Container removed outside HEAppE Management"
            self.inst.save()
            html = self.client.get("/qscheduler/").content.decode()
        self.assertIn("Archived ", html)
        self.assertIn("Container removed outside HEAppE Management", html)
        self.assertIn('data-action="restore"', html)
        self.assertIn("Delete with entities...", html)
        self.assertNotIn('data-action="assign"', html)


def _qs_is_archived(pk):
    from heappe_ui.models import QSchedulerInstance
    return QSchedulerInstance.objects.get(pk=pk).is_archived


class QSchedulerUnmanagedNotifierTests(TestCase):
    """Optional removal of a notifier no assignment manages (e.g. old one-notifier-per-HEAppE leftovers)."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)
        QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred,
                                            heappe_identifier="heappe-dev", notifications_enabled=True)

    def _run(self, name, clusters=None, connect_error=None, notifiers=("heappe-dev", "heappe-dev.Sim")):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_core import CommandResult
        from heappe_ui.view.qscheduler_deploy import remove_notifier_worker
        target = _cli_target(mock.Mock())
        target.list_notifiers.return_value = [{"name": n, "url": "http://h/cb"} for n in notifiers]
        target.cli.return_value = CommandResult(0, "ok", "")
        connect = mock.patch("heappe_ui.view.clusters.connect_heappe_management_api",
                             **({"side_effect": connect_error} if connect_error else {"return_value": (mock.Mock(), "sc", None)}))
        result = {}
        with connect, mock.patch.object(core, "target_for", return_value=target), \
             mock.patch.object(core, "qscheduler_clusters", return_value=clusters or []):
            remove_notifier_worker(lambda *_: None, result, self.inst.id, name)
        return target, result

    @staticmethod
    def _cluster(notifier):
        return {"id": 5, "name": "Sim", "custom_configuration": {"EnableCallback": "true", "QSchedulerNotifier": notifier}}

    def test_removes_unused_unmanaged_notifier_with_one_restart(self):
        target, result = self._run("heappe-dev", clusters=[self._cluster("heappe-dev.Sim")])
        self.assertEqual([c.args[0] for c in target.cli.call_args_list], [["notifier", "remove", "heappe-dev"]])
        target.restart.assert_called_once()
        self.assertEqual(result['notifier'], "heappe-dev")

    def test_refuses_managed_used_or_unverifiable(self):
        with self.assertRaisesRegex(RuntimeError, "belongs to a cluster"):
            self._run("heappe-dev.Sim")
        with self.assertRaisesRegex(RuntimeError, "still used by HEAppE cluster"):
            self._run("heappe-dev", clusters=[self._cluster("heappe-dev")])
        with self.assertRaisesRegex(RuntimeError, "Cannot check the clusters"):
            self._run("heappe-dev", connect_error=OSError("down"))
        with self.assertRaisesRegex(RuntimeError, "not registered"):
            self._run("other", notifiers=("heappe-dev.Sim",))

    def test_api_requires_acknowledgement(self):
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="nt_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        post = lambda data: self.client.post(f"/qscheduler/{self.inst.id}/notifier-remove/", data=json.dumps(data),
                                             content_type="application/json")
        with mock.patch.object(core, "start_operation", return_value=(True, "started")) as start:
            self.assertEqual(post({"name": "heappe-dev"}).status_code, 400)                          # not acknowledged
            self.assertEqual(post({"name": "heappe-dev.Sim", "acknowledged": True}).status_code, 400)  # managed
            self.assertEqual(post({"name": "a b", "acknowledged": True}).status_code, 400)
            start.assert_not_called()
            self.assertEqual(post({"name": "heappe-dev", "acknowledged": True}).status_code, 200)
            start.assert_called_once()


class QSchedulerClusterHealthTests(TestCase):
    """QScheduler panel of a cluster: attached instance, notifier checks, recreate notifier, recover machine."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)
        self.asg = QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred,
                                                       heappe_identifier="heappe-dev", notifications_enabled=True,
                                                       callback_url="http://h/cb")
        self.log = lambda *_: None

    @staticmethod
    def _cluster(machine="Sim", notifier="heappe-dev.Sim", token="********", callbacks="true", cid=5):
        cfg = {"QSchedulerHost": "qs-1", "QSchedulerPort": "4300", "EnableCallback": callbacks}
        if notifier:
            cfg["QSchedulerNotifier"] = notifier
        if token:
            cfg["QSchedulerNotifyToken"] = token
        return {"id": cid, "name": f"cl-{machine}", "scheduler_type": 32, "master_node_name": "qs-1", "port": 4300,
                "custom_configuration": cfg, "custom_configuration_vault_toggles": {"QSchedulerNotifyToken": True},
                "node_types": [{"id": 50 + cid, "name": machine, "queue": machine, "file_transfer_method_id": 9,
                                "cluster_node_type_aggregation": {"id": 7}, "number_of_nodes": 1, "cores_per_node": 1,
                                "max_walltime": 86400}]}

    def _target(self, notifiers=(("heappe-dev.Sim", "http://h/cb"),), machines=("Sim",)):
        from heappe_ui.view.qscheduler_core import CommandResult
        t = mock.Mock()
        t.list_notifiers.return_value = [{"name": n, "url": u} for n, u in notifiers]
        t.list_machines.return_value = None if machines is None else [{"name": m, "backend": "test"} for m in machines]
        t.cli.return_value = CommandResult(0, "ok", "")
        return _cli_target(t)

    def _status(self, cluster, target):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_cluster_health import cluster_status
        with mock.patch.object(core, "target_for", return_value=target):
            return cluster_status("dev", cluster)

    def test_status_ok(self):
        s = self._status(self._cluster(), self._target())
        self.assertEqual((s['instance']['name'], s['assigned'], s['machine']), ("qs-1", True, "Sim"))
        self.assertTrue(s['notifications']['ok'])
        self.assertEqual(s['notifications']['problems'], [])
        self.assertTrue(s['machine_status']['registered'])

    def test_status_reports_notifier_problems_and_missing_machine(self):
        s = self._status(self._cluster(notifier="heappe-dev", token=""),
                         self._target(notifiers=(("heappe-dev.Sim", "http://old/cb"),), machines=("Other",)))
        problems = " | ".join(s['notifications']['problems'])
        self.assertIn("expected 'heappe-dev.Sim'", problems)
        self.assertIn("no QSchedulerNotifyToken", problems)
        self.assertIn("http://old/cb", problems)
        self.assertFalse(s['notifications']['ok'])
        self.assertEqual(s['machine_status'], {'registered': False, 'machines': ["Other"]})
        s = self._status(self._cluster(), self._target(notifiers=()))
        self.assertIn("not registered in QScheduler", " ".join(s['notifications']['problems']))

    def test_status_notifications_off_and_unknown_instance(self):
        self.asg.notifications_enabled = False
        self.asg.save()
        s = self._status(self._cluster(), self._target())
        self.assertIn("notifications are off", s['notifications']['problems'][0])
        self.assertTrue(self._status(self._cluster(callbacks="false", notifier=None, token=""), self._target())['notifications']['ok'])
        other = dict(self._cluster(), master_node_name="elsewhere", custom_configuration={"QSchedulerPort": "4300"})
        self.assertIsNone(self._status(other, self._target())['instance'])
        self.asg.delete()
        self.assertFalse(self._status(self._cluster(), self._target())['assigned'])

    def _worker(self, fn, cluster, target, *args, clusters=None):
        from heappe_ui.view import qscheduler_core as core
        controller = mock.Mock()
        controller.heappe_management_cluster_get.return_value = cluster
        result = {}
        with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)), \
             mock.patch.object(core, "target_for", return_value=target), \
             mock.patch.object(core, "qscheduler_clusters", return_value=clusters if clusters is not None else [cluster]), \
             mock.patch.object(core, "update_cluster_notifications") as upd:
            fn(self.log, result, "dev", cluster['id'], *args)
        return controller, upd, result

    def test_recreate_notifier_new_token_and_old_removed(self):
        from heappe_ui.view.qscheduler_cluster_health import recreate_notifier_worker
        target = self._target(notifiers=(("heappe-dev.Old", "http://h/cb"), ("heappe-dev.Sim", "http://h/cb")))
        cluster = self._cluster(notifier="heappe-dev.Old")
        _, upd, result = self._worker(recreate_notifier_worker, cluster, target)
        cmds = [c.args[0] for c in target.cli.call_args_list]
        self.assertIn(["notifier", "remove", "heappe-dev.Old"], cmds)
        self.assertIn(["notifier", "remove", "heappe-dev.Sim"], cmds)      # recreated: cannot be updated in place
        added = [c for c in cmds if c[:2] == ["notifier", "add"]]
        self.assertEqual(added[0][2:5], ["heappe-dev.Sim", "--url", "http://h/cb"])
        target.restart.assert_called_once()
        name, token = upd.call_args.args[3]
        self.assertEqual((name, token), ("heappe-dev.Sim", added[0][-1]))
        self.assertEqual(result['removed'], ["heappe-dev.Old"])

    def test_recreate_keeps_notifier_used_by_another_cluster(self):
        from heappe_ui.view.qscheduler_cluster_health import recreate_notifier_worker
        target = self._target(notifiers=(("heappe-dev.Old", "http://h/cb"),))
        cluster = self._cluster(notifier="heappe-dev.Old")
        other = self._cluster(machine="Old", notifier="heappe-dev.Old", cid=6)
        self._worker(recreate_notifier_worker, cluster, target, clusters=[cluster, other])
        self.assertNotIn(["notifier", "remove", "heappe-dev.Old"], [c.args[0] for c in target.cli.call_args_list])

    def test_recreate_with_notifications_off_disables_callbacks(self):
        from heappe_ui.view.qscheduler_cluster_health import recreate_notifier_worker
        self.asg.notifications_enabled = False
        self.asg.save()
        target = self._target()
        _, upd, _ = self._worker(recreate_notifier_worker, self._cluster(), target)
        self.assertEqual([c.args[0] for c in target.cli.call_args_list], [["notifier", "remove", "heappe-dev.Sim"]])
        self.assertIsNone(upd.call_args.args[3])

    def test_recover_registers_new_machine(self):
        from heappe_ui.models import QSchedulerMachine
        from heappe_ui.view.qscheduler_cluster_health import recover_machine_worker, parse_recover_options
        opts, errors = parse_recover_options({"mode": "new", "backend": "test", "queue_size": "6"}, "Sim")
        self.assertEqual(errors, [])
        target = self._target(notifiers=(), machines=())
        controller, upd, result = self._worker(recover_machine_worker, self._cluster(), target, opts)
        cmds = [c.args[0] for c in target.cli.call_args_list]
        self.assertEqual(cmds[0][:3], ["machine", "add", "Sim"])
        self.assertEqual([c[:3] for c in cmds[1:]], [["notifier", "add", "heappe-dev.Sim"]])
        target.restart.assert_called_once()
        controller.heappe_management_cluster_node_type_put.assert_not_called()
        self.assertEqual(QSchedulerMachine.objects.get(qscheduler=self.inst, name="Sim").options["queue_size"], 6)
        self.assertEqual(upd.call_args.args[3][0], "heappe-dev.Sim")

    def test_recover_switches_to_existing_machine(self):
        from heappe_ui.view.qscheduler_cluster_health import recover_machine_worker, parse_recover_options
        opts, _ = parse_recover_options({"mode": "existing", "machine_name": "VLQ"}, "Sim")
        target = self._target(notifiers=(("heappe-dev.Sim", "http://h/cb"),), machines=("VLQ",))
        controller, upd, result = self._worker(recover_machine_worker, self._cluster(), target, opts)
        cmds = [c.args[0] for c in target.cli.call_args_list]
        self.assertFalse(any(c[0] == "machine" for c in cmds))
        self.assertIn(["notifier", "remove", "heappe-dev.Sim"], cmds)
        self.assertEqual([c[2] for c in cmds if c[:2] == ["notifier", "add"]], ["heappe-dev.VLQ"])
        body = controller.heappe_management_cluster_node_type_put.call_args.kwargs['body']
        self.assertEqual((body['Queue'], body['Name'], body['ClusterNodeTypeAggregationId']), ("VLQ", "VLQ", 7))
        self.assertEqual(upd.call_args.args[3][0], "heappe-dev.VLQ")
        self.assertEqual(result['machine'], "VLQ")

    def test_recover_refusals(self):
        from heappe_ui.view.qscheduler_cluster_health import recover_machine_worker, parse_recover_options
        opts, _ = parse_recover_options({"mode": "existing", "machine_name": "VLQ"}, "Sim")
        with self.assertRaisesRegex(RuntimeError, "already uses machine 'VLQ'"):
            self._worker(recover_machine_worker, self._cluster(), self._target(machines=("VLQ",)), opts,
                         clusters=[self._cluster(), self._cluster(machine="VLQ", cid=6)])
        with self.assertRaisesRegex(RuntimeError, "does not exist"):
            self._worker(recover_machine_worker, self._cluster(), self._target(machines=()), opts)
        new, _ = parse_recover_options({"mode": "new", "backend": "test"}, "Sim")
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self._worker(recover_machine_worker, self._cluster(), self._target(machines=("Sim",)), new)
        _, errors = parse_recover_options({"mode": "new", "backend": "iqm"}, "Sim")
        self.assertTrue(any("token" in e for e in errors))
        from datetime import datetime, timezone
        self.inst.archived_at = datetime.now(timezone.utc)
        self.inst.save()
        with self.assertRaisesRegex(RuntimeError, "archived"):
            self._worker(recover_machine_worker, self._cluster(), self._target(), new)

    def test_views(self):
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="ch_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session["middleware_deployed_version"] = "6.5.0"
        session.save()
        with mock.patch.object(core, "start_operation", return_value=(True, "started")) as start:
            r = self.client.post("/clusters/qscheduler/cluster/5/recreate-notifier/", data="{}", content_type="application/json")
            self.assertEqual(r.status_code, 400)                                   # HEAppE < 6.6.0
            session["middleware_deployed_version"] = "6.6.0"
            session.save()
            r = self.client.post("/clusters/qscheduler/cluster/5/recover-machine/", data=json.dumps({"mode": "existing"}),
                                 content_type="application/json")
            self.assertEqual(r.status_code, 400)                                   # no machine selected
            start.assert_not_called()
            r = self.client.post("/clusters/qscheduler/cluster/5/recreate-notifier/", data="{}", content_type="application/json")
            self.assertEqual(r.status_code, 200)
            r = self.client.post("/clusters/qscheduler/cluster/5/recover-machine/",
                                 data=json.dumps({"mode": "new", "backend": "test", "current_machine": "Sim"}),
                                 content_type="application/json")
            self.assertEqual(r.status_code, 200)
        controller = mock.Mock()
        controller.heappe_management_cluster_get.return_value = self._cluster()
        with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)), \
             mock.patch.object(core, "target_for", return_value=self._target()):
            d = self.client.get("/clusters/qscheduler/cluster/5/status/").json()
        self.assertEqual((d['status'], d['instance']['name'], d['notifications']['ok']), ("success", "qs-1", True))

    def test_cluster_detail_template_shows_panel_only_for_qscheduler_clusters(self):
        from django.template.loader import render_to_string
        ctx = {'active_tab': 'detail', 'proxy_connections': [], 'is_v6_4_0_plus': True, 'is_v6_5_0_plus': True,
               'custom_configuration_json': '{}', 'custom_configuration_vault_toggles_json': '{}',
               'custom_config_metadata_json': '[]', 'filetransfer_methods': []}
        html = render_to_string("cluster_detail.html", dict(ctx, cluster={'id': 5, 'name': 'cl', 'scheduler_type': 32}))
        self.assertIn('id="qs-cluster-status"', html)
        self.assertIn('id="qsRecoverModal"', html)
        html = render_to_string("cluster_detail.html", dict(ctx, cluster={'id': 5, 'name': 'cl', 'scheduler_type': 4}))
        self.assertNotIn('id="qs-cluster-status"', html)
        html = render_to_string("cluster_detail.html", dict(ctx, cluster={'scheduler_type': 32}))   # create form
        self.assertNotIn('id="qs-cluster-status"', html)


class QSchedulerClusterMoveTests(TestCase):
    """Move a cluster whose QScheduler is gone to another healthy instance (the cluster is kept)."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.old = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                     service_host="qs-1", port=4300)
        self.new = QSchedulerInstance.objects.create(name="qs-2", kind="managed", container_name="qs-2",
                                                     service_host="qs-2", port=4400)
        for inst in (self.old, self.new):
            QSchedulerAssignment.objects.create(qscheduler=inst, heappe_instance=self.cred, heappe_identifier="heappe-dev",
                                                notifications_enabled=True, callback_url="http://h/cb")
        self.log = lambda *_: None

    _cluster = staticmethod(QSchedulerClusterHealthTests._cluster)

    def _target(self, machines=("Sim",), health=200):
        from heappe_ui.view.qscheduler_core import CommandResult
        t = mock.Mock()
        t.health.return_value = health
        t.list_machines.return_value = [{"name": m, "backend": "test"} for m in machines]
        t.list_notifiers.return_value = []
        t.cli.return_value = CommandResult(0, "ok", "")
        return _cli_target(t)

    def _move(self, opts_data, target, on_new=(), old_target=None, cluster=None):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_cluster_health import move_cluster_worker, parse_move_options
        opts, errors = parse_move_options(dict({"qscheduler_id": str(self.new.id)}, **opts_data), "Sim")
        self.assertEqual(errors, [])
        cluster = cluster or self._cluster()
        controller = mock.Mock()
        controller.heappe_management_cluster_get.return_value = cluster
        targets = {"qs-2": target, "qs-1": old_target or mock.Mock(**{"list_notifiers.side_effect": RuntimeError("gone")})}
        clusters = lambda c, sc, inst: list(on_new) if inst.name == "qs-2" else [cluster]
        result = {}
        with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(controller, "sc", None)), \
             mock.patch.object(core, "target_for", side_effect=lambda inst: targets[inst.name]), \
             mock.patch.object(core, "qscheduler_clusters", side_effect=clusters), \
             mock.patch.object(core, "DockerCli"), \
             mock.patch.object(core, "update_cluster_notifications") as upd, \
             mock.patch.object(core, "repoint_file_transfer_methods") as ftm:
            move_cluster_worker(self.log, result, "dev", 5, opts)
        return controller, upd, ftm, result

    def test_status_offers_move_for_unreachable_or_unknown_instance(self):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_cluster_health import cluster_status
        broken = mock.Mock(**{"list_notifiers.side_effect": RuntimeError("SSH connection failed")})
        with mock.patch.object(core, "target_for", return_value=broken):
            s = cluster_status("dev", self._cluster())
        self.assertTrue(s['can_move'])
        self.assertEqual([c['name'] for c in s['move_candidates']], ["qs-2"])   # not the cluster's own instance
        other = dict(self._cluster(), master_node_name="gone-host", custom_configuration={"QSchedulerPort": "4300"})
        s = cluster_status("dev", other)
        self.assertTrue(s['can_move'])
        self.assertEqual(len(s['move_candidates']), 2)
        healthy = mock.Mock(**{"list_notifiers.return_value": [], "list_machines.return_value": []})
        with mock.patch.object(core, "target_for", return_value=healthy):
            self.assertFalse(cluster_status("dev", self._cluster())['can_move'])

    def test_move_with_new_machine_keeps_cluster(self):
        from heappe_ui.models import QSchedulerMachine
        target = self._target(machines=())
        controller, upd, ftm, result = self._move({"mode": "new", "backend": "test"}, target)
        cmds = [c.args[0] for c in target.cli.call_args_list]
        self.assertEqual([c[:3] for c in cmds], [["machine", "add", "Sim"], ["notifier", "add", "heappe-dev.Sim"]])
        target.restart.assert_called_once()
        controller.heappe_management_cluster_delete.assert_not_called()
        self.assertEqual(upd.call_args.kwargs['location'], ("qs-2", 4400))
        self.assertEqual(upd.call_args.args[3][0], "heappe-dev.Sim")
        self.assertEqual(ftm.call_args.args[3:5], ("qs-2", 4400))
        self.assertTrue(QSchedulerMachine.objects.filter(qscheduler=self.new, name="Sim").exists())
        self.assertEqual((result['qscheduler'], result['from']), ("qs-2", "qs-1"))

    def test_move_to_existing_machine_with_other_name(self):
        target = self._target(machines=("VLQ",))
        controller, upd, _, _ = self._move({"mode": "existing", "machine_name": "VLQ"}, target)
        self.assertFalse(any(c.args[0][0] == "machine" for c in target.cli.call_args_list))
        self.assertEqual(controller.heappe_management_cluster_node_type_put.call_args.kwargs['body']['Queue'], "VLQ")
        self.assertEqual(upd.call_args.args[3][0], "heappe-dev.VLQ")

    def test_move_removes_old_notifier_when_old_instance_reachable(self):
        old_target = _cli_target(mock.Mock())
        old_target.list_notifiers.return_value = [{"name": "heappe-dev.Sim", "url": "http://h/cb"}]
        target = self._target(machines=("Sim",))
        from heappe_ui.view import qscheduler_core as core
        # the old instance only sees other clusters: the moving one is excluded
        self._move({"mode": "existing", "machine_name": "Sim"}, target, old_target=old_target)
        self.assertIn(["notifier", "remove", "heappe-dev.Sim"], [c.args[0] for c in old_target.cli.call_args_list])

    def test_move_refusals(self):
        with self.assertRaisesRegex(RuntimeError, "already uses machine 'Sim'"):
            self._move({"mode": "existing", "machine_name": "Sim"}, self._target(), on_new=[self._cluster(cid=9)])
        with self.assertRaisesRegex(RuntimeError, "not healthy"):
            self._move({"mode": "new", "backend": "test"}, self._target(machines=(), health=None))
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            self._move({"mode": "new", "backend": "test"}, self._target(machines=("Sim",)))
        from heappe_ui.view.qscheduler_cluster_health import parse_move_options
        _, errors = parse_move_options({"mode": "new", "backend": "test"}, "Sim")
        self.assertTrue(any("Select the QScheduler" in e for e in errors))

    def test_move_api_requires_assigned_target(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="mv_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session["middleware_deployed_version"] = "6.6.0"
        session.save()
        lonely = QSchedulerInstance.objects.create(name="qs-3", kind="managed", container_name="qs-3", service_host="qs-3")
        with mock.patch.object(core, "start_operation", return_value=(True, "started")) as start:
            post = lambda qid: self.client.post("/clusters/qscheduler/cluster/5/move/", content_type="application/json",
                                                data=json.dumps({"qscheduler_id": qid, "mode": "new", "backend": "test",
                                                                 "current_machine": "Sim"}))
            self.assertEqual(post(lonely.id).status_code, 400)
            start.assert_not_called()
            self.assertEqual(post(self.new.id).status_code, 200)
            start.assert_called_once()


class QSchedulerImageBuildTests(TestCase):
    """Rebuild / clean rebuild (no cache) of the QScheduler image on deploy, update and restore."""

    def test_build_args_and_options(self):
        from heappe_ui.view.qscheduler_deploy import build_args, parse_deploy_options, parse_update_options
        self.assertEqual(build_args("qs:latest", "https://g/q.git", "main"), ["build", "-t", "qs:latest", "https://g/q.git#main"])
        self.assertEqual(build_args("qs:latest", "https://g/q.git", "main", True)[:3], ["build", "--no-cache", "--pull"])
        self.assertTrue(parse_deploy_options({"no_cache": True}, "x")[0]['no_cache'])
        self.assertFalse(parse_deploy_options({}, "x")[0]['no_cache'])
        self.assertTrue(parse_update_options({"no_cache": "on"})[0]['no_cache'])

    def test_clean_rebuild_builds_even_if_image_exists(self):
        from heappe_ui.view.qscheduler_deploy import _build_or_check_image
        docker = mock.Mock(where="")
        docker.exists.return_value = True
        _build_or_check_image(docker, "git", "https://g/q.git", "main", "qs:latest", False, lambda *_: None)
        docker.run.assert_not_called()                                   # existing image reused
        _build_or_check_image(docker, "git", "https://g/q.git", "main", "qs:latest", False, lambda *_: None, no_cache=True)
        self.assertEqual(docker.run.call_args.args[0][:3], ["build", "--no-cache", "--pull"])
        docker.reset_mock()
        _build_or_check_image(docker, "image", "", "", "qs:latest", False, lambda *_: None, no_cache=True)
        docker.run.assert_not_called()                                   # no build for an existing image source

    def test_update_passes_clean_rebuild(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_deploy as d
        inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1", service_host="qs-1")
        target = mock.Mock()
        target.docker.inspect.return_value = None                        # stop right after the build step would run
        with mock.patch.object(d.core, "target_for", return_value=target), \
             mock.patch.object(d, "_build_or_check_image") as build:
            with self.assertRaises(RuntimeError):
                d.update_worker(lambda *_: None, {}, inst.id, d.parse_update_options({"no_cache": True})[0], "u")
        build.assert_not_called()                                         # container missing: refused before building
        target.docker.inspect.return_value = {"Config": {}}
        with mock.patch.object(d.core, "target_for", return_value=target), \
             mock.patch.object(d, "_build_or_check_image", side_effect=RuntimeError("stop")) as build:
            with self.assertRaisesRegex(RuntimeError, "stop"):
                d.update_worker(lambda *_: None, {}, inst.id, d.parse_update_options({"no_cache": True})[0], "u")
        self.assertTrue(build.call_args.kwargs['no_cache'])


class QSchedulerNetworkSubnetTests(TestCase):
    """Internal database networks get a /27 from a dedicated pool (Docker's default pools can run out)."""

    def _docker(self, subnets, create_results):
        from heappe_ui.view.qscheduler_core import CommandResult
        docker = mock.Mock()
        docker.json.return_value = [{"IPAM": {"Config": [{"Subnet": s}]}} for s in subnets]
        results = iter(create_results)
        docker.run.side_effect = lambda args, *a, **k: (CommandResult(0, "id1 id2", "") if args[:2] == ["network", "ls"]
                                                        else next(results))
        return docker

    def test_picks_first_free_subnet_and_retries_on_overlap(self):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_core import CommandResult
        docker = self._docker(["172.17.0.0/16", "10.213.0.0/26"],
                              [CommandResult(1, "", "Pool overlaps with other one on this address space"), CommandResult(0, "ok", "")])
        subnet = core.create_internal_network(docker, "qs-1_db_net", {"qscheduler.instance": "qs-1"}, lambda *_: None)
        self.assertEqual(subnet, "10.213.0.72/29")                    # default /29: .0/26 used, .64 overlapped meanwhile
        create = [c.args[0] for c in docker.run.call_args_list if c.args[0][:2] == ["network", "create"]]
        self.assertEqual(create[0][create[0].index("--subnet") + 1], "10.213.0.64/29")
        self.assertIn("--internal", create[1])
        self.assertEqual(create[1][-1], "qs-1_db_net")

    def test_selected_network_size(self):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_core import CommandResult
        from heappe_ui.view.qscheduler_deploy import parse_deploy_options
        from heappe_ui.view.qscheduler_recovery import parse_restore_options
        from heappe_ui.models import QSchedulerInstance
        self.assertEqual(parse_deploy_options({}, "x")[0]['network_prefix'], 29)             # default /29
        self.assertEqual(parse_deploy_options({"network_prefix": "/29"}, "x")[0]['network_prefix'], 29)
        self.assertEqual(parse_deploy_options({"network_prefix": 24}, "x")[0]['network_prefix'], 24)
        for bad in ("23", "30", "big"):
            self.assertTrue(any("Network size" in e for e in parse_deploy_options({"network_prefix": bad}, "x")[1]), bad)
        with self.settings(QSCHEDULER_NETWORK_PREFIX=28):
            self.assertEqual(parse_deploy_options({}, "x")[0]['network_prefix'], 28)       # default from settings
        inst = QSchedulerInstance(name="qs-1", kind="managed", port=4300)
        self.assertEqual(parse_restore_options({"network_prefix": "26"}, inst)[0]['network_prefix'], 26)
        docker = self._docker(["10.213.0.0/29"], [CommandResult(0, "ok", "")])
        self.assertEqual(core.create_internal_network(docker, "n", {}, lambda *_: None, prefix=29), "10.213.0.8/29")
        docker = self._docker([], [CommandResult(0, "ok", "")])
        self.assertEqual(core.create_internal_network(docker, "n", {}, lambda *_: None, prefix=24), "10.213.0.0/24")

    def test_deploy_passes_network_size(self):
        from heappe_ui.view import qscheduler_deploy as d
        opts, _ = d.parse_deploy_options({"network_prefix": "28"}, "abcd1234")
        docker = mock.Mock(where="")
        with mock.patch.object(d, "_build_or_check_image"), \
             mock.patch("heappe_ui.view.qscheduler_network.existing_layout", return_value=None), \
                mock.patch("heappe_ui.view.qscheduler_network.create",
                           side_effect=lambda dk, n, sub, i, lg: __import__("heappe_ui.view.qscheduler_network", fromlist=["layout"]).layout(sub)), \
                mock.patch("heappe_ui.view.qscheduler_network.propose", return_value={'subnet': "10.213.8.0/27"}), \
                mock.patch.object(d.core, "create_internal_network", side_effect=RuntimeError("stop")) as create:
            with self.assertRaisesRegex(RuntimeError, "stop"):
                d.deploy_service(docker, opts, lambda *_: None)
        self.assertEqual((create.call_args.args[1], create.call_args.kwargs['prefix']), ("qscheduler-abcd1234_db_net", 28))

    def test_other_errors_and_configuration(self):
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view.qscheduler_core import CommandResult
        docker = self._docker([], [CommandResult(1, "", "permission denied")])
        with self.assertRaisesRegex(RuntimeError, "permission denied.*QSCHEDULER_NETWORK_POOL"):
            core.create_internal_network(docker, "n", {}, lambda *_: None)
        with self.settings(QSCHEDULER_NETWORK_POOL="192.168.250.0/26", QSCHEDULER_NETWORK_PREFIX=27):
            docker = self._docker(["192.168.250.0/27", "192.168.250.32/27"], [])
            with self.assertRaisesRegex(RuntimeError, "pool exhausted"):
                core.create_internal_network(docker, "n", {}, lambda *_: None)
        with self.settings(QSCHEDULER_NETWORK_POOL="10.0.0.0/28", QSCHEDULER_NETWORK_PREFIX=27):
            with self.assertRaisesRegex(RuntimeError, "does not fit"):
                core.network_pool()



class _ExtraHostsTestBase(TestCase):
    """Fixtures for the Extra Hosts tab: a temporary compose project 'inst' and request helpers."""

    BASE_COMPOSE = (
        "services:\n"
        "  heappe:\n"
        "    image: heappe\n"
        "    extra_hosts:\n"
        "      - \"host.docker.internal:host-gateway\"\n"
        "  datastagingapi:\n"
        "    image: ds\n"
    )

    def setUp(self):
        import tempfile
        from django.contrib.auth.models import User
        from heappe_ui.view import extra_hosts
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="eh_admin", password="pw")
        self.tmp = tempfile.mkdtemp()
        self.compose_dir = os.path.join(self.tmp, "inst", "heappe-core")
        os.makedirs(self.compose_dir)
        with open(os.path.join(self.compose_dir, "docker-compose.yml"), "w") as f:
            f.write(self.BASE_COMPOSE)
        self.override = os.path.join(self.compose_dir, "docker-compose.override.yml")
        for p in [mock.patch.object(extra_hosts, "DEPLOYMENT_BASE_PATH", self.tmp),
                  mock.patch.object(extra_hosts, "_compose_running_hosts", return_value=None)]:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _call(self, method="get", **data):
        import json
        from heappe_ui.view.extra_hosts import instance_extra_hosts_view
        req = getattr(self.factory, method)("/deploy/inst/extra-hosts/", data)
        req.user = self.user
        req.session = {}
        req._dont_enforce_csrf_checks = True
        resp = instance_extra_hosts_view(req, "inst")
        return resp.status_code, json.loads(resp.content)

    def _section(self, data, key):
        return next(s for s in data["sections"] if s["key"] == key)

    def _override(self):
        import yaml
        with open(self.override) as f:
            return yaml.safe_load(f)

    def _qscheduler(self, container_hosts, kind="managed", **kw):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        cred = InstanceCredentials.objects.create(instance_name="inst", heappe_host="h", heappe_login="u",
                                                  heappe_password="p", heappe_port="5000")
        inst = QSchedulerInstance.objects.create(name="qs-1", kind=kind, container_name="qs-1", service_host="qs-1", **kw)
        QSchedulerAssignment.objects.create(qscheduler=inst, heappe_instance=cred)
        docker = mock.Mock(where="")
        docker.inspect.return_value = {"HostConfig": {"ExtraHosts": container_hosts}}
        p = mock.patch("heappe_ui.view.qscheduler_core.target_for", return_value=mock.Mock(docker=docker))
        p.start()
        self.addCleanup(p.stop)
        return inst



class ExtraHostsViewTests(_ExtraHostsTestBase):
    """Extra hosts of the heappe / datastagingapi compose services."""

    def test_list_shows_both_services_with_default_read_only(self):
        code, data = self._call()
        self.assertEqual(code, 200)
        self.assertEqual([s["key"] for s in data["sections"]], ["compose:heappe", "compose:datastagingapi"])
        heappe = self._section(data, "compose:heappe")
        self.assertEqual(heappe["hosts"][0]["entry"], "host.docker.internal:host-gateway")
        self.assertFalse(heappe["hosts"][0]["editable"])
        self.assertEqual(self._section(data, "compose:datastagingapi")["hosts"], [])

    def _apply(self, target, hosts, returncode=0):
        import json
        result = mock.Mock(returncode=returncode, stderr="boom")
        with mock.patch("heappe_ui.view.deploy.execute_docker_compose", return_value=result) as m:
            code, data = self._call("post", target=target, action="apply",
                                    hosts=json.dumps([{"hostname": h, "ip": ip} for h, ip in hosts]))
        return code, data, m

    def test_apply_saves_list_per_service(self):
        code, _, m = self._apply("compose:heappe", [("login.cluster", "10.0.0.5"), ("", "")])   # empty row ignored
        self.assertEqual(code, 200)
        self.assertEqual(m.call_args[0][0][-3:], ["--no-deps", "--force-recreate", "heappe"])
        code, _, m = self._apply("compose:datastagingapi", [("ds.cluster", "10.0.0.9")])
        self.assertEqual(code, 200)
        self.assertEqual(m.call_args[0][0][-1], "datastagingapi")
        svcs = self._override()["services"]
        self.assertEqual(svcs["heappe"]["extra_hosts"], ["login.cluster:10.0.0.5"])
        self.assertEqual(svcs["datastagingapi"]["extra_hosts"], ["ds.cluster:10.0.0.9"])

        self._apply("compose:heappe", [("login2.cluster", "10.0.0.6")])                    # edit
        self.assertEqual(self._override()["services"]["heappe"]["extra_hosts"], ["login2.cluster:10.0.0.6"])
        self._apply("compose:heappe", [])                                                   # remove all
        self.assertNotIn("heappe", self._override()["services"])
        self._apply("compose:datastagingapi", [])
        self.assertFalse(os.path.exists(self.override))

        with open(os.path.join(self.compose_dir, "docker-compose.yml")) as f:
            self.assertEqual(f.read(), self.BASE_COMPOSE)

    def test_default_entry_is_protected(self):
        code, _, m = self._apply("compose:heappe", [("host.docker.internal", "1.2.3.4")])
        self.assertEqual(code, 403)
        m.assert_not_called()
        self.assertFalse(os.path.exists(self.override))
        self._apply("compose:heappe", [("a", "10.0.0.1")])
        code, data = self._call()
        self.assertEqual([h["entry"] for h in self._section(data, "compose:heappe")["hosts"]],
                         ["host.docker.internal:host-gateway", "a:10.0.0.1"])

    def test_validation_duplicates_and_unknown_target(self):
        self.assertEqual(self._apply("compose:heappe", [("bad host", "10.0.0.1")])[0], 400)
        self.assertEqual(self._apply("compose:heappe", [("ok", "999.1.1.1")])[0], 400)
        code, data, m = self._apply("compose:heappe", [("ok", "10.0.0.1"), ("OK", "10.0.0.2")])
        self.assertEqual(code, 409)
        self.assertIn("Row 2", data["message"])
        m.assert_not_called()
        self.assertEqual(self._apply("compose:mssql", [("a", "10.0.0.2")])[0], 404)
        self.assertEqual(self._call("post", target="compose:heappe", action="add")[0], 400)

    def test_apply_failure_keeps_saved_list(self):
        code, data, _ = self._apply("compose:heappe", [("a", "10.0.0.1")], returncode=1)
        self.assertEqual(code, 500)
        self.assertIn("saved but not applied", data["message"])
        self.assertEqual(self._override()["services"]["heappe"]["extra_hosts"], ["a:10.0.0.1"])

    def test_override_keeps_other_content(self):
        with open(self.override, "w") as f:
            f.write("services:\n  heappe:\n    environment:\n      FOO: bar\n")
        self._apply("compose:heappe", [("a.b", "::1")])
        heappe = self._override()["services"]["heappe"]
        self.assertEqual((heappe["environment"], heappe["extra_hosts"]), ({"FOO": "bar"}, ["a.b:::1"]))
        self._apply("compose:heappe", [])
        self.assertNotIn("extra_hosts", self._override()["services"]["heappe"])


class QSchedulerExtraHostsTests(_ExtraHostsTestBase):
    """Extra hosts of the QScheduler instances assigned to a HEAppE instance."""

    def test_qscheduler_section_lists_container_hosts(self):
        self._qscheduler(["host.docker.internal:host-gateway", "iqm.local:10.1.1.1"])
        code, data = self._call()
        qs = data["sections"][-1]
        self.assertEqual(qs["kind"], "qscheduler")
        self.assertEqual([(h["entry"], h["editable"]) for h in qs["hosts"]],
                         [("host.docker.internal:host-gateway", False), ("iqm.local:10.1.1.1", True)])
        self.assertFalse(qs["pending_apply"])

    def test_qscheduler_apply_stores_list_and_starts_operation(self):
        import json
        inst = self._qscheduler(["host.docker.internal:host-gateway", "iqm.local:10.1.1.1"])
        hosts = json.dumps([{"hostname": "iqm.local", "ip": "10.1.1.1"}, {"hostname": "a.b", "ip": "10.0.0.1"}])
        with mock.patch("heappe_ui.view.qscheduler_core.start_operation", return_value=(True, "ok")) as m:
            code, data = self._call("post", target=f"qscheduler:{inst.pk}", action="apply", hosts=hosts)
        self.assertEqual((code, data["status"]), (200, "started"))
        self.assertEqual(m.call_args[0][2], inst.pk)
        inst.refresh_from_db()
        self.assertEqual(inst.extra_hosts, ["iqm.local:10.1.1.1", "a.b:10.0.0.1"])
        bad = json.dumps([{"hostname": "host.docker.internal", "ip": "1.1.1.1"}])
        with mock.patch("heappe_ui.view.qscheduler_core.start_operation") as m:
            code, _ = self._call("post", target=f"qscheduler:{inst.pk}", action="apply", hosts=bad)
        self.assertEqual(code, 403)
        m.assert_not_called()

    def test_qscheduler_busy_operation_reports_saved(self):
        import json
        inst = self._qscheduler([])
        with mock.patch("heappe_ui.view.qscheduler_core.start_operation", return_value=(False, "Another operation")):
            code, data = self._call("post", target=f"qscheduler:{inst.pk}", action="apply",
                                    hosts=json.dumps([{"hostname": "a", "ip": "10.0.0.1"}]))
        self.assertEqual(code, 409)
        self.assertIn("saved but not applied", data["message"])

    def test_qscheduler_of_other_instance_or_ssh_container_not_listed(self):
        from heappe_ui.models import QSchedulerInstance
        QSchedulerInstance.objects.create(name="qs-other", kind="managed", container_name="qs-other", service_host="x")
        self._qscheduler([], kind="ssh_container")
        code, data = self._call()
        self.assertEqual([s["kind"] for s in data["sections"]], ["compose", "compose"])

    def test_qscheduler_container_extra_hosts(self):
        from heappe_ui.view.extra_hosts import qscheduler_container_extra_hosts
        self.assertIsNone(qscheduler_container_extra_hosts(["a:1.1.1.1"], None))
        self.assertEqual(qscheduler_container_extra_hosts(["host.docker.internal:host-gateway", "a:1.1.1.1"],
                                                          ["b:2.2.2.2", "host.docker.internal:9.9.9.9"]),
                         ["host.docker.internal:host-gateway", "b:2.2.2.2"])

    def test_recreate_args_extra_hosts(self):
        from heappe_ui.view import qscheduler_deploy as q
        info = {"Id": "abc", "Name": "/qs-1", "Config": {"Image": "qs", "Cmd": ["serve", "--port", "4300"]},
                "HostConfig": {"ExtraHosts": ["kept:1.1.1.1"]}, "NetworkSettings": {"Networks": {}}}
        args, _, _ = q.recreate_args_from_inspect(info, "qs")
        self.assertIn("kept:1.1.1.1", args)                     # update keeps the container's extra hosts
        args, _, _ = q.recreate_args_from_inspect(info, "qs", extra_hosts=["new:2.2.2.2"])
        self.assertNotIn("kept:1.1.1.1", args)
        self.assertEqual(args[args.index("--add-host") + 1], "new:2.2.2.2")

    def test_extra_hosts_worker_recreates_with_same_image(self):
        from heappe_ui.view import qscheduler_deploy as q
        inst = self._qscheduler([])
        inst.extra_hosts = ["a.b:10.0.0.1"]
        inst.save()
        docker = mock.Mock(where="")
        docker.inspect.return_value = {"Id": "abc", "Name": "/qs-1",
                                       "Config": {"Image": "qs:v1", "Cmd": ["serve", "--port", "4300"]},
                                       "HostConfig": {"ExtraHosts": ["host.docker.internal:host-gateway"]},
                                       "NetworkSettings": {"Networks": {}}}
        target = mock.Mock(docker=docker)
        result = {}
        with mock.patch("heappe_ui.view.qscheduler_core.target_for", return_value=target):
            q.extra_hosts_worker(lambda *_: None, result, inst.pk, "u1")
        self.assertEqual(result["extra_hosts"], ["host.docker.internal:host-gateway", "a.b:10.0.0.1"])
        create = next(c.args[0] for c in docker.run.call_args_list if c.args[0][0] == "create")
        self.assertIn("a.b:10.0.0.1", create)
        self.assertIn("host.docker.internal:host-gateway", create)
        self.assertIn("qs:v1", create)
        target.wait_healthy.assert_called_once()


class QSchedulerAdminApiTests(TestCase):
    """QScheduler >= 0.2.1: machines and notifiers only over the admin API (no restart, no CLI); CLI for older."""

    def _target(self, version="qscheduler v0.2.1", responses=None):
        from heappe_ui.view.qscheduler_core import QsTarget, CommandResult

        class Fake(QsTarget):
            def __init__(self):
                self.port, self.requests, self.cli_calls, self.restarted = 4300, [], [], 0

            def version(self):
                return version

            def admin_request(self, method, path, body=None, timeout=60):
                self.requests.append((method, path, body))
                res = (responses or {}).get((method, path), (200, "[]"))
                if isinstance(res, Exception):
                    raise res
                return res

            def cli(self, args, log, check=True, timeout=0):
                self.cli_calls.append(list(args))
                return CommandResult(0, "ok", "")

            def restart(self, log):
                self.restarted += 1
        return Fake()

    def _opts(self, **kw):
        return dict({"machine_name": "Sim", "backend": "test", "queue_size": 4, "limit_check_interval": "2s",
                     "max_session_time": "2h", "default_task_time_limit": "1h", "max_clock_skew": "4s",
                     "iqm_url": "", "iqm_token": "", "iqm_device": "", "iqm_poll_interval": "500ms"}, **kw)

    def test_version_gate(self):
        from heappe_ui.view.qscheduler_core import supports_admin_api, parse_version
        self.assertEqual(parse_version("qscheduler v0.2.1"), (0, 2, 1))
        self.assertTrue(supports_admin_api("qscheduler v0.2.1"))
        self.assertTrue(supports_admin_api("qscheduler v0.10.0"))
        self.assertTrue(supports_admin_api("qscheduler v1.0.0"))
        self.assertFalse(supports_admin_api("qscheduler v0.2.0"))
        self.assertFalse(supports_admin_api(None))
        self.assertFalse(supports_admin_api("qscheduler"))

    def test_machine_request_body(self):
        from heappe_ui.view.qscheduler_core import machine_request, duration_ms
        self.assertEqual(machine_request(self._opts()), {
            "name": "Sim", "queue_size": 4, "limit_check_interval_ms": 2000, "max_session_time_ms": 7200000,
            "default_task_time_limit_ms": 3600000, "max_clock_skew_ms": 4000, "backend": {"type": "test"}})
        iqm = machine_request(self._opts(backend="iqm", iqm_url="https://iqm", iqm_token="t", iqm_device="garnet"))
        self.assertEqual(iqm["backend"], {"type": "iqm", "url": "https://iqm", "token": "t", "machine_name": "garnet",
                                          "poll_interval_ms": 500})
        self.assertEqual(duration_ms("1d"), 86400000)
        self.assertEqual(duration_ms("5m"), 300000)
        with self.assertRaises(ValueError):
            duration_ms("5 minutes")

    def test_admin_api_writes_need_no_restart(self):
        from heappe_ui.view import qscheduler_core as core
        t = self._target(responses={("POST", "/machines"): (201, "{}"), ("POST", "/notifiers"): (201, "{}")})
        logs = []
        self.assertTrue(t.uses_admin_api(logs.append))
        self.assertEqual(t.add_machine(self._opts(), logs.append).returncode, 0)
        self.assertTrue(core.replace_notifiers(t, {"heappe-dev.Sim": ("http://h/cb", "tok")}, (), {}, logs.append))
        self.assertTrue(core.apply_changes(mock.Mock(restart_pending=False), t, logs.append))
        self.assertEqual(t.restarted, 0)
        self.assertEqual(t.cli_calls, [])
        self.assertEqual([r[:2] for r in t.requests], [("POST", "/machines"), ("POST", "/notifiers")])
        self.assertEqual(t.requests[0][2]["name"], "Sim")
        self.assertEqual(t.requests[1][2], {"name": "heappe-dev.Sim", "url": "http://h/cb", "token": "tok"})
        self.assertTrue(any("admin API" in l for l in logs))

    def test_admin_api_errors_match_cli_wording(self):
        t = self._target(responses={("POST", "/machines"): (409, '{"error": "exists"}'),
                                    ("DELETE", "/machine/Sim"): (404, ""),
                                    ("DELETE", "/machine/VLQ"): (409, "busy"),
                                    ("DELETE", "/machine/X?force=true"): (200, '{"tasks": 3, "sessions": 1}'),
                                    ("DELETE", "/notifiers/a.b"): (404, "")})
        log = lambda *_: None
        res = t.add_machine(self._opts(), log)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("already exists", res.output)
        self.assertIn("not found", t.remove_machine("Sim", False, log).output)
        self.assertIn("has tasks or sessions", t.remove_machine("VLQ", False, log).output)
        ok = t.remove_machine("X", True, log)
        self.assertEqual(ok.returncode, 0)
        self.assertIn("3 task(s), 1 session(s)", ok.stdout)
        self.assertFalse(t.remove_notifier("a.b", log, check=False))
        with self.assertRaises(RuntimeError):
            t.remove_notifier("a.b", log)
        self.assertFalse(t.reload_needed)

    def test_lists_over_admin_api(self):
        t = self._target(responses={
            ("GET", "/machines"): (200, '[{"name": "Sim", "backend": {"type": "test"}}, '
                                        '{"name": "G", "backend": {"type": "iqm", "url": "u"}}]'),
            ("GET", "/notifiers"): (200, '[{"name": "n", "url": "http://h/cb", "has_token": true}]')})
        self.assertEqual(t.list_machines(), [{"name": "Sim", "backend": "test"}, {"name": "G", "backend": "iqm"}])
        self.assertEqual(t.list_notifiers(), [{"name": "n", "has_token": True, "url": "http://h/cb"}])

    def test_old_version_uses_cli_and_restarts(self):
        from heappe_ui.view import qscheduler_core as core
        t = self._target(version="qscheduler v0.2.0")
        logs = []
        self.assertEqual(t.add_machine(self._opts(), logs.append).returncode, 0)
        t.add_notifier("n", "http://h/cb", "tok", logs.append)
        self.assertEqual([c[:2] for c in t.cli_calls], [["machine", "add"], ["notifier", "add"]])
        self.assertEqual(t.requests, [])
        self.assertTrue(t.reload_needed)
        self.assertTrue(core.apply_changes(mock.Mock(restart_pending=False), t, logs.append))
        self.assertEqual(t.restarted, 1)
        self.assertTrue(any("CLI" in l for l in logs))

    def test_admin_token_problem_stops_without_cli(self):
        from heappe_ui.view.qscheduler_admin import AdminTokenError
        inst = mock.Mock(pk=7, kind="managed")
        inst.name = "qs-1"
        t = self._target(responses={("DELETE", "/machine/Sim"): AdminTokenError(inst, "rejected"),
                                    ("GET", "/machines"): AdminTokenError(inst, "missing")})
        with self.assertRaises(AdminTokenError) as ctx:
            t.remove_machine("Sim", False, lambda *_: None)
        self.assertEqual(ctx.exception.info()["reason"], "rejected")
        self.assertTrue(ctx.exception.can_regenerate)
        with self.assertRaises(AdminTokenError):
            t.list_machines()                     # no fallback to the database either
        self.assertEqual(t.cli_calls, [])

    def test_admin_request_needs_admin_client_and_hides_details(self):
        from heappe_ui.view.qscheduler_core import QsTarget
        from heappe_ui.view.qscheduler_admin import AdminApiUnavailable
        with self.assertRaises(AdminApiUnavailable):
            QsTarget().admin_request("GET", "/machines")
        t = QsTarget()
        t.admin_client = mock.Mock()
        t.admin_client.request.side_effect = ValueError("token secret in here")
        with self.assertRaises(RuntimeError) as ctx:
            t.admin_request("GET", "/machines")
        self.assertNotIn("secret", str(ctx.exception))
        t.admin_client.request.side_effect = None
        t.admin_client.request.return_value = (200, "[]")
        self.assertEqual(t.admin_request("GET", "/machines"), (200, "[]"))

    def test_admin_token_redacted_and_added_on_update(self):
        from heappe_ui.view.qscheduler_core import redact_args
        from heappe_ui.view.qscheduler_deploy import admin_token_env, recreate_args_from_inspect
        self.assertEqual(redact_args(["-e", "ADMIN_TOKEN=abc"]), ["-e", "ADMIN_TOKEN=********"])
        info = {"Name": "/qs", "Config": {"Env": ["DATABASE_URL=postgres://x", "ADMIN_TOKEN="], "Cmd": ["serve"]}}
        env = admin_token_env(info, lambda *_: None)
        self.assertTrue(env["ADMIN_TOKEN"])
        args, _, _ = recreate_args_from_inspect(info, "qs:new", extra_env=env)
        envs = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
        self.assertEqual(envs, ["DATABASE_URL=postgres://x", f"ADMIN_TOKEN={env['ADMIN_TOKEN']}"])
        info["Config"]["Env"] = ["ADMIN_TOKEN=keep"]
        self.assertIsNone(admin_token_env(info, lambda *_: None))



class QSchedulerAdminProxyTests(TestCase):
    """Admin proxy container, admin client over HTTP, encrypted admin token and the admin token API."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerInstance, QSchedulerAssignment
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_login="u",
                                                       heappe_password="p", heappe_port="5000")
        self.asg = QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred,
                                                       network="dev_external_network")

    def _docker(self, proxy=None, container_env=None):
        """Fake docker CLI: inspect of the proxy / service container, records run() calls."""
        docker = mock.Mock(where="")
        state = {"proxy": proxy}

        def inspect(name):
            if name.endswith("-admin-proxy"):
                return state["proxy"]
            return {"Config": {"Env": container_env or []}}

        def run(args, log=None, check=True, **kw):
            if args[0] == "run":
                labels = dict(a.split("=", 1) for i, a in enumerate(args) if i and args[i - 1] == "--label")
                state["proxy"] = {"Config": {"Labels": labels, "Image": args[args.index("sh") - 1]},
                                  "State": {"Status": "running"},
                                  "NetworkSettings": {"Networks": {args[args.index("--network") + 1]: {}},
                                                      "Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49001"}]}}}
            return mock.Mock(returncode=0)
        docker.inspect.side_effect = inspect
        docker.run.side_effect = run
        docker.exists.side_effect = lambda kind, name: state["proxy"] is not None
        return docker, state

    def test_proxy_config_forwards_only_admin_endpoints(self):
        from heappe_ui.view.qscheduler_admin import proxy_config, proxy_run_args
        conf = proxy_config("qs-1", 4300)
        self.assertIn("set $qscheduler http://qs-1:4300;", conf)
        self.assertIn("location ~ ^/(machines|notifiers)$", conf)
        self.assertIn("location ~ ^/(machine|notifiers)/[^/]+$", conf)
        self.assertIn("location / { return 404; }", conf)
        args = proxy_run_args(self.inst)
        self.assertIn("127.0.0.1::8080", args)                 # published on localhost only
        self.assertEqual(args[args.index("--network") + 1], "bridge")    # internal networks cannot publish
        self.assertIn("qscheduler.admin-upstream=qs-1:4300", args)

    def test_ensure_proxy_creates_repairs_and_follows_networks(self):
        from heappe_ui.view import qscheduler_admin as qa
        docker, state = self._docker()
        self.assertEqual(qa.ensure_proxy(self.inst, docker=docker, extra_networks=["other_net"]), 49001)
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertEqual(cmds[0][0], "run")
        self.assertIn(["network", "connect", "other_net", "qs-1-admin-proxy"], cmds)
        # upstream changed (restore under a new name): recreated
        docker.run.reset_mock()
        self.inst.service_host = "qs-2"
        qa.ensure_proxy(self.inst, docker=docker)
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertEqual(cmds[0], ["rm", "-f", "qs-1-admin-proxy"])
        self.assertEqual(cmds[1][0], "run")
        # a network that is no longer used is disconnected
        state["proxy"]["NetworkSettings"]["Networks"]["gone_net"] = {}
        docker.run.reset_mock()
        qa.ensure_proxy(self.inst, docker=docker)
        self.assertIn(["network", "disconnect", "gone_net", "qs-1-admin-proxy"], [c.args[0] for c in docker.run.call_args_list])

    def test_proxy_needs_an_assignment_and_is_removed_with_the_last(self):
        from heappe_ui.view import qscheduler_admin as qa
        self.asg.delete()
        with self.assertRaises(qa.AdminApiUnavailable):
            qa.ensure_proxy(self.inst, docker=self._docker()[0])
        # with a QScheduler network the proxy joins it, no assignment needed
        self.inst.qs_network = "qs-1_qs_net"
        docker, _ = self._docker()
        qa.ensure_proxy(self.inst, docker=docker)
        self.assertIn(["network", "connect", "qs-1_qs_net", "qs-1-admin-proxy"], [c.args[0] for c in docker.run.call_args_list])
        self.inst.qs_network = ""
        docker, _ = self._docker(proxy={"Config": {}})
        with mock.patch.object(qa, "DockerCli", return_value=docker):
            qa.sync_proxy(self.inst)
        self.assertIn(["rm", "-f", "qs-1-admin-proxy"], [c.args[0] for c in docker.run.call_args_list])

    def test_admin_token_encrypted_and_adopted_from_container(self):
        from heappe_ui.view import qscheduler_admin as qa
        self.assertEqual(self.inst.admin_token, "")
        docker, _ = self._docker(container_env=["DATABASE_URL=x", "ADMIN_TOKEN=from-env-123"])
        self.assertEqual(qa.admin_token(self.inst, docker), "from-env-123")
        self.inst.refresh_from_db()
        self.assertNotIn("from-env-123", self.inst.admin_token_encrypted)
        self.assertEqual(self.inst.admin_token, "from-env-123")
        self.inst.admin_token = ""
        self.inst.kind = "ssh_container"
        with self.assertRaises(qa.AdminTokenError) as ctx:
            qa.admin_token(self.inst, docker)
        self.assertFalse(ctx.exception.can_regenerate)

    def test_client_talks_http_with_bearer_token(self):
        """Real HTTP against a local server standing in for the proxy: method, path, token, body; 401/403."""
        import http.server
        import threading
        from heappe_ui.view import qscheduler_admin as qa
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def _reply(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                seen.append((self.command, self.path, self.headers.get("Authorization"), body))
                code = {"/notifiers/denied": 401, "/notifiers/off": 403}.get(self.path, 201)
                out = b'{"ok": true}'
                self.send_response(code)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            do_POST = do_DELETE = do_GET = _reply

            def log_message(self, *a):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.inst.admin_token = "adm1n-token"
        self.inst.save()
        try:
            with mock.patch.object(qa, "ensure_proxy", return_value=server.server_port):
                client = qa.AdminClient(self.inst)
                body = {"name": "heappe-dev.Sim", "url": "http://h/cb?a=1", "token": "it's \"quoted\""}
                self.assertEqual(client.request("POST", "/notifiers", body), (201, '{"ok": true}'))
                with self.assertRaises(qa.AdminTokenError) as ctx:
                    client.request("DELETE", "/notifiers/denied")
                self.assertEqual(ctx.exception.reason, "rejected")
                self.assertNotIn("adm1n-token", str(ctx.exception))
                with self.assertRaises(qa.AdminTokenError) as ctx:
                    client.request("DELETE", "/notifiers/off")
                self.assertEqual(ctx.exception.reason, "not_set")
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(seen[0][:3], ("POST", "/notifiers", "Bearer adm1n-token"))
        self.assertEqual(json.loads(seen[0][3]), body)

    def test_token_error_found_through_wrapping_and_reported_by_operation(self):
        from heappe_ui.view import qscheduler_admin as qa
        from heappe_ui.view import qscheduler_core as core
        err = qa.AdminTokenError(self.inst, "missing")
        try:
            try:
                raise err
            except RuntimeError as e:
                raise RuntimeError(f"Update failed and was rolled back: {e}")
        except RuntimeError as wrapped:
            self.assertIs(qa.find_admin_token_error(wrapped), err)

        def worker(log, result):
            raise RuntimeError("wrapped") from err
        with mock.patch("threading.Thread") as th:
            core.start_operation("x", worker)
            th.call_args.kwargs["target"]()
        status = core.operation_status()
        self.assertFalse(status["success"])
        self.assertEqual(status["result"]["admin_token_error"]["reason"], "missing")
        self.assertEqual(status["result"]["admin_token_error"]["instance_id"], self.inst.pk)

    def _api(self, data):
        from django.contrib.auth.models import User
        if not getattr(self, "_logged", False):
            self.client.force_login(User.objects.create_user(username="tok_admin", password="p"))
            session = self.client.session
            session["chosen_instance"] = "dev"
            session.save()
            self._logged = True
        resp = self.client.post(f"/qscheduler/{self.inst.pk}/admin-token/", data=json.dumps(data),
                                content_type="application/json")
        return resp.status_code, resp.json()

    def test_admin_token_api_show_set_regenerate(self):
        from heappe_ui.view import qscheduler_admin as qa
        from heappe_ui.view import qscheduler_core as core
        self.inst.admin_token = "stored-token-1"
        self.inst.save()
        code, data = self._api({"action": "show"})
        self.assertEqual((code, data["token"]), (200, "stored-token-1"))

        self.assertEqual(self._api({"action": "set", "token": "short"})[0], 400)
        with mock.patch.object(qa.AdminClient, "request", side_effect=qa.AdminTokenError(self.inst, "rejected")):
            code, data = self._api({"action": "set", "token": "wrong-token-123"})
        self.assertEqual(code, 400)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.admin_token, "stored-token-1")         # not stored
        with mock.patch.object(qa.AdminClient, "request", return_value=(200, "[]")):
            code, data = self._api({"action": "set", "token": "other-panel-token"})
        self.assertEqual(code, 200)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.admin_token, "other-panel-token")

        with mock.patch.object(core, "start_operation", return_value=(True, "started")) as m:
            self.assertEqual(self._api({"action": "regenerate"})[0], 200)
        self.assertEqual(m.call_args.args[2], self.inst.pk)

    def test_regenerate_worker_recreates_with_new_token(self):
        from heappe_ui.view import qscheduler_deploy as d
        docker = mock.Mock(where="")
        docker.inspect.return_value = {"Id": "abc", "Name": "/qs-1",
                                       "Config": {"Image": "qs:v1", "Cmd": ["serve", "--port", "4300"],
                                                  "Env": ["DATABASE_URL=x", "ADMIN_TOKEN=old"]},
                                       "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
        target = mock.Mock(docker=docker)
        target.uses_admin_api.return_value = True
        target.admin_request.return_value = (200, "[]")
        with mock.patch("heappe_ui.view.qscheduler_core.target_for", return_value=target), \
                mock.patch("heappe_ui.view.qscheduler_core.new_admin_token", return_value="brand-new-token"):
            d.regenerate_admin_token_worker(lambda *_: None, {}, self.inst.pk, "u1")
        create = next(c.args[0] for c in docker.run.call_args_list if c.args[0][0] == "create")
        self.assertIn("ADMIN_TOKEN=brand-new-token", create)
        self.assertNotIn("ADMIN_TOKEN=old", create)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.admin_token, "brand-new-token")
        target.admin_request.assert_called_once_with("GET", "/notifiers")

    def test_register_stores_entered_token(self):
        from heappe_ui.view.qscheduler_deploy import parse_register_options
        opts, errors = parse_register_options({"kind": "local", "container_name": "qs-ext", "admin_token": "bad token"})
        self.assertTrue(any("Admin token" in e for e in errors))
        opts, errors = parse_register_options({"kind": "local", "container_name": "qs-ext", "admin_token": "tok-12345"})
        self.assertEqual((errors, opts["admin_token"]), ([], "tok-12345"))


@unittest.skipUnless(os.environ.get("QS_DOCKER_TESTS"), "real Docker test: set QS_DOCKER_TESTS=1 (and QS_TEST_IMAGE)")
class QSchedulerSharedDbDockerTests(TestCase):
    """End to end against Docker: shared database, instance schema, backup/restore, undeploy, removal."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        self.image = os.environ.get("QS_TEST_IMAGE", "qscheduler:v0.2.1-tag")
        self.backups = tempfile.mkdtemp(prefix="qs-e2e-backups-")
        self.settings_override = override_settings(QSCHEDULER_BACKUP_DIR=self.backups)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.logs = []
        self.log = lambda m: self.logs.append(m)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil
        import subprocess
        from heappe_ui.view import qscheduler_shared_db as sdb
        for c in subprocess.run(["docker", "ps", "-aq", "--filter", "name=qse2e-"], capture_output=True, text=True).stdout.split():
            subprocess.run(["docker", "rm", "-f", c], capture_output=True)
        subprocess.run(["docker", "rm", "-f", sdb.SHARED_NAME], capture_output=True)
        for n in subprocess.run(["docker", "network", "ls", "-q", "--filter", "name=qse2e-"], capture_output=True, text=True).stdout.split():
            subprocess.run(["docker", "network", "rm", n], capture_output=True)
        subprocess.run(["docker", "network", "rm", sdb.SHARED_NETWORK], capture_output=True)
        subprocess.run(["docker", "volume", "rm", sdb.SHARED_VOLUME], capture_output=True)
        shutil.rmtree(self.backups, ignore_errors=True)

    def test_shared_database_lifecycle(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_shared_db as sdb
        docker = core.DockerCli()

        # 1. shared database
        result = {}
        sdb.deploy_shared_worker(self.log, result, {'image': "postgres:16"})
        status = sdb.shared_status()
        self.assertTrue(status['running'], status)
        self.assertTrue(status['version'].startswith("16"))

        # 2. instance in a schema
        opts, errors = d.parse_deploy_options({"name": "qse2e", "source": "image", "image": self.image,
                                               "db_mode": "shared"}, "e2e00001")
        self.assertEqual(errors, [])
        result = {}
        d.deploy_worker(self.log, result, opts)
        inst = QSchedulerInstance.objects.get(pk=result['id'])
        self.assertEqual((inst.db_kind, inst.db_schema), ("shared", "qs_qse2e_e2e00001"))
        self.assertIn("@qscheduler-shared-pgsql:5432/qscheduler", inst.database_url)
        tables = sdb.psql(docker, "SELECT count(*) FROM pg_tables WHERE schemaname = 'qs_qse2e_e2e00001';").strip()
        self.assertGreaterEqual(int(tables), 7)
        self.assertEqual(sdb.psql(docker, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';").strip(), "0")
        self.assertIn("qse2e-e2e00001_db_net", docker.networks_of(sdb.SHARED_NAME))
        self.assertEqual([s['instance'] for s in sdb.shared_status()['schemas']], [inst.name])

        # machine through the service's own CLI (writes into the role's schema)
        target = core.target_for(inst)
        target.cli(core.machine_args({"action": "add", "machine_name": "Sim", "backend": "test", "queue_size": 4,
                                      "limit_check_interval": "2s", "max_session_time": "2h",
                                      "default_task_time_limit": "1h", "max_clock_skew": "4s"}), self.log)
        count = lambda: sdb.psql(docker, "SELECT count(*) FROM qs_qse2e_e2e00001.machines;").strip()
        self.assertEqual(count(), "1")

        # 3. backup, change, restore
        result = {}
        sdb.backup_worker(self.log, result, inst.id)
        backups = sdb.list_backups(inst)
        self.assertEqual([b['file'] for b in backups], [result['file']])
        self.assertRegex(result['file'], r"_v0\.2\.1\.dump$")
        sdb.psql(docker, "DELETE FROM qs_qse2e_e2e00001.machines;")
        self.assertEqual(count(), "0")
        docker.run(["stop", inst.container_name], self.log)
        sdb.restore_instance(inst, result['file'], self.log)
        docker.run(["start", inst.container_name], self.log)
        target.wait_healthy(self.log)
        self.assertEqual(count(), "1")
        target.close()

        # 4. undeploy drops schema and role, removes the network
        result = {}
        d.undeploy_worker(self.log, result, inst.id, True)
        self.assertFalse(sdb.schema_exists(docker, "qs_qse2e_e2e00001"))
        self.assertFalse(sdb.role_exists(docker, "qs_qse2e_e2e00001"))
        self.assertNotIn("qse2e-e2e00001_db_net", docker.networks_of(sdb.SHARED_NAME))
        self.assertIsNone(docker.json(["network", "inspect", "qse2e-e2e00001_db_net"]))

        # 5. remove the shared database
        sdb.remove_shared_worker(self.log, {}, True)
        self.assertFalse(docker.exists("container", sdb.SHARED_NAME))
        self.assertIsNone(sdb.shared_database())

    def test_dedicated_database_backup_and_restore(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_shared_db as sdb
        docker = core.DockerCli()
        opts, errors = d.parse_deploy_options({"name": "qse2e", "source": "image", "image": self.image,
                                               "db_mode": "new"}, "e2e00002")
        self.assertEqual(errors, [])
        result = {}
        d.deploy_worker(self.log, result, opts)
        inst = QSchedulerInstance.objects.get(pk=result['id'])
        self.assertEqual(inst.db_kind, "dedicated")
        pg = f"{inst.container_name}-pgsql"
        sql = lambda q: sdb.psql(docker, q, container=pg, user="qscheduler").strip()
        target = core.target_for(inst)
        target.cli(core.machine_args({"action": "add", "machine_name": "Sim", "backend": "test", "queue_size": 4,
                                      "limit_check_interval": "2s", "max_session_time": "2h",
                                      "default_task_time_limit": "1h", "max_clock_skew": "4s"}), self.log)
        result = {}
        sdb.backup_worker(self.log, result, inst.id)
        self.assertTrue(os.path.isfile(os.path.join(sdb.backup_dir_of(inst), result['file'])))
        sql("DELETE FROM machines;")
        docker.run(["stop", inst.container_name], self.log)
        sdb.restore_instance(inst, result['file'], self.log)
        docker.run(["start", inst.container_name], self.log)
        target.wait_healthy(self.log)
        target.close()
        self.assertEqual(sql("SELECT count(*) FROM machines;"), "1")
        sdb.delete_backup(inst, result['file'])
        self.assertEqual(sdb.list_backups(inst), [])
        d.undeploy_worker(self.log, {}, inst.id, True)
        self.assertFalse(docker.exists("container", pg))


class QSchedulerSharedDbTests(TestCase):
    """Shared database: naming, SQL, deploy/undeploy integration, backups, API guards (Docker mocked)."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        from heappe_ui.models import QSchedulerDatabase
        self.backups = tempfile.mkdtemp(prefix="qs-unit-backups-")
        o = override_settings(QSCHEDULER_BACKUP_DIR=self.backups)
        o.enable()
        self.addCleanup(o.disable)
        self.QSchedulerDatabase = QSchedulerDatabase

    def tearDown(self):
        import shutil
        shutil.rmtree(self.backups, ignore_errors=True)

    def _db(self):
        db = self.QSchedulerDatabase(name="qscheduler-shared-pgsql", image="postgres:16", volume="v", database="qscheduler",
                                     home_network="qscheduler-shared-db_net", backup_dir=self.backups)
        db.admin_password = "adminpw"
        db.save()
        return db

    def _inst(self, **kw):
        from heappe_ui.models import QSchedulerInstance
        args = dict(name="qs-1", kind="managed", container_name="qs-1", service_host="qs-1", port=4300)
        args.update(kw)
        return QSchedulerInstance.objects.create(**args)

    def test_names_and_sql(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        self.assertEqual(sdb.schema_name_for("My-QS.dev-5190156f"), "qs_my_qs_dev_5190156f")
        self.assertEqual(len(sdb.schema_name_for("a" * 80)), 63)
        with self.assertRaises(ValueError):
            sdb.ident('qs_x"; DROP TABLE x; --')
        sql = sdb.create_schema_sql("qs_a", "abcdef0123456789")
        self.assertIn('CREATE ROLE "qs_a" LOGIN PASSWORD \'abcdef0123456789\';', sql)
        self.assertIn('CREATE SCHEMA "qs_a" AUTHORIZATION "qs_a";', sql)
        self.assertIn('ALTER ROLE "qs_a" SET search_path = "qs_a";', sql)
        self.assertIn('GRANT CONNECT ON DATABASE "qscheduler" TO "qs_a";', sql)
        with self.assertRaises(ValueError):
            sdb.create_schema_sql("qs_a", "bad'password-0000")
        drop = sdb.drop_schema_sql("qs_a")
        self.assertIn('DROP SCHEMA IF EXISTS "qs_a" CASCADE;', drop)
        self.assertIn("DROP ROLE", drop)

    def test_psql_sends_sql_on_stdin_quietly(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        from heappe_ui.view.qscheduler_core import CommandResult
        docker = mock.Mock()
        docker.run.return_value = CommandResult(0, "1\n", "")
        sdb.psql(docker, "CREATE ROLE x PASSWORD 'secret';", lambda *_: None)
        args, kwargs = docker.run.call_args
        self.assertNotIn("secret", " ".join(args[0]))
        self.assertEqual(kwargs["input"], "CREATE ROLE x PASSWORD 'secret';")
        self.assertTrue(kwargs["quiet"])
        docker.run.return_value = CommandResult(1, "", "ERROR: boom")
        with self.assertRaises(RuntimeError):
            sdb.psql(docker, "SELECT 1")

    def test_deploy_service_shared_branch(self):
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_shared_db as sdb
        db = self._db()
        opts, errors = d.parse_deploy_options({"name": "qs", "source": "image", "image": "qs:v1", "db_mode": "shared"}, "u1")
        self.assertEqual(errors, [])
        docker = mock.Mock()
        target = mock.Mock()
        target.version.return_value = "qscheduler v0.2.1"
        with mock.patch.object(d, "_build_or_check_image"), \
                mock.patch.object(sdb, "require_running", return_value=db), \
                mock.patch.object(sdb, "create_instance_schema", return_value=("qs_qs_u1", "pw" * 10)) as create, \
                mock.patch.object(sdb, "connect_network") as connect, \
                mock.patch("heappe_ui.view.qscheduler_core.create_internal_network"), \
                mock.patch("heappe_ui.view.qscheduler_network.existing_layout", return_value=None), \
                mock.patch("heappe_ui.view.qscheduler_network.create",
                           side_effect=lambda dk, n, sub, i, lg: __import__("heappe_ui.view.qscheduler_network", fromlist=["layout"]).layout(sub)), \
                mock.patch("heappe_ui.view.qscheduler_network.propose", return_value={'subnet': "10.213.8.0/27"}), \
                mock.patch.object(d, "DockerTarget", return_value=target):
            info = d.deploy_service(docker, opts, lambda *_: None)
        create.assert_called_once()
        connect.assert_called_once_with(docker, db, "qs-u1_db_net", mock.ANY)
        self.assertEqual((info['db_kind'], info['db_schema'], info['shared_database']), ("shared", "qs_qs_u1", db))
        self.assertEqual(info['database_url'], f"postgres://qs_qs_u1:{'pw' * 10}@qscheduler-shared-pgsql:5432/qscheduler")
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertIn(["network", "connect", "--alias", "qs-u1", "qs-u1_db_net", "qs-u1"], cmds)

    def test_deploy_service_shared_failure_lists_cleanup(self):
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_shared_db as sdb
        db = self._db()
        opts, _ = d.parse_deploy_options({"name": "qs", "source": "image", "image": "qs:v1", "db_mode": "shared"}, "u1")
        docker = mock.Mock()
        docker.run.side_effect = RuntimeError("create failed")
        logs = []
        with mock.patch.object(d, "_build_or_check_image"), \
                mock.patch.object(sdb, "require_running", return_value=db), \
                mock.patch.object(sdb, "create_instance_schema", return_value=("qs_qs_u1", "pw" * 10)), \
                mock.patch.object(sdb, "connect_network"), \
                mock.patch("heappe_ui.view.qscheduler_network.existing_layout", return_value=None), \
                mock.patch("heappe_ui.view.qscheduler_network.create",
                           side_effect=lambda dk, n, sub, i, lg: __import__("heappe_ui.view.qscheduler_network", fromlist=["layout"]).layout(sub)), \
                mock.patch("heappe_ui.view.qscheduler_network.propose", return_value={'subnet': "10.213.8.0/27"}), \
                mock.patch("heappe_ui.view.qscheduler_core.create_internal_network"):
            with self.assertRaises(RuntimeError):
                d.deploy_service(docker, opts, logs.append)
        text = "\n".join(logs)
        self.assertIn("docker network disconnect qs-u1_db_net qscheduler-shared-pgsql", text)
        self.assertIn("DROP SCHEMA qs_qs_u1 CASCADE", text)
        self.assertLess(text.index("network disconnect"), text.index("docker network rm qs-u1_db_net"))

    def test_undeploy_shared_drops_or_keeps_schema(self):
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_shared_db as sdb
        db = self._db()
        for remove_data in (True, False):
            inst = self._inst(db_kind="shared", db_schema="qs_qs_1", shared_database=db)
            docker = mock.Mock()
            docker.inspect.return_value = None
            docker.exists.return_value = False
            docker.json.return_value = None
            with mock.patch.object(d, "DockerCli", return_value=docker), \
                    mock.patch.object(sdb, "disconnect_network") as disc, \
                    mock.patch.object(sdb, "drop_instance_schema") as drop, \
                    mock.patch.object(d.qadmin, "remove_proxy"):
                d.undeploy_worker(lambda *_: None, {}, inst.id, remove_data)
            disc.assert_called_once_with(docker, db, "qs-1_db_net", mock.ANY)
            self.assertEqual(drop.called, remove_data)

    def test_backup_files_listing_and_delete(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        from datetime import datetime, timezone
        inst = self._inst(db_kind="dedicated")
        self.assertTrue(sdb.can_backup(inst))
        self.assertFalse(sdb.can_backup(self._inst(name="ext", container_name="ext", kind="local")))
        name = sdb.backup_file_name("qscheduler v0.2.1", datetime(2026, 10, 27, 20, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(name, "20261027T200501Z_v0.2.1.dump")
        self.assertEqual(sdb.backup_file_name(None, datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)), "20260102T030405Z.dump")
        d = sdb.backup_dir_of(inst)
        os.makedirs(d)
        for f in (name, "notes.txt", "20260102T030405Z.dump"):
            open(os.path.join(d, f), "w").write("x")
        self.assertEqual([b['file'] for b in sdb.list_backups(inst)], [name, "20260102T030405Z.dump"])
        for bad in ("../x.dump", "/etc/passwd", "notes.txt"):
            with self.assertRaises(ValueError):
                sdb.delete_backup(inst, bad)
        sdb.delete_backup(inst, name)
        self.assertEqual(len(sdb.list_backups(inst)), 1)
        with self.assertRaises(RuntimeError):
            sdb.backup_instance(self._inst(name="ext2", container_name="ext2", kind="local"), lambda *_: None)

    def test_update_refuses_major_version_change(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        self._db()
        docker = mock.Mock()
        docker.inspect.return_value = {"NetworkSettings": {"Networks": {}}}
        with mock.patch.object(sdb, "DockerCli", return_value=docker), \
                mock.patch.object(sdb, "server_major", return_value=16), \
                mock.patch.object(sdb, "image_major", return_value=17):
            with self.assertRaises(RuntimeError) as ctx:
                sdb.update_shared_worker(lambda *_: None, {}, {'image': "postgres:17"}, "u1")
        self.assertIn("major", str(ctx.exception))
        self.assertNotIn(["stop", "qscheduler-shared-pgsql"], [c.args[0] for c in docker.run.call_args_list])

    def test_shared_db_api_guards(self):
        from django.contrib.auth.models import User
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view import qscheduler_shared_db as sdb
        self.client.force_login(User.objects.create_user(username="sdb_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        post = lambda data: self.client.post("/qscheduler/shared-database/", data=json.dumps(data), content_type="application/json")
        with mock.patch.object(sdb, "shared_status", return_value={'deployed': False, 'image': "postgres:16"}):
            self.assertFalse(self.client.get("/qscheduler/shared-database/").json()['deployed'])
        with mock.patch.object(core, "start_operation", return_value=(True, "ok")) as op:
            self.assertEqual(post({"action": "deploy"}).status_code, 200)
            self.assertEqual(op.call_args.args[2], {'image': "postgres:16"})
        db = self._db()
        self.assertEqual(post({"action": "deploy"}).status_code, 400)                 # already deployed
        self._inst(db_kind="shared", db_schema="qs_qs_1", shared_database=db)
        self.assertIn("still use", post({"action": "remove"}).json()['message'])
        self.assertEqual(post({"action": "drop_schema", "schema": "qs_qs_1"}).status_code, 400)   # used
        self.assertEqual(post({"action": "drop_schema", "schema": "public"}).status_code, 400)
        with mock.patch.object(core, "start_operation", return_value=(True, "ok")):
            self.assertEqual(post({"action": "drop_schema", "schema": "qs_orphan"}).status_code, 200)

    def test_deploy_api_requires_shared_database(self):
        from django.contrib.auth.models import User
        self.client.force_login(User.objects.create_user(username="sdb_admin2", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        with mock.patch("heappe_ui.view.qscheduler_deploy.DockerCli") as dc:
            dc.return_value.exists.return_value = False
            resp = self.client.post("/qscheduler/deploy/", data=json.dumps({"db_mode": "shared", "source": "image",
                                                                             "image": "qs:v1"}),
                                    content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("No shared database", resp.json()['message'])

    def test_restore_reuses_shared_schema(self):
        from heappe_ui.view import qscheduler_recovery as rec
        from heappe_ui.view import qscheduler_shared_db as sdb
        db = self._db()
        inst = self._inst(db_kind="shared", db_schema="qs_qs_1", shared_database=db,
                          database_url="postgres://qs_qs_1:pw@qscheduler-shared-pgsql:5432/qscheduler")
        docker = mock.Mock()
        docker.exists.return_value = False
        docker.json.return_value = None
        with mock.patch.object(sdb, "schema_exists", return_value=True):
            self.assertIn("schema 'qs_qs_1'", rec.reusable_database(docker, inst))
            with mock.patch.object(sdb, "require_running", return_value=db), \
                    mock.patch.object(sdb, "connect_network") as connect, \
                    mock.patch("heappe_ui.view.qscheduler_core.create_internal_network") as net:
                url, network = rec._prepare_reused_database(docker, inst, lambda *_: None)
        self.assertEqual((url, network), (inst.database_url, "qs-1_db_net"))
        net.assert_called_once()
        connect.assert_called_once_with(docker, db, "qs-1_db_net", mock.ANY)

    def test_workers_with_mocked_docker(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        from heappe_ui.view.qscheduler_core import CommandResult

        class FakeDocker:
            def __init__(self, outputs=None):
                self.calls, self.outputs = [], outputs or {}

            def run(self, args, log=None, check=True, timeout=0, quiet=False, input=None):
                self.calls.append((list(args), input))
                for key, out in self.outputs.items():
                    if key in " ".join(args) or (input and key in input):
                        return CommandResult(0, out, "")
                return CommandResult(0, "", "")

            def exists(self, kind, name):
                return False

            def json(self, args):
                return None

            def inspect(self, name):
                return {"State": {"Status": "running"}, "NetworkSettings": {"Networks": {}}}

        # deploy: network, volume, run with backup mount, hardening SQL; record saved with encrypted password
        docker = FakeDocker()
        with mock.patch.object(sdb, "DockerCli", return_value=docker), \
                mock.patch("heappe_ui.view.qscheduler_core.create_internal_network") as net:
            sdb.deploy_shared_worker(lambda *_: None, {}, {'image': "postgres:16"})
        net.assert_called_once()
        run = next(a for a, _ in docker.calls if a[0] == "run")
        self.assertIn(f"{self.backups}:/backups", run)
        self.assertIn("--network", run)
        self.assertNotIn("-p", run)
        self.assertTrue(any(i and "REVOKE ALL ON SCHEMA public" in i for _, i in docker.calls))
        db = sdb.shared_database()
        self.assertTrue(db.admin_password)
        self.assertNotIn(db.admin_password, db.admin_password_encrypted)

        # status parses schemas and maps instances
        inst = self._inst(db_kind="shared", db_schema="qs_qs_1", shared_database=db)
        docker = FakeDocker({"SHOW server_version": "16.4\n", "pg_namespace n": "qs_old|8192|0\nqs_qs_1|65536|2\n"})
        with mock.patch.object(sdb, "DockerCli", return_value=docker):
            st = sdb.shared_status()
        self.assertEqual(st['version'], "16.4")
        self.assertEqual([(s['schema'], s['instance'], s['connections']) for s in st['schemas']],
                         [("qs_old", None, 0), ("qs_qs_1", "qs-1", 2)])

        # shared backup: pg_dump -n into the mount, checked with pg_restore --list
        listing = "; Archive\n215; 1259 16390 TABLE qs_qs_1 machines qs_qs_1\n3401; 0 16390 TABLE DATA qs_qs_1 machines\n"

        class DumpDocker(FakeDocker):
            def run(self, args, log=None, check=True, timeout=0, quiet=False, input=None):
                if "pg_dump" in args:
                    path = args[args.index("-f") + 1].replace("/backups", self_backups, 1)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    open(path, "w").write("dump")
                return super().run(args, log, check, timeout, quiet, input)
        self_backups = self.backups
        docker = DumpDocker({"pg_restore --list": listing})
        with mock.patch.object(sdb, "DockerCli", return_value=docker):
            path = sdb.backup_instance(inst, lambda *_: None, "qscheduler v0.2.1")
        dump = next(a for a, _ in docker.calls if "pg_dump" in a)
        self.assertEqual(dump[dump.index("-n") + 1], "qs_qs_1")
        self.assertTrue(path.endswith("_v0.2.1.dump") and os.path.isfile(path))

        # a dump without tables is refused and removed
        docker = DumpDocker({"pg_restore --list": "; empty\n"})
        with mock.patch.object(sdb, "DockerCli", return_value=docker):
            with self.assertRaises(RuntimeError):
                sdb.backup_instance(inst, lambda *_: None)
        self.assertEqual(len(sdb.list_backups(inst)), 1)

        # dedicated backup: pg_dump in <name>-pgsql, docker cp out, temp file removed
        ded = self._inst(name="qs-2", container_name="qs-2", db_kind="dedicated")

        class CpDocker(FakeDocker):
            def run(self, args, log=None, check=True, timeout=0, quiet=False, input=None):
                if args[0] == "cp":
                    open(args[2], "w").write("dump")
                return super().run(args, log, check, timeout, quiet, input)
        docker = CpDocker({"pg_restore --list": listing})
        with mock.patch.object(sdb, "DockerCli", return_value=docker):
            sdb.backup_instance(ded, lambda *_: None)
        names = [a[:3] for a, _ in docker.calls]
        self.assertIn(["exec", "qs-2-pgsql", "pg_dump"], names)
        self.assertEqual([a[0] for a, _ in docker.calls].count("cp"), 1)
        self.assertEqual(docker.calls[-1][0][:4], ["exec", "qs-2-pgsql", "rm", "-f"])

        # remove: refused while used, then removes container, network, volume
        with self.assertRaises(RuntimeError):
            sdb.remove_shared_worker(lambda *_: None, {}, True)
        inst.delete()
        ded.delete()
        docker = FakeDocker()
        docker.json = lambda args: {"x": 1}
        with mock.patch.object(sdb, "DockerCli", return_value=docker):
            sdb.remove_shared_worker(lambda *_: None, {}, True)
        cmds = [a for a, _ in docker.calls]
        self.assertIn(["volume", "rm", "qscheduler-shared-pgdata"], cmds)
        self.assertIsNone(sdb.shared_database())


@unittest.skipUnless(os.environ.get("QS_DOCKER_TESTS"), "real Docker test: set QS_DOCKER_TESTS=1 (and QS_TEST_IMAGE)")
class QSchedulerMigrateToSharedDockerTests(QSchedulerSharedDbDockerTests):
    """End to end: dedicated PostgreSQL -> schema in the shared database."""

    def test_shared_database_lifecycle(self):        # covered by the parent class
        pass

    def test_dedicated_database_backup_and_restore(self):
        pass

    def test_migrate_dedicated_to_shared(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_shared_db as sdb
        docker = core.DockerCli()
        sdb.deploy_shared_worker(self.log, {}, {'image': "postgres:16"})
        opts, _ = d.parse_deploy_options({"name": "qse2e", "source": "image", "image": self.image, "db_mode": "new"},
                                         "e2e00003")
        result = {}
        d.deploy_worker(self.log, result, opts)
        inst = QSchedulerInstance.objects.get(pk=result['id'])
        pg = f"{inst.container_name}-pgsql"
        machine = lambda n: core.machine_args({"action": "add", "machine_name": n, "backend": "test", "queue_size": 4,
                                               "limit_check_interval": "2s", "max_session_time": "2h",
                                               "default_task_time_limit": "1h", "max_clock_skew": "4s"})
        target = core.target_for(inst)
        target.cli(machine("Sim"), self.log)
        target.cli(["project", "add", "p1", "--limit", "1h"], self.log, check=False)
        target.close()
        before = sdb.table_counts(docker, pg, "qscheduler", "qscheduler", "public")

        result = {}
        sdb.migrate_to_shared_worker(self.log, result, inst.id, {'remove_old': False}, "mig00001")
        inst.refresh_from_db()
        role = "qs_qse2e_e2e00003"
        self.assertEqual((inst.db_kind, inst.db_schema, result['schema']), ("shared", role, role))
        self.assertIn(f"postgres://{role}:", inst.database_url)
        self.assertEqual(sdb.table_counts(docker, sdb.SHARED_NAME, "postgres", "qscheduler", role), before)
        self.assertEqual(sdb.psql(docker, f"SELECT tableowner FROM pg_tables WHERE schemaname = '{role}' GROUP BY 1;").strip(), role)
        self.assertEqual(sdb.psql(docker, "SELECT count(*) FROM pg_database WHERE datname LIKE 'qsmig_%';").strip(), "0")
        self.assertEqual((docker.inspect(pg) or {}).get("State", {}).get("Status"), "exited")      # kept, stopped
        env = dict(e.split("=", 1) for e in docker.inspect(inst.container_name)["Config"]["Env"] if "=" in e)
        self.assertIn("@qscheduler-shared-pgsql:5432/qscheduler", env["DATABASE_URL"])
        self.assertTrue(env.get("ADMIN_TOKEN"))                                                     # kept

        # the service works on the new schema: data visible, sequences continue, new rows land there
        target = core.target_for(inst)
        self.assertEqual(target.health(), 200)
        target.cli(machine("Sim2"), self.log)
        target.close()
        self.assertEqual(sdb.psql(docker, f"SELECT count(*) FROM {role}.machines;").strip(), "2")
        self.assertEqual(sdb.psql(docker, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';").strip(), "0")

        # the backup of the old database stays
        self.assertEqual([b['file'] for b in sdb.list_backups(inst)], [result['backup']])
        d.undeploy_worker(self.log, {}, inst.id, True)
        self.assertFalse(docker.exists("container", pg))


class QSchedulerMigrateToSharedTests(TestCase):
    """Migration dedicated -> shared database: SQL, guards, cleanup on failure (Docker mocked)."""

    def setUp(self):
        import tempfile
        from django.test import override_settings
        from heappe_ui.models import QSchedulerDatabase, QSchedulerInstance
        self.backups = tempfile.mkdtemp(prefix="qs-mig-")
        o = override_settings(QSCHEDULER_BACKUP_DIR=self.backups)
        o.enable()
        self.addCleanup(o.disable)
        self.db = QSchedulerDatabase.objects.create(name="qscheduler-shared-pgsql", image="postgres:16", volume="v",
                                                    database="qscheduler", home_network="n", backup_dir=self.backups)
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300, db_kind="dedicated",
                                                      database_url="postgres://qscheduler:pw@qs-1-pgsql:5432/qscheduler")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.backups, ignore_errors=True)

    def test_sql_steps(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        steps = sdb.migrate_sql_steps("qs_qs_1", "a" * 48, "qsmig_u1")
        self.assertIn("CREATE ROLE \"qs_qs_1\" LOGIN PASSWORD", steps['role'][1])
        self.assertIn('CREATE DATABASE "qsmig_u1" OWNER "qs_qs_1";', steps['tmp_db'][1])
        self.assertEqual(steps['rename'][0], "qsmig_u1")
        self.assertIn('ALTER SCHEMA public RENAME TO "qs_qs_1";', steps['rename'][1])
        self.assertIn('ALTER ROLE "qs_qs_1" SET search_path = "qs_qs_1";', steps['grants'][1])
        self.assertIn('DROP DATABASE IF EXISTS "qsmig_u1";', steps['drop_tmp'][1])

    def test_failure_cleans_up_and_restarts_on_old_database(self):
        from heappe_ui.view import qscheduler_shared_db as sdb
        docker = mock.Mock()
        docker.inspect.return_value = {"Config": {"Image": "qs:v1"}}
        docker.exists.return_value = True
        docker.run.return_value = mock.Mock(returncode=0)
        sql = []
        counts = iter([{"machines": 2}, {"machines": 1}])           # copy lost a row
        with mock.patch.object(sdb, "DockerCli", return_value=docker), \
                mock.patch.object(sdb, "require_running", return_value=self.db), \
                mock.patch.object(sdb, "role_exists", return_value=False), \
                mock.patch.object(sdb, "schema_exists", return_value=False), \
                mock.patch.object(sdb, "table_counts", side_effect=lambda *a: next(counts)), \
                mock.patch.object(sdb, "backup_instance", return_value=os.path.join(self.backups, "qs-1", "x.dump")), \
                mock.patch.object(sdb, "psql", side_effect=lambda d, q, *a, **k: sql.append(q) or ""), \
                mock.patch.object(sdb, "disconnect_network") as disc, \
                mock.patch("heappe_ui.view.qscheduler_core.target_for"), \
                mock.patch("heappe_ui.view.qscheduler_deploy.recreate_container") as recreate:
            with self.assertRaises(RuntimeError) as ctx:
                sdb.migrate_to_shared_worker(lambda *_: None, {}, self.inst.id, {}, "u1")
        self.assertIn("differs", str(ctx.exception))
        recreate.assert_not_called()                                 # never switched
        self.assertTrue(any('DROP SCHEMA IF EXISTS "qs_qs_1"' in q for q in sql))
        self.assertTrue(any('DROP DATABASE IF EXISTS "qsmig_u1"' in q for q in sql))
        disc.assert_called_once()
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertEqual(cmds[-1], ["start", "qs-1"])
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.db_kind, "dedicated")

    def test_api_guards(self):
        from django.contrib.auth.models import User
        from heappe_ui.view import qscheduler_core as core
        self.client.force_login(User.objects.create_user(username="mig_admin", password="p"))
        session = self.client.session
        session["chosen_instance"] = "dev"
        session.save()
        url = f"/qscheduler/{self.inst.id}/migrate-to-shared/"
        with mock.patch.object(core, "start_operation", return_value=(True, "ok")) as op:
            self.assertEqual(self.client.post(url, data='{"remove_old": true}', content_type="application/json").status_code, 200)
        self.assertEqual(op.call_args.args[3], {'remove_old': True})
        self.inst.db_kind = "shared"
        self.inst.save()
        self.assertEqual(self.client.post(url, data="{}", content_type="application/json").status_code, 400)
        self.inst.db_kind = "dedicated"
        self.inst.save()
        self.db.delete()
        resp = self.client.post(url, data="{}", content_type="application/json")
        self.assertIn("No shared database", resp.json()['message'])


class HeappeDbStartupIssueTests(TestCase):
    """HEAppE that started before SQL Server was ready is recognised, so the UI can propose restarting it."""

    class FakeContainer:
        def __init__(self, service, status='running', health='healthy', logs=b''):
            self.labels = {'com.docker.compose.service': service}
            self.status = status
            self.id = f"id-{service}"
            self.name = f"inst_{service}"
            self.attrs = {'State': {'StartedAt': '2026-10-27T20:43:53.561Z', 'Health': {'Status': health}}}
            self._logs = logs
            self.logs_kwargs = None

        def logs(self, **kwargs):
            self.logs_kwargs = kwargs
            return self._logs

    PRELOGIN = (b"Starting migration and seeding into the new database.\n"
                b" ---> Microsoft.Data.SqlClient.SqlException (0x80131904): A connection was successfully established "
                b"with the server, but then an error occurred during the pre-login handshake.\n")

    def detect(self, *containers):
        from heappe_ui.view.deploy import detect_heappe_db_startup_issue
        return detect_heappe_db_startup_issue(list(containers))

    def test_unhealthy_heappe_with_prelogin_error_and_healthy_sql(self):
        heappe = self.FakeContainer('heappe', health='unhealthy', logs=self.PRELOGIN)
        issue = self.detect(heappe, self.FakeContainer('mssql'))
        self.assertEqual(issue['container_id'], 'id-heappe')
        self.assertTrue(issue['mssql_ready'])
        self.assertIn('pre-login handshake', issue['error'])
        self.assertEqual(heappe.logs_kwargs['since'].isoformat(), '2026-10-27T20:43:53')   # only since last start

    def test_sql_not_healthy_yet(self):
        issue = self.detect(self.FakeContainer('heappe', health='unhealthy', logs=self.PRELOGIN),
                            self.FakeContainer('mssql', health='starting'))
        self.assertFalse(issue['mssql_ready'])

    def test_no_issue(self):
        cases = [
            (self.FakeContainer('heappe', health='healthy', logs=self.PRELOGIN), self.FakeContainer('mssql')),
            (self.FakeContainer('heappe', health='starting', logs=self.PRELOGIN), self.FakeContainer('mssql')),
            (self.FakeContainer('heappe', status='exited', health='unhealthy', logs=self.PRELOGIN),
             self.FakeContainer('mssql')),
            (self.FakeContainer('heappe', health='unhealthy', logs=b"DbContextException: MigrationMismatch\n"),
             self.FakeContainer('mssql')),
            (self.FakeContainer('mssql'),),
        ]
        for containers in cases:
            self.assertIsNone(self.detect(*containers))


import subprocess


class RestartAllCommandTests(TestCase):
    """Restart All skips one-shot init jobs, whose stale containers fail to restart when their network is gone."""

    def run_cmd(self, listed):
        from heappe_ui.view import deploy
        base = ["docker", "compose", "--profile", "db", "-p", "inst"]
        with mock.patch.object(deploy, "execute_docker_compose", return_value=listed) as ex:
            cmd = deploy.restart_all_command(base, "/x")
        self.assertEqual(ex.call_args[0][0], base + ["config", "--services"])
        return cmd[len(base):]

    def test_skips_one_shot_services(self):
        listed = subprocess.CompletedProcess([], 0, stdout="mssql\nheappe-init\nheappe\nvault\notel-collector-init\n")
        self.assertEqual(self.run_cmd(listed), ["restart", "mssql", "heappe", "vault"])

    def test_plain_restart_from_dropdown(self):
        from heappe_ui.view import deploy
        base = ["docker", "compose", "-p", "inst"]
        ok = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(deploy, "execute_docker_compose", return_value=ok) as ex:
            deploy.run_bg_restart_all("/x", "inst", base, None, None, plain=True)
        self.assertEqual([c[0][0] for c in ex.call_args_list], [base + ["restart"]])
        self.assertEqual(deploy.RESTART_STATES["inst"]["status"], "done")

    def test_falls_back_to_plain_restart(self):
        self.assertEqual(self.run_cmd(subprocess.CompletedProcess([], 1, stdout="", stderr="boom")), ["restart"])


class ContainerCardTests(TestCase):
    """Container cards are named and grouped by compose service, not by container name."""

    class C:
        def __init__(self, service, status='running', health='', exit_code=0, ports=None, name=None):
            self.labels = {'com.docker.compose.service': service} if service else {}
            self.status = status
            self.name = name or f"qscheduler_autodeploy_{service}"
            self.attrs = {'State': {'Health': {'Status': health} if health else None, 'ExitCode': exit_code,
                                    'StartedAt': '2026-10-29T08:14:54.1Z', 'FinishedAt': '0001-01-01T00:00:00Z'},
                          'NetworkSettings': {'Ports': ports or {}}, 'HostConfig': {'RestartPolicy': {'Name': 'no'}}}

    def test_describe(self):
        from heappe_ui.view.deploy import describe_container
        ports = {'80/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '5000'}, {'HostIp': '::', 'HostPort': '5000'}],
                 '443/tcp': None}
        info = describe_container(self.C('heappe', health='healthy', ports=ports), 'qscheduler_autodeploy')
        self.assertEqual((info['title'], info['section'], info['badge']), ("HEAppE API", 'api', "Healthy"))
        self.assertEqual(info['ports'], ["5000 → 80/tcp", "443/tcp (internal)"])          # IPv4 + IPv6 shown once
        self.assertEqual(info['config_file'], 'appsettings.json')

        job = describe_container(self.C('heappe-init', status='exited', exit_code=0))
        self.assertEqual((job['section'], job['badge'], job['tone']), ('jobs', "Completed", 'secondary'))
        self.assertEqual(describe_container(self.C('heappe-init', status='exited', exit_code=128))['badge'], "Failed")
        self.assertEqual(describe_container(self.C('mssql', status='exited', exit_code=1))['badge'], "Exited")
        self.assertEqual(describe_container(self.C('heappe', health='unhealthy'))['tone'], 'danger')

        other = describe_container(self.C('', name='qscheduler_autodeploy_slurm1'), 'qscheduler_autodeploy')
        self.assertEqual((other['title'], other['section'], other['can_delete']), ('slurm1', 'other', True))

    def test_sections_ignore_instance_name(self):
        """An instance named like a section keyword (e.g. 'qscheduler_...') keeps every card in its own section."""
        from heappe_ui.view.deploy import build_container_sections
        cs = [self.C(s) for s in ('vault', 'heappe-init', 'mssql', 'heappe', 'datastagingapi')]
        sections = build_container_sections(cs, 'qscheduler_autodeploy')
        self.assertEqual([(s['key'], [i['info']['service'] for i in s['items']]) for s in sections],
                         [('api', ['heappe', 'datastagingapi']), ('db', ['mssql']), ('infra', ['vault']),
                          ('jobs', ['heappe-init'])])


class QSchedulerNetworkTests(TestCase):
    """QScheduler network: subnet layout and proposal, aliases, override file, static IPs (Docker mocked)."""

    def setUp(self):
        from heappe_ui.models import QSchedulerInstance
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)

    def test_layout_and_subnet_input(self):
        from heappe_ui.view import qscheduler_network as qn
        self.assertEqual(qn.layout("10.213.4.0/27"), {'subnet': "10.213.4.0/27", 'gateway': "10.213.4.1",
                                                      'ip': "10.213.4.2", 'ip_range': "10.213.4.16/28"})
        self.assertIsNone(qn.parse_subnet(""))
        self.assertEqual(str(qn.parse_subnet(" 10.213.8.0/28 ")), "10.213.8.0/28")
        for bad, text in (("10.213.4.1/27", "host bits"), ("8.8.8.0/27", "private"), ("10.0.0.0/29", "size"),
                          ("nonsense", "CIDR")):
            with self.assertRaisesRegex(ValueError, text):
                qn.parse_subnet(bad)
        self.assertEqual(qn.parse_prefix(""), 27)
        self.assertEqual(qn.parse_prefix("/26"), 26)
        with self.assertRaises(ValueError):
            qn.parse_prefix("29")

    def test_proposal_skips_used_subnets_and_overlap_offers_a_free_one(self):
        import ipaddress
        from heappe_ui.view import qscheduler_network as qn
        used = [ipaddress.ip_network("10.213.0.0/29"), ipaddress.ip_network("10.213.0.32/27")]
        with mock.patch.object(qn.core, "used_subnets", return_value=used):
            self.assertEqual(qn.propose(mock.Mock(), 27)['subnet'], "10.213.0.64/27")   # .0/27 overlaps the /29
            with self.assertRaises(qn.SubnetUnavailable) as ctx:
                qn.check_free(mock.Mock(), "10.213.0.32/27")
        self.assertEqual(ctx.exception.proposal, "10.213.0.64/27")
        self.assertIn("Free subnet of the same size: 10.213.0.64/27", str(ctx.exception))

    def test_create_network_arguments(self):
        from heappe_ui.view import qscheduler_network as qn
        from heappe_ui.view.qscheduler_core import CommandResult
        docker = mock.Mock()
        docker.run.return_value = CommandResult(0, "id", "")
        with mock.patch.object(qn.core, "used_subnets", return_value=[]):
            lay = qn.create(docker, "qs-1_qs_net", "10.213.4.0/27", "qs-1", lambda *_: None)
        args = docker.run.call_args.args[0]
        self.assertEqual(lay['ip'], "10.213.4.2")
        for a in ("--internal", "10.213.4.0/27", "10.213.4.1", "10.213.4.16/28", "qs-1_qs_net"):
            self.assertIn(a, args)
        docker.run.return_value = CommandResult(1, "", "Pool overlaps with other one on this address space")
        with mock.patch.object(qn.core, "used_subnets", return_value=[]), \
                mock.patch.object(qn, "propose", return_value={'subnet': "10.213.4.32/27"}):
            with self.assertRaises(qn.SubnetUnavailable) as ctx:
                qn.create(docker, "qs-1_qs_net", "10.213.4.0/27", "qs-1", lambda *_: None)
        self.assertEqual(ctx.exception.proposal, "10.213.4.32/27")

    def test_aliases(self):
        from heappe_ui.models import QSchedulerInstance
        from heappe_ui.view import qscheduler_network as qn
        self.assertEqual(qn.validate_alias("VLQ.machine.qscheduler.it4i.cz."), "vlq.machine.qscheduler.it4i.cz")
        self.assertEqual(qn.validate_alias("vlq.qpu.example.org"), "vlq.qpu.example.org")   # any provider's domain
        for bad in ("bad_label.machine.qscheduler.it4i.cz", "-x.example.org", "a" * 64 + ".example.org", ""):
            with self.assertRaises(ValueError):
                qn.validate_alias(bad)
        with self.settings(QSCHEDULER_ALIAS_ZONE="machine.qscheduler.it4i.cz"):
            with self.assertRaisesRegex(ValueError, "not inside the alias zone"):
                qn.validate_alias("vlq.example.org")
        QSchedulerInstance.objects.create(name="qs-2", kind="managed", container_name="qs-2", service_host="qs-2",
                                          aliases=["used.machine.qscheduler.it4i.cz"])
        aliases, errors = qn.parse_aliases("a.machine.qscheduler.it4i.cz, a.machine.qscheduler.it4i.cz\n"
                                           "used.machine.qscheduler.it4i.cz", self.inst)
        self.assertEqual(aliases, ["a.machine.qscheduler.it4i.cz", "used.machine.qscheduler.it4i.cz"])
        self.assertEqual(errors, ["Alias 'used.machine.qscheduler.it4i.cz' is already used by QScheduler instance 'qs-2'."])
        with self.settings(QSCHEDULER_ALIAS_ZONE="qs.example.org"):
            self.assertEqual(qn.parse_aliases(["x.qs.example.org"], self.inst), (["x.qs.example.org"], []))
        self.inst.aliases, self.inst.service_host = ["a.machine.qscheduler.it4i.cz"], "qs-host"
        self.assertEqual(qn.network_aliases(self.inst), ["qs-host", "a.machine.qscheduler.it4i.cz"])
        self.assertEqual(self.inst.hosts, ["qs-host", "a.machine.qscheduler.it4i.cz"])

    def test_override_network_keeps_the_rest_of_the_file(self):
        import tempfile
        import yaml
        from heappe_ui.view import extra_hosts as eh
        path = os.path.join(tempfile.mkdtemp(prefix="qs-ovr-"), "docker-compose.override.yml")
        eh.write_override_extra_hosts(path, "heappe", [("login.local", "10.0.0.5")])
        eh.set_override_network(path, "heappe", "qs-1_qs_net", True)
        eh.set_override_network(path, "heappe", "qs-2_qs_net", True)
        data = yaml.safe_load(open(path))
        self.assertEqual(data['services']['heappe']['extra_hosts'], ["login.local:10.0.0.5"])
        self.assertEqual(list(data['services']['heappe']['networks']), ["qs-1_qs_net", "qs-2_qs_net"])
        self.assertEqual(data['networks']['qs-1_qs_net'], {'external': True})
        self.assertEqual(eh.override_networks(path, "heappe"), ["qs-1_qs_net", "qs-2_qs_net"])
        eh.set_override_network(path, "heappe", "qs-1_qs_net", False)
        data = yaml.safe_load(open(path))
        self.assertEqual(list(data['services']['heappe']['networks']), ["qs-2_qs_net"])
        self.assertNotIn("qs-1_qs_net", data['networks'])
        eh.set_override_network(path, "heappe", "qs-2_qs_net", False)
        eh.write_override_extra_hosts(path, "heappe", [])
        self.assertFalse(os.path.exists(path))                     # nothing left: file removed

    def test_recreate_keeps_static_ip_and_aliases(self):
        from heappe_ui.view import qscheduler_deploy as q
        info = {"Id": "abcdef1234567890", "Name": "/qs-1",
                "Config": {"Image": "qs", "Cmd": ["serve", "--port", "4300"], "Env": []},
                "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
                "NetworkSettings": {"Networks": {
                    "bridge": {"Aliases": None},
                    "qs-1_qs_net": {"Aliases": ["qs-1", "vlq.machine.qscheduler.it4i.cz"],
                                    "IPAMConfig": {"IPv4Address": "10.213.4.2"}}}}}
        internal = {"qs-1_qs_net": True}
        with mock.patch.object(q, "_network_is_internal", side_effect=lambda n, d=None: internal.get(n, False)):
            args, nets, _ = q.recreate_args_from_inspect(info, "qs:new")
        self.assertEqual(nets[0][0], "bridge")
        self.assertNotIn("--ip", args)                            # bridge: dynamic
        self.assertEqual(nets[1], ("qs-1_qs_net", ["qs-1", "vlq.machine.qscheduler.it4i.cz"], "10.213.4.2"))
        docker, target = mock.Mock(), mock.Mock()
        with mock.patch.object(q, "_network_is_internal", side_effect=lambda n, d=None: internal.get(n, False)):
            q.recreate_container(docker, target, info, "qs:new", None, lambda *_: None, "u1", "Update")
        connect = [c.args[0] for c in docker.run.call_args_list if c.args[0][:2] == ["network", "connect"]][0]
        self.assertEqual(connect, ["network", "connect", "--alias", "qs-1", "--alias", "vlq.machine.qscheduler.it4i.cz",
                                   "--ip", "10.213.4.2", "qs-1_qs_net", "qs-1"])

    def test_deploy_creates_network_and_connects_with_static_ip(self):
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_network as qn
        opts, errors = d.parse_deploy_options({"name": "qs", "source": "image", "image": "qs:v1", "db_mode": "existing",
                                               "database_url": "postgres://u:p@h/db", "qs_subnet": "10.213.4.0/27",
                                               "aliases": "vlq.machine.qscheduler.it4i.cz"}, "u1")
        self.assertEqual(errors, [])
        from heappe_ui.view.qscheduler_core import CommandResult
        docker, target = mock.Mock(), mock.Mock()
        docker.json.return_value = None                            # network does not exist yet
        docker.run.return_value = CommandResult(0, "", "")
        target.version.return_value = "qscheduler 0.2.1"
        with mock.patch.object(d, "_build_or_check_image"), mock.patch.object(d, "DockerTarget", return_value=target), \
                mock.patch.object(qn.core, "used_subnets", return_value=[]):
            info = d.deploy_service(docker, opts, lambda *_: None)
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertIn("--internal", next(c for c in cmds if c[:2] == ["network", "create"]))
        self.assertIn(["network", "connect", "--ip", "10.213.4.2", "--alias", "vlq.machine.qscheduler.it4i.cz",
                       "qs-u1_qs_net", "qs-u1"], cmds)
        self.assertEqual((info['qs_network'], info['qs_subnet'], info['qs_ip']), ("qs-u1_qs_net", "10.213.4.0/27", "10.213.4.2"))
        _, errors = d.parse_deploy_options({"qs_subnet": "10.213.4.3/27", "aliases": "bad_alias.example.org"}, "u2")
        self.assertEqual(len(errors), 2)


class QSchedulerNetworkWorkerTests(TestCase):
    """Migrate to QScheduler network, aliases, assign / unassign, Extra Hosts aliases (Docker and HEAppE mocked)."""

    def setUp(self):
        from heappe_ui.models import InstanceCredentials, QSchedulerAssignment, QSchedulerInstance
        self.cred = InstanceCredentials.objects.create(instance_name="dev", heappe_host="h", heappe_port=5000)
        self.inst = QSchedulerInstance.objects.create(name="qs-1", kind="managed", container_name="qs-1",
                                                      service_host="qs-1", port=4300)
        self.asg = QSchedulerAssignment.objects.create(qscheduler=self.inst, heappe_instance=self.cred,
                                                       network="dev_external_network")
        self.logs = []

    def _docker(self, qs_networks):
        docker = mock.Mock()
        docker.inspect.return_value = {"Name": "/qs-1"}
        docker.networks_of.side_effect = lambda name: list(qs_networks)
        docker.json.return_value = None
        docker.run.return_value = mock.Mock(returncode=0, output="")
        return docker

    def _migrate(self, docker, check=None):
        from heappe_ui.view import qscheduler_network as qn
        with mock.patch.object(qn, "DockerCli", return_value=docker), \
                mock.patch.object(qn.core, "used_subnets", return_value=[]), \
                mock.patch.object(qn, "heappe_join", return_value="dev_heappe") as join, \
                mock.patch.object(qn, "heappe_leave") as leave, \
                mock.patch.object(qn.core, "check_from_heappe", side_effect=check), \
                mock.patch("heappe_ui.view.qscheduler_admin.remove_proxy"), \
                mock.patch("heappe_ui.view.qscheduler_admin.ensure_proxy"):
            result = {}
            try:
                qn.migrate_network_worker(self.logs.append, result, self.inst.id, {'qs_subnet': "10.213.4.0/27"})
            finally:
                self.join, self.leave = join, leave
        return result

    def test_migrate_switches_after_heappe_reaches_qscheduler(self):
        docker = self._docker(["bridge", "qs-1_db_net", "dev_external_network"])
        result = self._migrate(docker)
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertIn(["network", "connect", "--ip", "10.213.4.2", "qs-1_qs_net", "qs-1"], cmds)
        self.assertIn(["network", "disconnect", "dev_external_network", "qs-1"], cmds)
        self.assertLess(cmds.index(["network", "connect", "--ip", "10.213.4.2", "qs-1_qs_net", "qs-1"]),
                        cmds.index(["network", "disconnect", "dev_external_network", "qs-1"]))
        self.assertNotIn(["network", "disconnect", "qs-1_db_net", "qs-1"], cmds)
        self.join.assert_called_once_with("dev", "qs-1_qs_net", mock.ANY)
        self.inst.refresh_from_db(); self.asg.refresh_from_db()
        self.assertEqual((self.inst.qs_network, self.inst.qs_ip, self.asg.network), ("qs-1_qs_net", "10.213.4.2", "qs-1_qs_net"))
        self.assertEqual(result['qs_subnet'], "10.213.4.0/27")

    def test_migrate_rolls_back_when_heappe_cannot_reach_it(self):
        docker = self._docker(["bridge", "dev_external_network"])
        with self.assertRaisesRegex(RuntimeError, "rolled back"):
            self._migrate(docker, check=RuntimeError("not reachable"))
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.leave.assert_called_once_with("dev", "qs-1_qs_net", mock.ANY)
        self.assertIn(["network", "rm", "qs-1_qs_net"], cmds)
        self.assertNotIn(["network", "disconnect", "dev_external_network", "qs-1"], cmds)
        self.inst.refresh_from_db(); self.asg.refresh_from_db()
        self.assertEqual((self.inst.qs_network, self.asg.network), ("", "dev_external_network"))

    def test_aliases_reconnect_and_refuse_removing_used_alias(self):
        from heappe_ui.view import qscheduler_network as qn
        self.inst.qs_network, self.inst.qs_ip = "qs-1_qs_net", "10.213.4.2"
        self.inst.aliases = ["old.machine.qscheduler.it4i.cz"]
        self.inst.save()
        cluster = {'id': 7, 'name': "VLQ", 'master_node_name': "old.machine.qscheduler.it4i.cz", 'custom_configuration': {}}
        docker = self._docker([])
        with mock.patch.object(qn, "DockerCli", return_value=docker), \
                mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(mock.Mock(), "sc", None)), \
                mock.patch.object(qn.core, "qscheduler_clusters", return_value=[cluster]), \
                mock.patch.object(qn.core, "find_heappe_api_container", return_value="dev_heappe"), \
                mock.patch.object(qn.core, "check_from_heappe") as check:
            with self.assertRaisesRegex(RuntimeError, "still used by HEAppE 'dev' cluster"):
                qn.aliases_worker(self.logs.append, {}, self.inst.id, ["new.machine.qscheduler.it4i.cz"])
            docker.run.assert_not_called()
            qn.aliases_worker(self.logs.append, {}, self.inst.id,
                              ["old.machine.qscheduler.it4i.cz", "new.machine.qscheduler.it4i.cz"])
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertEqual(cmds, [["network", "disconnect", "qs-1_qs_net", "qs-1"],
                                ["network", "connect", "--ip", "10.213.4.2", "--alias", "old.machine.qscheduler.it4i.cz",
                                 "--alias", "new.machine.qscheduler.it4i.cz", "qs-1_qs_net", "qs-1"]])
        self.assertEqual(check.call_count, 2)
        self.inst.refresh_from_db()
        self.assertEqual(self.inst.aliases, ["old.machine.qscheduler.it4i.cz", "new.machine.qscheduler.it4i.cz"])

    def test_heappe_join_and_leave_use_the_override_file(self):
        import tempfile
        from heappe_ui.view import extra_hosts as eh
        from heappe_ui.view import qscheduler_network as qn
        base = tempfile.mkdtemp(prefix="qs-join-")
        os.makedirs(os.path.join(base, "dev", "heappe-core"))
        open(os.path.join(base, "dev", "heappe-core", "docker-compose.yml"), "w").write("services: {}\n")
        docker = self._docker([])
        with mock.patch.object(eh, "DEPLOYMENT_BASE_PATH", base), mock.patch.object(qn, "DockerCli", return_value=docker), \
                mock.patch.object(qn.core, "find_heappe_api_container", return_value="dev_heappe"):
            self.assertEqual(qn.heappe_join("dev", "qs-1_qs_net", self.logs.append), "dev_heappe")
            override = os.path.join(base, "dev", "heappe-core", "docker-compose.override.yml")
            self.assertEqual(eh.override_networks(override, "heappe"), ["qs-1_qs_net"])
            docker.networks_of.side_effect = lambda name: ["qs-1_qs_net"]
            qn.heappe_leave("dev", "qs-1_qs_net", self.logs.append)
        cmds = [c.args[0] for c in docker.run.call_args_list]
        self.assertEqual(cmds, [["network", "connect", "qs-1_qs_net", "dev_heappe"],
                                ["network", "disconnect", "qs-1_qs_net", "dev_heappe"]])
        self.assertFalse(os.path.exists(override))

    def test_extra_hosts_lists_aliases_by_resolution(self):
        from heappe_ui.models import QSchedulerAssignment, QSchedulerInstance
        from heappe_ui.view import extra_hosts as eh
        self.inst.qs_network, self.inst.qs_ip, self.inst.aliases = "qs-1_qs_net", "10.213.4.2", ["a.machine.qscheduler.it4i.cz"]
        self.inst.save()
        legacy = QSchedulerInstance.objects.create(name="qs-old", kind="local", container_name="qs-old", service_host="qs-old",
                                                   aliases=["b.machine.qscheduler.it4i.cz"])
        remote = QSchedulerInstance.objects.create(name="qs-r", kind="ssh_host", container_name="qs-r", service_host="r",
                                                   aliases=["c.machine.qscheduler.it4i.cz", "d.machine.qscheduler.it4i.cz"])
        for q in (legacy, remote):
            QSchedulerAssignment.objects.create(qscheduler=q, heappe_instance=self.cred)
        with mock.patch.object(eh.ComposeTarget, "state", return_value=([], [("c.machine.qscheduler.it4i.cz", "10.9.9.9")])):
            rows = {r['alias']: r for r in eh.qscheduler_aliases("dev")}
        self.assertEqual(rows["a.machine.qscheduler.it4i.cz"]['mode'], "dns")
        self.assertIn("10.213.4.2", rows["a.machine.qscheduler.it4i.cz"]['detail'])
        self.assertEqual(rows["b.machine.qscheduler.it4i.cz"]['mode'], "pending")
        self.assertEqual((rows["c.machine.qscheduler.it4i.cz"]['mode'], rows["c.machine.qscheduler.it4i.cz"]['ip']), ("manual", "10.9.9.9"))
        self.assertEqual(rows["d.machine.qscheduler.it4i.cz"]['ip'], "")

    def test_assign_joins_heappe_to_the_qscheduler_network(self):
        from heappe_ui.view import qscheduler_deploy as d
        self.asg.delete()
        self.inst.qs_network = "qs-1_qs_net"
        self.inst.save()
        target = mock.Mock()
        target.list_notifiers.return_value = []
        with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api", return_value=(mock.Mock(), "sc", None)), \
                mock.patch.object(d.core, "heappe_identity", return_value=("6.6.0", "dev")), \
                mock.patch.object(d.core, "qscheduler_clusters", return_value=[]), \
                mock.patch.object(d.core, "target_for", return_value=target), \
                mock.patch.object(d.core, "resolve_heappe_service_network") as legacy, \
                mock.patch.object(d.core, "restart_heappe") as restart, \
                mock.patch.object(d.core, "check_from_heappe"), \
                mock.patch.object(d.qnet, "heappe_join", return_value="dev_heappe") as join:
            d.assign_worker(self.logs.append, {}, self.inst.id, {'heappe_instance_id': str(self.cred.id),
                                                                  'notifications_enabled': True, 'callback_url': ""})
        join.assert_called_once_with("dev", "qs-1_qs_net", mock.ANY)
        legacy.assert_not_called()
        restart.assert_not_called()                                # no HEAppE restart needed
        from heappe_ui.models import QSchedulerAssignment
        asg = QSchedulerAssignment.objects.get(qscheduler=self.inst)
        self.assertEqual(asg.network, "qs-1_qs_net")
        self.assertEqual(asg.callback_url, "http://dev_heappe:80/heappe/JobManagement/TaskCallback")


@unittest.skipUnless(os.environ.get("QS_DOCKER_TESTS"), "real Docker test: set QS_DOCKER_TESTS=1 (and QS_TEST_IMAGE)")
class QSchedulerNetworkDockerTests(TestCase):
    """End to end against Docker: QScheduler network, static IP, aliases, admin proxy, update, migration, undeploy."""
    ALIAS = "vlq.machine.qscheduler.it4i.cz"
    ALIAS2 = "vlq2.machine.qscheduler.it4i.cz"

    def setUp(self):
        import subprocess
        import tempfile
        from heappe_ui.models import InstanceCredentials
        self.image = os.environ.get("QS_TEST_IMAGE", "qscheduler:v0.2.1-tag")
        self.logs = []
        self.log = lambda m: self.logs.append(m)
        self.addCleanup(self._cleanup)
        # A stand-in for the HEAppE API container of instance "qse2n" (has curl, like the HEAppE image)
        self.base = tempfile.mkdtemp(prefix="qs-e2n-")
        os.makedirs(os.path.join(self.base, "qse2n", "heappe-core"))
        open(os.path.join(self.base, "qse2n", "heappe-core", "docker-compose.yml"), "w").write("services: {}\n")
        subprocess.run(["docker", "network", "create", "qse2n_external_network"], capture_output=True, check=True)
        subprocess.run(["docker", "run", "-d", "--name", "qse2n_heappe", "--network", "qse2n_external_network",
                        "--entrypoint", "sleep", "curlimages/curl:8.11.1", "3600"], capture_output=True, check=True)
        self.cred = InstanceCredentials.objects.create(instance_name="qse2n", heappe_host="h", heappe_port=5000)

    def _cleanup(self):
        import shutil
        import subprocess
        for c in subprocess.run(["docker", "ps", "-aq", "--filter", "name=qse2n"], capture_output=True, text=True).stdout.split():
            subprocess.run(["docker", "rm", "-f", c], capture_output=True)
        for n in subprocess.run(["docker", "network", "ls", "-q", "--filter", "name=qse2n"], capture_output=True, text=True).stdout.split():
            subprocess.run(["docker", "network", "rm", n], capture_output=True)
        for v in subprocess.run(["docker", "volume", "ls", "-q", "--filter", "name=qse2n"], capture_output=True, text=True).stdout.split():
            subprocess.run(["docker", "volume", "rm", v], capture_output=True)
        shutil.rmtree(self.base, ignore_errors=True)

    def _ip(self, docker, container, net):
        n = ((docker.inspect(container) or {}).get("NetworkSettings") or {}).get("Networks") or {}
        return (n.get(net) or {}).get("IPAddress")

    def _deploy(self, d, uid, aliases):
        opts, errors = d.parse_deploy_options({"name": "qse2n", "source": "image", "image": self.image, "db_mode": "new",
                                               "aliases": aliases}, uid)
        self.assertEqual(errors, [])
        result = {}
        d.deploy_worker(self.log, result, opts)
        return result

    def test_network_lifecycle(self):
        from heappe_ui.models import QSchedulerAssignment, QSchedulerInstance
        from heappe_ui.view import extra_hosts as eh
        from heappe_ui.view import qscheduler_admin as qa
        from heappe_ui.view import qscheduler_core as core
        from heappe_ui.view import qscheduler_deploy as d
        from heappe_ui.view import qscheduler_network as qn
        docker = core.DockerCli()
        with mock.patch.object(eh, "DEPLOYMENT_BASE_PATH", self.base):
            # 1. deploy: own network, static .2, alias
            r = self._deploy(d, "e2e00001", self.ALIAS)
            inst = QSchedulerInstance.objects.get(pk=r['id'])
            self.assertEqual(inst.qs_network, "qse2n-e2e00001_qs_net")
            import ipaddress
            self.assertEqual(inst.qs_ip, str(ipaddress.ip_network(inst.qs_subnet).network_address + 2))
            self.assertEqual(self._ip(docker, inst.container_name, inst.qs_network), inst.qs_ip)
            self.assertTrue(docker.network_is_internal(inst.qs_network))

            # 2. HEAppE joins (live + override) and reaches QScheduler by container name and by alias
            heappe = qn.heappe_join("qse2n", inst.qs_network, self.log)
            self.assertEqual(heappe, "qse2n_heappe")
            asg = QSchedulerAssignment.objects.create(qscheduler=inst, heappe_instance=self.cred, network=inst.qs_network)
            override = os.path.join(self.base, "qse2n", "heappe-core", "docker-compose.override.yml")
            self.assertEqual(eh.override_networks(override, "heappe"), [inst.qs_network])
            core.check_from_heappe(heappe, inst.container_name, 4300, "/health", self.log)
            core.check_from_heappe(heappe, self.ALIAS, 4300, "/health", self.log)
            dyn = self._ip(docker, heappe, inst.qs_network)
            self.assertNotEqual(dyn, inst.qs_ip)

            # 3. admin API through the proxy on the QScheduler network
            status, _ = qa.AdminClient(inst, docker).request("GET", "/machines")
            self.assertEqual(status, 200)
            self.assertIn("bridge", docker.networks_of(qa.proxy_name(inst)))

            # 4. update (recreate): same static address, alias still answers
            target = core.target_for(inst)
            info = docker.inspect(inst.container_name)
            d.recreate_container(docker, target, info, self.image, None, self.log, "e2eupd01", "Update")
            self.assertEqual(self._ip(docker, inst.container_name, inst.qs_network), inst.qs_ip)
            core.check_from_heappe(heappe, self.ALIAS, 4300, "/health", self.log)

            # 5. aliases: add one (reconnect), both answer
            with mock.patch("heappe_ui.view.clusters.connect_heappe_management_api",
                            return_value=(mock.Mock(heappe_management_clusters_get=mock.Mock(return_value=[])), "sc", None)):
                qn.aliases_worker(self.log, {}, inst.id, [self.ALIAS, self.ALIAS2])
            core.check_from_heappe(heappe, self.ALIAS2, 4300, "/health", self.log)
            self.assertEqual(self._ip(docker, inst.container_name, inst.qs_network), inst.qs_ip)

            # 6. a second instance as before the QScheduler network existed: on the HEAppE network, no static IP
            r2 = self._deploy(d, "e2e00002", "")
            old = QSchedulerInstance.objects.get(pk=r2['id'])
            docker.run(["network", "disconnect", old.qs_network, old.container_name], self.log)
            docker.run(["network", "rm", old.qs_network], self.log)
            docker.run(["network", "connect", "qse2n_external_network", old.container_name], self.log)
            old.qs_network = old.qs_subnet = old.qs_ip = ""
            old.save()
            QSchedulerAssignment.objects.create(qscheduler=old, heappe_instance=self.cred, network="qse2n_external_network")
            core.check_from_heappe(heappe, old.container_name, 4300, "/health", self.log)
            qn.migrate_network_worker(self.log, {}, old.id, {})
            old.refresh_from_db()
            self.assertEqual(old.qs_network, "qse2n-e2e00002_qs_net")
            self.assertEqual(self._ip(docker, old.container_name, old.qs_network), old.qs_ip)
            self.assertNotIn("qse2n_external_network", docker.networks_of(old.container_name))
            core.check_from_heappe(heappe, old.container_name, 4300, "/health", self.log)
            self.assertEqual(sorted(eh.override_networks(override, "heappe")), sorted([inst.qs_network, old.qs_network]))

            # 7. unassign + undeploy: HEAppE leaves, networks removed
            for q in (inst, old):
                qn.heappe_leave("qse2n", q.qs_network, self.log)
                q.assignments.all().delete()
                d.undeploy_worker(self.log, {}, q.id, True)
                self.assertIsNone(docker.json(["network", "inspect", q.qs_network]))
            self.assertFalse(os.path.exists(override))
            self.assertEqual(docker.networks_of("qse2n_heappe"), ["qse2n_external_network"])
