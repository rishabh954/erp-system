"""Sales API URLs"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import InvoiceViewSet, PaymentViewSet, QuotationViewSet, SalesOrderViewSet

app_name = "api_sales"
router = DefaultRouter()
router.register("quotations", QuotationViewSet, basename="quotation")
router.register("orders", SalesOrderViewSet, basename="order")
router.register("invoices", InvoiceViewSet, basename="invoice")
router.register("payments", PaymentViewSet, basename="payment")

urlpatterns = [path("", include(router.urls))]
