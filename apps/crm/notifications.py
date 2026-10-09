from django.urls import reverse

from apps.notifications.models import Notification
from apps.notifications.services import NotificationService


def notify_lead_created(lead, created_by):
    recipients = {
        user.pk: user
        for user in (created_by, lead.assigned_to)
        if user is not None
    }
    return NotificationService.send_bulk(
        recipients=recipients.values(),
        title="New lead created",
        message=f"Lead {lead.number} - {lead.name} was created.",
        notification_type=Notification.NotificationType.INFO,
        channels=["in_app"],
        action_url=reverse("crm:lead_detail", kwargs={"pk": lead.pk}),
        company=lead.company,
        related_object=lead,
    )
