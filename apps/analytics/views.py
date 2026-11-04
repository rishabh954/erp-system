"""
Enterprise Reporting Engine — Views
All report CRUD, export (Excel/CSV/PDF), pivot, chart, and scheduling.
"""

import json
import logging
import math
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import DetailView, ListView, TemplateView, View

from core.tenancy import get_active_company

from .models import CustomReport, ReportExecution, SavedReport, ScheduledReport
from .services import export_csv, export_excel, export_pdf, get_data, get_pivot_data

logger = logging.getLogger(__name__)

REPORT_MODEL_MAP = {
    "sales": ("sales", "SalesOrder", "company"),
    "purchases": ("purchase", "PurchaseOrder", "company"),
    "accounting": ("accounting", "JournalItem", "journal_entry__company"),
}


def _report_model(module, company_id):
    from .services import get_queryset_for_module

    if module == SavedReport.Module.ACCOUNTS:
        from apps.accounting.models import Account

        return Account
    queryset = get_queryset_for_module(module, company_id)
    if queryset is None:
        raise ValueError("Select a supported report module.")
    return queryset.model


def _valid_report_field(model, value, label="field"):
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError(f"Select a valid report {label}.")
    current_model = model
    for part in value.split("__"):
        if not part or part.startswith("_"):
            raise ValueError(f"Select a valid report {label}.")
        try:
            field = current_model._meta.get_field(part)
        except Exception:
            raise ValueError(f"Select a valid report {label}.") from None
        if field.is_relation:
            current_model = field.related_model
            if current_model is None:
                raise ValueError(f"Select a valid report {label}.")
    return value


def _report_columns(raw, model):
    if isinstance(raw, str):
        columns = [column.strip() for column in raw.split(",") if column.strip()]
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        columns = [item.strip() for item in raw if item.strip()]
    else:
        raise ValueError("Report columns must be a comma-separated list.")
    if not columns or len(columns) > 50:
        raise ValueError("Select between 1 and 50 report columns.")
    if len(set(columns)) != len(columns):
        raise ValueError("Report columns cannot contain duplicates.")
    for column in columns:
        _valid_report_field(model, column, "column")
    return columns


def _report_filters(raw, model):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("Report filters must be valid JSON.") from None
    if not isinstance(raw, dict) or len(raw) > 50:
        raise ValueError("Report filters must be an object with at most 50 fields.")
    for field, value in raw.items():
        _valid_report_field(model, field, "filter")
        if isinstance(value, (list, dict)) or (
            isinstance(value, float) and not math.isfinite(value)
        ):
            raise ValueError("Report filter values must be finite scalar values.")
    return raw


def _parse_report_boolean(value, label):
    if value is None:
        return False
    if value == "on":
        return True
    raise ValueError(f"Invalid value for {label}.")


def _validate_report_payload(data, company_id):
    name = data.get("name", "Untitled Report").strip()
    if not name or len(name) > 200:
        raise ValueError("Report name is required and must be 200 characters or fewer.")
    description = data.get("description", "").strip()
    module = data.get("module", data.get("module_source", "invoices")).strip()
    if module not in SavedReport.Module.values:
        raise ValueError("Select a valid report module.")
    aggregate_function = data.get("aggregate_function")
    if aggregate_function and aggregate_function not in {
        choice[0] for choice in CustomReport.AGGREGATE_CHOICES
    }:
        raise ValueError("Select a valid aggregate function.")
    model = _report_model(module, company_id)

    raw_columns = data.get("columns")
    if raw_columns is None:
        # Older Report Builder clients submit grouping and aggregate fields
        # instead of the column list used by the current report model.
        legacy_columns = [
            data.get("group_by_field", "").strip(),
            data.get("aggregate_field", "").strip(),
        ]
        raw_columns = [column for column in legacy_columns if column]
    columns = _report_columns(raw_columns, model)
    filters = _report_filters(data.get("filters_json", "{}"), model)

    sort_by = data.get("sort_by", "-created_at").strip() or "-created_at"
    sort_field = sort_by[1:] if sort_by.startswith("-") else sort_by
    _valid_report_field(model, sort_field, "sort field")

    chart_type = data.get("chart_type", SavedReport.ChartType.NONE)
    if chart_type not in SavedReport.ChartType.values:
        raise ValueError("Select a valid chart type.")

    optional_fields = {}
    for key in ("chart_group_by", "chart_value_field", "pivot_row", "pivot_col", "pivot_value"):
        value = data.get(key, "").strip()
        if value:
            optional_fields[key] = _valid_report_field(model, value, key.replace("_", " "))
        else:
            optional_fields[key] = ""

    return {
        "name": name,
        "description": description,
        "module": module,
        "columns": columns,
        "filters": filters,
        "sort_by": sort_by,
        "chart_type": chart_type,
        **optional_fields,
        "enable_pivot": _parse_report_boolean(
            data.get("enable_pivot"), "pivot option"
        ),
        "is_public": _parse_report_boolean(data.get("is_public"), "public option"),
    }


def get_reportable_fields(model_class):
    """Return concrete scalar fields that can safely be used in report queries."""
    return {
        field.name
        for field in model_class._meta.concrete_fields
        if not field.is_relation
    }


class ReportsMixin(LoginRequiredMixin):
    """Base mixin for all reporting views."""

    @property
    def company(self):
        company = get_active_company(self.request)
        if not company:
            raise PermissionDenied("No active company membership.")
        return company

    @property
    def company_id(self):
        return self.company.pk

    def get_saved_reports(self):
        company = self.company
        return SavedReport.objects.filter(
            (Q(company=company) & (Q(created_by=self.request.user) | Q(is_public=True)))
            | Q(company__isnull=True, created_by=self.request.user)
        )

    def get_scheduled_reports(self):
        return ScheduledReport.objects.filter(
            report__in=self.get_saved_reports(), created_by=self.request.user
        )


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
        ctx["saved_reports"] = self.get_saved_reports().order_by("-created_at")[:10]
        return ctx

    def post(self, request, *args, **kwargs):
        data = request.POST
        try:
            report_data = _validate_report_payload(data, self.company_id)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("analytics:builder")

        report = SavedReport.objects.create(
            **report_data,
            created_by=request.user,
            company=self.company,
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
        return self.get_saved_reports().order_by("-created_at")


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
            report__in=self.get_saved_reports(), triggered_by=self.request.user
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
        return get_object_or_404(self.get_saved_reports(), pk=self.kwargs["pk"])

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

        ctx["schedules"] = report.schedules.filter(
            is_active=True, created_by=self.request.user
        )
        ctx["executions"] = report.executions.filter(
            triggered_by=self.request.user
        ).order_by("-started_at")[:10]
        return ctx


# ── Export Endpoints ───────────────────────────────────────────────────────────


class ReportExportView(ReportsMixin, View):
    required_permission = "analytics.export"

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
        if fmt not in {"csv", "xlsx", "pdf"}:
            return HttpResponse("Invalid format", status=400)
        report = get_object_or_404(self.get_saved_reports(), pk=pk)
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


class QuickExportView(ReportsMixin, View):
    required_permission = "analytics.export"

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
        if fmt not in {"csv", "xlsx", "pdf"}:
            return HttpResponse("Invalid format", status=400)
        module = request.GET.get("module", "invoices")
        try:
            if module not in SavedReport.Module.values:
                raise ValueError("Select a valid report module.")
            model = _report_model(module, self.company_id)
            columns = _report_columns(
                request.GET.get("columns", "number,status,total,created_at"), model
            )
            sort_by = request.GET.get("sort_by", "-created_at").strip() or "-created_at"
            _valid_report_field(
                model,
                sort_by[1:] if sort_by.startswith("-") else sort_by,
                "sort field",
            )
            raw_limit = request.GET.get("limit", "5000")
            if not raw_limit.isdecimal():
                raise ValueError("Export limit must be a whole number.")
            limit = int(raw_limit)
            if not 1 <= limit <= 10000:
                raise ValueError("Export limit must be between 1 and 10000.")
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

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
        report = get_object_or_404(self.get_saved_reports(), pk=pk)
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
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        if not isinstance(payload, dict):
            return JsonResponse({"error": "The preview request must be an object."}, status=400)

        module = payload.get("module", "")
        columns = payload.get("columns", [])

        # Build sort_by string
        sort_field = payload.get("sort_field", "")
        sort_order = payload.get("sort_order", "asc")
        try:
            if not isinstance(sort_field, str):
                raise ValueError("Sort field must be text.")
            if module not in SavedReport.Module.values:
                raise ValueError("Select a valid report module.")
            model = _report_model(module, self.company_id)
            columns = _report_columns(columns, model)
            if not isinstance(sort_order, str) or sort_order not in {"asc", "desc"}:
                raise ValueError("Select a valid sort order.")
            if sort_field:
                _valid_report_field(model, sort_field, "sort field")
            limit = payload.get("preview_limit", 25)
            if type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError("Preview limit must be a whole number between 1 and 100.")
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

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
        report = get_object_or_404(self.get_saved_reports(), pk=pk)
        data = request.POST
        try:
            frequency = data.get("frequency", ScheduledReport.Frequency.MONTHLY)
            export_format = data.get(
                "export_format", ScheduledReport.ExportFormat.PDF
            )
            if frequency not in ScheduledReport.Frequency.values:
                raise ValueError("Select a valid schedule frequency.")
            if export_format not in ScheduledReport.ExportFormat.values:
                raise ValueError("Select a valid export format.")
            recipients = data.get("recipients", "").strip()
            recipient_list = [email.strip() for email in recipients.split(",")]
            if not recipients or any(not email for email in recipient_list):
                raise ValueError("Enter one or more comma-separated email addresses.")
            for email in recipient_list:
                validate_email(email)
            subject = data.get("subject", "").strip()
            if len(subject) > 255:
                raise ValueError("Subject must be 255 characters or fewer.")
            body = data.get("body", "")
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
            return redirect("analytics:report_detail", pk=pk)

        schedule = ScheduledReport.objects.create(
            report=report,
            frequency=frequency,
            export_format=export_format,
            recipients=", ".join(recipient_list),
            subject=subject,
            body=body,
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
        schedule = get_object_or_404(self.get_scheduled_reports(), pk=pk)
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
        ctx["saved_reports"] = self.get_saved_reports().order_by("-updated_at")[:8]
        ctx["recent_executions"] = (
            ReportExecution.objects.filter(
                report__in=self.get_saved_reports(), triggered_by=user
            )
            .select_related("report")
            .order_by("-started_at")[:10]
        )
        ctx["modules"] = SavedReport.Module.choices
        ctx["scheduled_count"] = self.get_scheduled_reports().filter(
            is_active=True
        ).count()
        return ctx


# ── Report Delete ──────────────────────────────────────────────────────────────


class ReportDeleteView(ReportsMixin, View):
    required_permission = "analytics.delete"
    def post(self, request, pk):
        report = get_object_or_404(self.get_saved_reports(), pk=pk)
        report.delete()
        messages.success(request, f"Report '{report.name}' deleted.")
        return redirect("analytics:saved_reports")


class ReportBulkDeleteView(ReportsMixin, View):
    required_permission = "analytics.delete"
    def post(self, request):
        pks = request.POST.get("pks", "")
        pk_list = [pk.strip() for pk in pks.split(",") if pk.strip()]
        try:
            pk_list = list(dict.fromkeys(str(UUID(pk)) for pk in pk_list))
        except (ValueError, TypeError, AttributeError):
            messages.error(request, "Select valid report IDs.")
            return redirect("analytics:saved_reports")
        if pk_list:
            deleted, _ = self.get_saved_reports().filter(pk__in=pk_list).delete()
            messages.success(request, f"Successfully deleted {deleted} reports.")
        return redirect("analytics:saved_reports")


# ── Legacy / Internal API ────────────────────────────────────────────────────────


class GenerateReportAPIView(ReportsMixin, View):
    required_permission = "analytics.read"
    def get(self, request, *args, **kwargs):
        from django.apps import apps as django_apps

        report_id = request.GET.get("report_id")
        if not report_id:
            return JsonResponse({"error": "No report ID provided"}, status=400)

        report = get_object_or_404(CustomReport, pk=report_id, created_by=request.user)

        model_info = REPORT_MODEL_MAP.get(report.module_source)
        if not model_info:
            return JsonResponse({"error": "Invalid module source"}, status=400)
        app_label, model_name, company_path = model_info

        try:
            ModelClass = django_apps.get_model(app_label, model_name)
        except LookupError:
            return JsonResponse(
                {"error": f"Model not found: {app_label}.{model_name}"}, status=400
            )

        allowed_fields = get_reportable_fields(ModelClass)
        if (
            report.group_by_field not in allowed_fields
            or report.aggregate_field not in allowed_fields
        ):
            return JsonResponse(
                {"error": "Invalid report field."},
                status=400,
            )

        from django.db.models import Avg, Count, Sum

        agg_map = {"sum": Sum, "avg": Avg, "count": Count}
        aggregate_class = agg_map.get(report.aggregate_function)
        if aggregate_class is None:
            return JsonResponse({"error": "Invalid aggregate function."}, status=400)
        agg_func = aggregate_class(report.aggregate_field)

        try:
            qs = (
                ModelClass.objects.filter(**{company_path: self.company})
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
        model_info = REPORT_MODEL_MAP.get(module_source)
        if not model_info:
            return JsonResponse({"fields": []})
        app_label, model_name, _company_path = model_info
        try:
            ModelClass = django_apps.get_model(app_label, model_name)
            return JsonResponse({"fields": sorted(get_reportable_fields(ModelClass))})
        except LookupError:
            return JsonResponse({"fields": []})
