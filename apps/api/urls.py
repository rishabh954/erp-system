from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
from .explorer_view import APIExplorerView

from . import views

router = DefaultRouter()

# CRM
router.register(r'crm/leads', views.LeadViewSet, basename='lead')
router.register(r'crm/customers', views.CustomerViewSet, basename='customer')

# Sales
router.register(r'sales/quotations', views.QuotationViewSet, basename='quotation')
router.register(r'sales/orders', views.SalesOrderViewSet, basename='salesorder')
router.register(r'sales/invoices', views.InvoiceViewSet, basename='invoice')

# Purchase
router.register(r'purchase/vendors', views.VendorViewSet, basename='vendor')
router.register(r'purchase/orders', views.PurchaseOrderViewSet, basename='purchaseorder')
router.register(r'purchase/bills', views.BillViewSet, basename='bill')

# Inventory
router.register(r'inventory/products', views.ProductViewSet, basename='product')
router.register(r'inventory/warehouses', views.WarehouseViewSet, basename='warehouse')

# HRMS
router.register(r'hrms/employees', views.EmployeeViewSet, basename='employee')
router.register(r'hrms/leaves', views.LeaveRequestViewSet, basename='leaverequest')

# Manufacturing
router.register(r'manufacturing/orders', views.ManufacturingOrderViewSet, basename='manufacturingorder')
router.register(r'manufacturing/boms', views.BOMViewSet, basename='bom')

app_name = 'api'

urlpatterns = [
    # JWT Auth endpoints
    path('auth/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/token/verify/', TokenVerifyView.as_view(), name='token_verify'),

    # OpenAPI Schema
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('schema/swagger/', SpectacularSwaggerView.as_view(url_name='api:schema'), name='swagger-ui'),
    path('schema/redoc/', SpectacularRedocView.as_view(url_name='api:schema'), name='redoc'),

    # Internal API Explorer UI
    path('explorer/', APIExplorerView.as_view(), name='explorer'),

    # All registered viewset routes
    path('', include(router.urls)),
]
