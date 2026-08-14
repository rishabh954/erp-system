"""
Administration Module Models
Covers: Designations, Number Series, Approval Matrix, Communication Config,
        Document Templates, Import/Export, Backup, Audit/Activity Logs,
        API Keys, Integrations, Webhooks, Dashboard/Report Builder, System Settings
"""

import secrets

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped, UUIDModel

# ═══════════════════════════════ DESIGNATION ══════════════════════════════════


class Designation(CompanyScoped):
    """Job designation / title within a company."""

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, blank=True)
    department = models.ForeignKey(
        "company.Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="designations",
    )
    level = models.PositiveSmallIntegerField(
        default=1, help_text="Hierarchy level (1=entry, 10=C-suite)"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_designations"
        ordering = ["level", "name"]

    def __str__(self):
        return self.name


# ══════════════════════════════ NUMBER SERIES ═════════════════════════════════


class NumberSeries(CompanyScoped):
    """Auto-numbering rules for each document type."""

    class DocType(models.TextChoices):
        QUOTATION = "quotation", _("Quotation")
        SALES_ORDER = "sales_order", _("Sales Order")
        INVOICE = "invoice", _("Invoice")
        CREDIT_NOTE = "credit_note", _("Credit Note")
        PURCHASE_REQUEST = "purchase_request", _("Purchase Request")
        PURCHASE_ORDER = "purchase_order", _("Purchase Order")
        BILL = "bill", _("Bill")
        RECEIPT = "receipt", _("Receipt")
        PAYMENT = "payment", _("Payment")
        JOURNAL_ENTRY = "journal_entry", _("Journal Entry")
        LEAD = "lead", _("Lead")
        EMPLOYEE = "employee", _("Employee")
        PAYSLIP = "payslip", _("Payslip")
        LEAVE_REQUEST = "leave_request", _("Leave Request")
        EXPENSE_CLAIM = "expense_claim", _("Expense Claim")
        MFG_ORDER = "mfg_order", _("Manufacturing Order")
        ASSET = "asset", _("Asset")
        HELPDESK_TICKET = "helpdesk_ticket", _("Helpdesk Ticket")

    doc_type = models.CharField(max_length=50, choices=DocType.choices)
    prefix = models.CharField(max_length=20, default="", blank=True)
    suffix = models.CharField(max_length=20, default="", blank=True)
    padding = models.PositiveSmallIntegerField(
        default=4, help_text="Zero-padding length"
    )
    current_sequence = models.PositiveIntegerField(default=0)
    reset_period = models.CharField(
        max_length=10,
        choices=[("never", "Never"), ("yearly", "Yearly"), ("monthly", "Monthly")],
        default="never",
    )
    last_reset = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_number_series"
        unique_together = ("company", "doc_type")

    def __str__(self):
        return f"{self.company.name} | {self.get_doc_type_display()}"

    def get_next_number(self):
        """Atomically increments and returns the next formatted number."""
        from django.db import transaction

        with transaction.atomic():
            obj = NumberSeries.objects.select_for_update().get(pk=self.pk)
            obj.current_sequence += 1
            obj.save(update_fields=["current_sequence"])
            seq = str(obj.current_sequence).zfill(obj.padding)

            import datetime

            now = datetime.timezone.now()

            prefix = obj.prefix or ""
            suffix = obj.suffix or ""

            # Fetch active fiscal year if {FY} or {FY_SHORT} is used
            if (
                "{FY}" in prefix
                or "{FY}" in suffix
                or "{FY_SHORT}" in prefix
                or "{FY_SHORT}" in suffix
            ):
                from apps.company.models import FiscalYear

                fy = FiscalYear.objects.filter(
                    company=obj.company, is_current=True
                ).first()
                fy_str = fy.name if fy else f"{now.year}/{str(now.year + 1)[-2:]}"

                # For {FY_SHORT}, convert "FY 2026-2027" to "2026/27"
                import re

                match = re.search(r"(\d{4})-(\d{4})", fy_str)
                if match:
                    fy_short_str = f"{match.group(1)}/{match.group(2)[-2:]}"
                else:
                    fy_short_str = fy_str

                prefix = prefix.replace("{FY}", fy_str).replace(
                    "{FY_SHORT}", fy_short_str
                )
                suffix = suffix.replace("{FY}", fy_str).replace(
                    "{FY_SHORT}", fy_short_str
                )

            # Replace date variables
            date_replacements = {
                "{YYYY}": now.strftime("%Y"),
                "{YY}": now.strftime("%y"),
                "{MM}": now.strftime("%m"),
                "{DD}": now.strftime("%d"),
            }
            for key, val in date_replacements.items():
                prefix = prefix.replace(key, val)
                suffix = suffix.replace(key, val)

            return f"{prefix}{seq}{suffix}"


# ══════════════════════════════ APPROVAL MATRIX ═══════════════════════════════


class ApprovalMatrix(CompanyScoped):
    """Threshold-based approval routing (e.g. PO > ₹50,000 → CFO)."""

    class DocType(models.TextChoices):
        PURCHASE_ORDER = "purchase_order", _("Purchase Order")
        EXPENSE_CLAIM = "expense_claim", _("Expense Claim")
        LEAVE_REQUEST = "leave_request", _("Leave Request")
        SALES_DISCOUNT = "sales_discount", _("Sales Discount")
        CREDIT_NOTE = "credit_note", _("Credit Note")
        JOURNAL_ENTRY = "journal_entry", _("Journal Entry")

    doc_type = models.CharField(max_length=50, choices=DocType.choices)
    name = models.CharField(max_length=200)
    min_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    max_amount = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leave blank for unlimited",
    )
    approver_role = models.CharField(max_length=50, blank=True)
    approver_user = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_assignments",
    )
    level = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_approval_matrix"
        ordering = ["doc_type", "level", "min_amount"]

    def __str__(self):
        return f"{self.name} ({self.get_doc_type_display()} L{self.level})"


# ═══════════════════════════ COMMUNICATION CONFIG ════════════════════════════


class EmailConfig(CompanyScoped):
    """SMTP email configuration per company."""

    name = models.CharField(max_length=100, default="Default")
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField(default=587)
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=100, blank=True)
    reply_to = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "admin_email_configs"

    def __str__(self):
        return f"{self.name} ({self.host})"


class SMSConfig(CompanyScoped):
    """SMS gateway configuration."""

    class Provider(models.TextChoices):
        TWILIO = "twilio", _("Twilio")
        MSG91 = "msg91", _("MSG91")
        NEXMO = "nexmo", _("Vonage / Nexmo")
        FAST2SMS = "fast2sms", _("Fast2SMS")
        CUSTOM = "custom", _("Custom HTTP")

    name = models.CharField(max_length=100, default="Default SMS")
    provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.TWILIO
    )
    api_key = models.CharField(max_length=500)
    api_secret = models.CharField(max_length=500, blank=True)
    sender_id = models.CharField(max_length=20, blank=True)
    base_url = models.URLField(blank=True, help_text="For custom HTTP provider")
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "admin_sms_configs"

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"


class WhatsAppConfig(CompanyScoped):
    """WhatsApp Business API configuration."""

    class Provider(models.TextChoices):
        META_CLOUD = "meta_cloud", _("Meta Cloud API")
        TWILIO = "twilio", _("Twilio")
        WATI = "wati", _("WATI")
        GUPSHUP = "gupshup", _("Gupshup")

    name = models.CharField(max_length=100, default="Default WhatsApp")
    provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.META_CLOUD
    )
    phone_number_id = models.CharField(max_length=100, blank=True)
    waba_id = models.CharField(max_length=100, blank=True, verbose_name="WABA ID")
    access_token = models.TextField(blank=True)
    api_key = models.CharField(max_length=500, blank=True)
    webhook_verify_token = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_whatsapp_configs"

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"


class NotificationTemplate(CompanyScoped):
    """Reusable notification templates for email/SMS/WhatsApp."""

    class Channel(models.TextChoices):
        EMAIL = "email", _("Email")
        SMS = "sms", _("SMS")
        WHATSAPP = "whatsapp", _("WhatsApp")
        IN_APP = "in_app", _("In-App")

    class TriggerEvent(models.TextChoices):
        INVOICE_CREATED = "invoice_created", _("Invoice Created")
        PAYMENT_RECEIVED = "payment_received", _("Payment Received")
        PO_APPROVED = "po_approved", _("Purchase Order Approved")
        LEAVE_APPROVED = "leave_approved", _("Leave Approved")
        LEAVE_REJECTED = "leave_rejected", _("Leave Rejected")
        PAYSLIP_GENERATED = "payslip_generated", _("Payslip Generated")
        TICKET_CREATED = "ticket_created", _("Ticket Created")
        TICKET_RESOLVED = "ticket_resolved", _("Ticket Resolved")
        USER_INVITED = "user_invited", _("User Invited")
        CUSTOM = "custom", _("Custom")

    name = models.CharField(max_length=200)
    channel = models.CharField(max_length=20, choices=Channel.choices)
    trigger_event = models.CharField(
        max_length=50, choices=TriggerEvent.choices, default=TriggerEvent.CUSTOM
    )
    subject = models.CharField(
        max_length=500, blank=True, help_text="Email subject (supports {{variables}})"
    )
    body = models.TextField(
        help_text="Template body. Use {{variable_name}} for placeholders."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "admin_notification_templates"

    def __str__(self):
        return f"{self.name} ({self.get_channel_display()})"


# ══════════════════════════ DOCUMENT TEMPLATE BUILDER ════════════════════════


class DocumentTemplate(CompanyScoped):
    """HTML/Jinja2 document templates for printed documents."""

    class DocType(models.TextChoices):
        INVOICE = "invoice", _("Invoice")
        QUOTATION = "quotation", _("Quotation")
        PURCHASE_ORDER = "purchase_order", _("Purchase Order")
        DELIVERY_NOTE = "delivery_note", _("Delivery Note")
        PAYSLIP = "payslip", _("Payslip")
        RECEIPT = "receipt", _("Receipt")
        OFFER_LETTER = "offer_letter", _("Offer Letter")
        CUSTOM = "custom", _("Custom")

    name = models.CharField(max_length=200)
    doc_type = models.CharField(max_length=30, choices=DocType.choices)
    html_content = models.TextField(
        help_text="Jinja2 HTML template. Variables: {{invoice}}, {{company}}, etc."
    )
    css_content = models.TextField(blank=True, help_text="Custom CSS for print styling")
    is_default = models.BooleanField(default=False)
    page_size = models.CharField(
        max_length=10,
        choices=[("A4", "A4"), ("A5", "A5"), ("Letter", "Letter")],
        default="A4",
    )
    orientation = models.CharField(
        max_length=10,
        choices=[("portrait", "Portrait"), ("landscape", "Landscape")],
        default="portrait",
    )

    class Meta:
        db_table = "admin_document_templates"

    def __str__(self):
        return f"{self.name} ({self.get_doc_type_display()})"


# ═══════════════════════════ IMPORT / EXPORT ══════════════════════════════════


class ImportJob(CompanyScoped):
    """Tracks data import jobs (CSV/Excel)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    class Module(models.TextChoices):
        CUSTOMERS = "customers", _("Customers")
        VENDORS = "vendors", _("Vendors")
        PRODUCTS = "products", _("Products")
        EMPLOYEES = "employees", _("Employees")
        ACCOUNTS = "accounts", _("Chart of Accounts")
        LEADS = "leads", _("Leads")

    module = models.CharField(max_length=30, choices=Module.choices)
    file = models.FileField(upload_to="imports/")
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    total_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    error_log = models.TextField(blank=True)
    imported_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="import_jobs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admin_import_jobs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Import {self.get_module_display()} — {self.status}"


class ExportJob(CompanyScoped):
    """Tracks data export requests."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PROCESSING = "processing", _("Processing")
        READY = "ready", _("Ready")
        FAILED = "failed", _("Failed")

    module = models.CharField(max_length=50)
    filters = models.JSONField(default=dict)
    format = models.CharField(
        max_length=10,
        choices=[("csv", "CSV"), ("xlsx", "Excel"), ("pdf", "PDF")],
        default="csv",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    output_file = models.FileField(upload_to="exports/", null=True, blank=True)
    requested_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="export_jobs",
    )
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admin_export_jobs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Export {self.module} ({self.format}) — {self.status}"


# ═══════════════════════════════ BACKUP ════════════════════════════════════════


class BackupRecord(CompanyScoped):
    """Tracks database and media backup records."""

    class BackupType(models.TextChoices):
        FULL = "full", _("Full Backup")
        DATABASE = "database", _("Database Only")
        MEDIA = "media", _("Media Only")

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", _("In Progress")
        COMPLETED = "completed", _("Completed")
        FAILED = "failed", _("Failed")

    backup_type = models.CharField(
        max_length=20, choices=BackupType.choices, default=BackupType.FULL
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.IN_PROGRESS
    )
    file_path = models.CharField(max_length=500, blank=True)
    file_size = models.BigIntegerField(default=0, help_text="Bytes")
    initiated_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="backups",
    )
    notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admin_backup_records"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_backup_type_display()} — {self.status} — {self.created_at.date()}"

    @property
    def file_size_display(self):
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024**2:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / 1024**2:.1f} MB"


# ════════════════════════════ AUDIT & ACTIVITY LOGS ══════════════════════════


class AuditLog(UUIDModel):
    """Field-level change tracking across all models."""

    class Action(models.TextChoices):
        CREATE = "create", _("Create")
        UPDATE = "update", _("Update")
        DELETE = "delete", _("Delete")
        LOGIN = "login", _("Login")
        LOGOUT = "logout", _("Logout")
        EXPORT = "export", _("Export")
        IMPORT = "import", _("Import")

    company = models.ForeignKey(
        "company.Company",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_audit_logs",
    )
    user = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_audit_logs",
    )
    action = models.CharField(
        max_length=20, choices=Action.choices, default=Action.CREATE, db_index=True
    )
    model_name = models.CharField(max_length=100, db_index=True)
    object_id = models.CharField(max_length=100, blank=True)
    object_repr = models.CharField(max_length=300, blank=True)
    changes = models.JSONField(
        default=dict, help_text='{"field": {"old": ..., "new": ...}}'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "admin_audit_logs"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["user", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.action} on {self.model_name} by {self.user} at {self.timestamp}"


class ActivityLog(UUIDModel):
    """High-level user activity stream (page views, module access, etc.)."""

    class ActivityType(models.TextChoices):
        LOGIN = "login", _("Logged In")
        LOGOUT = "logout", _("Logged Out")
        PAGE_VIEW = "page_view", _("Page View")
        RECORD_VIEW = "record_view", _("Record Viewed")
        SEARCH = "search", _("Search")
        REPORT_RUN = "report_run", _("Report Run")
        EXPORT = "export", _("Data Exported")
        IMPORT = "import", _("Data Imported")
        SETTINGS_CHANGE = "settings_change", _("Settings Changed")

    company = models.ForeignKey(
        "company.Company",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_activity_logs",
    )
    user = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_activity_logs",
    )
    activity_type = models.CharField(
        max_length=30, choices=ActivityType.choices, db_index=True
    )
    description = models.CharField(max_length=500)
    module = models.CharField(max_length=50, blank=True, db_index=True)
    url = models.CharField(max_length=500, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    extra_data = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "admin_activity_logs"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.user} — {self.get_activity_type_display()} — {self.timestamp}"


# ═══════════════════════════ API MANAGEMENT ════════════════════════════════════


class APIKey(CompanyScoped):
    """Scoped API keys for external system integrations."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        REVOKED = "revoked", _("Revoked")
        EXPIRED = "expired", _("Expired")

    name = models.CharField(max_length=200)
    key = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ACTIVE
    )
    scopes = models.JSONField(
        default=list, help_text='["read:invoices", "write:orders"]'
    )
    created_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="api_keys",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    request_count = models.PositiveBigIntegerField(default=0)
    rate_limit = models.PositiveIntegerField(
        default=1000, help_text="Requests per hour"
    )

    class Meta:
        db_table = "admin_api_keys"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.key:
            self.key = secrets.token_urlsafe(48)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.status})"


# ══════════════════════════ INTEGRATION CENTER ════════════════════════════════


class Integration(CompanyScoped):
    """Third-party integration configurations."""

    class IntegrationType(models.TextChoices):
        PAYMENT_GATEWAY = "payment_gateway", _("Payment Gateway")
        ECOMMERCE = "ecommerce", _("E-Commerce")
        SHIPPING = "shipping", _("Shipping / Logistics")
        ACCOUNTING = "accounting", _("Accounting Software")
        CRM = "crm", _("CRM")
        MARKETING = "marketing", _("Marketing")
        HR = "hr", _("HR Software")
        CUSTOM = "custom", _("Custom API")

    class Status(models.TextChoices):
        CONNECTED = "connected", _("Connected")
        DISCONNECTED = "disconnected", _("Disconnected")
        ERROR = "error", _("Error")

    name = models.CharField(max_length=200)
    integration_type = models.CharField(max_length=30, choices=IntegrationType.choices)
    provider = models.CharField(
        max_length=100, help_text="e.g. Razorpay, Shopify, Shiprocket"
    )
    credentials = models.JSONField(default=dict, help_text="Encrypted credentials JSON")
    settings = models.JSONField(default=dict, help_text="Provider-specific settings")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DISCONNECTED
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "admin_integrations"

    def __str__(self):
        return f"{self.name} ({self.provider})"


class WebhookEndpoint(CompanyScoped):
    """Outbound webhook subscriptions."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        INACTIVE = "inactive", _("Inactive")
        FAILED = "failed", _("Failed")

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    secret = models.CharField(
        max_length=200, blank=True, help_text="HMAC signing secret"
    )
    events = models.JSONField(
        default=list, help_text='["invoice.created", "order.shipped"]'
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ACTIVE
    )
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    failure_count = models.PositiveSmallIntegerField(default=0)
    headers = models.JSONField(default=dict, help_text="Custom HTTP headers")

    class Meta:
        db_table = "admin_webhook_endpoints"

    def __str__(self):
        return f"{self.name} → {self.url}"


# ══════════════════════════ DASHBOARD BUILDER ═════════════════════════════════


class CustomDashboard(CompanyScoped):
    """User-defined dashboard layouts."""

    name = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)
    owner = models.ForeignKey(
        "authentication.User",
        on_delete=models.CASCADE,
        related_name="dashboards",
    )
    layout = models.JSONField(
        default=list, help_text="Array of widget position configs"
    )
    shared_with_roles = models.JSONField(default=list)

    class Meta:
        db_table = "admin_custom_dashboards"

    def __str__(self):
        return f"{self.name} ({self.owner})"


class DashboardWidget(CompanyScoped):
    """Configurable chart/KPI widget definitions."""

    class WidgetType(models.TextChoices):
        KPI_CARD = "kpi_card", _("KPI Card")
        BAR_CHART = "bar_chart", _("Bar Chart")
        LINE_CHART = "line_chart", _("Line Chart")
        PIE_CHART = "pie_chart", _("Pie Chart")
        TABLE = "table", _("Data Table")
        FUNNEL = "funnel", _("Funnel Chart")
        GAUGE = "gauge", _("Gauge")

    dashboard = models.ForeignKey(
        CustomDashboard, on_delete=models.CASCADE, related_name="widgets"
    )
    title = models.CharField(max_length=200)
    widget_type = models.CharField(max_length=20, choices=WidgetType.choices)
    data_source = models.CharField(
        max_length=200, help_text="API endpoint or query name"
    )
    config = models.JSONField(
        default=dict, help_text="Chart.js / widget configuration JSON"
    )
    position_x = models.PositiveSmallIntegerField(default=0)
    position_y = models.PositiveSmallIntegerField(default=0)
    width = models.PositiveSmallIntegerField(
        default=6, help_text="Bootstrap cols (1-12)"
    )
    height = models.PositiveSmallIntegerField(default=4, help_text="Grid rows")
    refresh_interval = models.PositiveIntegerField(
        default=0, help_text="Seconds, 0=no auto-refresh"
    )

    class Meta:
        db_table = "admin_dashboard_widgets"

    def __str__(self):
        return f"{self.title} ({self.get_widget_type_display()})"


# ══════════════════════════ REPORT BUILDER ════════════════════════════════════


class CustomReport(CompanyScoped):
    """Saved report definitions with filters and columns."""

    class ReportFormat(models.TextChoices):
        TABLE = "table", _("Table")
        CHART = "chart", _("Chart")
        PIVOT = "pivot", _("Pivot Table")
        MIXED = "mixed", _("Table + Chart")

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    module = models.CharField(max_length=50, help_text="e.g. sales, hrms, accounting")
    base_model = models.CharField(
        max_length=100, help_text="e.g. apps.sales.models.Invoice"
    )
    columns = models.JSONField(
        default=list,
        help_text='[{"field": "total", "label": "Total", "aggregate": "sum"}]',
    )
    filters = models.JSONField(default=dict)
    group_by = models.JSONField(default=list)
    order_by = models.CharField(max_length=100, blank=True)
    report_format = models.CharField(
        max_length=10, choices=ReportFormat.choices, default=ReportFormat.TABLE
    )
    chart_config = models.JSONField(default=dict)
    is_public = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="custom_reports",
    )

    class Meta:
        db_table = "admin_custom_reports"

    def __str__(self):
        return self.name


# ══════════════════════════ SYSTEM SETTINGS ═══════════════════════════════════


class SystemSetting(UUIDModel):
    """Global system-level key/value settings (not company-scoped)."""

    class Category(models.TextChoices):
        GENERAL = "general", _("General")
        SECURITY = "security", _("Security")
        PERFORMANCE = "performance", _("Performance")
        MAINTENANCE = "maintenance", _("Maintenance")
        LOCALIZATION = "localization", _("Localization")

    key = models.CharField(max_length=200, unique=True, db_index=True)
    value = models.TextField(blank=True)
    value_type = models.CharField(
        max_length=10,
        choices=[
            ("string", "String"),
            ("integer", "Integer"),
            ("boolean", "Boolean"),
            ("json", "JSON"),
        ],
        default="string",
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.GENERAL
    )
    label = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    is_sensitive = models.BooleanField(
        default=False, help_text="If True, value is masked in UI"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "admin_system_settings"
        ordering = ["category", "key"]

    def __str__(self):
        return f"{self.key} = {self.value if not self.is_sensitive else '***'}"

    @classmethod
    def get(cls, key, default=None):
        try:
            obj = cls.objects.get(key=key)
            if obj.value_type == "boolean":
                return obj.value.lower() in ("true", "1", "yes")
            elif obj.value_type == "integer":
                return int(obj.value)
            elif obj.value_type == "json":
                import json

                return json.loads(obj.value)
            return obj.value
        except cls.DoesNotExist:
            return default


class RolePermission(CompanyScoped):
    role = models.CharField(max_length=30)
    module = models.CharField(max_length=50)
    can_view = models.BooleanField(default=False)
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)

    class Meta:
        db_table = "admin_role_permission"
        unique_together = ("company", "role", "module")


class BackupSchedule(CompanyScoped):
    frequency = models.CharField(
        max_length=20,
        choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
    )
    time_of_day = models.TimeField()
    retention_days = models.PositiveSmallIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    destination = models.CharField(
        max_length=50,
        choices=[("local", "Local"), ("s3", "AWS S3"), ("gcs", "Google Cloud Storage")],
        default="local",
    )

    class Meta:
        db_table = "admin_backup_schedule"


class InstalledApp(CompanyScoped):
    """Tracks which modular apps are enabled for the company."""

    class AppChoices(models.TextChoices):
        ACCOUNTING = "accounting", _("Accounting")
        CRM = "crm", _("CRM")
        SALES = "sales", _("Sales")
        PURCHASE = "purchase", _("Purchase")
        INVENTORY = "inventory", _("Inventory")
        MANUFACTURING = "manufacturing", _("Manufacturing")
        HRMS = "hrms", _("HR & Payroll")
        PROJECTS = "projects", _("Projects")
        HELPDESK = "helpdesk", _("Helpdesk")
        ASSETS = "assets", _("Assets")
        POS = "pos", _("Point of Sale")
        DOCUMENTS = "documents", _("Documents")
        PORTALS = "portals", _("Customer & Vendor Portals")
        ANALYTICS = "analytics", _("Reporting & Analytics")
        WORKFLOW = "workflow", _("Workflows")

    app_label = models.CharField(max_length=50, choices=AppChoices.choices)
    is_active = models.BooleanField(default=True)
    installed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_installed_apps"
        unique_together = ("company", "app_label")
