"""
Assets Celery Tasks - Depreciation Processing
"""

import logging
from decimal import Decimal

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def process_depreciation():
    """Calculate and record monthly depreciation for all active assets."""
    from apps.assets.models import Asset, DepreciationEntry

    today = timezone.localdate()
    period_start = today.replace(day=1)
    import calendar

    last_day = calendar.monthrange(today.year, today.month)[1]
    period_end = today.replace(day=last_day)

    active_assets = Asset.objects.filter(
        status="active",
        is_deleted=False,
        purchase_date__lte=today,
    ).exclude(depreciation_entries__period_start=period_start)

    created = 0
    for asset in active_assets:
        try:
            annual = asset.calculate_annual_depreciation()
            if annual <= 0:
                continue
            monthly = annual / Decimal("12")

            new_value = max(asset.current_value - monthly, asset.salvage_value)
            actual_dep = asset.current_value - new_value

            if actual_dep <= 0:
                continue

            DepreciationEntry.objects.create(
                company=asset.company,
                asset=asset,
                period_start=period_start,
                period_end=period_end,
                depreciation_amount=actual_dep,
                book_value_before=asset.current_value,
                book_value_after=new_value,
                created_by_id=None,
            )

            asset.current_value = new_value
            asset.accumulated_depreciation += actual_dep
            asset.save(update_fields=["current_value", "accumulated_depreciation"])
            created += 1

        except Exception as e:
            logger.error(f"Depreciation error for asset {asset.pk}: {e}")

    logger.info(f"Depreciation processed for {created} assets")


# ── HelpDesk Tasks ────────────────────────────────────────────────────────────


@shared_task
def check_sla_breaches():
    """Flag tickets that have breached their SLA."""
    from django.utils import timezone

    from apps.helpdesk.models import Ticket
    from apps.notifications.tasks import send_bulk_notification

    now = timezone.now()
    breached = Ticket.objects.filter(
        status__in=["open", "in_progress"],
        sla_due_at__lt=now,
        sla_breached=False,
        is_deleted=False,
    )

    for ticket in breached:
        ticket.sla_breached = True
        ticket.save(update_fields=["sla_breached"])

        # Notify assigned agent and managers
        recipients = []
        if ticket.assigned_to:
            recipients.append(str(ticket.assigned_to_id))

        from apps.authentication.models import User

        managers = User.objects.filter(
            role__in=["company_admin"],
            companies=ticket.company,
            is_active=True,
        ).values_list("pk", flat=True)
        recipients.extend([str(pk) for pk in managers])

        if recipients:
            send_bulk_notification.delay(
                recipient_ids=recipients,
                title=f"SLA Breached: Ticket {ticket.number}",
                message=f'Ticket "{ticket.title}" has breached its SLA.',
                notification_type="alert",
                action_url=f"/helpdesk/tickets/{ticket.pk}/",
                company_id=str(ticket.company_id),
            )

    logger.info(f"Flagged {breached.count()} SLA breaches")


# ── Authentication Tasks ──────────────────────────────────────────────────────


@shared_task
def cleanup_expired_sessions():
    """Remove expired user sessions."""
    from django.utils import timezone

    from apps.authentication.models import UserSession

    deleted = UserSession.objects.filter(expires_at__lt=timezone.now()).delete()
    logger.info(f"Cleaned up {deleted[0]} expired sessions")


@shared_task
def cleanup_old_audit_logs():
    """Remove audit logs older than retention period."""
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from apps.authentication.models import ActivityLog

    days = settings.ERP_SETTINGS.get("AUDIT_LOG_RETENTION_DAYS", 365)
    cutoff = timezone.now() - timedelta(days=days)
    deleted = ActivityLog.objects.filter(created_at__lt=cutoff).delete()
    logger.info(f"Deleted {deleted[0]} old audit log entries")
