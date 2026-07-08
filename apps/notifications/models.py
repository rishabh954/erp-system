from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped

# ═══════════════════════════════ NOTIFICATIONS ════════════════════════════════


class Notification(CompanyScoped):
    class NotificationType(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")
        ERROR = "error", _("Error")
        APPROVAL = "approval", _("Approval Required")
        REMINDER = "reminder", _("Reminder")
        ALERT = "alert", _("Alert")

    recipient = models.ForeignKey(
        "authentication.User", on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(
        max_length=15, choices=NotificationType.choices, default=NotificationType.INFO
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    action_url = models.CharField(max_length=500, blank=True)
    action_label = models.CharField(max_length=100, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    object_id = models.CharField(max_length=100, blank=True)
    source_object = GenericForeignKey("content_type", "object_id")
    extra_data = models.JSONField(default=dict)

    class Meta:
        db_table = "notifications_notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"{self.recipient} | {self.title}"

    def mark_read(self):
        from django.utils import timezone

        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])


class EmailLog(CompanyScoped):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")
        BOUNCED = "bounced", _("Bounced")

    recipient_email = models.EmailField()
    recipient_name = models.CharField(max_length=255, blank=True)
    subject = models.CharField(max_length=500)
    body = models.TextField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    template = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "notifications_email_logs"
        ordering = ["-created_at"]


class SMSLog(CompanyScoped):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Failed")

    recipient_phone = models.CharField(max_length=20)
    recipient_name = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "notifications_sms_logs"
        ordering = ["-created_at"]


class WhatsAppLog(CompanyScoped):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SENT = "sent", _("Sent")
        DELIVERED = "delivered", _("Delivered")
        READ = "read", _("Read")
        FAILED = "failed", _("Failed")

    recipient_phone = models.CharField(max_length=20)
    recipient_name = models.CharField(max_length=255, blank=True)
    template_name = models.CharField(max_length=100)
    template_data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    message_id = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "notifications_whatsapp_logs"
        ordering = ["-created_at"]


class NotificationPreference(CompanyScoped):
    user = models.ForeignKey(
        "authentication.User",
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.CharField(
        max_length=15, choices=Notification.NotificationType.choices
    )
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "notifications_preferences"
        unique_together = ["user", "notification_type"]

    def __str__(self):
        return f"{self.user} - {self.get_notification_type_display()} Preferences"
