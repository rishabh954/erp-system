from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.company.models import CompanySettings

from .models import CreditNote, Invoice, Payment, SalesCommission


def sync_invoice_commission(invoice):
    if invoice.status != Invoice.Status.PAID or not invoice.sales_order_id:
        return

    sales_rep_id = invoice.sales_order.sales_rep_id
    if not sales_rep_id:
        return

    setting = CompanySettings.objects.filter(
        company=invoice.company, key="sales_commission_rate"
    ).first()
    try:
        commission_rate = Decimal(setting.value) if setting else Decimal("0.05")
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(
            "Company sales_commission_rate must be a decimal fraction, e.g. 0.05."
        ) from exc
    if not commission_rate.is_finite() or commission_rate < 0:
        raise ValueError("Company sales_commission_rate must be a non-negative decimal.")

    credited_amount = invoice.credit_notes.filter(
        status__in=[CreditNote.Status.ISSUED, CreditNote.Status.APPLIED]
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
    commissionable_total = max(Decimal("0"), invoice.total - credited_amount)
    amount = (commissionable_total * commission_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    with transaction.atomic():
        commission, created = SalesCommission.objects.get_or_create(
            company=invoice.company,
            invoice=invoice,
            sales_rep_id=sales_rep_id,
            defaults={
                "amount": amount,
                "status": SalesCommission.Status.PENDING,
            },
        )
        if not created and commission.amount != amount:
            commission.amount = amount
            commission.save(update_fields=["amount"])


@receiver(post_save, sender=Payment)
def generate_sales_commission(sender, instance, **kwargs):
    if instance.status == Payment.Status.COMPLETED and instance.invoice_id:
        sync_invoice_commission(instance.invoice)


@receiver(post_save, sender=Invoice)
def generate_paid_invoice_commission(sender, instance, **kwargs):
    if instance.status == Invoice.Status.PAID:
        sync_invoice_commission(instance)


@receiver(post_save, sender=CreditNote)
def adjust_sales_commission_for_credit_note(sender, instance, **kwargs):
    if instance.invoice_id and instance.company_id == instance.invoice.company_id:
        sync_invoice_commission(instance.invoice)
