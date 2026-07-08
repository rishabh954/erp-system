from decimal import Decimal

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Invoice, Payment, SalesCommission


@receiver(post_save, sender=Payment)
def generate_sales_commission(sender, instance, created, **kwargs):
    if instance.status == Payment.Status.COMPLETED and instance.invoice:
        invoice = instance.invoice
        # Only calculate if the invoice has a sales rep and is fully paid
        if (
            invoice.status == Invoice.Status.PAID
            and invoice.sales_order
            and invoice.sales_order.sales_rep
        ):
            # Let's say commission is 5% of the payment amount
            commission_rate = Decimal("0.05")
            commission_amount = instance.amount * commission_rate

            SalesCommission.objects.create(
                company=instance.company,
                sales_rep=invoice.sales_order.sales_rep,
                invoice=invoice,
                amount=commission_amount,
                status=SalesCommission.Status.PENDING,
            )
