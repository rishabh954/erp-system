"""
Asset Management Views
Asset Registration, Categories, Allocation, Depreciation, Maintenance
"""

from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, ListView, View

from core.mixins import CompanyMixin
from core.services import BaseService

from .forms import AssetForm, MaintenanceForm
from .models import Asset, AssetCategory, AssetMaintenance


class AssetListView(CompanyMixin, ListView):
    required_permission = "assets.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "assets.create"
            elif request.method in ["PUT", "PATCH"]:
                return "assets.update"
            elif request.method == "DELETE":
                return "assets.delete"
        return self.required_permission
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

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "assets.create"
            elif request.method in ["PUT", "PATCH"]:
                return "assets.update"
            elif request.method == "DELETE":
                return "assets.delete"
        return self.required_permission
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
        company = self.company()
        form = AssetForm(request.POST, request.FILES, company=company)
        if not form.is_valid():
            messages.error(request, "Please provide valid asset details.")
            return redirect("assets:list")
        try:
            with transaction.atomic():
                asset = form.save(commit=False)
                asset.company = company
                asset.current_value = asset.purchase_cost
                asset.status = Asset.Status.ACTIVE
                asset.number = BaseService.generate_sequence_number(
                    "AST", Asset, company.pk
                )
                asset.save()
            messages.success(
                request, f"Asset {asset.number} — {asset.name} registered."
            )
            return redirect("assets:detail", pk=asset.pk)
        except Exception:
            messages.error(request, "Asset registration failed.")
            return redirect("assets:list")


class ScheduleMaintenanceView(CompanyMixin, View):
    required_permission = "assets.create"
    def post(self, request, pk):
        asset = get_object_or_404(
            Asset, pk=pk, company=self.company(), is_deleted=False
        )
        form = MaintenanceForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Please provide valid maintenance details.")
            return redirect("assets:detail", pk=pk)
        try:
            with transaction.atomic():
                maint = form.save(commit=False)
                maint.company = self.company()
                maint.asset = asset
                maint.number = BaseService.generate_sequence_number(
                    "MNT", AssetMaintenance, self.company().pk
                )
                maint.save()

                asset.status = Asset.Status.UNDER_MAINTENANCE
                asset.save(update_fields=["status"])

            messages.success(request, "Maintenance scheduled.")
        except Exception:
            messages.error(request, "Maintenance could not be scheduled.")
        return redirect("assets:detail", pk=pk)


class CompleteMaintenanceView(CompanyMixin, View):
    required_permission = "assets.approve"
    def post(self, request, maint_pk):
        maint = get_object_or_404(
            AssetMaintenance, pk=maint_pk, company=self.company(), is_deleted=False
        )
        with transaction.atomic():
            maint.status = AssetMaintenance.Status.COMPLETED
            maint.completed_date = timezone.localdate()
            maint.save(update_fields=["status", "completed_date"])

            maint.asset.status = Asset.Status.ACTIVE
            maint.asset.save(update_fields=["status"])

        messages.success(request, "Maintenance marked as completed.")
        return redirect("assets:detail", pk=maint.asset.pk)


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path  # noqa: E402
from django.utils import timezone  # noqa: E402

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
