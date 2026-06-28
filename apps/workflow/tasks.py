"""
Enterprise Workflow — Celery Tasks
Handles escalation polling and scheduled reminder dispatch.
"""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task(name='workflow.check_escalations')
def check_escalations():
    """
    Periodic task — run every 30 minutes via Celery Beat.
    Checks all in-progress workflow instances for SLA breaches and triggers escalation.
    """
    try:
        from apps.workflow.engine import WorkflowEngine
        WorkflowEngine.check_and_escalate()
        logger.info("WorkflowEngine escalation check completed.")
    except Exception as e:
        logger.error(f"Escalation check failed: {e}", exc_info=True)


@shared_task(name='workflow.send_pending_reminders')
def send_pending_reminders():
    """
    Daily reminder task — nudges approvers who haven't acted in 24 hours.
    """
    from datetime import timedelta
    from django.utils import timezone
    from apps.workflow.models import WorkflowInstance, WorkflowNotificationTemplate
    from apps.workflow.engine import WorkflowEngine

    threshold = timezone.now() - timedelta(hours=24)
    instances = WorkflowInstance.objects.filter(
        status__in=['in_progress', 'pending'],
        current_step_started_at__lte=threshold,
    ).select_related('definition', 'current_step', 'initiated_by', 'company')

    for inst in instances:
        try:
            approvers = WorkflowEngine.get_pending_approvers(inst)
            document = inst.related_object
            if document:
                WorkflowEngine._send_notifications(
                    inst, document,
                    event=WorkflowNotificationTemplate.Event.REMINDER,
                    recipients=approvers,
                )
        except Exception as e:
            logger.error(f"Reminder failed for instance {inst.id}: {e}")

    logger.info(f"Sent pending reminders for {instances.count()} workflow instances.")
