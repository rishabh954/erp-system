import logging

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.helpdesk.tasks.check_sla_breaches")
def check_sla_breaches():
    """Flag tickets that have breached their SLA."""
    from apps.authentication.models import User
    from apps.company.models import Company
    from apps.helpdesk.models import Ticket
    from apps.notifications.tasks import send_bulk_notification

    now = timezone.now()
    breached_count = 0
    for company in Company.objects.filter(status="active", is_deleted=False):
        candidate_ids = Ticket.objects.filter(
            company=company,
            status__in=["open", "in_progress"],
            sla_due_at__lt=now,
            sla_breached=False,
            is_deleted=False,
        ).values_list("pk", flat=True)

        for ticket_id in candidate_ids:
            with transaction.atomic():
                ticket = (
                    Ticket.objects.select_for_update()
                    .filter(
                        company=company,
                        pk=ticket_id,
                        status__in=["open", "in_progress"],
                        sla_due_at__lt=now,
                        sla_breached=False,
                        is_deleted=False,
                    )
                    .first()
                )
                if ticket is None:
                    continue

                ticket.sla_breached = True
                ticket.save(update_fields=["sla_breached"])

                recipients = User.objects.filter(
                    companies=company,
                    is_active=True,
                ).filter(
                    Q(role="company_admin") | Q(pk=ticket.assigned_to_id)
                ).values_list("pk", flat=True)
                recipient_ids = [str(pk) for pk in recipients]
                if recipient_ids:
                    notification = {
                        "recipient_ids": recipient_ids,
                        "title": f"SLA Breached: Ticket {ticket.number}",
                        "message": f'Ticket "{ticket.title}" has breached its SLA.',
                        "notification_type": "alert",
                        "action_url": f"/helpdesk/tickets/{ticket.pk}/",
                        "company_id": str(company.pk),
                    }
                    transaction.on_commit(
                        lambda payload=notification: send_bulk_notification.delay(
                            **payload
                        )
                    )
                breached_count += 1

    logger.info("Flagged %s SLA breaches", breached_count)
    return breached_count
