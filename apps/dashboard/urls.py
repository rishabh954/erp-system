from django.urls import path
from .views import (
    DashboardIndexView, SalesDashboardView, FinanceDashboardView, PurchaseDashboardView,
    WarehouseDashboardView, HRDashboardView, CRMDashboardView, ProjectDashboardView,
    HelpdeskDashboardView, ExecutiveKPIDashboardView, CalendarView, CalendarEventsAPIView
)

app_name = 'dashboard'

urlpatterns = [
    path('', DashboardIndexView.as_view(), name='index'),
    path('sales/', SalesDashboardView.as_view(), name='sales'),
    path('finance/', FinanceDashboardView.as_view(), name='finance'),
    path('purchase/', PurchaseDashboardView.as_view(), name='purchase'),
    path('warehouse/', WarehouseDashboardView.as_view(), name='warehouse'),
    path('hr/', HRDashboardView.as_view(), name='hr'),
    path('crm/', CRMDashboardView.as_view(), name='crm'),
    path('projects/', ProjectDashboardView.as_view(), name='projects'),
    path('helpdesk/', HelpdeskDashboardView.as_view(), name='helpdesk'),
    path('executive-kpi/', ExecutiveKPIDashboardView.as_view(), name='executive_kpi'),
    path('calendar/', CalendarView.as_view(), name='calendar'),
    path('calendar/events/', CalendarEventsAPIView.as_view(), name='calendar_events'),
]
