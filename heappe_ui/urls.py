from django.urls import path
from . import views

urlpatterns = [
    # Index
    path('', views.index, name='index'),

    path('home/', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile_view'),
    path('profile/generate-session-code/', views.generate_session_code_view, name='generate_session_code_view'),
    path('dashboard/', views.dashboard_view, name='dashboard_view'),
    path('dashboard/health-partial/', views.dashboard_health_partial, name='dashboard_health_partial'),
    path('dashboard/metrics-partial/', views.dashboard_metrics_partial, name='dashboard_metrics_partial'),
    path('dashboard/jobs-distribution-partial/', views.dashboard_jobs_distribution_partial, name='dashboard_jobs_distribution_partial'),
    path('dashboard/jobs-history-partial/', views.dashboard_jobs_history_partial, name='dashboard_jobs_history_partial'),

    path("deploy/", views.deploy_view, name="deploy_view"),
    path("deploy/<str:instance_name>/", views.deploy_view, name="deploy_view"),
    path("deploy/<str:instance_name>/delete/", views.deploy_delete_instance, name="deploy_delete_instance"),
    path("deploy/<str:instance_name>/rename/", views.deploy_rename_instance, name="deploy_rename_instance"),
    path("deploy/<str:instance_name>/config/", views.instance_config_view, name="instance_config_view"),
    path("deploy/<str:instance_name>/update-status/", views.update_status_view, name="update_status"),
    path("deploy/<str:instance_name>/telemetry/toggle/", views.toggle_telemetry_view, name="toggle_telemetry"),
    path('chose-instance/', views.chose_instance_view, name='chose_instance_view'),
    path('reconnect/', views.reconnect_view, name='reconnect_view'),
    path('container/<str:container_id>/file/<str:action>/', views.handle_file_action, name='container_file_action'),

    # Clusters
    path('clusters/', views.cluster_list, name='cluster_list'),
    path('clusters/<int:cluster_id>/', views.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/<int:tab>', views.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/delete/', views.cluster_delete, name='cluster_delete'),
    path('clusters/<int:cluster_id>/export/', views.cluster_export, name='cluster_export'),
    path('clusters/import/', views.cluster_import, name='cluster_import'),
    path('clusters/new/', views.cluster_create, name='cluster_create'),
    path('clusters/setup-slurm/', views.setup_slurm_view, name='setup_slurm'),
    path('clusters/setup-slurm-status/', views.setup_slurm_status_view, name='setup_slurm_status'),
    path('clusters/setup-qscheduler/', views.setup_qscheduler_view, name='setup_qscheduler'),
    path('clusters/setup-qscheduler-status/', views.setup_qscheduler_status_view, name='setup_qscheduler_status'),
    path('clusters/setup-qscheduler-defaults/', views.setup_qscheduler_defaults_view, name='setup_qscheduler_defaults'),
    path('clusters/qscheduler-manage/', views.qscheduler_manage_view, name='qscheduler_manage'),

    # Queues
    path('queues/', views.queues_view, name='queues_view'),
    path('queues/new/<int:cluster_id>', views.queue_create, name='queue_create'),
    path('queues/<int:queue_id>/', views.queue_detail, name='queue_detail'),
    path('queues/<int:queue_id>/delete/', views.queue_delete, name='queue_delete'),
    path('queue-groups/', views.queue_groups, name='queue_groups'),
    path('queue-groups/<int:group_id>/', views.queue_group_detail, name='queue_group_detail'),
    path('queue-groups/<int:group_id>/modify/', views.queue_group_modify, name='queue_group_modify'),
    path('queue-groups/new/', views.queue_group_create, name='queue_group_create'),
    path('accounting/<int:project_id>', views.accounting_view, name='accounting'),

    # File transfer methods
    path('file-transfer-methods/new/', views.file_transfer_method_create, name='file_transfer_method_create'),

    # Aggregations
    path('aggregations/new/', views.aggregation_create, name='aggregation_create'),

    # Projects
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<int:project_id>/', views.project_detail, name='project_detail'),
    path('projects/assign/', views.project_assign_to_cluster, name='project_assign_to_cluster'),
    path('projects/unassign/<int:project_id>', views.delete_assignment, name='delete_assignment'),
    path('projects/', views.project_list, name='project_list'),
    path('projects/<int:project_id>/subprojects/create/', views.create_subproject, name='create_subproject'),
    path('projects/<int:project_id>/subprojects/<int:subproject_id>/modify/', views.modify_subproject, name='modify_subproject'),
    path('projects/<int:project_id>/subprojects/<int:subproject_id>/delete/', views.delete_subproject, name='delete_subproject'),
    path('submit-test-job/<int:command_template_id>', views.submit_job_view, name="submit_job_view"),
    path('job-status/<int:job_id>', views.job_status_view, name="job_status_view"),
    path('job-status/<int:job_id>/partial/', views.job_status_partial_view, name="job_status_partial"),
    path('job-status/<int:job_id>/file/', views.download_job_file_view, name="download_job_file"),
    path('job-live-details/<int:job_id>/', views.job_live_details_partial, name='job_live_details_partial'),

    # Command Templates
    path('command-templates/<int:project_id>/new/', views.command_template_create, name='command_template_create'),
    path('command-templates/<int:command_template_id>/', views.command_template_detail, name='command_template_detail'),
    path('command-templates/<int:command_template_id>/modify/', views.command_template_modify, name='command_template_modify'),
    path('command-templates/<int:command_template_id>/delete/', views.command_template_delete, name='command_template_delete'),
    path('command-templates/<int:command_template_id>/copy/', views.command_template_copy, name='command_template_copy'),


    path('instances/', views.instance_credentials_list, name='instance_credentials_list'),
    path('instances/<int:pk>/choose/', views.instance_credentials_list, name='instance_credentials_list'),
    path('instances/create/', views.instance_credentials_create, name='instance_credentials_create'),
    path('instances/<int:pk>/edit/', views.instance_credentials_edit, name='instance_credentials_edit'),
    path('instances/<int:pk>/delete/', views.instance_credentials_delete, name='instance_credentials_delete'),
    path('instances/<int:pk>/health/', views.instance_health_check_api, name='instance_health_check_api'),

    path('instances/choose/', views.chose_instance_view, name='chose_instance_view'),

    path('api/deploy-direct/', views.trigger_deployment_direct, name='trigger_deployment_direct'),
    path('api/system-update-status/', views.system_update_status_api, name='system_update_status_api'),
    path('fetch-branches/', views.fetch_repo_branches, name='fetch_branches'),

    path("logs/", views.log_viewer_view, name="logs"),
    path("logs/context/", views.logs_context_api, name="logs_context_api"),
    path('logs/<str:container_id>/', views.container_logs_view, name='container_logs'),
    path("fetch-new-logs/", views.fetch_new_logs, name="fetch_new_logs"),
    path('vault/unseal/', views.unseal_vault_api, name='unseal_vault_api'),

    path('api/check-updates/', views.check_for_updates, name='check_updates'),
    path('api/heappe-check/<str:min_version>/', views.heappe_check_api, name='heappe_check_api'),

    # Adaptor Users
    path('adaptor_users/new/', views.adaptor_user_create, name='adaptor_user_create'),
    path('adaptor_users/<str:adaptor_user_username>/', views.adaptor_user_detail, name='adaptor_user_detail'),
    path('adaptor_users/unassign/<str:adaptor_user_username>/', views.adaptor_user_unassign_from_project, name='adaptor_user_unassign_from_project'),
    path('adaptor_users/assign/<str:adaptor_user_username>/', views.adaptor_user_assign_to_project, name='adaptor_user_assign_to_project'),
    path('adaptor_users/assign-system-role/<str:adaptor_user_username>/', views.adaptor_user_assign_system_role, name='adaptor_user_assign_system_role'),
    path('adaptor_users/remove-system-role/<str:adaptor_user_username>/', views.adaptor_user_remove_system_role, name='adaptor_user_remove_system_role'),
    path('adaptor_users/toggle-block/<str:adaptor_user_username>/', views.adaptor_user_toggle_block_status, name='adaptor_user_toggle_block_status'),
    # urls.py
    path('manage-external-users/', views.manage_project_adaptor_users, name='manage_project_adaptor_users_base'),
    path('manage-external-users/<int:project_id>/', views.manage_project_adaptor_users,
         name='manage_project_adaptor_users'),
    path('api/invalidate-cache/', views.invalidate_cache_api, name='invalidate_cache_api'),
    path('database-backups/', views.database_backups, name='database_backups'),
    path('migration-package/', views.migration_package_view, name='migration_package'),
    path('migration-package/export/', views.export_migration_package, name='export_migration_package'),
    path('migration-package/import/', views.import_migration_package, name='import_migration_package'),
    path('report-error/', views.report_error_view, name='report_error_view'),
    path('interactive-docs/', views.interactive_docs_view, name='interactive_docs_view'),
    path('integration/', views.api_integration_view, name='api_integration_view'),
    path('integration/execute/', views.execute_api_call, name='execute_api_call'),


    # Admin Users Management & Decrypt view
    path('admin-users/', views.admin_users_list, name='admin_users_list'),
    path('admin-users/create/', views.admin_users_create, name='admin_users_create'),
    path('admin-users/<int:user_id>/edit/', views.admin_users_edit, name='admin_users_edit'),
    path('admin-users/<int:user_id>/password/', views.admin_users_password, name='admin_users_password'),
    path('admin-users/<int:user_id>/delete/', views.admin_users_delete, name='admin_users_delete'),
    path('decrypt/', views.decrypt_credentials_view, name='decrypt_credentials_view'),

    # Jaeger Tracing Natively
    path('jaeger/', views.jaeger_page, name='jaeger_page'),
    path('jaeger-proxy/', views.jaeger_proxy, name='jaeger_proxy_root'),
    path('jaeger-proxy/<path:path>', views.jaeger_proxy, name='jaeger_proxy'),

    # Telemetry & Monitoring Dashboard (v6.5.0+)
    path('monitoring/jobs/', views.admin_jobs_monitoring_view, name='admin_jobs_monitoring_view'),
    path('monitoring/telemetry/', views.external_services_telemetry_view, name='external_services_telemetry_view'),
    path('monitoring/telemetry/live-status/', views.external_services_live_status_api, name='external_services_live_status_api'),
    path('monitoring/telemetry/statistics/', views.external_services_statistics_api, name='external_services_statistics_api'),
    path('monitoring/telemetry/report/', views.external_services_report_api, name='external_services_report_api'),
    path('monitoring/telemetry/job/<int:job_id>/logs/', views.job_external_service_logs_api, name='job_external_service_logs_api'),

    # Quantum & QScheduler Management (v6.5.0+)
    path('clusters/<int:cluster_id>/quantum/architecture/', views.cluster_quantum_architecture_api, name='cluster_quantum_architecture_api'),
    path('clusters/<int:cluster_id>/quantum/calibration/', views.cluster_quantum_calibration_api, name='cluster_quantum_calibration_api'),
    path('clusters/<int:cluster_id>/qscheduler/sessions/', views.qscheduler_sessions_api, name='qscheduler_sessions_api'),
    path('clusters/qscheduler/sessions/open/', views.qscheduler_open_session_api, name='qscheduler_open_session_api'),
    path('clusters/qscheduler/sessions/<int:session_id>/close/', views.qscheduler_close_session_api, name='qscheduler_close_session_api'),
    path('clusters/qscheduler/tasks/<int:task_id>/result/', views.qscheduler_task_result_api, name='qscheduler_task_result_api'),
]