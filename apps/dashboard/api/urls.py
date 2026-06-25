"""Dashboard API URLs"""
from django.urls import path
from ..views import (
    CEODashboardAPIView, HRDashboardAPIView,
    SalesDashboardAPIView, FinanceDashboardAPIView,
    GlobalSearchAPIView,
)

app_name = 'api_dashboard'

urlpatterns = [
    path('ceo/', CEODashboardAPIView.as_view(), name='ceo'),
    path('hr/', HRDashboardAPIView.as_view(), name='hr'),
    path('sales/', SalesDashboardAPIView.as_view(), name='sales'),
    path('finance/', FinanceDashboardAPIView.as_view(), name='finance'),
    path('search/', GlobalSearchAPIView.as_view(), name='search'),
]
