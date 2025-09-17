from django.urls import path
from . import views

urlpatterns = [
    # Index
    path('', views.index, name='index'),

    path('home/', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile_view'),
    path('dashboard/', views.dashboard_view, name='dashboard_view'),
    path("logs/", views.logs_view, name="logs"),

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

    # Command Templates
    path('command-templates/<int:project_id>/new/', views.command_template_create, name='command_template_create'),
    path('command-templates/<int:command_template_id>/', views.command_template_detail, name='command_template_detail'),
    path('command-templates/<int:command_template_id>/modify/', views.command_template_modify, name='command_template_modify'),

    path('update-app/', views.update_app, name='update_app'),
]
