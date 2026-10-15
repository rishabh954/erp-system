import hashlib
import secrets

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.generic import View

from apps.administration.models import APIKey, BackupRecord, BackupSchedule
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
        return (
            self.request.user.is_superuser
            or self.request.user.get_role_for_company(company)
            in ["super_admin", "company_admin"]
        )


class APIKeyManagementView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "administration/api_keys.html"

    def get(self, request):
        keys = APIKey.objects.filter(company=get_active_company(request))
        return render(request, self.template_name, {"keys": keys})

    def post(self, request):
        name = request.POST.get("name")
        if name:
            raw_key = "erp_" + secrets.token_hex(20)
            APIKey.objects.create(
                company=get_active_company(request),
                name=name,
                key=hashlib.sha256(raw_key.encode()).hexdigest(),
                key_prefix=raw_key[:12],
                created_by=request.user,
                status=APIKey.Status.ACTIVE,
                scopes=[
                    scope.strip()
                    for scope in request.POST.get("scopes", "").split(",")
                    if scope.strip()
                ],
            )
            messages.success(
                request,
                f"API Key '{name}' generated successfully. Please copy it now as it won't be visible again: {raw_key}",
            )
        return redirect("administration:api_keys")


class APIKeyRevokeView(LoginRequiredMixin, AdminRequiredMixin, View):
    def post(self, request, pk):
        try:
            key = APIKey.objects.get(pk=pk, company=get_active_company(request))
            key.status = APIKey.Status.REVOKED
            key.save(update_fields=["status"])
            messages.success(request, f"API Key '{key.name}' revoked.")
        except APIKey.DoesNotExist:
            pass
        return redirect("administration:api_keys")


class BackupSchedulerView(LoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "administration/backup_schedule.html"

    def get(self, request):
        company = get_active_company(request)
        schedules = BackupSchedule.objects.filter(company=company)
        backups = BackupRecord.objects.filter(company=company).order_by("-created_at")[:20]
        return render(request, self.template_name, {"schedules": schedules, "backups": backups})

    def post(self, request):
        freq = request.POST.get("frequency", "daily")
        time = request.POST.get("time_of_day", "00:00")
        ret = request.POST.get("retention_days", 30)
        dest = request.POST.get("destination", "local")

        BackupSchedule.objects.create(
            company=get_active_company(request),
            frequency=freq,
            time_of_day=time,
            retention_days=ret,
            destination=dest,
        )
        messages.success(request, "Backup schedule created.")
        return redirect("administration:backup_schedule")


class BackupRunNowView(LoginRequiredMixin, AdminRequiredMixin, View):
    required_permission = "administration.update"

    def post(self, request):
        company = get_active_company(request)
        from apps.administration.tasks import generate_backup

        with transaction.atomic():
            record = BackupRecord.objects.create(
                company=company,
                backup_type=BackupRecord.BackupType.FULL,
                status=BackupRecord.Status.IN_PROGRESS,
                initiated_by=request.user,
            )
            transaction.on_commit(
                lambda: generate_backup.delay(str(record.pk), str(company.pk))
            )
        messages.success(request, "Backup queued.")
        return redirect("administration:backup_schedule")


class BackupDownloadView(LoginRequiredMixin, AdminRequiredMixin, View):
    required_permission = "administration.read"

    def get(self, request, pk):
        company = get_active_company(request)
        record = BackupRecord.objects.filter(
            pk=pk, company=company, status=BackupRecord.Status.COMPLETED
        ).first()
        if not record or not record.file_path:
            raise Http404
        try:
            file_handle = default_storage.open(record.file_path, "rb")
        except (FileNotFoundError, OSError):
            raise Http404 from None
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=f"backup-{record.pk}.json",
            content_type="application/json",
        )
