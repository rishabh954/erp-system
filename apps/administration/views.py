"""
Administration Module Views
Centralized Administration Center: 27 modules in one place.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from core.permissions import PermissionRequiredMixin
from django.views.generic import TemplateView, View

from .models import (
    ActivityLog,
    APIKey,
    ApprovalMatrix,
    AuditLog,
    BackupRecord,
    CustomDashboard,
    CustomReport,
    DashboardWidget,
    Designation,
    DocumentTemplate,
    EmailConfig,
    ExportJob,
    ImportJob,
    InstalledApp,
    Integration,
    NotificationTemplate,
    NumberSeries,
    SMSConfig,
    SystemSetting,
    WebhookEndpoint,
    WhatsAppConfig,
)


class AdminRequiredMixin(LoginRequiredMixin):
    """Only company admins / super admins can access Administration Center."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in ["super_admin", "company_admin"]:
            messages.error(
                request,
                "You do not have permission to access the Administration Center.",
            )
            return redirect("dashboard:home")
        return super().dispatch(request, *args, **kwargs)

    @property
    def company(self):
        return getattr(self.request.user, "primary_company", None)


class AppStoreView(AdminRequiredMixin, TemplateView):
    required_permission = "administration.read"
    template_name = "administration/app_store.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.primary_company
        installed = InstalledApp.objects.filter(
            company=company, is_active=True
        ).values_list("app_label", flat=True)

        ctx["apps"] = [
            {
                "id": "crm",
                "name": "CRM",
                "icon": "users",
                "description": "Manage leads, customers, and pipelines.",
            },
            {
                "id": "sales",
                "name": "Sales",
                "icon": "shopping-cart",
                "description": "Manage sales orders and invoices.",
            },
            {
                "id": "purchase",
                "name": "Purchasing",
                "icon": "shopping-bag",
                "description": "Manage purchase orders and bills.",
            },
            {
                "id": "inventory",
                "name": "Inventory",
                "icon": "boxes",
                "description": "Warehouse and stock management.",
            },
            {
                "id": "manufacturing",
                "name": "Manufacturing",
                "icon": "industry",
                "description": "Bills of Material and work orders.",
            },
            {
                "id": "hrms",
                "name": "HRMS",
                "icon": "user-tie",
                "description": "Employees, payroll, and attendance.",
            },
            {
                "id": "projects",
                "name": "Projects",
                "icon": "project-diagram",
                "description": "Project tracking and timesheets.",
            },
            {
                "id": "helpdesk",
                "name": "Helpdesk",
                "icon": "life-ring",
                "description": "Customer support tickets.",
            },
            {
                "id": "assets",
                "name": "Assets",
                "icon": "laptop",
                "description": "Fixed asset tracking.",
            },
            {
                "id": "pos",
                "name": "Point of Sale",
                "icon": "cash-register",
                "description": "Retail POS interface.",
            },
            {
                "id": "documents",
                "name": "Documents",
                "icon": "folder",
                "description": "Centralized document storage.",
            },
            {
                "id": "portals",
                "name": "Portals",
                "icon": "globe",
                "description": "Customer and Vendor self-service.",
            },
            {
                "id": "analytics",
                "name": "Analytics",
                "icon": "chart-bar",
                "description": "Advanced reporting and dashboards.",
            },
            {
                "id": "workflow",
                "name": "Workflows",
                "icon": "cogs",
                "description": "Automated business workflows.",
            },
        ]

        for app in ctx["apps"]:
            app["is_installed"] = app["id"] in installed

        return ctx

    def post(self, request):
        company = request.user.primary_company
        app_label = request.POST.get("app_label")
        action = request.POST.get("action")

        if action == "install":
            InstalledApp.objects.update_or_create(
                company=company, app_label=app_label, defaults={"is_active": True}
            )
            messages.success(request, f"Successfully installed {app_label.upper()}.")
        elif action == "uninstall":
            InstalledApp.objects.filter(company=company, app_label=app_label).update(
                is_active=False
            )
            messages.warning(request, f"Uninstalled {app_label.upper()}.")

        return redirect("administration:app_store")


# ── 1. Administration Dashboard ───────────────────────────────────────────────


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    required_permission = "administration.read"
    template_name = "administration/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company
        ctx.update(
            {
                "total_users": (
                    company.users.filter(is_active=True).count() if company else 0
                ),
                "total_api_keys": (
                    APIKey.objects.filter(company=company, status="active").count()
                    if company
                    else 0
                ),
                "recent_audit_logs": (
                    AuditLog.objects.filter(company=company).order_by("-timestamp")[:10]
                    if company
                    else []
                ),
                "recent_activity": (
                    ActivityLog.objects.filter(company=company).order_by("-timestamp")[
                        :10
                    ]
                    if company
                    else []
                ),
            }
        )
        return ctx


class HRManagerOrAdminMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        role = getattr(request.user, "role", "")
        if (
            role not in ("super_admin", "company_admin", "hr_manager")
            and not request.user.is_superuser
        ):
            messages.error(request, "You do not have permission to access Job Titles.")
            return redirect("dashboard:index")
        return super().dispatch(request, *args, **kwargs)

    @property
    def company(self):
        return self.request.user.primary_company


# ── 2. Designation Management (Job Titles) ────────────────────────────────────


class DesignationListView(HRManagerOrAdminMixin, View):
    required_permission = "administration.read"

    def get_required_permission(self, request=None):
        if request and request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            return "administration.create"
        return self.required_permission
    template_name = "administration/designations.html"

    def get(self, request):
        designations = Designation.objects.filter(company=self.company).order_by(
            "level", "name"
        )
        return render(
            request,
            self.template_name,
            {"designations": designations, "company": self.company},
        )

    def post(self, request):
        Designation.objects.create(
            company=self.company,
            name=request.POST.get("name", ""),
            code=request.POST.get("code", ""),
            level=int(request.POST.get("level", 1)),
        )
        messages.success(request, "Designation created successfully.")
        return redirect("administration:designations")


class DesignationDeleteView(HRManagerOrAdminMixin, View):
    required_permission = "administration.delete"
    def post(self, request, pk):
        obj = get_object_or_404(Designation, pk=pk, company=self.company)
        obj.delete()
        messages.success(request, "Designation deleted.")
        return redirect("administration:designations")


# ── 3. Number Series ──────────────────────────────────────────────────────────


class NumberSeriesListView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/number_series.html"

    def get(self, request):
        series = NumberSeries.objects.filter(company=self.company)
        doc_types = NumberSeries.DocType.choices
        return render(
            request, self.template_name, {"series": series, "doc_types": doc_types}
        )

    def post(self, request):
        dt = request.POST.get("doc_type")
        NumberSeries.objects.update_or_create(
            company=self.company,
            doc_type=dt,
            defaults={
                "prefix": request.POST.get("prefix", ""),
                "suffix": request.POST.get("suffix", ""),
                "padding": int(request.POST.get("padding", 4)),
                "reset_period": request.POST.get("reset_period", "never"),
                "is_active": True,
            },
        )
        messages.success(request, "Number series saved.")
        return redirect("administration:number_series")


# ── 4. Approval Matrix ────────────────────────────────────────────────────────


class ApprovalMatrixListView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/approval_matrix.html"

    def get(self, request):
        matrix = ApprovalMatrix.objects.filter(company=self.company)
        from apps.authentication.models import User

        users = User.objects.filter(companies=self.company, is_active=True)
        return render(
            request,
            self.template_name,
            {
                "matrix": matrix,
                "doc_types": ApprovalMatrix.DocType.choices,
                "users": users,
            },
        )

    def post(self, request):
        ApprovalMatrix.objects.create(
            company=self.company,
            doc_type=request.POST.get("doc_type"),
            name=request.POST.get("name"),
            min_amount=request.POST.get("min_amount", 0),
            max_amount=request.POST.get("max_amount") or None,
            approver_role=request.POST.get("approver_role", ""),
            approver_user_id=request.POST.get("approver_user") or None,
            level=int(request.POST.get("level", 1)),
        )
        messages.success(request, "Approval rule created.")
        return redirect("administration:approval_matrix")


class ApprovalMatrixDeleteView(AdminRequiredMixin, View):
    required_permission = "administration.delete"
    def post(self, request, pk):
        obj = get_object_or_404(ApprovalMatrix, pk=pk, company=self.company)
        obj.delete()
        messages.success(request, "Approval rule deleted.")
        return redirect("administration:approval_matrix")


# ── 5. Email Configuration ────────────────────────────────────────────────────


class EmailConfigView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/email_config.html"

    def get(self, request):
        configs = EmailConfig.objects.filter(company=self.company)
        return render(request, self.template_name, {"configs": configs})

    def post(self, request):
        action = request.POST.get("action")
        if action == "create":
            EmailConfig.objects.create(
                company=self.company,
                name=request.POST.get("name", "Default"),
                host=request.POST.get("host", ""),
                port=int(request.POST.get("port", 587)),
                username=request.POST.get("username", ""),
                password=request.POST.get("password", ""),
                use_tls="use_tls" in request.POST,
                from_email=request.POST.get("from_email", ""),
                from_name=request.POST.get("from_name", ""),
                is_default="is_default" in request.POST,
            )
            messages.success(request, "Email configuration saved.")
        return redirect("administration:email_config")


class EmailConfigDeleteView(AdminRequiredMixin, View):
    required_permission = "administration.delete"
    def post(self, request, pk):
        obj = get_object_or_404(EmailConfig, pk=pk, company=self.company)
        obj.delete()
        messages.success(request, "Email config deleted.")
        return redirect("administration:email_config")


class EmailConfigTestView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    """Send a test email to the authenticated user."""

    def post(self, request, pk):
        config = get_object_or_404(EmailConfig, pk=pk, company=self.company)
        try:
            from django.core.mail import get_connection, send_mail

            conn = get_connection(
                backend="django.core.mail.backends.smtp.EmailBackend",
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                use_tls=config.use_tls,
                use_ssl=config.use_ssl,
            )
            send_mail(
                subject="ERP Test Email",
                message="This is a test email from your ERP Administration Center.",
                from_email=config.from_email,
                recipient_list=[request.user.email],
                connection=conn,
            )
            messages.success(request, f"Test email sent to {request.user.email}.")
        except Exception as e:
            messages.error(request, f"Failed: {e}")
        return redirect("administration:email_config")


# ── 6. SMS Configuration ──────────────────────────────────────────────────────


class SMSConfigView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/sms_config.html"

    def get(self, request):
        configs = SMSConfig.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "configs": configs,
                "providers": SMSConfig.Provider.choices,
            },
        )

    def post(self, request):
        SMSConfig.objects.create(
            company=self.company,
            name=request.POST.get("name", "Default SMS"),
            provider=request.POST.get("provider", "twilio"),
            api_key=request.POST.get("api_key", ""),
            api_secret=request.POST.get("api_secret", ""),
            sender_id=request.POST.get("sender_id", ""),
        )
        messages.success(request, "SMS configuration saved.")
        return redirect("administration:sms_config")


# ── 7. WhatsApp Configuration ─────────────────────────────────────────────────


class WhatsAppConfigView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/whatsapp_config.html"

    def get(self, request):
        configs = WhatsAppConfig.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "configs": configs,
                "providers": WhatsAppConfig.Provider.choices,
            },
        )

    def post(self, request):
        WhatsAppConfig.objects.create(
            company=self.company,
            name=request.POST.get("name", "Default WhatsApp"),
            provider=request.POST.get("provider", "meta_cloud"),
            phone_number_id=request.POST.get("phone_number_id", ""),
            waba_id=request.POST.get("waba_id", ""),
            access_token=request.POST.get("access_token", ""),
        )
        messages.success(request, "WhatsApp configuration saved.")
        return redirect("administration:whatsapp_config")


# ── 8. Notification Templates ─────────────────────────────────────────────────


class NotificationCenterView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/notifications.html"

    def get(self, request):
        templates = NotificationTemplate.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "templates": templates,
                "channels": NotificationTemplate.Channel.choices,
                "events": NotificationTemplate.TriggerEvent.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "create":
            NotificationTemplate.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                channel=request.POST.get("channel"),
                trigger_event=request.POST.get("trigger_event", "custom"),
                subject=request.POST.get("subject", ""),
                body=request.POST.get("body", ""),
            )
            messages.success(request, "Notification template created.")
        elif action == "delete":
            pk = request.POST.get("pk")
            NotificationTemplate.objects.filter(pk=pk, company=self.company).delete()
            messages.success(request, "Template deleted.")
        return redirect("administration:notifications")


# ── 9. Document Template Builder ──────────────────────────────────────────────


class DocumentTemplateListView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/document_templates.html"

    def get(self, request):
        templates = DocumentTemplate.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "templates": templates,
                "doc_types": DocumentTemplate.DocType.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "create":
            DocumentTemplate.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                doc_type=request.POST.get("doc_type"),
                html_content=request.POST.get("html_content", ""),
                css_content=request.POST.get("css_content", ""),
                page_size=request.POST.get("page_size", "A4"),
                is_default="is_default" in request.POST,
            )
            messages.success(request, "Document template saved.")
        elif action == "delete":
            pk = request.POST.get("pk")
            DocumentTemplate.objects.filter(pk=pk, company=self.company).delete()
            messages.success(request, "Template deleted.")
        return redirect("administration:document_templates")


# ── 10. Data Import ───────────────────────────────────────────────────────────


class DataImportView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/import_export.html"

    def get(self, request):
        jobs = ImportJob.objects.filter(company=self.company).order_by("-created_at")[
            :20
        ]
        exports = ExportJob.objects.filter(company=self.company).order_by(
            "-created_at"
        )[:20]
        return render(
            request,
            self.template_name,
            {
                "import_jobs": jobs,
                "export_jobs": exports,
                "modules": ImportJob.Module.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "import" and request.FILES.get("file"):
            ImportJob.objects.create(
                company=self.company,
                module=request.POST.get("module"),
                file=request.FILES["file"],
                imported_by=request.user,
            )
            messages.success(
                request, "Import job submitted. Processing will begin shortly."
            )
        elif action == "export":
            ExportJob.objects.create(
                company=self.company,
                module=request.POST.get("module", ""),
                format=request.POST.get("format", "csv"),
                requested_by=request.user,
            )
            messages.success(
                request, "Export job queued. You will be notified when ready."
            )
        return redirect("administration:import_export")


# ── 11. Backup & Restore ──────────────────────────────────────────────────────


class BackupRestoreView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/backup_restore.html"

    def get(self, request):
        backups = BackupRecord.objects.filter(company=self.company).order_by(
            "-created_at"
        )[:20]
        return render(
            request,
            self.template_name,
            {
                "backups": backups,
                "backup_types": BackupRecord.BackupType.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "create":
            BackupRecord.objects.create(
                company=self.company,
                backup_type=request.POST.get("backup_type", "full"),
                initiated_by=request.user,
                notes=request.POST.get("notes", ""),
            )
            messages.success(
                request, "Backup job initiated. You will be notified when complete."
            )
        return redirect("administration:backup_restore")


# ── 12. Audit Logs ────────────────────────────────────────────────────────────


class AuditLogView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/audit_logs.html"

    def get(self, request):
        qs = AuditLog.objects.filter(company=self.company).order_by("-timestamp")
        # Filters
        action = request.GET.get("action")
        model = request.GET.get("model")
        user_id = request.GET.get("user")
        date_from = request.GET.get("date_from")
        date_to = request.GET.get("date_to")
        if action:
            qs = qs.filter(action=action)
        if model:
            qs = qs.filter(model_name__icontains=model)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if date_from:
            qs = qs.filter(timestamp__date__gte=date_from)
        if date_to:
            qs = qs.filter(timestamp__date__lte=date_to)

        from apps.authentication.models import User

        users = User.objects.filter(companies=self.company, is_active=True)
        return render(
            request,
            self.template_name,
            {
                "logs": qs[:200],
                "actions": AuditLog.Action.choices,
                "users": users,
            },
        )


# ── 13. Activity Logs ─────────────────────────────────────────────────────────


class ActivityLogView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/activity_logs.html"

    def get(self, request):
        qs = ActivityLog.objects.filter(company=self.company).order_by("-timestamp")
        user_id = request.GET.get("user")
        activity_type = request.GET.get("activity_type")
        if user_id:
            qs = qs.filter(user_id=user_id)
        if activity_type:
            qs = qs.filter(activity_type=activity_type)

        from apps.authentication.models import User

        users = User.objects.filter(companies=self.company, is_active=True)
        return render(
            request,
            self.template_name,
            {
                "logs": qs[:200],
                "activity_types": ActivityLog.ActivityType.choices,
                "users": users,
            },
        )


# ── 14. API Management ────────────────────────────────────────────────────────


class APIManagementView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/api_management.html"

    def get(self, request):
        keys = APIKey.objects.filter(company=self.company).order_by("-created_at")
        return render(request, self.template_name, {"api_keys": keys})

    def post(self, request):
        action = request.POST.get("action")
        if action == "create":
            key = APIKey.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                scopes=request.POST.getlist("scopes"),
                rate_limit=int(request.POST.get("rate_limit", 1000)),
                created_by=request.user,
            )
            messages.success(request, f"API Key created. Copy it now: {key.key}")
        elif action == "revoke":
            pk = request.POST.get("pk")
            APIKey.objects.filter(pk=pk, company=self.company).update(status="revoked")
            messages.success(request, "API Key revoked.")
        return redirect("administration:api_management")


# ── 15. Integration Center ────────────────────────────────────────────────────


class IntegrationCenterView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/integrations.html"

    def get(self, request):
        integrations = Integration.objects.filter(company=self.company)
        webhooks = WebhookEndpoint.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "integrations": integrations,
                "webhooks": webhooks,
                "integration_types": Integration.IntegrationType.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "create_integration":
            Integration.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                integration_type=request.POST.get("integration_type"),
                provider=request.POST.get("provider"),
                credentials={"api_key": request.POST.get("api_key", "")},
            )
            messages.success(request, "Integration added.")
        elif action == "create_webhook":
            WebhookEndpoint.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                url=request.POST.get("url"),
                secret=request.POST.get("secret", ""),
                events=request.POST.get("events", "").split(","),
            )
            messages.success(request, "Webhook endpoint added.")
        elif action == "delete_integration":
            Integration.objects.filter(
                pk=request.POST.get("pk"), company=self.company
            ).delete()
            messages.success(request, "Integration removed.")
        elif action == "delete_webhook":
            WebhookEndpoint.objects.filter(
                pk=request.POST.get("pk"), company=self.company
            ).delete()
            messages.success(request, "Webhook removed.")
        return redirect("administration:integrations")


# ── 16. Dashboard Builder ─────────────────────────────────────────────────────


class DashboardBuilderView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/dashboard_builder.html"

    def get(self, request):
        dashboards = CustomDashboard.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "dashboards": dashboards,
                "widget_types": DashboardWidget.WidgetType.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "create_dashboard":
            CustomDashboard.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                owner=request.user,
                is_default="is_default" in request.POST,
            )
            messages.success(request, "Dashboard created.")
        elif action == "delete_dashboard":
            CustomDashboard.objects.filter(
                pk=request.POST.get("pk"), company=self.company
            ).delete()
            messages.success(request, "Dashboard deleted.")
        return redirect("administration:dashboard_builder")


# ── 17. Report Builder ────────────────────────────────────────────────────────


class ReportBuilderView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/report_builder.html"

    def get(self, request):
        reports = CustomReport.objects.filter(company=self.company)
        return render(
            request,
            self.template_name,
            {
                "reports": reports,
                "formats": CustomReport.ReportFormat.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "create":
            CustomReport.objects.create(
                company=self.company,
                name=request.POST.get("name"),
                description=request.POST.get("description", ""),
                module=request.POST.get("module"),
                base_model=request.POST.get("base_model", ""),
                report_format=request.POST.get("report_format", "table"),
                created_by=request.user,
            )
            messages.success(request, "Report definition saved.")
        elif action == "delete":
            CustomReport.objects.filter(
                pk=request.POST.get("pk"), company=self.company
            ).delete()
            messages.success(request, "Report deleted.")
        return redirect("administration:report_builder")


# ── 18. System Settings ────────────────────────────────────────────────────────


class SystemSettingsView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/system_settings.html"

    def get(self, request):
        settings = SystemSetting.objects.all().order_by("category", "key")
        by_category = {}
        for s in settings:
            by_category.setdefault(s.get_category_display(), []).append(s)
        return render(
            request,
            self.template_name,
            {
                "settings_by_category": by_category,
                "categories": SystemSetting.Category.choices,
            },
        )

    def post(self, request):
        action = request.POST.get("action")
        if action == "update":
            for key, value in request.POST.items():
                if key.startswith("setting_"):
                    setting_key = key[len("setting_") :]
                    SystemSetting.objects.filter(key=setting_key).update(value=value)
            messages.success(request, "System settings updated.")
        elif action == "create":
            SystemSetting.objects.get_or_create(
                key=request.POST.get("key"),
                defaults={
                    "value": request.POST.get("value", ""),
                    "value_type": request.POST.get("value_type", "string"),
                    "category": request.POST.get("category", "general"),
                    "label": request.POST.get("label", ""),
                    "description": request.POST.get("description", ""),
                },
            )
            messages.success(request, "Setting created.")
        return redirect("administration:system_settings")


# ── AJAX helpers ──────────────────────────────────────────────────────────────


class AuditLogDetailView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    def get(self, request, pk):
        log = get_object_or_404(AuditLog, pk=pk, company=self.company)
        return JsonResponse(
            {
                "action": log.action,
                "model": log.model_name,
                "object_repr": log.object_repr,
                "changes": log.changes,
                "user": str(log.user),
                "timestamp": log.timestamp.isoformat(),
                "ip_address": log.ip_address,
            }
        )


# ── Users ──────────────────────────────────────────────────────────────


class PendingUserApprovalListView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    template_name = "administration/pending_users.html"

    def get(self, request):
        from apps.authentication.models import User

        if request.user.role == User.Role.SUPER_ADMIN or request.user.is_superuser:
            pending_users = User.objects.filter(is_active=False).order_by(
                "-date_joined"
            )
        else:
            pending_users = User.objects.filter(
                is_active=False, companies=self.company
            ).order_by("-date_joined")
        return render(request, self.template_name, {"pending_users": pending_users})


class PendingUserApprovalActionView(AdminRequiredMixin, View):
    required_permission = "administration.read"
    def post(self, request, pk):
        from apps.authentication.models import User

        if request.user.role == User.Role.SUPER_ADMIN or request.user.is_superuser:
            user = get_object_or_404(User, pk=pk, is_active=False)
        else:
            user = get_object_or_404(
                User, pk=pk, companies=self.company, is_active=False
            )

        action = request.POST.get("action")

        if action == "approve":
            user.is_active = True
            # Auto-assign to admin's company if they have none
            if not user.companies.exists() and self.company:
                user.companies.add(self.company)
                user.primary_company = self.company
            user.save()
            ActivityLog.objects.create(
                user=request.user,
                company=self.company,
                activity_type=ActivityLog.ActivityType.SETTINGS_CHANGE,
                module="auth",
                description=f"Approved pending user: {user.email}",
            )
            messages.success(request, f"User {user.email} approved successfully.")
        elif action == "reject":
            email = user.email
            user.delete()
            ActivityLog.objects.create(
                user=request.user,
                company=self.company,
                activity_type=ActivityLog.ActivityType.SETTINGS_CHANGE,
                module="auth",
                description=f"Rejected and deleted pending user: {email}",
            )
            messages.success(request, f"User {email} rejected and removed.")

        return redirect("administration:pending_approvals")
