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

    def test_adjust_to_utc(self):
        from heappe_ui.views import adjust_to_utc
        # Zero offset
        d, t = adjust_to_utc('2026-10-22', '15:30', 0)
        self.assertEqual(d, '2026-10-22')
        self.assertEqual(t, '15:30')

        # Negative offset (CEST UTC+2 has JS offset -120)
        d, t = adjust_to_utc('2026-10-22', '17:30', -120)
        self.assertEqual(d, '2026-10-22')
        self.assertEqual(t, '15:30')

        # Midnight shift (01:00 CEST -> 23:00 previous day)
        d, t = adjust_to_utc('2026-10-23', '01:00', -120)
        self.assertEqual(d, '2026-10-22')
        self.assertEqual(t, '23:00')

        # Positive offset (US EST UTC-5 has JS offset +300)
        d, t = adjust_to_utc('2026-10-22', '10:30', 300)
        self.assertEqual(d, '2026-10-22')
        self.assertEqual(t, '15:30')

        # Empty time or invalid offset returns as-is
        d, t = adjust_to_utc('2026-10-22', '', -120)
        self.assertEqual(t, '')
        d, t = adjust_to_utc('2026-10-22', '15:30', 'invalid')
        self.assertEqual(t, '15:30')

    def test_matches_filters_open_ended_and_midnight(self):
        from heappe_ui.views import matches_filters
        entry_morning = {'timestamp_str': '2026-10-22 09:15:00', 'level': 'INFO', 'content': 'Morning'}
        entry_noon = {'timestamp_str': '2026-10-22 12:30:45', 'level': 'INFO', 'content': 'Noon'}
        entry_afternoon = {'timestamp_str': '2026-10-22 15:34:58', 'level': 'INFO', 'content': 'Afternoon'}
        entry_night = {'timestamp_str': '2026-10-22 23:45:00', 'level': 'INFO', 'content': 'Night'}
        entry_late_night = {'timestamp_str': '2026-10-22 00:30:00', 'level': 'INFO', 'content': 'Late night'}

        # Open-ended start (from 12:30 onwards)
        self.assertFalse(matches_filters(entry_morning, "", "", "12:30", ""))
        self.assertTrue(matches_filters(entry_noon, "", "", "12:30", ""))
        self.assertTrue(matches_filters(entry_afternoon, "", "", "12:30", ""))
        self.assertTrue(matches_filters(entry_night, "", "", "12:30", ""))

        # Open-ended end (up to 12:30)
        self.assertTrue(matches_filters(entry_morning, "", "", "", "12:30"))
        self.assertTrue(matches_filters(entry_noon, "", "", "", "12:30"))
        self.assertFalse(matches_filters(entry_afternoon, "", "", "", "12:30"))
        self.assertFalse(matches_filters(entry_night, "", "", "", "12:30"))

        # Midnight crossing interval (23:00 to 01:00)
        self.assertTrue(matches_filters(entry_night, "", "", "23:00", "01:00"))
        self.assertTrue(matches_filters(entry_late_night, "", "", "23:00", "01:00"))
        self.assertFalse(matches_filters(entry_noon, "", "", "23:00", "01:00"))

    def test_log_viewer_view_timezone_handling(self):
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from heappe_ui.views import log_viewer_view
        import json as pyjson

        factory = RequestFactory()
        user = User.objects.create_user(username='test_tz_viewer_user', password='password')

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            # Entry at 15:34:58 UTC
            tmp.write('{"timestamp":"2026-10-22T15:34:58.000Z","level":"INFO","logger":"L","message":"UTC log"}\n')
            tmp.flush()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                # 1. User inputs Local time 17:30 (CEST, offset -120), expecting to match 15:34:58 UTC
                req = factory.get('/logs/?date=2026-10-22&time_from=17:30&tz_mode=local&tz_offset=-120')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = log_viewer_view(req)
                self.assertEqual(resp.status_code, 200)
                # The entry at 15:34:58 UTC is after 15:30:00 UTC (17:30 CEST adjusted), so it matches!
                self.assertIn('UTC log', resp.content.decode('utf-8'))

                # 2. Open-ended start (time_to is empty) does NOT truncate logs occurring hours later
                req = factory.get('/logs/?date=2026-10-22&time_from=12:30&time_to=')
                req.user = user
                req.session = {'chosen_instance': 'test'}
                resp = log_viewer_view(req)
                self.assertEqual(resp.status_code, 200)
                self.assertIn('UTC log', resp.content.decode('utf-8'))
        finally:
            os.remove(tmp_path)
            user.delete()

    @mock.patch('os.path.exists')
    @mock.patch('os.path.isdir')
    @mock.patch('os.listdir')
    @mock.patch('os.path.getmtime')
    def test_get_log_file_paths_all_history(self, mock_getmtime, mock_listdir, mock_isdir, mock_exists):
        from heappe_ui.views import get_log_file_paths
        mock_exists.return_value = True
        mock_isdir.return_value = False
        mock_listdir.side_effect = lambda d: [
            '2026_07_12.log',
            '2026_07_13.log.1',
            '2026_07_13.log',
            '2026_07_10.json',
        ] if str(d).endswith('/API') else []
        mock_getmtime.side_effect = lambda path: 10

        # Query all history (date_str=None or 'ALL')
        paths = get_log_file_paths('test_instance', date_str=None, service='API')
        self.assertEqual(len(paths), 4)
        file_names = [os.path.basename(p[0]) for p in paths]
        # Should be chronologically sorted oldest to newest: 07-10, 07-12, 07-13.log.1, 07-13.log
        self.assertEqual(file_names, [
            '2026_07_10.json',
            '2026_07_12.log',
            '2026_07_13.log.1',
            '2026_07_13.log'
        ])

    def test_get_log_entries_backwards_across_all_history_with_search(self):
        from heappe_ui.views import get_log_entries_backwards

        with tempfile.NamedTemporaryFile(suffix='.log', mode='w+', delete=False) as f_old, \
             tempfile.NamedTemporaryFile(suffix='.log', mode='w+', delete=False) as f_mid, \
             tempfile.NamedTemporaryFile(suffix='.log', mode='w+', delete=False) as f_new:

            f_old.write("INFO 2026-07-10 10:00:00 Controller - TargetError in old file\n")
            f_old.flush()

            f_mid.write("INFO 2026-07-11 11:00:00 Controller - Normal message\n")
            f_mid.flush()

            f_new.write("INFO 2026-07-12 12:00:00 Controller - TargetError in new file\n")
            f_new.flush()

            old_path = f_old.name
            mid_path = f_mid.name
            new_path = f_new.name

        try:
            # Sorted oldest first
            log_paths = [(old_path, 'API'), (mid_path, 'API'), (new_path, 'API')]
            entries = list(get_log_entries_backwards(log_paths, max_entries=10, search_query='targeterror'))
            self.assertEqual(len(entries), 2)
            # Most recent first in get_log_entries_backwards
            self.assertIn('TargetError in new file', entries[0]['content'])
            self.assertIn('TargetError in old file', entries[1]['content'])
        finally:
            os.remove(old_path)
            os.remove(mid_path)
            os.remove(new_path)

    def test_log_viewer_view_all_history_mode(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username='test_all_history_user', password='password')
        self.client.force_login(user)
        session = self.client.session
        session['chosen_instance'] = 'develop'
        session.save()

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            tmp.write('{"timestamp":"2026-10-10T12:00:00.000Z","level":"INFO","logger":"L","message":"Historical log"}\n')
            tmp.flush()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]) as mock_paths:
                resp = self.client.get('/logs/?all_history=1')
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.context['all_history'])
                self.assertEqual(resp.context['selected_date'], '')
                self.assertFalse(resp.context['limit_reached'])
                # get_log_file_paths should be called with effective_date=None
                mock_paths.assert_called_with('develop', None, service='API')
        finally:
            os.remove(tmp_path)
            user.delete()

    def test_log_viewer_view_limit_10000_and_limit_reached(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username='test_limit_10000_user', password='password')
        self.client.force_login(user)
        session = self.client.session
        session['chosen_instance'] = 'develop'
        session.save()

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            for i in range(120):
                tmp.write(f'{{"timestamp":"2026-10-15T12:00:00.000Z","level":"INFO","logger":"L","message":"Log {i}"}}\n')
            tmp.flush()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                # Test limit=100 with 120 lines -> limit_reached should be True
                resp = self.client.get('/logs/?date=2026-10-15&limit=100')
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.context['limit'], 100)
                self.assertEqual(resp.context['logs_count'], 100)
                self.assertTrue(resp.context['limit_reached'])

                # Test limit=10000 is allowed
                resp_10k = self.client.get('/logs/?date=2026-10-15&limit=10000')
                self.assertEqual(resp_10k.status_code, 200)
                self.assertEqual(resp_10k.context['limit'], 10000)
                self.assertEqual(resp_10k.context['logs_count'], 120)
                self.assertFalse(resp_10k.context['limit_reached'])
        finally:
            os.remove(tmp_path)
            user.delete()

    def test_log_viewer_view_override_limit_parameter(self):
        from django.contrib.auth.models import User
        user = User.objects.create_user(username='test_override_user', password='password')
        self.client.force_login(user)
        session = self.client.session
        session['chosen_instance'] = 'develop'
        session.save()

        with tempfile.NamedTemporaryFile(suffix='.json', mode='w+', delete=False) as tmp:
            # 1,200 log entries (exceeding default 1,000 limit)
            for i in range(1200):
                tmp.write(f'{{"timestamp":"2026-10-15T12:{i//60:02d}:{i%60:02d}.000Z","level":"INFO","logger":"L","message":"Msg_{i}"}}\n')
            tmp.flush()
            tmp_path = tmp.name

        try:
            with mock.patch('heappe_ui.views.get_log_file_paths', return_value=[(tmp_path, 'API')]):
                # 1. Default request hits 1,000 limit and limit_reached is True
                resp = self.client.get('/logs/?date=2026-10-15')
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.context['logs_count'], 1000)
                self.assertTrue(resp.context['limit_reached'])
                self.assertFalse(resp.context['override_limit'])

                # 2. Request with override_limit=1 overrides the 1,000 limit and returns all 1,200 records
                resp_override = self.client.get('/logs/?date=2026-10-15&override_limit=1')
                self.assertEqual(resp_override.status_code, 200)
                self.assertTrue(resp_override.context['override_limit'])
                self.assertEqual(resp_override.context['logs_count'], 1200)
                self.assertFalse(resp_override.context['limit_reached'])

                # 3. Request with limit=override also activates override
                resp_select = self.client.get('/logs/?date=2026-10-15&limit=override')
                self.assertEqual(resp_select.status_code, 200)
                self.assertTrue(resp_select.context['override_limit'])
                self.assertEqual(resp_select.context['logs_count'], 1200)
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
        self.assertIn('id="renameInstanceModal"', rendered)

    @mock.patch("heappe_ui.view.deploy.docker.from_env")
    @mock.patch("heappe_ui.view.deploy.execute_docker_compose")
    def test_rename_instance_success(self, mock_exec_compose, mock_docker_env):
        import tempfile
        import json
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.view.deploy import rename_instance
        import subprocess

        mock_exec_compose.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        mock_container = mock.MagicMock()
        mock_container.name = "develop_heappe"
        mock_container.status = "running"
        mock_container.labels = {"com.docker.compose.project": "develop"}

        mock_client = mock.MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_client.volumes.list.return_value = []
        mock_docker_env.return_value = mock_client

        inst = InstanceCredentials.objects.create(
            instance_name="develop",
            heappe_host="localhost",
            heappe_login="admin",
            heappe_password="pwd",
            heappe_port="5000",
            log_db_host="localhost",
            log_db_port="6000",
            log_db_user="SA",
            log_db_password="pwd",
            log_db_database="db",
            is_deployed=True
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            old_dir = os.path.join(temp_dir, "develop")
            core_dir = os.path.join(old_dir, "heappe-core")
            confs_dir = os.path.join(old_dir, "app", "confs")
            os.makedirs(core_dir, exist_ok=True)
            os.makedirs(confs_dir, exist_ok=True)

            # Write .env
            env_file = os.path.join(core_dir, ".env")
            with open(env_file, "w") as f:
                f.write(
                    f"INSTANCE_NAME=develop\n"
                    f"HOST_MSSQL_NAME=mssql-develop\n"
                    f"HOST_APP_NAME=heappe-develop\n"
                    f"BASE_PATH={temp_dir}/develop/app/confs\n"
                    f"SHARED_VAULT_FILE_NAME=credentials_develop\n"
                )

            # Write credentials vault file
            with open(os.path.join(old_dir, "credentials_develop"), "w") as f:
                f.write("vault_secret")

            # Write appsettings.json
            appsettings_file = os.path.join(confs_dir, "appsettings.json")
            with open(appsettings_file, "w") as f:
                json.dump({
                    "ConnectionStrings": {
                        "MiddlewareContext": "Server=develop_mssql;Database=heappe;"
                    },
                    "ApplicationAPISettings": {
                        "DeploymentSettings": {
                            "HostPostfix": "develop",
                            "Name": "develop instance"
                        }
                    },
                    "HPCConnectionFrameworkSettings": {
                        "ScriptsSettings": {
                            "InstanceIdentifierPath": "develop"
                        }
                    }
                }, f)

            res = rename_instance(
                old_name="develop",
                new_name="core_dev_it4i_develop",
                base_path=temp_dir,
                update_identifier=True,
                restart_containers=True
            )

            self.assertTrue(res["success"])
            self.assertTrue(res["files_moved"])
            new_dir = os.path.join(temp_dir, "core_dev_it4i_develop")
            self.assertTrue(os.path.exists(new_dir))
            self.assertFalse(os.path.exists(old_dir))

            # Verify .env updated
            with open(os.path.join(new_dir, "heappe-core", ".env"), "r") as f:
                new_env = f.read()
            self.assertIn("INSTANCE_NAME=core_dev_it4i_develop", new_env)
            self.assertIn("HOST_MSSQL_NAME=mssql-core_dev_it4i_develop", new_env)
            self.assertIn(f"BASE_PATH={temp_dir}/core_dev_it4i_develop/app/confs", new_env)
            self.assertIn("SHARED_VAULT_FILE_NAME=credentials_core_dev_it4i_develop", new_env)

            # Verify vault credentials file renamed
            self.assertTrue(os.path.exists(os.path.join(new_dir, "credentials_core_dev_it4i_develop")))

            # Verify appsettings.json updated
            with open(os.path.join(new_dir, "app", "confs", "appsettings.json"), "r") as f:
                new_appsettings = json.load(f)
            self.assertIn("Server=core_dev_it4i_develop_mssql;", new_appsettings["ConnectionStrings"]["MiddlewareContext"])
            self.assertEqual(new_appsettings["ApplicationAPISettings"]["DeploymentSettings"]["HostPostfix"], "core_dev_it4i_develop")
            self.assertEqual(new_appsettings["HPCConnectionFrameworkSettings"]["ScriptsSettings"]["InstanceIdentifierPath"], "core_dev_it4i_develop")

            # Verify DB updated
            inst.refresh_from_db()
            self.assertEqual(inst.instance_name, "core_dev_it4i_develop")

    def test_rename_instance_validation_errors(self):
        from heappe_ui.models import InstanceCredentials
        from heappe_ui.view.deploy import rename_instance

        # 1. Empty name
        res = rename_instance("develop", "")
        self.assertFalse(res["success"])
        self.assertIn("cannot be empty", res["errors"][0])

        # 2. Invalid chars
        res = rename_instance("develop", "Invalid-Name!")
        self.assertFalse(res["success"])
        self.assertIn("lowercase", res["errors"][0])

        # 3. Same name
        res = rename_instance("develop", "develop")
        self.assertFalse(res["success"])
        self.assertIn("must be different", res["errors"][0])

        # 4. Conflict with existing
        InstanceCredentials.objects.create(instance_name="existing_target", heappe_host="h", heappe_login="u", heappe_password="p", heappe_port="5000")
        res = rename_instance("develop", "existing_target")
        self.assertFalse(res["success"])
        self.assertIn("already exists", res["errors"][0])

    @mock.patch("heappe_ui.view.deploy.rename_instance")
    def test_deploy_rename_instance_view_ajax(self, mock_rename):
        from heappe_ui.view.deploy import deploy_rename_instance
        import json

        mock_rename.return_value = {
            "success": True,
            "old_name": "develop",
            "new_name": "core_dev_it4i_develop",
            "errors": []
        }

        req = self.factory.post("/deploy/develop/rename/", {
            "new_instance_name": "core_dev_it4i_develop",
            "source_project": "develop",
            "update_identifier": "true",
            "restart_containers": "true"
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        req.user = self.user
        req.session = {"chosen_instance": "develop"}
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, '_messages', FallbackStorage(req))

        resp = deploy_rename_instance(req, instance_name="develop")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["redirect_url"], "/deploy/core_dev_it4i_develop/")
        self.assertEqual(req.session["chosen_instance"], "core_dev_it4i_develop")












class QSchedulerDeployTests(TestCase):
    """Tests for the automated QScheduler deployment helpers (one HEAppE cluster == one QScheduler machine)."""

    def test_parse_defaults_new_instance(self):
        from heappe_ui.view.qscheduler_deploy import parse_qscheduler_options
        opts, errors = parse_qscheduler_options({}, "abcd1234")
        self.assertEqual(errors, [])
        self.assertEqual(opts['target'], 'new')
        self.assertEqual(opts['container_name'], 'qscheduler-abcd1234')
        self.assertEqual(opts['machine_name'], 'SimulatorMachine')
        self.assertEqual(opts['project_name'], 'qs-abcd1234')
        self.assertTrue(opts['enable_callback'])
        self.assertIsNone(opts['host_port'])

    def test_parse_existing_requires_instance(self):
        from heappe_ui.view.qscheduler_deploy import parse_qscheduler_options
        _, errors = parse_qscheduler_options({"target": "existing"}, "x")
        self.assertTrue(any("instance" in e for e in errors))
        opts, errors = parse_qscheduler_options({"target": "existing", "existing_container": "qscheduler-1"}, "x")
        self.assertEqual(errors, [])
        self.assertEqual(opts['container_name'], 'qscheduler-1')

    def test_parse_iqm_validation(self):
        from heappe_ui.view.qscheduler_deploy import parse_qscheduler_options
        _, errors = parse_qscheduler_options({"backend": "iqm", "machine_name": "VLQ", "iqm_check_interval": "500"}, "x")
        self.assertTrue(any("IQM server URL" in e for e in errors))
        self.assertTrue(any("device" in e for e in errors))
        self.assertTrue(any("unit suffix" in e for e in errors))

    def test_machine_add_args_order_test_backend(self):
        from heappe_ui.view.qscheduler_deploy import parse_qscheduler_options, build_machine_add_args
        opts, _ = parse_qscheduler_options({"machine_name": "Sim"}, "x")
        args = build_machine_add_args(opts, "http://h/heappe/JobManagement/TaskCallback", "tok")
        self.assertEqual(args[:3], ["machine", "add", "Sim"])
        # global options must precede the backend sub-command
        self.assertLess(args.index("--notify-url"), args.index("test"))
        self.assertEqual(args[-1], "test")

    def test_machine_add_args_iqm(self):
        from heappe_ui.view.qscheduler_deploy import parse_qscheduler_options, build_machine_add_args
        opts, errors = parse_qscheduler_options({"backend": "iqm", "machine_name": "VLQ", "iqm_url": "https://vlq.it4i.cz",
                                                 "iqm_device": "star24", "iqm_token": "secret"}, "x")
        self.assertEqual(errors, [])
        args = build_machine_add_args(opts)
        i = args.index("iqm")
        self.assertIn("--machine-name", args[i:])
        self.assertIn("--token", args[i:])
        self.assertNotIn("--notify-url", args)

    def test_cluster_custom_configuration(self):
        from heappe_ui.view.qscheduler_deploy import parse_qscheduler_options, build_cluster_custom_configuration
        opts, _ = parse_qscheduler_options({"port": "4301", "store_token_in_vault": True}, "x")
        cfg, toggles = build_cluster_custom_configuration(opts, "tok", "6.5.2")
        self.assertEqual(cfg["QSchedulerPort"], "4301")
        self.assertEqual(cfg["QSchedulerHost"], "qscheduler-x")
        self.assertEqual(cfg["EnableCallback"], "true")
        self.assertEqual(cfg["ClusterCallbackNotifyToken"], "tok")
        self.assertTrue(toggles["ClusterCallbackNotifyToken"])

    def test_redact_args(self):
        from heappe_ui.view.qscheduler_deploy import redact_args
        out = redact_args(["-e", "DATABASE_URL=postgres://u:pw@h/db", "--token", "abc", "-e", "POSTGRES_PASSWORD=x"])
        joined = " ".join(out)
        self.assertNotIn("pw@", joined)
        self.assertNotIn("abc", joined)
        self.assertNotIn("PASSWORD=x", joined)

    def test_parse_serve_port(self):
        from heappe_ui.view.qscheduler_deploy import _parse_serve_port
        self.assertEqual(_parse_serve_port(["serve", "--port", "4305"]), 4305)
        self.assertEqual(_parse_serve_port(["serve"]), 4300)

    @mock.patch("heappe_ui.view.qscheduler_deploy.threading.Thread")
    @mock.patch("heappe_ui.view.qscheduler_deploy._container_exists", return_value=False)
    def test_setup_view_rejects_old_heappe(self, _exists, _thread):
        import json as _json
        from heappe_ui.view.qscheduler_deploy import setup_qscheduler_view
        request = RequestFactory().post("/clusters/setup-qscheduler/", data=_json.dumps({}), content_type="application/json")
        request.user = User.objects.create_user(username="qs_old", password="p")
        request.session = {"chosen_instance": "test", "middleware_deployed_version": "6.4.0"}
        response = setup_qscheduler_view(request)
        self.assertEqual(response.status_code, 400)
        _thread.assert_not_called()


class QSchedulerManageTests(TestCase):
    """Update-from-git / undeploy helpers for QScheduler instances deployed by this tool."""

    INFO = {"Id": "abcdef1234567890", "Name": "/qs-1",
            "Config": {"Image": "qscheduler:latest", "Cmd": ["serve", "--port", "4301"],
                       "Env": ["DATABASE_URL=postgres://u:pw@qs-1-pgsql:5432/db", "PATH=/usr/bin"],
                       "Labels": {"com.docker.compose.service": "qscheduler"}},
            "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"},
                           "PortBindings": {"4301/tcp": [{"HostIp": "127.0.0.1", "HostPort": "14301"}]}},
            "NetworkSettings": {"Networks": {"qs-1_db_net": {"Aliases": ["qs-1", "abcdef123456"]},
                                             "inst_external_network": {"Aliases": ["qs-1"]}}}}

    def test_parse_manage_options(self):
        from heappe_ui.view.qscheduler_deploy import parse_manage_options
        opts, errors = parse_manage_options({"action": "undeploy", "instance": "qs-1"})
        self.assertEqual(errors, [])
        self.assertTrue(opts['remove_clusters'])
        self.assertFalse(opts['remove_data'])
        _, errors = parse_manage_options({"action": "update", "instance": "qs-1", "repo": "file:///etc"})
        self.assertTrue(errors)
        _, errors = parse_manage_options({"action": "drop", "instance": ""})
        self.assertEqual(len(errors), 2)

    def test_recreate_args_keep_configuration(self):
        from heappe_ui.view import qscheduler_deploy as q
        internal = {"qs-1_db_net": True, "inst_external_network": False}
        with mock.patch.object(q, "_network_is_internal", side_effect=lambda n: internal[n]):
            args, nets, port = q.recreate_args_from_inspect(self.INFO, "qscheduler:new", {"qscheduler.branch": "v2"})
        self.assertEqual(port, 4301)
        self.assertEqual(nets[0][0], "inst_external_network")       # egress-capable network first
        self.assertIn("127.0.0.1:14301:4301", args)
        self.assertIn("DATABASE_URL=postgres://u:pw@qs-1-pgsql:5432/db", args)
        self.assertFalse(any(a.startswith("PATH=") for a in args))
        self.assertIn("qscheduler.branch=v2", args)
        self.assertIn("--health-cmd", args)
        self.assertEqual(args[-4:], ["qscheduler:new", "serve", "--port", "4301"])
        self.assertNotIn("abcdef123456", sum((a for _, a in nets), []))


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
        self.assertIn("core_dev_default_develop", content)

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

