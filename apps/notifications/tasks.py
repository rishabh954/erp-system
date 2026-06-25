"""
Notifications Celery Tasks
Email, in-app notifications, scheduled reminders
"""

from celery import shared_task
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_email_task(self, to_email, to_name, subject, template, context, company_id=None):
    """Send a rendered HTML email with plain text fallback."""
    try:
        if company_id:
            from apps.company.models import Company
            try:
                company = Company.objects.get(pk=company_id)
                context['company'] = company
            except Company.DoesNotExist:
                pass

        context.setdefault('site_url', settings.ERP_SETTINGS.get('SITE_URL', 'http://localhost'))
        context.setdefault('support_email', settings.DEFAULT_FROM_EMAIL)

        html_content = render_to_string(f'emails/{template}.html', context)
        text_content = strip_tags(html_content)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[f'{to_name} <{to_email}>' if to_name else to_email],
        )
        msg.attach_alternative(html_content, 'text/html')
        msg.send()

        # Log it
        from apps.notifications.models import EmailLog
        EmailLog.objects.create(
            recipient_email=to_email,
            recipient_name=to_name,
            subject=subject,
            body=html_content[:5000],
            status='sent',
            template=template,
        )
        logger.info(f'Email sent to {to_email}: {subject}')

    except Exception as exc:
        logger.error(f'Email send failed to {to_email}: {exc}')
        from apps.notifications.models import EmailLog
        EmailLog.objects.create(
            recipient_email=to_email,
            recipient_name=to_name,
            subject=subject,
            body='',
            status='failed',
            error_message=str(exc),
            template=template,
        )
        raise self.retry(exc=exc)


@shared_task
def send_bulk_notification(recipient_ids, title, message, notification_type='info',
                           action_url='', company_id=None):
    """Send in-app notifications to multiple users."""
    from apps.notifications.models import Notification
    from apps.authentication.models import User

    if not company_id:
        return

    try:
        from apps.company.models import Company
        company = Company.objects.get(pk=company_id)
    except Exception:
        return

    users = User.objects.filter(pk__in=recipient_ids, is_active=True)
    notifications = [
        Notification(
            company=company,
            recipient=user,
            notification_type=notification_type,
            title=title,
            message=message,
            action_url=action_url,
        )
        for user in users
    ]
    Notification.objects.bulk_create(notifications, batch_size=500)
    logger.info(f'Bulk notification sent to {len(notifications)} users: {title}')


@shared_task
def process_workflow_step(instance_id, step_id):
    """Advance a workflow instance to the next step."""
    from apps.workflow.models import WorkflowInstance, WorkflowStep
    try:
        instance = WorkflowInstance.objects.get(pk=instance_id)
        step = WorkflowStep.objects.get(pk=step_id)

        if step.step_type == 'notification':
            # Determine recipient and send notification
            if step.approver_type == 'role':
                from apps.authentication.models import User
                recipients = User.objects.filter(
                    role=step.approver_role,
                    companies=instance.company,
                    is_active=True,
                )
                send_bulk_notification.delay(
                    recipient_ids=list(recipients.values_list('pk', flat=True)),
                    title=step.action_config.get('notification_title', 'Action Required'),
                    message=step.action_config.get('notification_message', ''),
                    notification_type='approval',
                    company_id=str(instance.company_id),
                )
    except Exception as e:
        logger.error(f'Workflow step processing failed: {e}')
