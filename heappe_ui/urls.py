from django.urls import path
from heappe_ui.view import (
    home, auth, backup, logs, system_update, credentials, project,
    queue, clusters, aggregations, utils, deploy, accounting,
    file_transfer_method, command_template, adaptor_user
)

urlpatterns = [
    # Index
    path('', home.index, name='index'),

    path('home/', home.home, name='home'),
    path('login/', utils.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('profile/', auth.profile_view, name='profile_view'),
    path('dashboard/', home.dashboard_view, name='dashboard_view'),

    path("deploy/", deploy.deploy_view, name="deploy_view"),
    path("deploy/<str:instance_name>/", deploy.deploy_view, name="deploy_view"),
    path('chose-instance/', home.chose_instance_view, name='chose_instance_view'),
    path('reconnect/', auth.reconnect_view, name='reconnect_view'),
    path('container/<str:container_id>/file/<str:action>/', deploy.handle_file_action, name='container_file_action'),

    # Clusters
    path('clusters/', clusters.cluster_list, name='cluster_list'),
    path('clusters/<int:cluster_id>/', clusters.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/<int:tab>', clusters.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/delete/', clusters.cluster_delete, name='cluster_delete'),
    path('clusters/new/', clusters.cluster_create, name='cluster_create'),

    # Queues
    path('queues/', queue.queues_view, name='queues_view'),
    path('queues/new/<int:cluster_id>', queue.queue_create, name='queue_create'),
    path('queues/<int:queue_id>/', queue.queue_detail, name='queue_detail'),
    path('queues/<int:queue_id>/delete/', queue.queue_delete, name='queue_delete'),
    path('queue-groups/', queue.queue_groups, name='queue_groups'),
    path('queue-groups/<int:group_id>/', queue.queue_group_detail, name='queue_group_detail'),
    path('queue-groups/<int:group_id>/modify/', queue.queue_group_modify, name='queue_group_modify'),
    path('queue-groups/new/', queue.queue_group_create, name='queue_group_create'),
    path('accounting/<int:project_id>', accounting.accounting_view, name='accounting'),

    # File transfer methods
    path('file-transfer-methods/new/', file_transfer_method.file_transfer_method_create, name='file_transfer_method_create'),

    # Aggregations
    path('aggregations/new/', aggregations.aggregation_create, name='aggregation_create'),

    # Projects
    path('projects/new/', project.project_create, name='project_create'),
    path('projects/<int:project_id>/', project.project_detail, name='project_detail'),
    path('projects/assign/', project.project_assign_to_cluster, name='project_assign_to_cluster'),
    path('projects/unassign/<int:project_id>', project.delete_assignment, name='delete_assignment'),
    path('projects/', project.project_list, name='project_list'),
    path('submit-test-job/<int:command_template_id>', project.submit_job_view, name="submit_job_view"),
    path('job-status/<int:job_id>', project.job_status_view, name="job_status_view"),
    path('job-status/<int:job_id>/task/<int:task_id>/file/<str:file_name>/', project.job_task_file_view, name="job_task_file_view"),

    # Command Templates
    path('command-templates/<int:project_id>/new/', command_template.command_template_create, name='command_template_create'),
    path('command-templates/<int:command_template_id>/', command_template.command_template_detail, name='command_template_detail'),
    path('command-templates/<int:command_template_id>/modify/', command_template.command_template_modify, name='command_template_modify'),
    path('command-templates/<int:command_template_id>/delete/', command_template.command_template_delete, name='command_template_delete'),

    path('update-app/', system_update.update_app, name='update_app'),

    path('instances/', credentials.instance_credentials_list, name='instance_credentials_list'),
    path('instances/<int:pk>/choose/', credentials.instance_credentials_list, name='instance_credentials_list'),
    path('instances/create/', credentials.instance_credentials_create, name='instance_credentials_create'),
    path('instances/<int:pk>/edit/', credentials.instance_credentials_edit, name='instance_credentials_edit'),
    path('instances/<int:pk>/delete/', credentials.instance_credentials_delete, name='instance_credentials_delete'),
    path('instances/choose/', home.chose_instance_view, name='chose_instance_view'),

    path('update/', system_update.update_server_page, name='update_server_page'),
    path('api/check-repo/', system_update.check_repo_and_fetch_branches, name='check_repo_and_fetch_branches'),
    path('api/deploy-direct/', system_update.trigger_deployment_direct, name='trigger_deployment_direct'),
    path('fetch-branches/', deploy.fetch_repo_branches, name='fetch_branches'),

    path("logs/", logs.log_viewer_view, name="logs"),
    path('logs/<str:container_id>/', deploy.container_logs_view, name='container_logs'),
    path("fetch-new-logs/", logs.fetch_new_logs, name="fetch_new_logs"),

    path('api/check-updates/', system_update.check_for_updates, name='check_updates'),
    path('api/heappe-check/<str:min_version>/', system_update.heappe_check_api, name='heappe_check_api'),

    # Backup & Restore
    path('backup-restore/', backup.backup_restore_view, name='backup_restore'),

    # Adaptor Users
    path('adaptor_users/new/', adaptor_user.adaptor_user_create, name='adaptor_user_create'),
    path('adaptor_users/<str:adaptor_user_username>/', adaptor_user.adaptor_user_detail, name='adaptor_user_detail'),
    path('adaptor_users/unassign/<str:adaptor_user_username>/', adaptor_user.adaptor_user_unassign_from_project, name='adaptor_user_unassign_from_project'),
    path('adaptor_users/assign/<str:adaptor_user_username>/', adaptor_user.adaptor_user_assign_to_project, name='adaptor_user_assign_to_project'),
    # urls.py
    path('manage-external-users/', project.manage_project_adaptor_users, name='manage_project_adaptor_users_base'),
    path('manage-external-users/<int:project_id>/', project.manage_project_adaptor_users,
         name='manage_project_adaptor_users'),
]
