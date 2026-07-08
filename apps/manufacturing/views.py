from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from .models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
    Routing,
    WorkCenter,
    WorkOrder,
)


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


# ════════════════════════ WORK CENTERS & ROUTINGS ════════════════════════════


class WorkCenterListView(CompanyMixin, ListView):
    template_name = "manufacturing/work_centers/list.html"
    context_object_name = "work_centers"

    def get_queryset(self):
        return WorkCenter.objects.filter(company=self.company()).order_by("name")


class RoutingListView(CompanyMixin, ListView):
    template_name = "manufacturing/routings/list.html"
    context_object_name = "routings"

    def get_queryset(self):
        return Routing.objects.filter(company=self.company()).order_by("name")


# ════════════════════════ BILLS OF MATERIAL ══════════════════════════════════


class BOMListView(CompanyMixin, ListView):
    template_name = "manufacturing/boms/list.html"
    context_object_name = "boms"

    def get_queryset(self):
        return (
            BillOfMaterial.objects.filter(company=self.company())
            .select_related("product", "routing")
            .order_by("-created_at")
        )


class BOMDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/boms/detail.html"
    context_object_name = "bom"

    def get_queryset(self):
        return BillOfMaterial.objects.filter(company=self.company())


class BOMCreateView(CompanyMixin, View):
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

        try:
            product_id = request.POST.get("product")
            routing_id = request.POST.get("routing")
            quantity = float(request.POST.get("quantity", 1))

            product = get_object_or_404(Product, pk=product_id, company=self.company())
            routing = (
                Routing.objects.filter(pk=routing_id, company=self.company()).first()
                if routing_id
                else None
            )

            bom = BillOfMaterial.objects.create(
                company=self.company(),
                product=product,
                routing=routing,
                quantity=quantity,
                is_active=True,
            )

            # Simple line parsing: expect component_id[], quantity[], scrap[]
            components = request.POST.getlist("component_id[]")
            qty_list = request.POST.getlist("line_quantity[]")
            scrap_list = request.POST.getlist("scrap_percentage[]")

            for i, comp_id in enumerate(components):
                if comp_id and float(qty_list[i]) > 0:
                    BillOfMaterialLine.objects.create(
                        bom=bom,
                        component_id=comp_id,
                        quantity=float(qty_list[i]),
                        scrap_percentage=float(scrap_list[i] if scrap_list[i] else 0),
                    )

            messages.success(request, f"BOM for {product.name} created.")
            return redirect("manufacturing:bom_detail", pk=bom.pk)
        except Exception as e:
            messages.error(request, f"Error creating BOM: {e}")
            return redirect("manufacturing:bom_create")


# ════════════════════════ MANUFACTURING ORDERS ═══════════════════════════════


class MOListView(CompanyMixin, ListView):
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
    template_name = "manufacturing/orders/detail.html"
    context_object_name = "order"

    def get_queryset(self):
        return ManufacturingOrder.objects.filter(company=self.company())


class MOCreateView(CompanyMixin, View):
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
        try:
            bom_id = request.POST.get("bom")
            warehouse_id = request.POST.get("warehouse")
            qty = float(request.POST.get("quantity_to_produce", 1))

            bom = get_object_or_404(BillOfMaterial, pk=bom_id, company=self.company())

            mo = ManufacturingOrder.objects.create(
                company=self.company(),
                product=bom.product,
                bom=bom,
                quantity_to_produce=qty,
                warehouse_id=warehouse_id if warehouse_id else None,
                planned_start_date=request.POST.get("planned_start_date") or None,
                planned_end_date=request.POST.get("planned_end_date") or None,
            )
            messages.success(request, f"Manufacturing Order {mo.number} created.")
            return redirect("manufacturing:mo_detail", pk=mo.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return redirect("manufacturing:mo_create")


class MOActionView(CompanyMixin, View):
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

from .models import DowntimeLog, ScrapOrder


class ScrapOrderListView(CompanyMixin, ListView):
    template_name = "manufacturing/scrap/list.html"
    context_object_name = "scrap_orders"

    def get_queryset(self):
        return ScrapOrder.objects.filter(company=self.company()).select_related(
            "product", "work_center", "manufacturing_order"
        )


class ScrapOrderDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/scrap/detail.html"
    context_object_name = "scrap_order"

    def get_queryset(self):
        return ScrapOrder.objects.filter(company=self.company()).select_related(
            "product", "work_center", "manufacturing_order"
        )


class DowntimeLogListView(CompanyMixin, ListView):
    template_name = "manufacturing/downtime/list.html"
    context_object_name = "downtime_logs"

    def get_queryset(self):
        return DowntimeLog.objects.filter(company=self.company()).select_related(
            "work_center"
        )


class DowntimeLogDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/downtime/detail.html"
    context_object_name = "downtime_log"

    def get_queryset(self):
        return DowntimeLog.objects.filter(company=self.company()).select_related(
            "work_center"
        )


class WorkOrderListView(CompanyMixin, ListView):
    template_name = "manufacturing/work_orders/list.html"
    context_object_name = "work_orders"

    def get_queryset(self):
        return WorkOrder.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_center"
        )


class WorkOrderDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/work_orders/detail.html"
    context_object_name = "work_order"

    def get_queryset(self):
        return WorkOrder.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_center"
        )


class WorkOrderStartView(CompanyMixin, View):
    def post(self, request, pk):
        wo = get_object_or_404(WorkOrder, pk=pk, company=self.company())
        if wo.status in [WorkOrder.Status.PENDING, WorkOrder.Status.READY]:
            wo.status = WorkOrder.Status.IN_PROGRESS
            wo.save()
            messages.success(request, f"Work Order {wo.number} started.")
        return redirect("manufacturing:work_order_detail", pk=wo.pk)


class WorkOrderCompleteView(CompanyMixin, View):
    def post(self, request, pk):
        wo = get_object_or_404(WorkOrder, pk=pk, company=self.company())
        if wo.status == WorkOrder.Status.IN_PROGRESS:
            wo.status = WorkOrder.Status.DONE
            wo.save()
            messages.success(request, f"Work Order {wo.number} completed.")
        return redirect("manufacturing:work_order_detail", pk=wo.pk)


# ════════════════════════ QUALITY CONTROL & COSTING ═══════════════════════════
from .models import ProductionCosting, QualityCheck


class QualityCheckListView(CompanyMixin, ListView):
    template_name = "manufacturing/qc/list.html"
    context_object_name = "quality_checks"

    def get_queryset(self):
        return QualityCheck.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_order", "inspector"
        )


class QualityCheckDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/qc/detail.html"
    context_object_name = "quality_check"

    def get_queryset(self):
        return QualityCheck.objects.filter(company=self.company()).select_related(
            "manufacturing_order", "work_order", "inspector"
        )


class ProductionCostingListView(CompanyMixin, ListView):
    template_name = "manufacturing/costing/list.html"
    context_object_name = "costings"

    def get_queryset(self):
        return ProductionCosting.objects.filter(company=self.company()).select_related(
            "manufacturing_order__product"
        )


class ProductionCostingDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/costing/detail.html"
    context_object_name = "costing"

    def get_queryset(self):
        return ProductionCosting.objects.filter(company=self.company()).select_related(
            "manufacturing_order__product"
        )


# ════════════════════════ DASHBOARD, MRP, MAINTENANCE ═════════════════════════

from django.views.generic import TemplateView

from .models import MaintenanceRequest, MaterialPlan
from .services import MRPService


class ManufacturingDashboardView(CompanyMixin, TemplateView):
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
    template_name = "manufacturing/mrp/list.html"
    context_object_name = "plans"

    def get_queryset(self):
        return MaterialPlan.objects.filter(company=self.company())


class MaterialPlanDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/mrp/detail.html"
    context_object_name = "plan"

    def get_queryset(self):
        return MaterialPlan.objects.filter(company=self.company()).prefetch_related(
            "items__product"
        )


class MaterialPlanRunView(CompanyMixin, View):
    def post(self, request, pk):
        plan = get_object_or_404(MaterialPlan, pk=pk, company=self.company())
        MRPService.run_mrp(plan.id)
        messages.success(request, f"MRP Run completed for {plan.name}")
        return redirect("manufacturing:mrp_detail", pk=plan.id)


class MaintenanceRequestListView(CompanyMixin, ListView):
    template_name = "manufacturing/maintenance/list.html"
    context_object_name = "requests"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            work_center__company=self.company()
        ).select_related("work_center")


class MaintenanceRequestDetailView(CompanyMixin, DetailView):
    template_name = "manufacturing/maintenance/detail.html"
    context_object_name = "maintenance_request"

    def get_queryset(self):
        return MaintenanceRequest.objects.filter(
            work_center__company=self.company()
        ).select_related("work_center")
