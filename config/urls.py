"""
Enterprise ERP — Root URL Configuration
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # API v1
    path('api/v1/', include([
        path('auth/', include('apps.authentication.api.urls', namespace='api_auth')),
        path('company/', include('apps.company.api.urls', namespace='api_company')),
        path('hrms/', include('apps.hrms.api.urls', namespace='api_hrms')),
        path('crm/', include('apps.crm.api.urls', namespace='api_crm')),
        path('sales/', include('apps.sales.api.urls', namespace='api_sales')),
        path('purchase/', include('apps.purchase.api.urls', namespace='api_purchase')),
        path('inventory/', include('apps.inventory.api.urls', namespace='api_inventory')),  # noqa: E501
        path('accounting/', include('apps.accounting.api.urls', namespace='api_accounting')),  # noqa: E501
        path('projects/', include('apps.projects.api.urls', namespace='api_projects')),
        path('assets/', include('apps.assets.api.urls', namespace='api_assets')),
        path('helpdesk/', include('apps.helpdesk.api.urls', namespace='api_helpdesk')),
        path('documents/', include('apps.documents.api.urls', namespace='api_documents')),  # noqa: E501
        path('notifications/', include('apps.notifications.api.urls', namespace='api_notifications')),  # noqa: E501
        path('workflow/', include('apps.workflow.api.urls', namespace='api_workflow')),
        path('dashboard/', include('apps.dashboard.api.urls', namespace='api_dashboard')),  # noqa: E501
        path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    ])),
]

# Web UI URLs
urlpatterns += [
    path('auth/', include('apps.authentication.urls', namespace='auth')),
    path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),

    # PWA
    path('manifest.json', TemplateView.as_view(template_name='manifest.json', content_type='application/json')),  # noqa: E501
    path('service-worker.js', TemplateView.as_view(template_name='service-worker.js', content_type='application/javascript')),  # noqa: E501
    path('offline/', TemplateView.as_view(template_name='offline.html'), name='offline'),  # noqa: E501

    path('manufacturing/', include('apps.manufacturing.urls', namespace='manufacturing')),  # noqa: E501
    path('api/', include('apps.api.urls', namespace='api')),
    path('portals/', include('apps.portals.urls', namespace='portals')),
    path('administration/', include('apps.administration.urls', namespace='administration')),  # noqa: E501
    path('company/', include('apps.company.urls', namespace='company')),
    path('hrms/', include('apps.hrms.urls', namespace='hrms')),
    path('crm/', include('apps.crm.urls', namespace='crm')),
    path('sales/', include('apps.sales.urls', namespace='sales')),
    path('purchase/', include('apps.purchase.urls', namespace='purchase')),
    path('inventory/', include('apps.inventory.urls', namespace='inventory')),
    path('accounting/', include('apps.accounting.urls', namespace='accounting')),
    path('projects/', include('apps.projects.urls', namespace='projects')),
    path('assets/', include('apps.assets.urls', namespace='assets')),
    path('helpdesk/', include('apps.helpdesk.urls', namespace='helpdesk')),
    path('documents/', include('apps.documents.urls', namespace='documents')),
    path('workflow/', include('apps.workflow.urls', namespace='workflow')),
    path('notifications/', include('apps.notifications.urls', namespace='notifications')),  # noqa: E501
    path('analytics/', include('apps.analytics.urls', namespace='analytics')),
    path('pos/', include('apps.pos.urls', namespace='pos')),
    path('ai/', include('apps.ai.urls', namespace='ai')),
]

# Redirect root to dashboard
from django.views.generic import RedirectView  # noqa: E402

urlpatterns += [path('', RedirectView.as_view(url='/dashboard/', permanent=False))]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

    try:
        import debug_toolbar
        urlpatterns = [path('__debug__/', include(debug_toolbar.urls))] + urlpatterns
    except ImportError:
        pass

# Admin customization
admin.site.site_header = "Enterprise ERP Administration"
admin.site.site_title = "ERP Admin"
admin.site.index_title = "ERP System Control Panel"
