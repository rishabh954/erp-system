from django.views.generic import TemplateView, View, ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.contrib import messages
from apps.administration.models import BackupSchedule, APIKey, RolePermission
import secrets

class AdminRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.role in ['super_admin', 'company_admin']

class APIKeyManagementView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'administration/api_keys.html'
    
    def get(self, request):
        keys = APIKey.objects.filter(company=request.user.primary_company)
        return render(request, self.template_name, {'keys': keys})
        
    def post(self, request):
        name = request.POST.get('name')
        if name:
            new_key = APIKey.objects.create(
                company=request.user.primary_company,
                name=name,
                key="erp_" + secrets.token_hex(20),
                status=APIKey.Status.ACTIVE
            )
            messages.success(request, f"API Key '{name}' generated successfully. Please copy it now as it won't be visible again: {new_key.key}")
        return redirect('administration:api_keys')

class APIKeyRevokeView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        try:
            key = APIKey.objects.get(pk=pk, company=request.user.primary_company)
            key.status = APIKey.Status.REVOKED
            key.save(update_fields=['status'])
            messages.success(request, f"API Key '{key.name}' revoked.")
        except APIKey.DoesNotExist:
            pass
        return redirect('administration:api_keys')

class BackupSchedulerView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = 'administration/backup_schedule.html'
    
    def get(self, request):
        schedules = BackupSchedule.objects.filter(company=request.user.primary_company)
        return render(request, self.template_name, {'schedules': schedules})
        
    def post(self, request):
        freq = request.POST.get('frequency', 'daily')
        time = request.POST.get('time_of_day', '00:00')
        ret = request.POST.get('retention_days', 30)
        dest = request.POST.get('destination', 'local')
        
        BackupSchedule.objects.create(
            company=request.user.primary_company,
            frequency=freq,
            time_of_day=time,
            retention_days=ret,
            destination=dest
        )
        messages.success(request, "Backup schedule created.")
        return redirect('administration:backup_schedule')
