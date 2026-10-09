import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.helpdesk.tasks.check_sla_breaches")
def check_sla_breaches():
    """Flag tickets that have breached their SLA."""
    from apps.authentication.models import User
    from apps.helpdesk.models import Ticket
    from apps.notifications.tasks import send_bulk_notification

    breached = Ticket.objects.filter(
        status__in=["open", "in_progress"],
        sla_due_at__lt=timezone.now(),
        sla_breached=False,
        is_deleted=False,
    )

    for ticket in breached:
        ticket.sla_breached = True
        ticket.save(update_fields=["sla_breached"])

        recipients = []
        if ticket.assigned_to:
            recipients.append(str(ticket.assigned_to_id))

        managers = User.objects.filter(
            role__in=["company_admin"],
            companies=ticket.company,
            is_active=True,
        ).values_list("pk", flat=True)
        recipients.extend(str(pk) for pk in managers)

        if recipients:
            send_bulk_notification.delay(
                recipient_ids=recipients,
                title=f"SLA Breached: Ticket {ticket.number}",
                message=f'Ticket "{ticket.title}" has breached its SLA.',
                notification_type="alert",
                action_url=f"/helpdesk/tickets/{ticket.pk}/",
                company_id=str(ticket.company_id),
            )

    count = breached.count()
    logger.info("Flagged %s SLA breaches", count)
    return count
