from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('', views.AnalyticsDashboardView.as_view(), name='dashboard'),
    path('builder/', views.ReportBuilderView.as_view(), name='builder'),
    path('api/generate/', views.GenerateReportAPIView.as_view(), name='api_generate_report'),
    path('api/fields/', views.GetModuleFieldsAPIView.as_view(), name='api_get_fields'),
    path('reports/<int:pk>/delete/', views.ReportDeleteView.as_view(), name='report_delete'),
]
