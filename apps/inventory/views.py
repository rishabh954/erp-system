import logging
"""
Inventory Views
Products, Warehouses, Stock Movements, Transfers, Reports
"""

from core.mixins import CompanyMixin
from core.permissions import PermissionRequiredMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, F, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView, View

from .models import (
    InventoryTransfer,
    Product,
    ProductCategory,
    StockMovement,
    StockRecord,
    Warehouse,
)


logger = logging.getLogger(__name__)


# ════════════════════════ PRODUCTS ═══════════════════════════════════════════


class ProductListView(CompanyMixin, ListView):
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
    template_name = "inventory/products/list.html"
    context_object_name = "products"
    paginate_by = 30

    def get_queryset(self):
        qs = (
            Product.objects.filter(company=self.company(), is_deleted=False)
            .select_related("category", "brand", "uom", "tax")
            .annotate(
                _total_stock_annotated=Sum(
                    "stock_records__quantity_on_hand",
                    filter=Q(stock_records__is_deleted=False)
                )
            )
            .order_by("name")
        )

        q = self.request.GET.get("q", "")
        cat = self.request.GET.get("category", "")
        active = self.request.GET.get("active", "")
        low = self.request.GET.get("low_stock", "")

        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q)
            )
        if cat:
            qs = qs.filter(category_id=cat)
        if active:
            qs = qs.filter(is_active=active == "1")
        if low:
            # annotate with total stock and filter below reorder point
            qs = qs.annotate(total_stock=Sum("stock_records__quantity_on_hand")).filter(
                total_stock__lte=F("reorder_point")
            )

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ProductCategory.objects.filter(
            company=self.company(), is_active=True, is_deleted=False
        )
        ctx["total_products"] = Product.objects.filter(
            company=self.company(), is_deleted=False
        ).count()
        ctx["low_stock_count"] = (
            Product.objects.filter(
                company=self.company(), is_deleted=False, is_active=True
            )
            .annotate(total_stock=Sum("stock_records__quantity_on_hand"))
            .filter(total_stock__lte=F("reorder_point"))
            .count()
        )
        return ctx


class ProductDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/products/detail.html"
    context_object_name = "product"

    def get_object(self):
        return get_object_or_404(
            Product, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = self.object
        ctx["stock_records"] = StockRecord.objects.filter(
            product=product, is_deleted=False
        ).select_related("warehouse", "bin_location")
        ctx["recent_movements"] = (
            StockMovement.objects.filter(product=product, is_deleted=False)
            .select_related("warehouse")
            .order_by("-movement_date")[:20]
        )
        ctx["total_stock"] = product.total_stock
        ctx["stock_value"] = sum(
            r.quantity_on_hand * r.average_cost for r in ctx["stock_records"]
        )
        return ctx


class ProductCreateView(CompanyMixin, View):
    required_permission = "inventory.create"
    template_name = "inventory/products/form.html"

    def get(self, request):
        return render(request, self.template_name, self._ctx())

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            product = Product(
                company=company,
                sku=data["sku"],
                barcode=data.get("barcode", ""),
                name=data["name"],
                description=data.get("description", ""),
                product_type=data.get("product_type", "stockable"),
                category_id=data.get("category") or None,
                brand_id=data.get("brand") or None,
                uom_id=data.get("uom") or None,
                cost_price=float(data.get("cost_price", 0)),
                sale_price=float(data.get("sale_price", 0)),
                min_stock_level=float(data.get("min_stock_level", 0)),
                reorder_point=float(data.get("reorder_point", 0)),
                reorder_quantity=float(data.get("reorder_quantity", 0)),
                tax_id=data.get("tax") or None,
                is_active=data.get("is_active") == "on",
                is_purchasable=data.get("is_purchasable") == "on",
                is_sellable=data.get("is_sellable") == "on",
            )
            if request.FILES.get("image"):
                product.image = request.FILES["image"]
            product.save()
            messages.success(
                request, f"Product {product.name} ({product.sku}) created."
            )
            return redirect("inventory:product_detail", pk=product.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return render(request, self.template_name, self._ctx())

    def _ctx(self):
        from apps.company.models import Tax

        from .models import Brand, ProductCategory, UnitOfMeasure

        c = self.company()
        return {
            "categories": ProductCategory.objects.filter(
                company=c, is_active=True, is_deleted=False
            ),
            "brands": Brand.objects.filter(company=c, is_active=True, is_deleted=False),
            "uoms": UnitOfMeasure.objects.filter(
                company=c, is_active=True, is_deleted=False
            ),
            "taxes": Tax.objects.filter(company=c, is_active=True),
            "product_type_choices": Product.ProductType.choices,
        }


# ════════════════════════ WAREHOUSES ══════════════════════════════════════════


class WarehouseListView(CompanyMixin, ListView):
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
    template_name = "inventory/warehouses/list.html"
    context_object_name = "warehouses"

    def get_queryset(self):
        return (
            Warehouse.objects.filter(company=self.company(), is_deleted=False)
            .select_related("branch", "manager")
            .annotate(
                stock_value=Sum(F("stock_records__quantity_on_hand") * F("stock_records__average_cost"), filter=Q(stock_records__is_deleted=False)),
                product_count=Count("stock_records__product", distinct=True, filter=Q(stock_records__quantity_on_hand__gt=0, stock_records__is_deleted=False)),
            )
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Use annotated fields instead of separate queries per warehouse
        for wh in ctx["warehouses"]:
            wh.stock_value = wh.stock_value or 0

        from django.contrib.auth import get_user_model

        from apps.company.models import Branch

        User = get_user_model()
        ctx["branches"] = Branch.objects.filter(company=self.company(), is_active=True)
        # assuming users are linked via UserCompany or simply filtering by primary_company for simplicity
        ctx["users"] = User.objects.filter(
            primary_company=self.company(), is_active=True
        )
        return ctx


class WarehouseCreateView(CompanyMixin, View):
    required_permission = "inventory.create"
    def post(self, request):
        try:
            from django.contrib.auth import get_user_model

            get_user_model()

            branch_id = request.POST.get("branch")
            manager_id = request.POST.get("manager")

            Warehouse.objects.create(
                company=self.company(),
                name=request.POST["name"],
                code=request.POST["code"],
                address=request.POST.get("address", ""),
                branch_id=branch_id if branch_id else None,
                manager_id=manager_id if manager_id else None,
                is_active=request.POST.get("is_active") == "on",
            )
            messages.success(request, "Warehouse created successfully.")
        except Exception as e:
            messages.error(request, f"Error creating warehouse: {e}")
        return redirect("inventory:warehouses")


class WarehouseUpdateView(CompanyMixin, View):
    required_permission = "inventory.update"
    def post(self, request, pk):
        try:
            wh = get_object_or_404(Warehouse, pk=pk, company=self.company())
            wh.name = request.POST["name"]
            wh.code = request.POST["code"]
            wh.address = request.POST.get("address", "")
            branch_id = request.POST.get("branch")
            manager_id = request.POST.get("manager")
            wh.branch_id = branch_id if branch_id else None
            wh.manager_id = manager_id if manager_id else None
            wh.is_active = request.POST.get("is_active") == "on"
            wh.save()
            messages.success(request, "Warehouse updated successfully.")
        except Exception as e:
            messages.error(request, f"Error updating warehouse: {e}")
        return redirect("inventory:warehouses")


class WarehouseDeleteView(CompanyMixin, View):
    required_permission = "inventory.delete"
    def post(self, request, pk):
        try:
            wh = get_object_or_404(Warehouse, pk=pk, company=self.company())
            wh.is_deleted = True
            wh.is_active = False
            wh.save()
            messages.success(request, "Warehouse archived successfully.")
        except Exception as e:
            messages.error(request, f"Error deleting warehouse: {e}")
        return redirect("inventory:warehouses")


# ════════════════════════ STOCK MOVEMENTS ═════════════════════════════════════


class StockMovementListView(CompanyMixin, ListView):
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
    template_name = "inventory/movements/list.html"
    context_object_name = "movements"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            StockMovement.objects.filter(company=self.company(), is_deleted=False)
            .select_related("product", "warehouse")
            .order_by("-movement_date", "-created_at")
        )

        product = self.request.GET.get("product", "")
        wh = self.request.GET.get("warehouse", "")
        mtype = self.request.GET.get("type", "")

        if product:
            qs = qs.filter(product_id=product)
        if wh:
            qs = qs.filter(warehouse_id=wh)
        if mtype:
            qs = qs.filter(movement_type=mtype)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        ctx["warehouses"] = Warehouse.objects.filter(
            company=c, is_deleted=False
        ).order_by("name")
        ctx["products"] = Product.objects.filter(company=c, is_deleted=False).order_by(
            "name"
        )
        ctx["movement_type_choices"] = StockMovement.MovementType.choices
        return ctx


class StockAdjustmentView(CompanyMixin, View):
    required_permission = "inventory.create"
    template_name = "inventory/movements/adjustment.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "products": Product.objects.filter(
                    company=self.company(), is_active=True, is_deleted=False
                ),
                "warehouses": Warehouse.objects.filter(
                    company=self.company(), is_active=True, is_deleted=False
                ),
            },
        )

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            product = get_object_or_404(Product, pk=data["product"], company=company)
            warehouse = get_object_or_404(
                Warehouse, pk=data["warehouse"], company=company
            )

            from .services import StockService

            service = StockService(user=request.user, company=company)
            mov = service.adjust_stock(
                product=product,
                warehouse=warehouse,
                qty_input=data["quantity"],
                adjustment_type=data.get("adjustment_type", "add"),
                notes=data.get("notes", ""),
            )

            messages.success(request, f"Stock adjustment recorded for {product.name}.")
            return redirect("inventory:movements")
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Adjustment error: {e}")

        return redirect("inventory:movements")


# ════════════════════════ INVENTORY TRANSFERS ════════════════════════════════


class TransferListView(CompanyMixin, ListView):
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
    template_name = "inventory/transfers/list.html"
    context_object_name = "transfers"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            InventoryTransfer.objects.filter(company=self.company(), is_deleted=False)
            .select_related("from_warehouse", "to_warehouse", "approved_by")
            .order_by("-transfer_date", "-created_at")
        )

        status = self.request.GET.get("status", "")
        from_wh = self.request.GET.get("from_warehouse", "")
        to_wh = self.request.GET.get("to_warehouse", "")

        if status:
            qs = qs.filter(status=status)
        if from_wh:
            qs = qs.filter(from_warehouse_id=from_wh)
        if to_wh:
            qs = qs.filter(to_warehouse_id=to_wh)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        ctx["warehouses"] = Warehouse.objects.filter(
            company=c, is_deleted=False
        ).order_by("name")
        ctx["status_choices"] = InventoryTransfer.Status.choices
        return ctx


class TransferCreateView(CompanyMixin, View):
    required_permission = "inventory.create"
    template_name = "inventory/transfers/form.html"

    def get(self, request):
        c = self.company()
        return render(
            request,
            self.template_name,
            {
                "warehouses": Warehouse.objects.filter(
                    company=c, is_active=True, is_deleted=False
                ).order_by("name"),
                "products": Product.objects.filter(
                    company=c, is_active=True, is_deleted=False
                ).order_by("name"),
            },
        )

    def post(self, request):
        company = self.company()
        try:
            from .services import TransferService

            service = TransferService(user=request.user, company=company)
            transfer = service.create_transfer(request.POST, request.user)
            messages.success(
                request, f"Inventory Transfer {transfer.number} created in draft."
            )
            return redirect("inventory:transfer_detail", pk=transfer.pk)
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error: {e}")

        return render(
            request,
            self.template_name,
            {
                "warehouses": Warehouse.objects.filter(
                    company=company, is_active=True, is_deleted=False
                ).order_by("name"),
                "products": Product.objects.filter(
                    company=company, is_active=True, is_deleted=False
                ).order_by("name"),
            },
        )


class TransferDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/transfers/detail.html"
    context_object_name = "transfer"

    def get_object(self):
        return get_object_or_404(
            InventoryTransfer,
            pk=self.kwargs["pk"],
            company=self.company(),
            is_deleted=False,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lines"] = self.object.lines.all().select_related("product", "variant")
        return ctx


class TransferActionView(CompanyMixin, View):
    required_permission = "inventory.approve"
    def post(self, request, pk):
        transfer = get_object_or_404(
            InventoryTransfer, pk=pk, company=self.company(), is_deleted=False
        )
        action = request.POST.get("action")

        try:
            from .services import TransferService

            service = TransferService(user=request.user, company=self.company())
            transfer = service.process_transfer(
                transfer, action, request.POST, request.user
            )

            if action == "submit":
                if transfer.status == InventoryTransfer.Status.PENDING_APPROVAL:
                    messages.success(
                        request, f"{transfer.number} submitted for approval."
                    )
                else:
                    messages.success(
                        request,
                        f"{transfer.number} auto-approved (no matching policies).",
                    )
            elif action == "ship":
                messages.success(
                    request, f"{transfer.number} shipped and marked In Transit."
                )
            elif action == "receive":
                messages.success(request, f"{transfer.number} received successfully.")
            elif action == "cancel":
                messages.warning(request, f"{transfer.number} has been cancelled.")

        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Action Error: {e}")

        return redirect("inventory:transfer_detail", pk=pk)


# ════════════════════════ REPORTS ════════════════════════════════════════════


class ProductCategoryAjaxCreateView(CompanyMixin, View):
    required_permission = "inventory.create"
    def post(self, request):
        company = self.company()
        name = request.POST.get("name", "").strip()
        if not name:
            return JsonResponse(
                {"status": "error", "message": "Name is required"}, status=400
            )

        try:
            from .models import ProductCategory

            cat = ProductCategory.objects.create(
                company=company,
                name=name,
                code=request.POST.get("code", "").strip(),
            )
            return JsonResponse(
                {"status": "success", "category": {"id": str(cat.id), "name": cat.name}}
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"status": "error", "message": "An unexpected error occurred."}, status=400)


class ProductCategoryListView(CompanyMixin, ListView):
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
    model = ProductCategory
    template_name = "inventory/categories/list.html"
    context_object_name = "categories"
    paginate_by = 30

    def get_queryset(self):
        qs = ProductCategory.objects.filter(company=self.company())
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs.order_by("name")


from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, UpdateView


class ProductCategoryCreateView(CompanyMixin, SuccessMessageMixin, CreateView):
    required_permission = "inventory.create"
    model = ProductCategory
    template_name = "inventory/categories/form.html"
    fields = ["name", "code", "parent", "description", "is_active"]
    success_url = reverse_lazy("inventory:categories")
    success_message = "Category created successfully."

    def form_valid(self, form):
        form.instance.company = self.company()
        return super().form_valid(form)


class ProductCategoryUpdateView(CompanyMixin, SuccessMessageMixin, UpdateView):
    required_permission = "inventory.update"
    model = ProductCategory
    template_name = "inventory/categories/form.html"
    fields = ["name", "code", "parent", "description", "is_active"]
    success_url = reverse_lazy("inventory:categories")
    success_message = "Category updated successfully."

    def get_queryset(self):
        return ProductCategory.objects.filter(company=self.company())


class ProductCategoryDeleteView(CompanyMixin, DeleteView):
    required_permission = "inventory.delete"
    model = ProductCategory
    template_name = "inventory/categories/confirm_delete.html"
    success_url = reverse_lazy("inventory:categories")

    def get_queryset(self):
        return ProductCategory.objects.filter(company=self.company())

    def form_valid(self, form):
        from django.http import HttpResponseRedirect
        from django.utils import timezone

        success_url = self.get_success_url()
        self.object.is_deleted = True
        self.object.is_active = False
        self.object.deleted_at = timezone.now()
        self.object.deleted_by = self.request.user
        self.object.save()
        return HttpResponseRedirect(success_url)


class InventoryReportsView(CompanyMixin, TemplateView):
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
    template_name = "inventory/reports/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()

        # ── KPI Summary ──────────────────────────────────────────────────────
        ctx["total_value"] = (
            StockRecord.objects.filter(company=company, is_deleted=False).aggregate(
                val=Sum(F("quantity_on_hand") * F("average_cost"))
            )["val"]
            or 0
        )

        ctx["total_products"] = Product.objects.filter(
            company=company, is_active=True, is_deleted=False
        ).count()

        ctx["total_warehouses"] = Warehouse.objects.filter(
            company=company, is_active=True, is_deleted=False
        ).count()

        # Count of products with stock <= reorder_point
        ctx["low_stock_count"] = (
            Product.objects.filter(company=company, is_active=True, is_deleted=False)
            .annotate(stock=Sum("stock_records__quantity_on_hand"))
            .filter(stock__lte=F("reorder_point"))
            .count()
        )

        # Total stock movements in last 30 days
        from datetime import timedelta

        thirty_days_ago = timezone.now().date() - timedelta(days=30)
        ctx["movements_30d"] = StockMovement.objects.filter(
            company=company, is_deleted=False, movement_date__gte=thirty_days_ago
        ).count()

        # ── Low Stock Items (table) ────────────────────────────────────────
        ctx["low_stock_items"] = (
            Product.objects.filter(company=company, is_active=True, is_deleted=False)
            .annotate(stock=Sum("stock_records__quantity_on_hand"))
            .filter(stock__lte=F("reorder_point"))
            .select_related("category", "uom")
            .order_by("stock")[:20]
        )

        # ── Top Products by Value ─────────────────────────────────────────
        ctx["top_value_items"] = (
            StockRecord.objects.filter(
                company=company, is_deleted=False, quantity_on_hand__gt=0
            )
            .select_related("product", "warehouse")
            .annotate(value=F("quantity_on_hand") * F("average_cost"))
            .order_by("-value")[:15]
        )

        # ── Warehouse Valuation Breakdown ─────────────────────────────────
        ctx["warehouse_valuations"] = (
            StockRecord.objects.filter(company=company, is_deleted=False)
            .values("warehouse__name", "warehouse__code")
            .annotate(
                total_value=Sum(F("quantity_on_hand") * F("average_cost")),
                total_qty=Sum("quantity_on_hand"),
                sku_count=Count("product", distinct=True),
            )
            .order_by("-total_value")
        )

        # Compute max_value for chart scaling in template
        wv = list(ctx["warehouse_valuations"])
        ctx["warehouse_max_value"] = (
            max((w["total_value"] or 0 for w in wv), default=1) or 1
        )

        # ── Dead Stock (>180 days no outbound) ─────────────────────────────
        one_eighty_days_ago = timezone.now().date() - timedelta(days=180)
        # Find products with stock but no recent movements
        active_product_ids = StockMovement.objects.filter(
            company=company,
            movement_date__gte=one_eighty_days_ago,
            movement_type__in=[
                StockMovement.MovementType.DELIVERY,
                StockMovement.MovementType.PRODUCTION_OUT,
            ],
        ).values_list("product_id", flat=True)

        dead_stock = (
            StockRecord.objects.filter(company=company, quantity_on_hand__gt=0)
            .exclude(product_id__in=active_product_ids)
            .aggregate(val=Sum(F("quantity_on_hand") * F("average_cost")))["val"]
            or 0
        )
        ctx["dead_stock_value"] = dead_stock

        # ── Cycle Counts & QA Pending ──────────────────────────────────────
        from .models import CycleCount, QualityInspection

        ctx["pending_cycle_counts"] = CycleCount.objects.filter(
            company=company, status__in=["draft", "in_progress", "counted"]
        ).count()
        ctx["pending_qa"] = QualityInspection.objects.filter(
            company=company, status="pending"
        ).count()

        # ── Category Breakdown ────────────────────────────────────────────
        ctx["category_breakdown"] = (
            Product.objects.filter(company=company, is_active=True, is_deleted=False)
            .values("category__name")
            .annotate(
                product_count=Count("id"),
                total_value=Sum(
                    F("stock_records__quantity_on_hand")
                    * F("stock_records__average_cost")
                ),
            )
            .order_by("-product_count")[:8]
        )

        # ── Recent Stock Movements ────────────────────────────────────────
        ctx["recent_movements"] = (
            StockMovement.objects.filter(company=company, is_deleted=False)
            .select_related("product", "warehouse")
            .order_by("-movement_date", "-created_at")[:10]
        )

        return ctx


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

# ════════════════════════ DELIVERIES ═════════════════════════════════════════

from .models import DeliveryOrder


class DeliveryOrderListView(CompanyMixin, ListView):
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
    template_name = "inventory/deliveries/list.html"
    context_object_name = "deliveries"
    paginate_by = 25

    def get_queryset(self):
        qs = DeliveryOrder.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related("sales_order", "warehouse")
        status = self.request.GET.get("status")
        q = self.request.GET.get("q")

        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(Q(number__icontains=q) | Q(sales_order__number__icontains=q))

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = DeliveryOrder.Status.choices
        ctx["pending_count"] = DeliveryOrder.objects.filter(
            company=self.company(),
            is_deleted=False,
            status__in=[DeliveryOrder.Status.DRAFT, DeliveryOrder.Status.READY],
        ).count()
        return ctx


class DeliveryOrderDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/deliveries/detail.html"
    context_object_name = "delivery"

    def get_object(self):
        return get_object_or_404(
            DeliveryOrder,
            pk=self.kwargs["pk"],
            company=self.company(),
            is_deleted=False,
        )


class ShipDeliveryView(CompanyMixin, View):
    required_permission = "inventory.approve"
    def post(self, request, pk):
        delivery = get_object_or_404(
            DeliveryOrder, pk=pk, company=self.company(), is_deleted=False
        )
        try:
            from .services import DeliveryService

            service = DeliveryService(user=request.user, company=self.company())
            service.ship_delivery(delivery, request.user)
            messages.success(
                request, f"Delivery {delivery.number} successfully shipped!"
            )
        except ValueError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f"Error shipping delivery: {e}")

        return redirect("inventory:delivery_detail", pk=delivery.pk)


# ════════════════════════ ENTERPRISE INVENTORY VIEWS ═════════════════════════

from .models import ReorderRule


class ReorderRuleListView(CompanyMixin, ListView):
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
    template_name = "inventory/reorder_rules/list.html"
    context_object_name = "rules"

    def get_queryset(self):
        return ReorderRule.objects.filter(company=self.company()).select_related(
            "product", "warehouse"
        )


class ReorderRuleDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/reorder_rules/detail.html"
    context_object_name = "rule"

    def get_queryset(self):
        return ReorderRule.objects.filter(company=self.company()).select_related(
            "product", "warehouse"
        )


# ------------------------ ADVANCED WMS (PHASE 7) --------------------------------


class PickListListView(CompanyMixin, ListView):
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
    template_name = "inventory/wms/picklist_list.html"
    context_object_name = "picklists"
    paginate_by = 30

    def get_queryset(self):
        from .models import PickList

        qs = (
            PickList.objects.filter(company=self.company())
            .select_related("delivery_order", "warehouse", "assigned_to")
            .order_by("-created_at")
        )
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs


class PickListDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/wms/picklist_detail.html"
    context_object_name = "picklist"

    def get_object(self):
        from .models import PickList

        return get_object_or_404(PickList, pk=self.kwargs["pk"], company=self.company())


class ShipmentListView(CompanyMixin, ListView):
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
    template_name = "inventory/wms/shipment_list.html"
    context_object_name = "shipments"
    paginate_by = 30

    def get_queryset(self):
        from .models import Shipment

        qs = (
            Shipment.objects.filter(company=self.company())
            .select_related("delivery_order", "packing_slip")
            .order_by("-created_at")
        )
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs


class LotBatchListView(CompanyMixin, ListView):
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
    template_name = "inventory/wms/lot_list.html"
    context_object_name = "lots"
    paginate_by = 50

    def get_queryset(self):
        from .models import LotBatch

        qs = (
            LotBatch.objects.filter(company=self.company())
            .select_related("product", "vendor")
            .order_by("-manufacturing_date")
        )
        product = self.request.GET.get("product", "")
        if product:
            qs = qs.filter(product__name__icontains=product)
        return qs


class LandedCostListView(CompanyMixin, ListView):
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
    template_name = "inventory/wms/landed_cost_list.html"
    context_object_name = "landed_costs"
    paginate_by = 30

    def get_queryset(self):
        from .models import LandedCost

        qs = (
            LandedCost.objects.filter(company=self.company())
            .select_related("receipt")
            .order_by("-date")
        )
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs


class LotBatchDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/wms/lot_detail.html"
    context_object_name = "lot"

    def get_queryset(self):
        from .models import LotBatch

        return LotBatch.objects.filter(company=self.company()).select_related(
            "product", "vendor"
        )


class SerialNumberListView(CompanyMixin, ListView):
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
    template_name = "inventory/wms/serial_list.html"
    context_object_name = "serials"
    paginate_by = 50

    def get_queryset(self):
        from .models import SerialNumber

        qs = (
            SerialNumber.objects.filter(company=self.company())
            .select_related("product", "lot")
            .order_by("-created_at")
        )
        product = self.request.GET.get("product", "")
        if product:
            qs = qs.filter(product__name__icontains=product)
        return qs


class SerialNumberDetailView(CompanyMixin, DetailView):
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
    template_name = "inventory/wms/serial_detail.html"
    context_object_name = "serial"

    def get_queryset(self):
        from .models import SerialNumber

        return SerialNumber.objects.filter(company=self.company()).select_related(
            "product", "lot"
        )
