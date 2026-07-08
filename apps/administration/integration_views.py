from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.views.generic import TemplateView, View

from apps.administration.models import (
    EmailConfig,
    Integration,
    SMSConfig,
    WebhookEndpoint,
    WhatsAppConfig,
)


class AdminRequiredMixin(UserPassesTestMixin):
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
    template_name = "administration/integrations/oauth_connect.html"

    def get(self, request, provider):
        return render(request, self.template_name, {"provider": provider})

    def post(self, request, provider):
        company = request.user.primary_company
        integration_type = request.POST.get("integration_type", "custom")

        integration, created = Integration.objects.get_or_create(
            company=company,
            provider=provider,
            defaults={"integration_type": integration_type, "name": provider.title()},
        )
        integration.credentials = {
            "oauth_token": "mock_token_123",
            "refresh_token": "mock_refresh_456",
        }
        integration.status = Integration.Status.CONNECTED
        integration.save()

        messages.success(
            request, f"Successfully authenticated with {provider.title()}."
        )
        return redirect("administration:integrations_dashboard")


class WebhookManagementView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "administration/integrations/webhooks.html"

    def get(self, request):
        webhooks = WebhookEndpoint.objects.filter(company=request.user.primary_company)
        return render(request, self.template_name, {"webhooks": webhooks})

    def post(self, request):
        url = request.POST.get("url")
        events = request.POST.get("events", "*")
        if url:
            WebhookEndpoint.objects.create(
                company=request.user.primary_company,
                url=url,
                subscribed_events=[e.strip() for e in events.split(",")],
                status=WebhookEndpoint.Status.ACTIVE,
            )
            messages.success(request, "Webhook endpoint added.")
        return redirect("administration:webhooks")


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
            messages.error(request, f"Error processing file: {str(e)}")

        return redirect("administration:data_import")
