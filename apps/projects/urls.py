from django.urls import path
from .views import (
    ProjectListView, ProjectDetailView, ProjectCreateView,
    KanbanBoardView, MyTasksView, TaskCreateView, TaskDetailView,
    TaskMoveView, AddCommentView, LogTimeView,
)
app_name = 'projects'
urlpatterns = [
    path('', ProjectListView.as_view(), name='list'),
    path('create/', ProjectCreateView.as_view(), name='create'),
    path('<uuid:pk>/', ProjectDetailView.as_view(), name='detail'),
    path('<uuid:pk>/kanban/', KanbanBoardView.as_view(), name='kanban'),
    path('my-tasks/', MyTasksView.as_view(), name='my_tasks'),
    path('tasks/create/', TaskCreateView.as_view(), name='task_create'),
    path('tasks/<uuid:pk>/', TaskDetailView.as_view(), name='task_detail'),
    path('tasks/<uuid:pk>/move/', TaskMoveView.as_view(), name='task_move'),
    path('tasks/<uuid:pk>/comment/', AddCommentView.as_view(), name='task_comment'),
    path('tasks/<uuid:pk>/log-time/', LogTimeView.as_view(), name='task_log_time'),
    
    # Agile & Gantt & Risk
    path('sprints/<uuid:pk>/board/', __import__('apps.projects.views', fromlist=['AgileBoardView']).AgileBoardView.as_view(), name='agile_board'),
    path('<uuid:pk>/gantt/data/', __import__('apps.projects.views', fromlist=['ProjectGanttDataView']).ProjectGanttDataView.as_view(), name='gantt_data'),
    path('<uuid:pk>/risks/', __import__('apps.projects.views', fromlist=['ProjectRiskListView']).ProjectRiskListView.as_view(), name='risk_list'),
    path('risks/<uuid:pk>/', __import__('apps.projects.views', fromlist=['ProjectRiskDetailView']).ProjectRiskDetailView.as_view(), name='risk_detail'),
]
