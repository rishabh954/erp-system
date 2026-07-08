"""
Notifications Views and API
"""

from core.permissions import PermissionRequiredMixin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView
from rest_framework import permissions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import EmailLog, Notification, NotificationPreference, SMSLog, WhatsAppLog


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "title",
            "message",
            "action_url",
            "action_label",
            "is_read",
            "read_at",
            "extra_data",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    required_permission = "notifications.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "notifications.create"
            elif request.method in ["PUT", "PATCH"]:
                return "notifications.update"
            elif request.method == "DELETE":
                return "notifications.delete"
        return self.required_permission
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(
            recipient=self.request.user,
            company=self.request.user.primary_company,
        ).order_by("-created_at")
        is_read = self.request.query_params.get("is_read")
        if is_read is not None:
            qs = qs.filter(is_read=is_read.lower() == "true")
        return qs

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notif = self.get_object()
        notif.mark_read()
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        Notification.objects.filter(
            recipient=request.user,
            company=request.user.primary_company,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())
        return Response({"ok": True})

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        count = Notification.objects.filter(
            recipient=request.user,
            company=request.user.primary_company,
            is_read=False,
        ).count()
        return Response({"count": count})


# Web view
class NotificationListView(LoginRequiredMixin, ListView):
    required_permission = "notifications.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "notifications.create"
            elif request.method in ["PUT", "PATCH"]:
                return "notifications.update"
            elif request.method == "DELETE":
                return "notifications.delete"
        return self.required_permission
    template_name = "notifications/list.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        return Notification.objects.filter(
            recipient=self.request.user,
            company=self.request.user.primary_company,
        ).order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["unread_count"] = self.get_queryset().filter(is_read=False).count()
        return ctx


class MarkReadView(LoginRequiredMixin, View):
    required_permission = "notifications.update"
    def post(self, request, pk):
        from django.shortcuts import get_object_or_404

        notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notif.mark_read()
        return JsonResponse({"ok": True})


class NotificationPreferenceUpdateView(LoginRequiredMixin, ListView):
    required_permission = "notifications.update"
    template_name = "notifications/preferences.html"
    context_object_name = "preferences"

    def get_queryset(self):
        # Create missing preferences if any
        existing_types = NotificationPreference.objects.filter(
            user=self.request.user
        ).values_list("notification_type", flat=True)
        for choice in Notification.NotificationType.choices:
            if choice[0] not in existing_types:
                NotificationPreference.objects.create(
                    company=self.request.user.primary_company,
                    user=self.request.user,
                    notification_type=choice[0],
                )
        return NotificationPreference.objects.filter(user=self.request.user).order_by(
            "notification_type"
        )

    def post(self, request, *args, **kwargs):
        from django.contrib import messages

        preferences = self.get_queryset()
        for pref in preferences:
            pref.in_app_enabled = request.POST.get(f"in_app_{pref.pk}") == "on"
            pref.email_enabled = request.POST.get(f"email_{pref.pk}") == "on"
            pref.sms_enabled = request.POST.get(f"sms_{pref.pk}") == "on"
            pref.whatsapp_enabled = request.POST.get(f"whatsapp_{pref.pk}") == "on"
            pref.save()
        messages.success(request, "Notification preferences updated successfully.")
        return self.get(request, *args, **kwargs)


class AdminEmailLogListView(LoginRequiredMixin, ListView):
    required_permission = "notifications.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "notifications.create"
            elif request.method in ["PUT", "PATCH"]:
                return "notifications.update"
            elif request.method == "DELETE":
                return "notifications.delete"
        return self.required_permission
    template_name = "notifications/logs/email.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        return EmailLog.objects.filter(
            company=self.request.user.primary_company
        ).order_by("-created_at")


class AdminSMSLogListView(LoginRequiredMixin, ListView):
    required_permission = "notifications.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "notifications.create"
            elif request.method in ["PUT", "PATCH"]:
                return "notifications.update"
            elif request.method == "DELETE":
                return "notifications.delete"
        return self.required_permission
    template_name = "notifications/logs/sms.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        return SMSLog.objects.filter(
            company=self.request.user.primary_company
        ).order_by("-created_at")


class AdminWhatsAppLogListView(LoginRequiredMixin, ListView):
    required_permission = "notifications.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "notifications.create"
            elif request.method in ["PUT", "PATCH"]:
                return "notifications.update"
            elif request.method == "DELETE":
                return "notifications.delete"
        return self.required_permission
    template_name = "notifications/logs/whatsapp.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        return WhatsAppLog.objects.filter(
            company=self.request.user.primary_company
        ).order_by("-created_at")


# ── URL files ──────────────────────────────────────────────────────────────

# api/urls.py content
NOTIFICATION_API_URLS = """
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.notifications.views import NotificationViewSet

app_name = 'api_notifications'
router = DefaultRouter()
router.register('notifications', NotificationViewSet, basename='notification')
urlpatterns = [path('', include(router.urls))]
"""

# web urls.py content
NOTIFICATION_WEB_URLS = """
from django.urls import path
from apps.notifications.views import NotificationListView, MarkReadView
app_name = 'notifications'
urlpatterns = [
    path('', NotificationListView.as_view(), name='list'),
    path('<uuid:pk>/read/', MarkReadView.as_view(), name='mark_read'),
]
"""
