from django.urls import path
from .views import (
    AssetListView, AssetDetailView, AssetCreateView,
    ScheduleMaintenanceView, CompleteMaintenanceView,
)
app_name = 'assets'
urlpatterns = [
    path('', AssetListView.as_view(), name='list'),
    path('create/', AssetCreateView.as_view(), name='create'),
    path('<uuid:pk>/', AssetDetailView.as_view(), name='detail'),
    path('<uuid:pk>/maintenance/', ScheduleMaintenanceView.as_view(), name='schedule_maintenance'),
    path('maintenance/<uuid:maint_pk>/complete/', CompleteMaintenanceView.as_view(), name='complete_maintenance'),
]
