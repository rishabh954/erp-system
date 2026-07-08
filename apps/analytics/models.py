"""
Enterprise Reporting Engine — Models
Provides SavedReport, ScheduledReport, ReportExecution for all modules.
"""

import uuid

from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class SavedReport(models.Model):
    """
    A user-defined report configuration that can be saved and re-run.
    Stores the module, filters, columns, chart type and display options.
    """

    class Module(models.TextChoices):
        SALES_ORDERS = "sales_orders", "Sales Orders"
        INVOICES = "invoices", "Invoices"
        CUSTOMERS = "customers", "Customers"
        LEADS = "leads", "Leads (CRM)"
        PURCHASE_ORDERS = "purchase_orders", "Purchase Orders"
        PURCHASE_INVOICES = "purchase_invoices", "Purchase Invoices"
        VENDORS = "vendors", "Vendors"
        INVENTORY = "inventory", "Inventory / Stock"
        PRODUCTS = "products", "Products"
        EMPLOYEES = "employees", "Employees"
        PAYROLL = "payroll", "Payroll"
        ATTENDANCE = "attendance", "Attendance"
        LEAVE_REQUESTS = "leave_requests", "Leave Requests"
        JOURNAL_ENTRIES = "journal_entries", "Journal Entries"
        ACCOUNTS = "accounts", "Chart of Accounts"
        MANUFACTURING_ORDERS = "manufacturing_orders", "Manufacturing Orders"
        PROJECTS = "projects", "Projects"
        TASKS = "tasks", "Tasks"
        TIMESHEETS = "timesheets", "Timesheets"
        HELPDESK_TICKETS = "helpdesk_tickets", "Helpdesk Tickets"
        ASSETS = "assets", "Fixed Assets"

    class ChartType(models.TextChoices):
        NONE = "none", "No Chart (Table Only)"
        BAR = "bar", "Bar Chart"
        LINE = "line", "Line Chart"
        PIE = "pie", "Pie Chart"
        DOUGHNUT = "doughnut", "Doughnut Chart"
        AREA = "area", "Area Chart"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    module = models.CharField(max_length=50, choices=Module.choices)

    # Column config — stored as JSON list of field names
    columns = models.JSONField(default=list, help_text="List of field names to include")

    # Filter config — stored as JSON dict {field: value}
    filters = models.JSONField(
        default=dict, help_text="Dict of filter key->value pairs"
    )

    # Sorting — field name, prefix with - for descending
    sort_by = models.CharField(max_length=100, blank=True, default="-created_at")

    # Chart config
    chart_type = models.CharField(
        max_length=20, choices=ChartType.choices, default=ChartType.NONE
    )
    chart_group_by = models.CharField(
        max_length=100, blank=True, help_text="Field to group/label chart by"
    )
    chart_value_field = models.CharField(
        max_length=100, blank=True, help_text="Field for chart values"
    )

    # Pivot table config
    enable_pivot = models.BooleanField(default=False)
    pivot_row = models.CharField(max_length=100, blank=True)
    pivot_col = models.CharField(max_length=100, blank=True)
    pivot_value = models.CharField(max_length=100, blank=True)

    # Ownership
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="saved_reports"
    )
    company_id = models.IntegerField(null=True, blank=True, db_index=True)
    is_public = models.BooleanField(
        default=False, help_text="Visible to all users in the company"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "reports_saved_report"

    def __str__(self):
        return self.name


class ScheduledReport(models.Model):
    """
    A report scheduled to run automatically and be emailed to recipients.
    Uses Celery Beat for scheduling.
    """

    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        BIWEEKLY = "biweekly", "Every 2 Weeks"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"

    class ExportFormat(models.TextChoices):
        PDF = "pdf", "PDF"
        EXCEL = "xlsx", "Excel (XLSX)"
        CSV = "csv", "CSV"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        SavedReport, on_delete=models.CASCADE, related_name="schedules"
    )
    frequency = models.CharField(max_length=20, choices=Frequency.choices)
    export_format = models.CharField(
        max_length=10, choices=ExportFormat.choices, default=ExportFormat.PDF
    )

    # Email settings
    recipients = models.TextField(help_text="Comma-separated email addresses")
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    last_run = models.DateTimeField(null=True, blank=True)
    next_run = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="scheduled_reports"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reports_scheduled_report"

    def get_recipients_list(self):
        return [e.strip() for e in self.recipients.split(",") if e.strip()]

    def __str__(self):
        return f"{self.report.name} [{self.frequency}]"


class ReportExecution(models.Model):
    """
    Log of every time a report was run (manually or via schedule).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    report = models.ForeignKey(
        SavedReport, on_delete=models.SET_NULL, null=True, related_name="executions"
    )
    schedule = models.ForeignKey(
        ScheduledReport, on_delete=models.SET_NULL, null=True, blank=True
    )
    triggered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    row_count = models.IntegerField(default=0)
    export_format = models.CharField(max_length=10, blank=True)
    file_path = models.CharField(max_length=500, blank=True)
    error_message = models.TextField(blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        db_table = "reports_execution"

    def __str__(self):
        return f"Run of {self.report} at {self.started_at}"


# Legacy CustomReport kept for backward compatibility
class CustomReport(models.Model):
    MODULE_CHOICES = [
        ("sales", "Sales Orders"),
        ("purchases", "Purchase Orders"),
        ("inventory", "Inventory Transactions"),
        ("accounting", "Journal Items"),
    ]

    CHART_CHOICES = [
        ("bar", "Bar Chart"),
        ("line", "Line Chart"),
        ("pie", "Pie Chart"),
        ("doughnut", "Doughnut Chart"),
        ("table", "Data Table"),
    ]

    AGGREGATE_CHOICES = [
        ("sum", "Sum"),
        ("count", "Count"),
        ("avg", "Average"),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    module_source = models.CharField(max_length=50, choices=MODULE_CHOICES)
    chart_type = models.CharField(max_length=20, choices=CHART_CHOICES, default="bar")
    group_by_field = models.CharField(max_length=100)
    aggregate_field = models.CharField(max_length=100)
    aggregate_function = models.CharField(
        max_length=20, choices=AGGREGATE_CHOICES, default="sum"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="analytics_reports"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
