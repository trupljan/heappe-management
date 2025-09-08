from django.urls import path
from . import views

urlpatterns = [
    # Index
    path('', views.index, name='index'),

    # Clusters
    path('clusters/', views.cluster_list, name='cluster_list'),
    path('clusters/<int:cluster_id>/', views.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/<int:tab>', views.cluster_detail, name='cluster_detail'),
    path('clusters/<int:cluster_id>/delete/', views.cluster_delete, name='cluster_delete'),

    # Queues
    path('queues/', views.queue_list, name='queue_list'),  # pokud budeš mít seznam
    path('queues/new/', views.queue_create, name='queue_create'),
    path('queues/<int:queue_id>/', views.queue_detail, name='queue_detail'),
    path('queues/<int:queue_id>/delete/', views.queue_delete, name='queue_delete'),

    # File transfer methods
    path('file-transfer-methods/new/', views.file_transfer_method_create, name='file_transfer_method_create'),

    # Aggregations
    path('aggregations/new/', views.aggregation_create, name='aggregation_create'),

    # Projects
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<int:project_id>/', views.project_detail, name='project_detail'),
    path('projects/assign/', views.project_assign_to_cluster, name='project_assign_to_cluster'),

    # Command Templates
    path('command-templates/<int:project_id>/new/', views.command_template_create, name='command_template_create'),
    path('command-templates/<int:command_template_id>/', views.command_template_detail, name='command_template_detail'),
    path('command-templates/<int:command_template_id>/modify/', views.command_template_modify, name='command_template_modify'),

    path('update-app/', views.update_app, name='update_app'),
]
