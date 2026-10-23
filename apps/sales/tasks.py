"""
Sales Celery Tasks
"""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def check_overdue_invoices():
    """Mark invoices as overdue and send reminders."""
    from apps.company.models import Company
    from apps.notifications.tasks import send_email_task
    from apps.sales.models import Invoice

    today = timezone.localdate()
    processed = 0
    for company in Company.objects.filter(status="active", is_deleted=False):
        invoice_ids = Invoice.objects.filter(
            company=company,
            status__in=[Invoice.Status.SENT, Invoice.Status.PARTIAL],
            due_date__lt=today,
            is_deleted=False,
        ).values_list("pk", flat=True)

        for invoice_id in invoice_ids:
            with transaction.atomic():
                invoice = (
                    Invoice.objects.select_for_update()
                    .filter(
                        company=company,
                        pk=invoice_id,
                        status__in=[Invoice.Status.SENT, Invoice.Status.PARTIAL],
                        due_date__lt=today,
                        is_deleted=False,
                    )
                    .select_related("customer")
                    .first()
                )
                if invoice is None:
                    continue

                invoice.status = Invoice.Status.OVERDUE
                invoice.save(update_fields=["status"])
                processed += 1

                if invoice.customer.email:
                    email_payload = {
                        "to_email": invoice.customer.email,
                        "to_name": invoice.customer.name,
                        "subject": f"Payment Reminder: Invoice {invoice.number} is overdue",
                        "template": "invoice_overdue",
                        "context": {
                            "invoice_number": invoice.number,
                            "balance_due": float(invoice.balance_due),
                            "due_date": str(invoice.due_date),
                            "days_overdue": (today - invoice.due_date).days,
                        },
                        "company_id": str(company.pk),
                    }
                    transaction.on_commit(
                        lambda payload=email_payload: send_email_task.delay(**payload)
                    )

    logger.info("Processed %s overdue invoices", processed)
    return processed
