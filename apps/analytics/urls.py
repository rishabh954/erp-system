"""Analytics / Reporting Engine URLs"""
from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    # Dashboard
    path('', views.AnalyticsDashboardView.as_view(), name='dashboard'),

    # Report Builder
    path('builder/', views.ReportBuilderView.as_view(), name='builder'),

    # Saved Reports & Executions
    path('reports/', views.SavedReportsListView.as_view(), name='saved_reports'),
    path('reports/bulk-delete/', views.ReportBulkDeleteView.as_view(), name='bulk_delete'),
    path('executions/', views.ExecutionLogListView.as_view(), name='execution_log'),
    path('reports/<uuid:pk>/', views.ReportDetailView.as_view(), name='report_detail'),
    path('reports/<uuid:pk>/delete/', views.ReportDeleteView.as_view(), name='report_delete'),

    # Export from saved report
    path('reports/<uuid:pk>/export/<str:fmt>/', views.ReportExportView.as_view(), name='report_export'),

    # Quick export (no saved report)
    path('export/<str:fmt>/', views.QuickExportView.as_view(), name='quick_export'),

    # JSON API for chart data
    path('reports/<uuid:pk>/data/', views.ReportDataAPIView.as_view(), name='report_data'),

    # Module fields
    path('api/fields/', views.ModuleFieldsAPIView.as_view(), name='api_fields'),

    # Scheduling
    path('reports/<uuid:pk>/schedule/', views.ScheduleReportView.as_view(), name='schedule_report'),
    path('schedules/<uuid:pk>/delete/', views.ScheduleDeleteView.as_view(), name='schedule_delete'),

    # Legacy API endpoints (backward compat)
    path('api/generate/', views.GenerateReportAPIView.as_view(), name='api_generate_report'),
    path('api/fields/legacy/', views.GetModuleFieldsAPIView.as_view(), name='api_get_fields'),
]
