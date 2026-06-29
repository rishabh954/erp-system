from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.contrib import messages
from apps.administration.models import Integration, EmailConfig, SMSConfig, WhatsAppConfig, WebhookEndpoint

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role in ['super_admin', 'company_admin']

class IntegrationsDashboardView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'administration/integrations/dashboard.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.request.user.primary_company
        ctx['integrations'] = Integration.objects.filter(company=company)
        ctx['email_config'] = EmailConfig.objects.filter(company=company).first()
        ctx['sms_config'] = SMSConfig.objects.filter(company=company).first()
        ctx['whatsapp_config'] = WhatsAppConfig.objects.filter(company=company).first()
        ctx['webhooks'] = WebhookEndpoint.objects.filter(company=company)
        return ctx

class GenericIntegrationSetupView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'administration/integrations/generic_setup.html'
    
    def get(self, request, provider):
        company = request.user.primary_company
        integration = Integration.objects.filter(company=company, provider=provider).first()
        return render(request, self.template_name, {'provider': provider, 'integration': integration})
        
    def post(self, request, provider):
        company = request.user.primary_company
        api_key = request.POST.get('api_key')
        api_secret = request.POST.get('api_secret')
        integration_type = request.POST.get('integration_type', 'custom')
        
        integration, created = Integration.objects.get_or_create(
            company=company,
            provider=provider,
            defaults={'integration_type': integration_type, 'name': provider.title()}
        )
        integration.credentials = {'api_key': api_key, 'api_secret': api_secret}
        integration.status = Integration.Status.CONNECTED
        integration.save()
        
        messages.success(request, f"Successfully connected to {provider.title()}.")
        return redirect('administration:integrations_dashboard')

class OAuthMockConnectView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'administration/integrations/oauth_connect.html'
    
    def get(self, request, provider):
        return render(request, self.template_name, {'provider': provider})
        
    def post(self, request, provider):
        company = request.user.primary_company
        integration_type = request.POST.get('integration_type', 'custom')
        
        integration, created = Integration.objects.get_or_create(
            company=company,
            provider=provider,
            defaults={'integration_type': integration_type, 'name': provider.title()}
        )
        integration.credentials = {'oauth_token': 'mock_token_123', 'refresh_token': 'mock_refresh_456'}
        integration.status = Integration.Status.CONNECTED
        integration.save()
        
        messages.success(request, f"Successfully authenticated with {provider.title()}.")
        return redirect('administration:integrations_dashboard')

class WebhookManagementView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'administration/integrations/webhooks.html'
    
    def get(self, request):
        webhooks = WebhookEndpoint.objects.filter(company=request.user.primary_company)
        return render(request, self.template_name, {'webhooks': webhooks})
        
    def post(self, request):
        url = request.POST.get('url')
        events = request.POST.get('events', '*')
        if url:
            WebhookEndpoint.objects.create(
                company=request.user.primary_company,
                url=url,
                subscribed_events=[e.strip() for e in events.split(',')],
                status=WebhookEndpoint.Status.ACTIVE
            )
            messages.success(request, "Webhook endpoint added.")
        return redirect('administration:webhooks')

class DataImportView(LoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = 'administration/integrations/data_import.html'
    
    # In a real app, POST would process Excel/Tally XML files and create ImportJob.
    def post(self, request):
        file = request.FILES.get('import_file')
        import_type = request.POST.get('import_type')
        if file:
            messages.success(request, f"{import_type.title()} import job queued successfully. It will be processed in the background.")
        return redirect('administration:data_import')
