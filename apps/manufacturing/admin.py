from django.contrib import admin

from .models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
    Routing,
    RoutingOperation,
    WorkCenter,
    WorkOrder,
)


@admin.register(WorkCenter)
class WorkCenterAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "capacity", "cost_per_hour", "is_active"]
    search_fields = ["code", "name"]
    list_filter = ["is_active", "company"]


class RoutingOperationInline(admin.TabularInline):
    model = RoutingOperation
    extra = 1


@admin.register(Routing)
class RoutingAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_active"]
    search_fields = ["code", "name"]
    inlines = [RoutingOperationInline]
    list_filter = ["is_active", "company"]


class BillOfMaterialLineInline(admin.TabularInline):
    model = BillOfMaterialLine
    extra = 1


@admin.register(BillOfMaterial)
class BillOfMaterialAdmin(admin.ModelAdmin):
    list_display = ["number", "product", "quantity", "routing", "is_active"]
    search_fields = ["number", "product__name"]
    inlines = [BillOfMaterialLineInline]
    list_filter = ["is_active", "company"]


class WorkOrderInline(admin.TabularInline):
    model = WorkOrder
    extra = 0
    readonly_fields = [
        "number",
        "work_center",
        "name",
        "status",
        "expected_duration_minutes",
        "actual_duration_minutes",
    ]
    can_delete = False


@admin.register(ManufacturingOrder)
class ManufacturingOrderAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "product",
        "quantity_to_produce",
        "status",
        "planned_start_date",
    ]
    search_fields = ["number", "product__name"]
    list_filter = ["status", "company"]
    inlines = [WorkOrderInline]
    readonly_fields = ["quantity_produced"]


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ["number", "manufacturing_order", "work_center", "name", "status"]
    search_fields = ["number", "name", "manufacturing_order__number"]
    list_filter = ["status", "work_center", "company"]
