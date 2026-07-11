from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.purchase.models import RequestForQuotation, RFQLine
from core.services import BaseService

from .models import StockMovement


@receiver(post_save, sender=StockMovement)
def trigger_reorder_rules(sender, instance, created, **kwargs):
    if created and instance.movement_type in [
        StockMovement.MovementType.DELIVERY,
        StockMovement.MovementType.TRANSFER,
        StockMovement.MovementType.ADJUSTMENT,
    ]:
        product = instance.product
        from django.db import transaction

        with transaction.atomic():
            # Lock the reorder rule to prevent concurrent RFQ creation
            rule = (
                product.reorder_rules.select_for_update()
                .filter(warehouse=instance.warehouse, is_active=True)
                .first()
            )
            if rule:
                stock = (
                    product.stock_records.filter(
                        warehouse=instance.warehouse
                    ).aggregate(
                        total=__import__("django").db.models.Sum("quantity_on_hand")
                    )[
                        "total"
                    ]
                    or 0
                )
                if stock <= rule.min_quantity:
                    quantity_to_order = (
                        rule.max_quantity - stock
                        if rule.max_quantity > stock
                        else product.reorder_quantity
                    )
                    if quantity_to_order > 0:
                        # Check if there's already an active RFQ for this product
                        active_rfqs = RequestForQuotation.objects.filter(
                            company=instance.company,
                            status__in=[
                                RequestForQuotation.Status.DRAFT,
                                RequestForQuotation.Status.PUBLISHED,
                            ],
                            lines__product=product,
                        )
                        if not active_rfqs.exists():
                            # Create RFQ
                            rfq = RequestForQuotation(
                                company=instance.company,
                                title=f"Auto Reorder: {product.name}",
                                deadline=__import__("django")
                                .utils.timezone.now()
                                .date()
                                + __import__("datetime").timedelta(days=7),
                                created_by=(
                                    instance.created_by
                                    if hasattr(instance, "created_by")
                                    and instance.created_by
                                    else __import__("authentication")
                                    .models.User.objects.filter(is_superuser=True)
                                    .first()
                                ),
                            )
                            rfq.number = BaseService.generate_sequence_number("RFQ", RequestForQuotation, rfq.company_id)
                            rfq.save()

                            RFQLine.objects.create(
                                rfq=rfq,
                                product=product,
                                quantity=quantity_to_order,
                                description=f"Auto-generated from reorder rule (Min: {rule.min_quantity})",
                            )
