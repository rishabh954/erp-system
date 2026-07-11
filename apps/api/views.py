"""
ERP REST API ViewSets — Phase 13
All viewsets are company-scoped, with filtering, search & ordering.
"""

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from core.permissions import HasModulePermission

from . import serializers


# ─── Company Mixin ─────────────────────────────────────────────────────────────
class CompanyScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, HasModulePermission]
    required_permission = "api.access"  # Fallback/default
    """Base viewset that automatically filters queryset to the authenticated user's company."""

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]

    def get_company(self):
        return getattr(self.request.user, "company", None)

    def get_queryset(self):
        company = self.get_company()
        if company:
            return self.queryset.filter(company=company)
        return self.queryset.none()

    def perform_create(self, serializer):
        serializer.save(company=self.get_company())


# ─── CRM ──────────────────────────────────────────────────────────────────────
from apps.crm.models import Customer, Lead


@extend_schema(tags=["CRM"])
class LeadViewSet(CompanyScopedViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    queryset = Lead.objects.select_related("assigned_to").all()
    serializer_class = serializers.LeadSerializer
    filterset_fields = ["status", "source", "assigned_to"]
    search_fields = ["first_name", "last_name", "email", "company_name"]
    ordering_fields = ["created_at", "status"]
    ordering = ["-created_at"]


@extend_schema(tags=["CRM"])
class CustomerViewSet(CompanyScopedViewSet):
    required_permission = "crm.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "crm.create"
            elif request.method in ["PUT", "PATCH"]:
                return "crm.update"
            elif request.method == "DELETE":
                return "crm.delete"
        return self.required_permission
    queryset = Customer.objects.all()
    serializer_class = serializers.CustomerSerializer
    filterset_fields = ["customer_type", "is_active"]
    search_fields = ["name", "email", "customer_code", "tax_id"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]


# ─── Sales ────────────────────────────────────────────────────────────────────
from apps.sales.models import Invoice, Quotation, SalesOrder


@extend_schema(tags=["Sales"])
class QuotationViewSet(CompanyScopedViewSet):
    required_permission = "sales.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "sales.create"
            elif request.method in ["PUT", "PATCH"]:
                return "sales.update"
            elif request.method == "DELETE":
                return "sales.delete"
        return self.required_permission
    queryset = Quotation.objects.select_related("customer").all()
    serializer_class = serializers.ErpQuotationSerializer
    filterset_fields = ["status", "customer"]
    search_fields = ["number", "customer__name"]
    ordering_fields = ["created_at", "total"]
    ordering = ["-created_at"]


@extend_schema(tags=["Sales"])
class SalesOrderViewSet(CompanyScopedViewSet):
    required_permission = "sales.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "sales.create"
            elif request.method in ["PUT", "PATCH"]:
                return "sales.update"
            elif request.method == "DELETE":
                return "sales.delete"
        return self.required_permission
    queryset = SalesOrder.objects.select_related("customer").all()
    serializer_class = serializers.ErpSalesOrderSerializer
    filterset_fields = ["status", "customer"]
    search_fields = ["number", "customer__name"]
    ordering_fields = ["order_date", "total", "created_at"]
    ordering = ["-order_date"]


@extend_schema(tags=["Sales"])
class InvoiceViewSet(CompanyScopedViewSet):
    required_permission = "sales.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "sales.create"
            elif request.method in ["PUT", "PATCH"]:
                return "sales.update"
            elif request.method == "DELETE":
                return "sales.delete"
        return self.required_permission
    queryset = Invoice.objects.select_related("customer").all()
    serializer_class = serializers.ErpInvoiceSerializer
    filterset_fields = ["status", "customer"]
    search_fields = ["number", "customer__name"]
    ordering_fields = ["invoice_date", "due_date", "total"]
    ordering = ["-invoice_date"]


# ─── Purchase ─────────────────────────────────────────────────────────────────
from apps.purchase.models import Bill, PurchaseOrder, Vendor


@extend_schema(tags=["Purchase"])
class VendorViewSet(CompanyScopedViewSet):
    required_permission = "purchase.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "purchase.create"
            elif request.method in ["PUT", "PATCH"]:
                return "purchase.update"
            elif request.method == "DELETE":
                return "purchase.delete"
        return self.required_permission
    queryset = Vendor.objects.all()
    serializer_class = serializers.ErpVendorSerializer
    filterset_fields = ["vendor_type"]
    search_fields = ["name", "email", "vendor_code", "tax_id"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]


@extend_schema(tags=["Purchase"])
class PurchaseOrderViewSet(CompanyScopedViewSet):
    required_permission = "purchase.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "purchase.create"
            elif request.method in ["PUT", "PATCH"]:
                return "purchase.update"
            elif request.method == "DELETE":
                return "purchase.delete"
        return self.required_permission
    queryset = PurchaseOrder.objects.select_related("vendor").all()
    serializer_class = serializers.ErpPurchaseOrderSerializer
    filterset_fields = ["status", "vendor"]
    search_fields = ["number", "vendor__name"]
    ordering_fields = ["order_date", "total_amount", "created_at"]
    ordering = ["-order_date"]


@extend_schema(tags=["Purchase"])
class BillViewSet(CompanyScopedViewSet):
    required_permission = "purchase.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "purchase.create"
            elif request.method in ["PUT", "PATCH"]:
                return "purchase.update"
            elif request.method == "DELETE":
                return "purchase.delete"
        return self.required_permission
    queryset = Bill.objects.select_related("vendor").all()
    serializer_class = serializers.ErpBillSerializer
    filterset_fields = ["status", "vendor"]
    search_fields = ["number", "vendor__name"]
    ordering_fields = ["bill_date", "due_date", "total_amount"]
    ordering = ["-bill_date"]


# ─── Inventory ────────────────────────────────────────────────────────────────
from apps.inventory.models import Product, Warehouse


@extend_schema(tags=["Inventory"])
class ProductViewSet(CompanyScopedViewSet):
    required_permission = "inventory.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission
    queryset = Product.objects.select_related("category", "uom").all()
    serializer_class = serializers.ErpProductSerializer
    filterset_fields = ["product_type", "tracking_method", "category"]
    search_fields = ["name", "sku", "barcode"]
    ordering_fields = ["name", "sku", "cost_price", "sale_price", "created_at"]
    ordering = ["name"]


@extend_schema(tags=["Inventory"])
class WarehouseViewSet(CompanyScopedViewSet):
    required_permission = "inventory.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission
    queryset = Warehouse.objects.all()
    serializer_class = serializers.ErpWarehouseSerializer
    filterset_fields: list[str] = []
    search_fields = ["name", "code"]
    ordering_fields = ["name", "code"]
    ordering = ["name"]


# ─── HRMS ─────────────────────────────────────────────────────────────────────
from apps.hrms.models import Employee, LeaveRequest


@extend_schema(tags=["HRMS"])
class EmployeeViewSet(CompanyScopedViewSet):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    queryset = Employee.objects.select_related("department").all()
    serializer_class = serializers.EmployeeSerializer
    filterset_fields = ["department", "status"]
    search_fields = ["first_name", "last_name", "employee_number", "email"]
    ordering_fields = ["first_name", "last_name", "hire_date", "created_at"]
    ordering = ["first_name"]


@extend_schema(tags=["HRMS"])
class LeaveRequestViewSet(CompanyScopedViewSet):
    required_permission = "hrms.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "hrms.create"
            elif request.method in ["PUT", "PATCH"]:
                return "hrms.update"
            elif request.method == "DELETE":
                return "hrms.delete"
        return self.required_permission
    queryset = LeaveRequest.objects.select_related("employee").all()
    serializer_class = serializers.LeaveRequestSerializer
    filterset_fields = ["status", "employee"]
    search_fields = ["employee__first_name", "employee__last_name"]
    ordering_fields = ["start_date", "created_at"]
    ordering = ["-start_date"]


# ─── Manufacturing ────────────────────────────────────────────────────────────
from apps.manufacturing.models import BillOfMaterial, ManufacturingOrder


@extend_schema(tags=["Manufacturing"])
class ManufacturingOrderViewSet(CompanyScopedViewSet):
    required_permission = "manufacturing.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "manufacturing.create"
            elif request.method in ["PUT", "PATCH"]:
                return "manufacturing.update"
            elif request.method == "DELETE":
                return "manufacturing.delete"
        return self.required_permission
    queryset = ManufacturingOrder.objects.select_related("product", "bom").all()
    serializer_class = serializers.ManufacturingOrderSerializer
    filterset_fields = ["status", "product"]
    search_fields = ["number", "product__name"]
    ordering_fields = ["planned_start_date", "created_at"]
    ordering = ["-created_at"]


@extend_schema(tags=["Manufacturing"])
class BOMViewSet(CompanyScopedViewSet):
    required_permission = "manufacturing.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "manufacturing.create"
            elif request.method in ["PUT", "PATCH"]:
                return "manufacturing.update"
            elif request.method == "DELETE":
                return "manufacturing.delete"
        return self.required_permission
    queryset = BillOfMaterial.objects.select_related("product").all()
    serializer_class = serializers.BOMSerializer
    filterset_fields = ["is_active", "product"]
    search_fields = ["number", "product__name"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
