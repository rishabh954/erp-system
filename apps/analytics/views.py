"""
Enterprise Reporting Engine — Views
All report CRUD, export (Excel/CSV/PDF), pivot, chart, and scheduling.
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView, View

from .models import CustomReport, ReportExecution, SavedReport, ScheduledReport
from .services import export_csv, export_excel, export_pdf, get_data, get_pivot_data

logger = logging.getLogger(__name__)


class ReportsMixin(LoginRequiredMixin):
    """Base mixin for all reporting views."""

    @property
    def company_id(self):
        company = self.request.user.primary_company
        return company.id if company else None


# ── Report Builder ─────────────────────────────────────────────────────────────


class ReportBuilderView(ReportsMixin, TemplateView):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    template_name = "analytics/report_builder.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["modules"] = SavedReport.Module.choices
        ctx["chart_types"] = SavedReport.ChartType.choices
        ctx["saved_reports"] = SavedReport.objects.filter(
            created_by=self.request.user
        ).order_by("-created_at")[:10]
        return ctx

    def post(self, request, *args, **kwargs):
        data = request.POST
        columns_raw = data.get("columns", "")
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]

        try:
            filters = json.loads(data.get("filters_json", "{}"))
        except json.JSONDecodeError:
            filters = {}

        report = SavedReport.objects.create(
            name=data.get("name", "Untitled Report"),
            description=data.get("description", ""),
            module=data.get("module", "invoices"),
            columns=columns,
            filters=filters,
            sort_by=data.get("sort_by", "-created_at"),
            chart_type=data.get("chart_type", "none"),
            chart_group_by=data.get("chart_group_by", ""),
            chart_value_field=data.get("chart_value_field", ""),
            enable_pivot=data.get("enable_pivot") == "on",
            pivot_row=data.get("pivot_row", ""),
            pivot_col=data.get("pivot_col", ""),
            pivot_value=data.get("pivot_value", ""),
            created_by=request.user,
            company_id=self.company_id,
            is_public=data.get("is_public") == "on",
        )
        messages.success(request, f"Report '{report.name}' saved successfully!")
        return redirect("analytics:report_detail", pk=report.pk)


# ── Saved Reports List ─────────────────────────────────────────────────────────


class SavedReportsListView(ReportsMixin, ListView):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    template_name = "analytics/saved_reports.html"
    context_object_name = "reports"
    paginate_by = 20

    def get_queryset(self):
        return SavedReport.objects.filter(created_by=self.request.user).order_by(
            "-created_at"
        )


class ExecutionLogListView(ReportsMixin, ListView):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    template_name = "analytics/execution_log.html"
    context_object_name = "executions"
    paginate_by = 30

    def get_queryset(self):
        return ReportExecution.objects.filter(
            report__created_by=self.request.user
        ).order_by("-started_at")


# ── Report Detail / Runner ─────────────────────────────────────────────────────


class ReportDetailView(ReportsMixin, DetailView):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    template_name = "analytics/report_detail.html"
    context_object_name = "report"

    def get_object(self):
        return get_object_or_404(SavedReport, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        report = self.object

        from django.core.cache import cache

        cache_key = f"report_data_{report.pk}_{report.updated_at.timestamp()}"
        data = cache.get(cache_key)

        if data is None:
            data = get_data(
                module=report.module,
                company_id=self.company_id,
                columns=report.columns,
                filters=report.filters,
                sort_by=report.sort_by,
                limit=1000,
            )
            cache.set(cache_key, data, 60 * 15)

        ctx["data"] = data
        ctx["headers"] = report.columns
        ctx["total_rows"] = len(data)

        # Chart data
        if report.chart_type != "none" and report.chart_group_by:
            labels = [r.get(report.chart_group_by, "N/A") for r in data]
            if report.chart_value_field:
                vals_map = {}
                for r in data:
                    k = r.get(report.chart_group_by, "N/A")
                    try:
                        v = float(r.get(report.chart_value_field, 0))
                    except (ValueError, TypeError):
                        v = 0
                    vals_map[k] = vals_map.get(k, 0) + v
                ctx["chart_labels"] = json.dumps(list(vals_map.keys()))
                ctx["chart_values"] = json.dumps(list(vals_map.values()))
            else:
                counted = {}
                for item in labels:
                    counted[item] = counted.get(item, 0) + 1
                ctx["chart_labels"] = json.dumps(list(counted.keys()))
                ctx["chart_values"] = json.dumps(list(counted.values()))

        # Pivot table
        if report.enable_pivot and report.pivot_row and report.pivot_col:
            ctx["pivot_data"] = get_pivot_data(
                data, report.pivot_row, report.pivot_col, report.pivot_value
            )

        ctx["schedules"] = report.schedules.filter(is_active=True)
        ctx["executions"] = report.executions.order_by("-started_at")[:10]
        return ctx


# ── Export Endpoints ───────────────────────────────────────────────────────────


class ReportExportView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    """Handle CSV, Excel, PDF export for a saved report."""

    def get(self, request, pk, fmt):
        report = get_object_or_404(SavedReport, pk=pk)
        data = get_data(
            module=report.module,
            company_id=self.company_id,
            columns=report.columns,
            filters=report.filters,
            sort_by=report.sort_by,
            limit=10000,
        )
        safe_name = report.name.replace(" ", "_")
        timestamp = timezone.now().strftime("%Y%m%d_%H%M")
        filename = f"{safe_name}_{timestamp}"

        # Log execution
        ReportExecution.objects.create(
            report=report,
            triggered_by=request.user,
            status="success",
            row_count=len(data),
            export_format=fmt,
            completed_at=timezone.now(),
        )

        if fmt == "csv":
            return export_csv(data, f"{filename}.csv")
        elif fmt == "xlsx":
            return export_excel(data, f"{filename}.xlsx", sheet_name=report.name[:30])
        elif fmt == "pdf":
            return export_pdf(data, report_name=report.name, filename=f"{filename}.pdf")
        else:
            return HttpResponse("Invalid format", status=400)


class QuickExportView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    """Quick export from a module+columns+filters URL params — no saved report needed."""

    def get(self, request, fmt):
        module = request.GET.get("module", "invoices")
        columns_raw = request.GET.get("columns", "number,status,total,created_at")
        columns = [c.strip() for c in columns_raw.split(",") if c.strip()]
        sort_by = request.GET.get("sort_by", "-created_at")
        limit = int(request.GET.get("limit", 5000))

        data = get_data(
            module=module,
            company_id=self.company_id,
            columns=columns,
            filters={},
            sort_by=sort_by,
            limit=limit,
        )

        safe_module = module.replace("_", "-")
        timestamp = timezone.now().strftime("%Y%m%d_%H%M")
        filename = f"{safe_module}_{timestamp}"

        if fmt == "csv":
            return export_csv(data, f"{filename}.csv")
        elif fmt == "xlsx":
            return export_excel(
                data, f"{filename}.xlsx", sheet_name=module.replace("_", " ").title()
            )
        elif fmt == "pdf":
            return export_pdf(
                data,
                report_name=module.replace("_", " ").title(),
                filename=f"{filename}.pdf",
            )
        return HttpResponse("Invalid format", status=400)


# ── Report API (JSON data for charts) ─────────────────────────────────────────


class ReportDataAPIView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    """Returns report data as JSON for dynamic chart rendering."""

    def get(self, request, pk):
        report = get_object_or_404(SavedReport, pk=pk)
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 50))
        offset = (page - 1) * page_size

        data = get_data(
            module=report.module,
            company_id=self.company_id,
            columns=report.columns,
            filters=report.filters,
            sort_by=report.sort_by,
            limit=None,
        )

        total = len(data)
        page_data = data[offset : offset + page_size]

        return JsonResponse(
            {
                "data": page_data,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            }
        )


class PreviewAPIView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    """Generates preview data for the Report Builder."""

    def post(self, request):
        try:
            payload = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

        module = payload.get("module", "")
        columns = payload.get("columns", [])
        limit = payload.get("preview_limit", 25)

        # Build sort_by string
        sort_field = payload.get("sort_field", "")
        sort_order = payload.get("sort_order", "asc")
        sort_by = (
            f"-{sort_field}" if sort_order == "desc" and sort_field else sort_field
        )

        # For simplicity in the preview, we just fetch basic data.
        # More advanced filtering can be mapped here if needed.
        data = get_data(
            module=module,
            company_id=self.company_id,
            columns=columns,
            filters={},  # Can be expanded based on payload.get('filters')
            sort_by=sort_by,
            limit=limit,
        )

        # Format rows as lists corresponding to the columns order
        rows = []
        for d in data:
            row = []
            for col in columns:
                row.append(d.get(col, ""))
            rows.append(row)

        response_data = {
            "headers": columns,
            "rows": rows,
            "truncated": len(data) == limit,
            "chart": {"type": "none"},
        }

        # Basic chart handling if requested
        chart_type = payload.get("chart_type", "none")
        if chart_type != "none":
            group_by = payload.get("group_by", "")
            val_field = payload.get("value_field", "")
            if group_by:
                labels_dict = {}
                for r in data:
                    k = str(r.get(group_by, "N/A"))
                    try:
                        v = float(r.get(val_field, 1)) if val_field else 1
                    except Exception:
                        v = 1
                    labels_dict[k] = labels_dict.get(k, 0) + v

                response_data["chart"] = {
                    "type": chart_type,
                    "labels": list(labels_dict.keys()),
                    "values": list(labels_dict.values()),
                    "value_label": val_field or "Count",
                }

        # Basic pivot handling if requested
        if payload.get("is_pivot"):
            pivot_row = payload.get("pivot_row")
            pivot_col = payload.get("pivot_col")
            pivot_val = payload.get("pivot_value")
            if pivot_row and pivot_col:
                response_data["pivot"] = get_pivot_data(
                    data, pivot_row, pivot_col, pivot_val
                )

        return JsonResponse(response_data)


class ModuleFieldsAPIView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    """Returns the available columns for a given module."""

    FIELD_HINTS = {
        "sales_orders": [
            "number",
            "status",
            "total",
            "customer__name",
            "order_date",
            "delivery_date",
        ],
        "invoices": [
            "number",
            "status",
            "total",
            "balance_due",
            "customer__name",
            "invoice_date",
            "due_date",
        ],
        "customers": ["name", "phone", "email", "city", "country", "created_at"],
        "leads": [
            "name",
            "status",
            "source",
            "expected_value",
            "assigned_to__email",
            "created_at",
        ],
        "purchase_orders": ["number", "status", "total", "vendor__name", "order_date"],
        "purchase_invoices": [
            "number",
            "status",
            "total",
            "vendor__name",
            "bill_date",
            "due_date",
        ],
        "vendors": ["name", "phone", "email", "city", "country"],
        "inventory": [
            "product__name",
            "product__sku",
            "warehouse__name",
            "quantity",
            "average_cost",
        ],
        "products": [
            "name",
            "sku",
            "category__name",
            "standard_price",
            "product_type",
            "is_active",
        ],
        "employees": [
            "first_name",
            "last_name",
            "employee_id",
            "department__name",
            "designation",
            "status",
        ],
        "payroll": [
            "employee__first_name",
            "employee__last_name",
            "gross_salary",
            "net_salary",
            "status",
        ],
        "attendance": [
            "employee__first_name",
            "employee__last_name",
            "date",
            "status",
            "check_in",
            "check_out",
        ],
        "leave_requests": [
            "employee__first_name",
            "leave_type__name",
            "start_date",
            "end_date",
            "status",
        ],
        "journal_entries": ["number", "date", "status", "reference", "narration"],
        "manufacturing_orders": [
            "number",
            "status",
            "quantity_to_produce",
            "quantity_produced",
            "planned_start_date",
        ],
        "projects": [
            "name",
            "number",
            "status",
            "manager__email",
            "budget",
            "actual_cost",
            "start_date",
            "end_date",
        ],
        "tasks": [
            "title",
            "status",
            "priority",
            "project__name",
            "assigned_to__email",
            "due_date",
        ],
        "timesheets": ["user__email", "task__title", "date", "hours", "is_billable"],
        "helpdesk_tickets": [
            "number",
            "subject",
            "status",
            "priority",
            "customer__name",
            "assigned_to__email",
        ],
        "assets": [
            "name",
            "asset_code",
            "category__name",
            "status",
            "purchase_value",
            "current_value",
        ],
    }

    def get(self, request):
        module = request.GET.get("module", "")
        fields = self.FIELD_HINTS.get(module, [])
        return JsonResponse({"fields": fields})


# ── Scheduled Reports ──────────────────────────────────────────────────────────


class ScheduleReportView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    """Create or update a report schedule."""

    def post(self, request, pk):
        report = get_object_or_404(SavedReport, pk=pk)
        data = request.POST
        schedule = ScheduledReport.objects.create(
            report=report,
            frequency=data.get("frequency", "monthly"),
            export_format=data.get("export_format", "pdf"),
            recipients=data.get("recipients", ""),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            is_active=True,
            created_by=request.user,
        )
        messages.success(
            request,
            f"Report scheduled {schedule.frequency}! Will email: {schedule.recipients}",
        )
        return redirect("analytics:report_detail", pk=pk)


class ScheduleDeleteView(ReportsMixin, View):
    required_permission = "analytics.delete"
    def post(self, request, pk):
        schedule = get_object_or_404(ScheduledReport, pk=pk)
        report_pk = schedule.report_id
        schedule.delete()
        messages.success(request, "Schedule removed.")
        return redirect("analytics:report_detail", pk=report_pk)


# ── Analytics Dashboard ────────────────────────────────────────────────────────


class AnalyticsDashboardView(ReportsMixin, TemplateView):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    template_name = "analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["saved_reports"] = SavedReport.objects.filter(created_by=user).order_by(
            "-updated_at"
        )[:8]
        ctx["recent_executions"] = (
            ReportExecution.objects.filter(triggered_by=user)
            .select_related("report")
            .order_by("-started_at")[:10]
        )
        ctx["modules"] = SavedReport.Module.choices
        ctx["scheduled_count"] = ScheduledReport.objects.filter(
            created_by=user, is_active=True
        ).count()
        return ctx


# ── Report Delete ──────────────────────────────────────────────────────────────


class ReportDeleteView(ReportsMixin, View):
    required_permission = "analytics.delete"
    def post(self, request, pk):
        report = get_object_or_404(SavedReport, pk=pk, created_by=request.user)
        report.delete()
        messages.success(request, f"Report '{report.name}' deleted.")
        return redirect("analytics:saved_reports")


class ReportBulkDeleteView(ReportsMixin, View):
    required_permission = "analytics.delete"
    def post(self, request):
        pks = request.POST.get("pks", "")
        pk_list = [pk.strip() for pk in pks.split(",") if pk.strip()]
        if pk_list:
            deleted, _ = SavedReport.objects.filter(
                pk__in=pk_list, created_by=request.user
            ).delete()
            messages.success(request, f"Successfully deleted {deleted} reports.")
        return redirect("analytics:saved_reports")


# ── Legacy / Internal API ────────────────────────────────────────────────────────


class GenerateReportAPIView(ReportsMixin, View):
    required_permission = "analytics.approve"
    def get(self, request, *args, **kwargs):
        from django.apps import apps as django_apps

        report_id = request.GET.get("report_id")
        if not report_id:
            return JsonResponse({"error": "No report ID provided"}, status=400)

        report = get_object_or_404(CustomReport, pk=report_id, created_by=request.user)

        model_map = {
            "sales": ("sales", "SalesOrder"),
            "purchases": ("purchase", "PurchaseOrder"),
            "accounting": ("accounting", "JournalItem"),
        }
        app_label, model_name = model_map.get(report.module_source, (None, None))
        if not app_label:
            return JsonResponse({"error": "Invalid module source"}, status=400)

        try:
            ModelClass = django_apps.get_model(app_label, model_name)
        except LookupError:
            return JsonResponse(
                {"error": f"Model not found: {app_label}.{model_name}"}, status=400
            )

        from django.db.models import Avg, Count, Sum

        agg_map = {"sum": Sum, "avg": Avg, "count": Count}
        agg_func = agg_map.get(report.aggregate_function, Count)(report.aggregate_field)

        try:
            qs = (
                ModelClass.objects.all()
                .values(report.group_by_field)
                .annotate(value=agg_func)
                .order_by(report.group_by_field)
            )
            labels = [str(r[report.group_by_field]) or "Unknown" for r in qs]
            values = [float(r["value"] or 0) for r in qs]
            return JsonResponse(
                {
                    "labels": labels,
                    "values": values,
                    "chart_type": report.chart_type,
                    "name": report.name,
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=400)


class GetModuleFieldsAPIView(ReportsMixin, View):
    required_permission = "analytics.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "analytics.create"
            elif request.method in ["PUT", "PATCH"]:
                return "analytics.update"
            elif request.method == "DELETE":
                return "analytics.delete"
        return self.required_permission
    def get(self, request, *args, **kwargs):
        from django.apps import apps as django_apps

        module_source = request.GET.get("module", "")
        model_map = {
            "sales": ("sales", "SalesOrder"),
            "purchases": ("purchase", "PurchaseOrder"),
            "accounting": ("accounting", "JournalItem"),
        }
        app_label, model_name = model_map.get(module_source, (None, None))
        if not app_label:
            return JsonResponse({"fields": []})
        try:
            ModelClass = django_apps.get_model(app_label, model_name)
            fields = [
                f.name
                for f in ModelClass._meta.get_fields()
                if not f.is_relation or f.many_to_one
            ]
            return JsonResponse({"fields": sorted(fields)})
        except LookupError:
            return JsonResponse({"fields": []})
