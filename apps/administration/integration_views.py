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
from core.tenancy import get_active_company


class AdminRequiredMixin(HttpMethodPermissionMixin, UserPassesTestMixin):
    required_permission_module = "administration"

    def get_required_permission(self, request=None):
        if request is not None and request.method.upper() == "POST":
            return getattr(self, "required_permission", "administration.update")
        return "administration.read"
    def test_func(self):
        company = get_active_company(self.request)
        return self.request.user.is_superuser or (
            company is not None
            and self.request.user.get_role_for_company(company)
            in ["super_admin", "company_admin"]
        )


class IntegrationsDashboardView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = "administration/integrations/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = get_active_company(self.request)
        ctx["integrations"] = Integration.objects.filter(company=company)
        ctx["email_config"] = EmailConfig.objects.filter(company=company).first()
        ctx["sms_config"] = SMSConfig.objects.filter(company=company).first()
        ctx["whatsapp_config"] = WhatsAppConfig.objects.filter(company=company).first()
        ctx["webhooks"] = WebhookEndpoint.objects.filter(company=company)
        return ctx


class GenericIntegrationSetupView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "administration/integrations/generic_setup.html"

    def get(self, request, provider):
        company = get_active_company(request)
        integration = Integration.objects.filter(
            company=company, provider=provider
        ).first()
        return render(
            request,
            self.template_name,
            {"provider": provider, "integration": integration},
        )

    @transaction.atomic
    def post(self, request, provider):
        company = get_active_company(request)
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
        company = get_active_company(request)
        webhooks = WebhookEndpoint.objects.filter(company=company).prefetch_related("deliveries")
        return render(request, self.template_name, {"webhooks": webhooks})

    def post(self, request):
        url = request.POST.get("target_url") or request.POST.get("url")
        raw_events = request.POST.getlist("events")
        events = [
            event.strip()
            for item in raw_events or ["*"]
            for event in item.split(",")
            if event.strip()
        ]
        name = request.POST.get("name", url or "Webhook")
        parsed = urlparse(url or "")
        secure_required = not settings.DEBUG
        if url and parsed.scheme in ({"https"} if secure_required else {"http", "https"}) and parsed.netloc:
            secret = "whsec_" + secrets.token_urlsafe(32)
            with transaction.atomic():
                WebhookEndpoint.objects.create(
                    company=get_active_company(request),
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
            hook = WebhookEndpoint.objects.get(pk=pk, company=get_active_company(request))
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
            hook = WebhookEndpoint.objects.get(pk=pk, company=get_active_company(request))
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
                pk=pk, company=get_active_company(request)
            )
            integration.status = Integration.Status.DISCONNECTED
            integration.credentials = {}
            integration.save(update_fields=["status", "credentials"])
            messages.success(request, f"'{integration.name}' disconnected.")
        except Integration.DoesNotExist:
            messages.error(request, "Integration not found.")
        return redirect("administration:integrations_dashboard")