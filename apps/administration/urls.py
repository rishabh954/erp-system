from django.urls import path
from . import views

app_name = 'administration'

urlpatterns = [
    # Dashboard
    path('', views.AdminDashboardView.as_view(), name='dashboard'),

    # Organization
    path('designations/', views.DesignationListView.as_view(), name='designations'),
    path('designations/<uuid:pk>/delete/', views.DesignationDeleteView.as_view(), name='designation_delete'),
    path('number-series/', views.NumberSeriesListView.as_view(), name='number_series'),
    path('approval-matrix/', views.ApprovalMatrixListView.as_view(), name='approval_matrix'),
    path('approval-matrix/<uuid:pk>/delete/', views.ApprovalMatrixDeleteView.as_view(), name='approval_matrix_delete'),

    # Communication
    path('email-config/', views.EmailConfigView.as_view(), name='email_config'),
    path('email-config/<uuid:pk>/delete/', views.EmailConfigDeleteView.as_view(), name='email_config_delete'),
    path('email-config/<uuid:pk>/test/', views.EmailConfigTestView.as_view(), name='email_config_test'),
    path('sms-config/', views.SMSConfigView.as_view(), name='sms_config'),
    path('whatsapp-config/', views.WhatsAppConfigView.as_view(), name='whatsapp_config'),
    path('notifications/', views.NotificationCenterView.as_view(), name='notifications'),

    # Documents
    path('document-templates/', views.DocumentTemplateListView.as_view(), name='document_templates'),

    # Data
    path('import-export/', views.DataImportView.as_view(), name='import_export'),
    path('backup-restore/', views.BackupRestoreView.as_view(), name='backup_restore'),

    # Logs
    path('audit-logs/', views.AuditLogView.as_view(), name='audit_logs'),
    path('audit-logs/<uuid:pk>/detail/', views.AuditLogDetailView.as_view(), name='audit_log_detail'),
    path('activity-logs/', views.ActivityLogView.as_view(), name='activity_logs'),

    # API & Integrations
    path('api-management/', views.APIManagementView.as_view(), name='api_management'),
    path('integrations/', views.IntegrationCenterView.as_view(), name='integrations'),

    # Builder
    path('dashboard-builder/', views.DashboardBuilderView.as_view(), name='dashboard_builder'),
    path('report-builder/', views.ReportBuilderView.as_view(), name='report_builder'),

    # System
    path('system-settings/', views.SystemSettingsView.as_view(), name='system_settings'),
]
