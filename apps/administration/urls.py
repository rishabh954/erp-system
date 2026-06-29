from django.urls import path
from . import views
from . import security_views
from . import integration_views

app_name = 'administration'

urlpatterns = [
    # Dashboard
    path('', views.AdminDashboardView.as_view(), name='dashboard'),
    path('app-store/', views.AppStoreView.as_view(), name='app_store'),

    # Organization
    path('designations/', views.DesignationListView.as_view(), name='designations'),
    path('designations/<uuid:pk>/delete/', views.DesignationDeleteView.as_view(), name='designation_delete'),
    path('number-series/', views.NumberSeriesListView.as_view(), name='number_series'),
    path('approval-matrix/', views.ApprovalMatrixListView.as_view(), name='approval_matrix'),
    path('approval-matrix/<uuid:pk>/delete/', views.ApprovalMatrixDeleteView.as_view(), name='approval_matrix_delete'),
    
    # Users
    path('pending-approvals/', views.PendingUserApprovalListView.as_view(), name='pending_approvals'),
    path('pending-approvals/<uuid:pk>/action/', views.PendingUserApprovalActionView.as_view(), name='pending_approvals_action'),

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
    path('integrations/', integration_views.IntegrationsDashboardView.as_view(), name='integrations_dashboard'),
    path('integrations/setup/<str:provider>/', integration_views.GenericIntegrationSetupView.as_view(), name='integration_setup'),
    path('integrations/oauth/<str:provider>/', integration_views.OAuthMockConnectView.as_view(), name='oauth_connect'),
    path('integrations/webhooks/', integration_views.WebhookManagementView.as_view(), name='webhooks'),
    path('integrations/import/', integration_views.DataImportView.as_view(), name='data_import'),
    path('backup-restore/', views.BackupRestoreView.as_view(), name='backup_restore'),
    
    # Integrations & API
    path('api-keys/', security_views.APIKeyManagementView.as_view(), name='api_keys'),
    path('api-keys/<uuid:pk>/revoke/', security_views.APIKeyRevokeView.as_view(), name='api_key_revoke'),
    path('backup-schedule/', security_views.BackupSchedulerView.as_view(), name='backup_schedule'),

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
