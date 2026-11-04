from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from core.mixins import CompanyMixin

from .models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
    Routing,
    WorkCenter,
    WorkOrder,
)


def _positive_decimal(value, label, errors):
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        errors[label] = "Enter a valid number."
        return None
    if not result.is_finite() or result <= 0:
        errors[label] = "Enter a number greater than zero."
        return None
    return result


def _manufacturing_dates(data, errors):
    parsed = {}
    date_field = forms.DateField(required=False)
    for field in ("planned_start_date", "planned_end_date"):
        raw_value = data.get(field, "").strip()
        try:
            parsed[field] = date_field.clean(raw_value)
        except ValidationError:
            errors[field] = "Enter a valid date."
            parsed[field] = None

    start = parsed["planned_start_date"]
    end = parsed["planned_end_date"]
    if start and end and end < start:
        errors["planned_end_date"] = "End date cannot be before the start date."
    return parsed


# ════════════════════════ WORK CENTERS & ROUTINGS ════════════════════════════


class WorkCenterListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/work_centers/list.html"
    context_object_name = "work_centers"

    def get_queryset(self):
        return WorkCenter.objects.filter(company=self.company()).order_by("name")


class RoutingListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/routings/list.html"
    context_object_name = "routings"

    def get_queryset(self):
        return Routing.objects.filter(company=self.company()).order_by("name")


# ════════════════════════ BILLS OF MATERIAL ══════════════════════════════════


class BOMListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/boms/list.html"
    context_object_name = "boms"

    def get_queryset(self):
        return (
            BillOfMaterial.objects.filter(company=self.company())
            .select_related("product", "routing")
            .order_by("-created_at")
        )


class BOMDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/boms/detail.html"
    context_object_name = "bom"

    def get_queryset(self):
        return BillOfMaterial.objects.filter(company=self.company())


class BOMCreateView(CompanyMixin, View):
    required_permission = "manufacturing.create"
    def get(self, request):
        from apps.inventory.models import Product

        products = Product.objects.filter(
            company=self.company(), is_active=True, is_deleted=False
        )
        routings = Routing.objects.filter(company=self.company(), is_active=True)
        return render(
            request,
            "manufacturing/boms/form.html",
            {"products": products, "routings": routings},
        )

    def post(self, request):
        from apps.inventory.models import Product

        company = self.company()
        data = request.POST
        form_data = data.dict()
        errors = {}
        product_id = data.get("product", "").strip()
        routing_id = data.get("routing", "").strip()
        product = None
        routing = None
        try:
            product = Product.objects.filter(
                pk=product_id, company=company, is_active=True, is_deleted=False
            ).first()
        except (ValidationError, ValueError):
            pass
        if not product:
            errors["product"] = "Select an active product from this company."

        quantity = _positive_decimal(data.get("quantity", ""), "quantity", errors)
        if routing_id:
            try:
                routing = Routing.objects.filter(
                    pk=routing_id, company=company, is_active=True, is_deleted=False
                ).first()
            except (ValidationError, ValueError):
                pass
            if not routing:
                errors["routing"] = "Select an active routing from this company."

        components = data.getlist("component_id[]")
        quantities = data.getlist("line_quantity[]")
        scrap_values = data.getlist("scrap_percentage[]")
        component_rows = []
        parsed_lines = []
        if not components:
            errors["components"] = "Add at least one component."
        if len(components) != len(quantities) or (
            scrap_values and len(scrap_values) != len(components)
        ):
            errors["components"] = "Each component must have matching quantity data."

        for index, component_id in enumerate(components):
            row = {
                "component_id": component_id,
                "quantity": quantities[index] if index < len(quantities) else "",
                "scrap_percentage": (
                    scrap_values[index] if index < len(scrap_values) else ""
                ),
            }
            component_rows.append(row)
            row_key = f"component_{index}"
            row_product = None
            try:
                row_product = Product.objects.filter(
                    pk=component_id.strip(),
                    company=company,
                    is_active=True,
                    is_deleted=False,
                ).first()
            except (ValidationError, ValueError):
                pass
            if not row_product:
                errors[row_key] = "Select an active component from this company."
                row["component_error"] = errors[row_key]
                row["quantity_error"] = ""
                row["scrap_error"] = ""
                continue
            if product and row_product.pk == product.pk:
                errors[row_key] = "A finished product cannot be its own component."
            line_quantity = _positive_decimal(
                row["quantity"], f"{row_key}_quantity", errors
            )
            try:
                scrap = Decimal(row["scrap_percentage"].strip() or "0")
            except (InvalidOperation, ValueError):
                scrap = None
            if scrap is None or not scrap.is_finite() or not 0 <= scrap <= 100:
                errors[f"{row_key}_scrap"] = "Enter a scrap percentage from 0 to 100."
            if line_quantity is not None and scrap is not None and 0 <= scrap <= 100:
                parsed_lines.append(
                    {
                        "component": row_product,
                        "quantity": line_quantity,
                        "scrap_percentage": scrap,
                    }
                )
            row["component_error"] = errors.get(row_key, "")
            row["quantity_error"] = errors.get(f"{row_key}_quantity", "")
            row["scrap_error"] = errors.get(f"{row_key}_scrap", "")

        if errors:
            return render(
                request,
                "manufacturing/boms/form.html",
                {
                    "products": Product.objects.filter(
                        company=company, is_active=True, is_deleted=False
                    ),
                    "routings": Routing.objects.filter(
                        company=company, is_active=True, is_deleted=False
                    ),
                    "errors": errors,
                    "form_data": form_data,
                    "component_rows": component_rows,
                },
                status=400,
            )

        with transaction.atomic():
            bom = BillOfMaterial.objects.create(
                company=company,
                product=product,
                routing=routing,
                quantity=quantity,
                is_active=True,
            )
            BillOfMaterialLine.objects.bulk_create(
                [
                    BillOfMaterialLine(bom=bom, **line)
                    for line in parsed_lines
                ]
            )

        messages.success(request, f"BOM for {product.name} created.")
        return redirect("manufacturing:bom_detail", pk=bom.pk)


# ════════════════════════ MANUFACTURING ORDERS ═══════════════════════════════


class MOListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/orders/list.html"
    context_object_name = "orders"

    def get_queryset(self):
        qs = (
            ManufacturingOrder.objects.filter(company=self.company())
            .select_related("product", "bom")
            .order_by("-created_at")
        )
        status = self.request.GET.get("status")
        if status:
            qs = qs.filter(status=status)
        return qs


class MODetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/orders/detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return ManufacturingOrder.objects.filter(company=self.company())


class MOCreateView(CompanyMixin, View):
    required_permission = "manufacturing.create"
    def get(self, request):
        from apps.inventory.models import Warehouse

        boms = BillOfMaterial.objects.filter(
            company=self.company(), is_active=True
        ).select_related("product")
        warehouses = Warehouse.objects.filter(
            company=self.company(), is_active=True, is_deleted=False
        )
        return render(
            request,
            "manufacturing/orders/form.html",
            {"boms": boms, "warehouses": warehouses},
        )

    def post(self, request):
        from apps.inventory.models import Warehouse

        company = self.company()
        data = request.POST
        form_data = data.dict()
        errors = {}
        bom = None
        warehouse = None
        try:
            bom = BillOfMaterial.objects.select_related("product").filter(
                pk=data.get("bom", "").strip(),
                company=company,
                is_active=True,
                is_deleted=False,
            ).first()
        except (ValidationError, ValueError):
            pass
        if not bom or bom.product.company_id != company.pk or not bom.product.is_active:
            errors["bom"] = "Select an active bill of materials from this company."

        quantity = _positive_decimal(
            data.get("quantity_to_produce", ""), "quantity_to_produce", errors
        )
        warehouse_id = data.get("warehouse", "").strip()
        if warehouse_id:
            try:
                warehouse = Warehouse.objects.filter(
                    pk=warehouse_id,
                    company=company,
                    is_active=True,
                    is_deleted=False,
                ).first()
            except (ValidationError, ValueError):
                pass
            if not warehouse:
                errors["warehouse"] = "Select an active warehouse from this company."

        planned_dates = _manufacturing_dates(data, errors)
        if errors:
            return render(
                request,
                "manufacturing/orders/form.html",
                {
                    "boms": BillOfMaterial.objects.filter(
                        company=company, is_active=True, is_deleted=False
                    ).select_related("product"),
                    "warehouses": Warehouse.objects.filter(
                        company=company, is_active=True, is_deleted=False
                    ),
                    "errors": errors,
                    "form_data": form_data,
                },
                status=400,
            )

        mo = ManufacturingOrder.objects.create(
            company=company,
            product=bom.product,
            bom=bom,
            quantity_to_produce=quantity,
            warehouse=warehouse,
            planned_start_date=planned_dates["planned_start_date"],
            planned_end_date=planned_dates["planned_end_date"],
        )
        messages.success(request, f"Manufacturing Order {mo.number} created.")
        return redirect("manufacturing:mo_detail", pk=mo.pk)


class MOActionView(CompanyMixin, View):
    required_permission = "manufacturing.approve"
    def post(self, request, pk):
        mo = get_object_or_404(ManufacturingOrder, pk=pk, company=self.company())
        action = request.POST.get("action")

        if action == "confirm":
            mo.confirm()
            messages.success(request, "Order confirmed.")
        elif action == "start":
            if mo.status == ManufacturingOrder.Status.CONFIRMED:
                mo.status = ManufacturingOrder.Status.IN_PROGRESS
                mo.save(update_fields=["status"])
                messages.success(request, "Order started.")
        elif action == "done":
            mo.mark_done()
            messages.success(request, "Order marked as done and inventory updated.")
        elif action == "cancel":
            mo.status = ManufacturingOrder.Status.CANCELLED
            mo.save(update_fields=["status"])
            messages.warning(request, "Order cancelled.")

        return redirect("manufacturing:mo_detail", pk=pk)


# ════════════════════════ SCRAP & DOWNTIME ════════════════════════════════════

from .models import DowntimeLog, ScrapOrder  # noqa: E402


class ScrapOrderListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/scrap/list.html"
    context_object_name = "scrap_orders"

    def get_queryset(self):
        return ScrapOrder.objects.filter(company=self.company()).select_related(
            "product", "work_center", "manufacturing_order"
        )


class ScrapOrderDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/scrap/detail.html"
    context_object_name = "scrap_order"

    def get_queryset(self):
        return ScrapOrder.objects.filter(company=self.company()).select_related(
            "product", "work_center", "manufacturing_order"
        )


class DowntimeLogListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/downtime/list.html"
    context_object_name = "downtime_logs"

    def get_queryset(self):
        return DowntimeLog.objects.filter(company=self.company()).select_related(
            "work_center"
        )


class DowntimeLogDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/downtime/detail.html"
    context_object_name = "downtime_log"

    def get_queryset(self):
        return DowntimeLog.objects.filter(company=self.company()).select_related(
            "work_center"
        )


class WorkOrderListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/work_orders/list.html"
    context_object_name = "work_orders"

    def get_queryset(self):
        return WorkOrder.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_center"
        )


class WorkOrderDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/work_orders/detail.html"
    context_object_name = "work_order"

    def get_queryset(self):
        return WorkOrder.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_center"
        )


class WorkOrderStartView(CompanyMixin, View):
    required_permission = "manufacturing.update"
    def post(self, request, pk):
        wo = get_object_or_404(WorkOrder, pk=pk, company=self.company())
        if wo.status in [WorkOrder.Status.PENDING, WorkOrder.Status.READY]:
            wo.status = WorkOrder.Status.IN_PROGRESS
            wo.save()
            messages.success(request, f"Work Order {wo.number} started.")
        return redirect("manufacturing:work_order_detail", pk=wo.pk)


class WorkOrderCompleteView(CompanyMixin, View):
    required_permission = "manufacturing.approve"
    def post(self, request, pk):
        wo = get_object_or_404(WorkOrder, pk=pk, company=self.company())
        if wo.status == WorkOrder.Status.IN_PROGRESS:
            wo.status = WorkOrder.Status.DONE
            wo.save()
            messages.success(request, f"Work Order {wo.number} completed.")
        return redirect("manufacturing:work_order_detail", pk=wo.pk)


# ════════════════════════ QUALITY CONTROL & COSTING ═══════════════════════════
from .models import ProductionCosting, QualityCheck  # noqa: E402


class QualityCheckListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/qc/list.html"
    context_object_name = "quality_checks"

    def get_queryset(self):
        return QualityCheck.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_order", "inspector"
        )


class QualityCheckDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/qc/detail.html"
    context_object_name = "quality_check"

    def get_queryset(self):
        return QualityCheck.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_order", "inspector"
        )


class ProductionCostingListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/costing/list.html"
    context_object_name = "costings"

    def get_queryset(self):
        return ProductionCosting.objects.filter(company=self.company()).select_related(
            "manufacturing_order__product"
        )


class ProductionCostingDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/costing/detail.html"
    context_object_name = "costing"

    def get_queryset(self):
        return ProductionCosting.objects.filter(company=self.company()).select_related(
            "manufacturing_order__product"
        )


# ════════════════════════ DASHBOARD, MRP, MAINTENANCE ═════════════════════════

from django.views.generic import TemplateView  # noqa: E402

from .models import MaintenanceRequest, MaterialPlan  # noqa: E402
from .services import MRPService  # noqa: E402


class ManufacturingDashboardView(CompanyMixin, TemplateView):
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
    template_name = "manufacturing/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()

        # OEE / Scrap Rate approximation
        total_mo = ManufacturingOrder.objects.filter(
            company=company, status=ManufacturingOrder.Status.DONE
        ).count()
        ctx["total_mo_done"] = total_mo

        from django.db.models import Sum

        scrap_qty = (
            ScrapOrder.objects.filter(company=company).aggregate(Sum("quantity"))[
                "quantity__sum"
            ]
            or 0
        )
        ctx["total_scrap"] = scrap_qty

        # Active Maintenance
        ctx["active_maintenance"] = MaintenanceRequest.objects.filter(
            work_center__company=company,
            status__in=[
                MaintenanceRequest.Status.PENDING,
                MaintenanceRequest.Status.IN_PROGRESS,
            ],
        ).count()

        # MRP Plans
        ctx["recent_mrp"] = MaterialPlan.objects.filter(company=company).order_by(
            "-created_at"
        )[:5]

        return ctx


class MaterialPlanListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/mrp/list.html"
    context_object_name = "plans"

    def get_queryset(self):
        return MaterialPlan.objects.filter(company=self.company())


class MaterialPlanDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/mrp/detail.html"
    context_object_name = "plan"

    def get_queryset(self):
        return MaterialPlan.objects.filter(company=self.company()).prefetch_related(
            "items__product"
        )


class MaterialPlanRunView(CompanyMixin, View):
    required_permission = "manufacturing.create"
    def post(self, request, pk):
        plan = get_object_or_404(MaterialPlan, pk=pk, company=self.company())
        MRPService.run_mrp(plan.id, company_id=plan.company_id)
        messages.success(request, f"MRP Run completed for {plan.name}")
        return redirect("manufacturing:mrp_detail", pk=plan.id)


class MaintenanceRequestListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/maintenance/list.html"
    context_object_name = "requests"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            work_center__company=self.company()
        ).select_related("work_center")


class MaintenanceRequestDetailView(CompanyMixin, DetailView):
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
    template_name = "manufacturing/maintenance/detail.html"
    context_object_name = "maintenance_request"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            work_center__company=self.company()
        ).select_related("work_center")
