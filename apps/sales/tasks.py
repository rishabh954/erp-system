"""
Sales Celery Tasks
"""
from celery import shared_task
from datetime import date
import logging

logger = logging.getLogger(__name__)


@shared_task
def check_overdue_invoices():
    """Mark invoices as overdue and send reminders."""
    from apps.sales.models import Invoice
    from apps.notifications.tasks import send_email_task

    today = date.today()
    overdue = Invoice.objects.filter(
        status__in=['sent', 'partial'],
        due_date__lt=today,
        is_deleted=False,
    ).select_related('customer', 'company')

    for inv in overdue:
        # Update status
        inv.status = Invoice.Status.OVERDUE
        inv.save(update_fields=['status'])

        # Send reminder to customer
        if inv.customer.email:
            send_email_task.delay(
                to_email=inv.customer.email,
                to_name=inv.customer.name,
                subject=f'Payment Reminder: Invoice {inv.number} is overdue',
                template='invoice_overdue',
                context={
                    'invoice_number': inv.number,
                    'balance_due': float(inv.balance_due),
                    'due_date': str(inv.due_date),
                    'days_overdue': (today - inv.due_date).days,
                },
                company_id=str(inv.company_id),
            )

    logger.info(f'Processed {overdue.count()} overdue invoices')
