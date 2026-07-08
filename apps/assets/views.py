"""
Asset Management Views
Asset Registration, Categories, Allocation, Depreciation, Maintenance
"""

from core.permissions import PermissionRequiredMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from core.services import BaseService

from .models import Asset, AssetCategory, AssetMaintenance


class CompanyMixin(PermissionRequiredMixin):
    def company(self):
        return self.request.user.primary_company


class AssetListView(CompanyMixin, ListView):
    required_permission = "assets.read"
    template_name = "assets/list.html"
    context_object_name = "assets"
    paginate_by = 25

    def get_queryset(self):
        qs = (
            Asset.objects.filter(company=self.company(), is_deleted=False)
            .select_related("category", "assigned_to", "branch")
            .order_by("-purchase_date")
        )

        q = self.request.GET.get("q", "")
        status = self.request.GET.get("status", "")
        category = self.request.GET.get("category", "")

        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(asset_code__icontains=q)
                | Q(serial_number__icontains=q)
            )
        if status:
            qs = qs.filter(status=status)
        if category:
            qs = qs.filter(category_id=category)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        c = self.company()
        ctx["categories"] = AssetCategory.objects.filter(company=c, is_deleted=False)
        ctx["status_choices"] = Asset.Status.choices
        ctx["total_value"] = (
            Asset.objects.filter(
                company=c, status="active", is_deleted=False
            ).aggregate(t=Sum("current_value"))["t"]
            or 0
        )
        ctx["total_assets"] = Asset.objects.filter(company=c, is_deleted=False).count()
        return ctx


class AssetDetailView(CompanyMixin, DetailView):
    required_permission = "assets.read"
    template_name = "assets/detail.html"
    context_object_name = "asset"

    def get_object(self):
        return get_object_or_404(
            Asset, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        asset = self.object
        ctx["maintenances"] = asset.maintenances.filter(is_deleted=False).order_by(
            "-scheduled_date"
        )
        ctx["depreciation_entries"] = asset.depreciation_entries.filter(
            is_deleted=False
        ).order_by("-period_start")
        ctx["annual_depreciation"] = asset.calculate_annual_depreciation()
        return ctx


class AssetCreateView(CompanyMixin, View):
    required_permission = "assets.create"
    template_name = "assets/form.html"

    def get(self, request):
        from apps.authentication.models import User
        from apps.company.models import Branch
        from apps.purchase.models import Vendor

        c = self.company()
        return render(
            request,
            self.template_name,
            {
                "categories": AssetCategory.objects.filter(company=c, is_deleted=False),
                "branches": Branch.objects.filter(
                    company=c, is_active=True, is_deleted=False
                ),
                "vendors": Vendor.objects.filter(
                    company=c, status="active", is_deleted=False
                ).order_by("name"),
                "users": User.objects.filter(companies=c, is_active=True).order_by(
                    "first_name"
                ),
                "status_choices": Asset.Status.choices,
                "depreciation_methods": [
                    ("straight_line", "Straight Line"),
                    ("declining_balance", "Declining Balance"),
                    ("sum_of_years", "Sum of Years"),
                ],
            },
        )

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from decimal import Decimal

            purchase_cost = Decimal(data["purchase_cost"])
            asset = Asset(
                company=company,
                name=data["name"],
                asset_code=data.get("asset_code", ""),
                category_id=data["category"],
                branch_id=data.get("branch") or None,
                purchase_date=data["purchase_date"],
                purchase_cost=purchase_cost,
                salvage_value=Decimal(data.get("salvage_value", "0")),
                useful_life_years=int(data.get("useful_life_years", 5)),
                depreciation_method=data.get("depreciation_method", "straight_line"),
                current_value=purchase_cost,
                serial_number=data.get("serial_number", ""),
                model_number=data.get("model_number", ""),
                location=data.get("location", ""),
                assigned_to_id=data.get("assigned_to") or None,
                vendor_id=data.get("vendor") or None,
                warranty_expiry=data.get("warranty_expiry") or None,
                status="active",
                notes=data.get("notes", ""),
            )
            asset.number = BaseService.generate_sequence_number(
                "AST", Asset, company.pk
            )
            if request.FILES.get("image"):
                asset.image = request.FILES["image"]
            asset.save()
            messages.success(
                request, f"Asset {asset.number} — {asset.name} registered."
            )
            return redirect("assets:detail", pk=asset.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return redirect("assets:list")


class ScheduleMaintenanceView(CompanyMixin, View):
    required_permission = "assets.read"
    def post(self, request, pk):
        asset = get_object_or_404(
            Asset, pk=pk, company=self.company(), is_deleted=False
        )
        from decimal import Decimal

        try:
            maint = AssetMaintenance(
                company=self.company(),
                asset=asset,
                title=request.POST["title"],
                description=request.POST.get("description", ""),
                maintenance_type=request.POST.get("maintenance_type", "preventive"),
                scheduled_date=request.POST["scheduled_date"],
                cost=Decimal(request.POST.get("cost", "0")),
                performed_by=request.POST.get("performed_by", ""),
                next_maintenance_date=request.POST.get("next_maintenance_date") or None,
            )
            maint.number = BaseService.generate_sequence_number(
                "MNT", AssetMaintenance, self.company().pk
            )
            maint.save()

            asset.status = Asset.Status.UNDER_MAINTENANCE
            asset.save(update_fields=["status"])

            messages.success(request, "Maintenance scheduled.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
        return redirect("assets:detail", pk=pk)


class CompleteMaintenanceView(CompanyMixin, View):
    required_permission = "assets.approve"
    def post(self, request, maint_pk):
        maint = get_object_or_404(
            AssetMaintenance, pk=maint_pk, company=self.company(), is_deleted=False
        )
        maint.status = "completed"
        maint.completed_date = timezone.localdate()
        maint.save(update_fields=["status", "completed_date"])

        # Restore asset status
        maint.asset.status = Asset.Status.ACTIVE
        maint.asset.save(update_fields=["status"])

        messages.success(request, "Maintenance marked as completed.")
        return redirect("assets:detail", pk=maint.asset.pk)


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path
from django.utils import timezone

app_name = "assets"

urlpatterns = [
    path("", AssetListView.as_view(), name="list"),
    path("create/", AssetCreateView.as_view(), name="create"),
    path("<uuid:pk>/", AssetDetailView.as_view(), name="detail"),
    path(
        "<uuid:pk>/maintenance/",
        ScheduleMaintenanceView.as_view(),
        name="schedule_maintenance",
    ),
    path(
        "maintenance/<uuid:maint_pk>/complete/",
        CompleteMaintenanceView.as_view(),
        name="complete_maintenance",
    ),
]
