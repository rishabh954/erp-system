from datetime import timedelta

from celery import shared_task
from django.db.models import Max
from django.utils import timezone

from apps.crm.models import Lead
from apps.notifications.tasks import send_bulk_notification


@shared_task
def follow_up_leads():
    """
    Find leads with no activity for 7+ days and notify the assigned user.
    """
    seven_days_ago = timezone.now() - timedelta(days=7)

    # Leads with no activity or last activity > 7 days ago
    # We annotate the latest activity completion date or creation date
    leads = Lead.objects.annotate(
        last_activity_date=Max("activities__created_at")
    ).filter(
        status__in=[
            Lead.Status.NEW,
            Lead.Status.CONTACTED,
            Lead.Status.QUALIFIED,
            Lead.Status.PROPOSAL,
            Lead.Status.NEGOTIATION,
        ],
        assigned_to__isnull=False,
    )

    notifications = []
    for lead in leads:
        last_action_date = lead.last_activity_date or lead.created_at
        if last_action_date < seven_days_ago:
            notifications.append(
                {
                    "recipient_id": lead.assigned_to_id,
                    "title": "Lead Follow-up Required",
                    "message": f"The lead '{lead.name}' has had no activity for over 7 days. Please follow up.",
                    "notification_type": "reminder",
                    "action_url": f"/crm/leads/{lead.pk}/",
                    "action_label": "View Lead",
                }
            )

    if notifications:
        send_bulk_notification.delay(notifications)
        return f"Queued {len(notifications)} lead follow-up notifications."
    return "No follow-ups required."


@shared_task
def calculate_lead_scores():
    """
    Recalculate lead probability/scores based on activity, value, and current status.
    """
    leads = Lead.objects.filter(
        status__in=[
            Lead.Status.NEW,
            Lead.Status.CONTACTED,
            Lead.Status.QUALIFIED,
            Lead.Status.PROPOSAL,
            Lead.Status.NEGOTIATION,
        ]
    )

    updated_count = 0
    for lead in leads:
        base_prob = 10
        if lead.status == Lead.Status.CONTACTED:
            base_prob = 20
        elif lead.status == Lead.Status.QUALIFIED:
            base_prob = 40
        elif lead.status == Lead.Status.PROPOSAL:
            base_prob = 60
        elif lead.status == Lead.Status.NEGOTIATION:
            base_prob = 80

        # Boost based on activity count
        activity_count = lead.activities.count()
        activity_boost = min(activity_count * 2, 20)  # Max +20% from activities

        # New probability calculation
        new_prob = min(base_prob + activity_boost, 99)

        if lead.probability != new_prob:
            lead.probability = new_prob
            lead.save(update_fields=["probability"])
            updated_count += 1

    return f"Updated probability for {updated_count} leads."
