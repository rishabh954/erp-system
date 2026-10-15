import logging
import secrets
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.generic import TemplateView, View

from apps.administration.models import (
    EmailConfig,
    Integration,
    SMSConfig,
    WebhookEndpoint,
    WhatsAppConfig,
)
from core.permissions import HttpMethodPermissionMixin

logger = logging.getLogger(__name__)


class AdminRequiredMixin(HttpMethodPermissionMixin, UserPassesTestMixin):
    required_permission_module = "administration"

    def get_required_permission(self, request=None):
        if request is not None and request.method.upper() == "POST":
            return getattr(self, "required_permission", "administration.update")
        return "administration.read"
    def test_func(self):
        return self.request.user.role in ["super_admin", "company_admin"]


class IntegrationsDashboardView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = "administration/integrations/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.primary_company
        ctx["integrations"] = Integration.objects.filter(company=company)
        ctx["email_config"] = EmailConfig.objects.filter(company=company).first()
        ctx["sms_config"] = SMSConfig.objects.filter(company=company).first()
        ctx["whatsapp_config"] = WhatsAppConfig.objects.filter(company=company).first()
        ctx["webhooks"] = WebhookEndpoint.objects.filter(company=company)
        return ctx


class GenericIntegrationSetupView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "administration/integrations/generic_setup.html"

    def get(self, request, provider):
        company = request.user.primary_company
        integration = Integration.objects.filter(
            company=company, provider=provider
        ).first()
        return render(
            request,
            self.template_name,
            {"provider": provider, "integration": integration},
        )

    def post(self, request, provider):
        company = request.user.primary_company
        api_key = request.POST.get("api_key")
        api_secret = request.POST.get("api_secret")
        integration_type = request.POST.get("integration_type", "custom")

        integration, created = Integration.objects.get_or_create(
            company=company,
            provider=provider,
            defaults={"integration_type": integration_type, "name": provider.title()},
        )
        integration.credentials = {"api_key": api_key, "api_secret": api_secret}
        integration.status = Integration.Status.CONNECTED
        integration.save()

        messages.success(request, f"Successfully connected to {provider.title()}.")
        return redirect("administration:integrations_dashboard")


class OAuthMockConnectView(LoginRequiredMixin, AdminRequiredMixin, View):
    """
    OAuth connect placeholder.

    Real OAuth flows require a provider-specific client_id, client_secret, and
    a redirect URI registered with the provider. This view previously stored
    hardcoded fake tokens as real credentials, which silently broke any code
    that tried to use them.

    The view now returns HTTP 501 Not Implemented and tells the admin exactly
    what environment variables need to be configured before OAuth can work.
    Replace this view with a real OAuth flow (e.g. via python-social-auth or
    authlib) once provider credentials are available.
    """

    template_name = "administration/integrations/oauth_connect.html"

    def get(self, request, provider):
        return render(
            request,
            self.template_name,
            {
                "provider": provider,
                "not_implemented": True,
                "message": (
                    f"OAuth for '{provider}' is not yet configured. "
                    "Set the required environment variables and implement the "
                    "real OAuth flow before connecting this provider."
                ),
            },
        )

    def post(self, request, provider):
        messages.error(
            request,
            f"OAuth authentication for '{provider.title()}' is not yet implemented. "
            "Configure the provider credentials in your environment and implement "
            "the real OAuth callback before using this feature.",
        )
        return redirect("administration:integrations_dashboard")


class WebhookManagementView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "administration/integrations/webhooks.html"

    def get(self, request):
        webhooks = WebhookEndpoint.objects.filter(company=request.user.primary_company)
        return render(request, self.template_name, {"webhooks": webhooks})

    def post(self, request):
        url = request.POST.get("target_url") or request.POST.get("url")
        events = request.POST.getlist("events") or [
            value.strip() for value in request.POST.get("events", "*").split(",") if value.strip()
        ]
        name = request.POST.get("name", url or "Webhook")
        parsed = urlparse(url or "")
        secure_required = not settings.DEBUG
        if url and parsed.scheme in ({"https"} if secure_required else {"http", "https"}) and parsed.netloc:
            secret = "whsec_" + secrets.token_urlsafe(32)
            with transaction.atomic():
                WebhookEndpoint.objects.create(
                company=request.user.primary_company,
                name=name,
                url=url,
                secret=secret,
                events=events,
                status=WebhookEndpoint.Status.ACTIVE,
            )
            messages.success(request, f"Webhook endpoint added. Copy its signing secret now: {secret}")
        else:
            messages.error(request, "Enter a valid webhook URL (HTTPS is required in production).")
        return redirect("administration:webhooks")


# Alias — the modal posts to webhook_create, same logic as WebhookManagementView.post
WebhookCreateView = WebhookManagementView


class WebhookToggleView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Toggle active/inactive status of a webhook endpoint."""

    def post(self, request, pk):
        try:
            hook = WebhookEndpoint.objects.get(pk=pk, company=request.user.primary_company)
            if hook.status == WebhookEndpoint.Status.ACTIVE:
                hook.status = WebhookEndpoint.Status.INACTIVE
            else:
                hook.status = WebhookEndpoint.Status.ACTIVE
            hook.save(update_fields=["status"])
            messages.success(request, f"Webhook '{hook.name}' status updated.")
        except WebhookEndpoint.DoesNotExist:
            messages.error(request, "Webhook not found.")
        return redirect("administration:webhooks")


class WebhookDeleteView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Delete a webhook endpoint."""

    def post(self, request, pk):
        try:
            hook = WebhookEndpoint.objects.get(pk=pk, company=request.user.primary_company)
            hook.delete()
            messages.success(request, "Webhook deleted.")
        except WebhookEndpoint.DoesNotExist:
            messages.error(request, "Webhook not found.")
        return redirect("administration:webhooks")


class IntegrationDisconnectView(LoginRequiredMixin, AdminRequiredMixin, View):
    """Disconnect a third-party integration."""

    def post(self, request, pk):
        try:
            integration = Integration.objects.get(
                pk=pk, company=request.user.primary_company
            )
            integration.status = Integration.Status.DISCONNECTED
            integration.credentials = {}
            integration.save(update_fields=["status", "credentials"])
            messages.success(request, f"'{integration.name}' disconnected.")
        except Integration.DoesNotExist:
            messages.error(request, "Integration not found.")
        return redirect("administration:integrations_dashboard")


class DataImportView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = "administration/integrations/data_import.html"

    def post(self, request):
        file = request.FILES.get("import_file")
        import_type = request.POST.get("import_type")

        if not file:
            messages.error(request, "No file uploaded.")
            return redirect("administration:data_import")

        if not file.name.endswith(".csv"):
            messages.error(request, "Only CSV files are supported.")
            return redirect("administration:data_import")

        try:
            import csv
            from io import StringIO

            from apps.crm.models import Customer
            from apps.inventory.models import Product
            from apps.purchase.models import Vendor

            csv_file = file.read().decode("utf-8-sig")
            reader = csv.DictReader(StringIO(csv_file))

            success_count = 0
            company = request.user.primary_company

            for row in reader:
                if import_type == "product":
                    Product.objects.create(
                        company=company,
                        name=row.get("name", "Unknown Product"),
                        sku=row.get("sku", ""),
                        description=row.get("description", ""),
                        cost_price=row.get("cost_price", 0) or 0,
                        sale_price=row.get("sale_price", 0) or 0,
                    )
                elif import_type == "customer":
                    Customer.objects.create(
                        company=company,
                        name=row.get("name", "Unknown Customer"),
                        email=row.get("email", ""),
                        phone=row.get("phone", ""),
                        address_line1=row.get("address", ""),
                    )
                elif import_type == "vendor":
                    Vendor.objects.create(
                        company=company,
                        name=row.get("name", "Unknown Vendor"),
                        email=row.get("email", ""),
                        phone=row.get("phone", ""),
                        address_line1=row.get("address", ""),
                    )
                success_count += 1

            messages.success(
                request, f"Successfully imported {success_count} {import_type}(s)."
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            messages.error(request, f"Error processing file: {"An unexpected error occurred."}")

        return redirect("administration:data_import")
