"""
ERP REST API Serializers — Phase 13
Includes nested read fields and computed properties for all modules.
"""

from rest_framework import serializers

# ─── CRM ──────────────────────────────────────────────────────────────────────
from apps.crm.models import Customer, Lead


class LeadSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = "__all__"
        read_only_fields = ("company", "created_at", "updated_at")

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.get_full_name() if obj.assigned_to else None


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = "__all__"
        read_only_fields = ("company", "created_at", "updated_at")


# ─── Sales ────────────────────────────────────────────────────────────────────
from apps.sales.models import Invoice, Quotation, SalesOrder


class ErpQuotationSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Quotation
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None


class ErpSalesOrderSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = SalesOrder
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None


class ErpInvoiceSerializer(serializers.ModelSerializer):
    customer_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Invoice
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None


# ─── Purchase ─────────────────────────────────────────────────────────────────
from apps.purchase.models import Bill, PurchaseOrder, Vendor


class ErpVendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = "__all__"
        read_only_fields = ("company", "created_at", "updated_at")


class ErpPurchaseOrderSerializer(serializers.ModelSerializer):
    vendor_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_vendor_name(self, obj):
        return obj.vendor.name if obj.vendor else None


class ErpBillSerializer(serializers.ModelSerializer):
    vendor_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Bill
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_vendor_name(self, obj):
        return obj.vendor.name if obj.vendor else None


# ─── Inventory ────────────────────────────────────────────────────────────────
from apps.inventory.models import Product, Warehouse


class ErpProductSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    uom_code = serializers.SerializerMethodField()
    tracking_display = serializers.CharField(
        source="get_tracking_method_display", read_only=True
    )

    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = ("company", "created_at", "updated_at")

    def get_category_name(self, obj):
        return obj.category.name if obj.category else None

    def get_uom_code(self, obj):
        return obj.uom.abbreviation if obj.uom else None


class ErpWarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = "__all__"
        read_only_fields = ("company", "created_at", "updated_at")


# ─── HRMS ─────────────────────────────────────────────────────────────────────
from apps.hrms.models import Employee, LeaveRequest


class EmployeeSerializer(serializers.ModelSerializer):
    department_name = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = "__all__"
        read_only_fields = ("company", "employee_number", "created_at", "updated_at")

    def get_department_name(self, obj):
        return obj.department.name if obj.department else None

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = "__all__"
        read_only_fields = ("company", "created_at", "updated_at")

    def get_employee_name(self, obj):
        return (
            f"{obj.employee.first_name} {obj.employee.last_name}".strip()
            if obj.employee
            else None
        )


# ─── Manufacturing ────────────────────────────────────────────────────────────
from apps.manufacturing.models import BillOfMaterial, ManufacturingOrder


class ManufacturingOrderSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = ManufacturingOrder
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_product_name(self, obj):
        return obj.product.name if obj.product else None


class BOMSerializer(serializers.ModelSerializer):
    product_name = serializers.SerializerMethodField()

    class Meta:
        model = BillOfMaterial
        fields = "__all__"
        read_only_fields = ("company", "number", "created_at", "updated_at")

    def get_product_name(self, obj):
        return obj.product.name if obj.product else None
