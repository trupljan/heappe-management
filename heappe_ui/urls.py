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

    path("deploy/", views.deploy_view, name="deploy_view"),
    path("deploy/<str:instance_name>/", views.deploy_view, name="deploy_view"),
    path('chose-instance/', views.chose_instance_view, name='chose_instance_view'),
    path('reconnect/', views.reconnect_view, name='reconnect_view'),
    path('container/<str:container_id>/file/<str:action>/', views.handle_file_action, name='container_file_action'),

    # Clusters
    path('clusters/', views.cluster_list, name='cluster_list'),
    path('clusters/<int:cluster_id>/', views.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/<int:tab>', views.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/delete/', views.cluster_delete, name='cluster_delete'),
    path('clusters/new/', views.cluster_create, name='cluster_create'),

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
    path('submit-test-job/<int:command_template_id>', views.submit_job_view, name="submit_job_view"),
    path('job-status/<int:job_id>', views.job_status_view, name="job_status_view"),
    path('job-live-details/<int:job_id>/', views.job_live_details_partial, name='job_live_details_partial'),

    # Command Templates
    path('command-templates/<int:project_id>/new/', views.command_template_create, name='command_template_create'),
    path('command-templates/<int:command_template_id>/', views.command_template_detail, name='command_template_detail'),
    path('command-templates/<int:command_template_id>/modify/', views.command_template_modify, name='command_template_modify'),
    path('command-templates/<int:command_template_id>/delete/', views.command_template_delete, name='command_template_delete'),


    path('instances/', views.instance_credentials_list, name='instance_credentials_list'),
    path('instances/<int:pk>/choose/', views.instance_credentials_list, name='instance_credentials_list'),
    path('instances/create/', views.instance_credentials_create, name='instance_credentials_create'),
    path('instances/<int:pk>/edit/', views.instance_credentials_edit, name='instance_credentials_edit'),
    path('instances/<int:pk>/delete/', views.instance_credentials_delete, name='instance_credentials_delete'),
    path('instances/choose/', views.chose_instance_view, name='chose_instance_view'),

    path('api/deploy-direct/', views.trigger_deployment_direct, name='trigger_deployment_direct'),
    path('fetch-branches/', views.fetch_repo_branches, name='fetch_branches'),

    path("logs/", views.log_viewer_view, name="logs"),
    path("logs/context/", views.logs_context_api, name="logs_context_api"),
    path('logs/<str:container_id>/', views.container_logs_view, name='container_logs'),
    path("fetch-new-logs/", views.fetch_new_logs, name="fetch_new_logs"),

    path('api/check-updates/', views.check_for_updates, name='check_updates'),
    path('api/heappe-check/<str:min_version>/', views.heappe_check_api, name='heappe_check_api'),

    # Adaptor Users
    path('adaptor_users/new/', views.adaptor_user_create, name='adaptor_user_create'),
    path('adaptor_users/<str:adaptor_user_username>/', views.adaptor_user_detail, name='adaptor_user_detail'),
    path('adaptor_users/unassign/<str:adaptor_user_username>/', views.adaptor_user_unassign_from_project, name='adaptor_user_unassign_from_project'),
    path('adaptor_users/assign/<str:adaptor_user_username>/', views.adaptor_user_assign_to_project, name='adaptor_user_assign_to_project'),
    # urls.py
    path('manage-external-users/', views.manage_project_adaptor_users, name='manage_project_adaptor_users_base'),
    path('manage-external-users/<int:project_id>/', views.manage_project_adaptor_users,
         name='manage_project_adaptor_users'),
    path('api/invalidate-cache/', views.invalidate_cache_api, name='invalidate_cache_api'),
]
