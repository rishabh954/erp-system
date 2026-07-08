from django.urls import path

from .views import (
    AdminEmailLogListView,
    AdminSMSLogListView,
    AdminWhatsAppLogListView,
    MarkReadView,
    NotificationListView,
    NotificationPreferenceUpdateView,
)

app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="list"),
    path(
        "preferences/", NotificationPreferenceUpdateView.as_view(), name="preferences"
    ),
    path("logs/email/", AdminEmailLogListView.as_view(), name="logs_email"),
    path("logs/sms/", AdminSMSLogListView.as_view(), name="logs_sms"),
    path("logs/whatsapp/", AdminWhatsAppLogListView.as_view(), name="logs_whatsapp"),
    path("<uuid:pk>/read/", MarkReadView.as_view(), name="mark_read"),
]
