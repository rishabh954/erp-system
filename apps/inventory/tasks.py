"""
Inventory Celery Tasks
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_low_stock_alerts():
    """Alert inventory managers about products below reorder point."""
    from django.db.models import DecimalField, F, Q, Sum, Value
    from django.db.models.functions import Coalesce

    from apps.authentication.models import User
    from apps.company.models import Company
    from apps.inventory.models import Product
    from apps.notifications.tasks import send_bulk_notification

    alert_count = 0
    for company in Company.objects.filter(status="active", is_deleted=False):
        low_stock = (
            Product.objects.filter(
                company=company,
                is_active=True,
                is_deleted=False,
                product_type="stockable",
            )
            .annotate(
                alert_total_stock=Coalesce(
                    Sum(
                        "stock_records__quantity_on_hand",
                        filter=Q(
                            stock_records__company=company,
                            stock_records__is_deleted=False,
                        ),
                    ),
                    Value(0),
                    output_field=DecimalField(max_digits=15, decimal_places=4),
                )
            )
            .filter(alert_total_stock__lte=F("reorder_point"))
        )

        for product in low_stock:
            managers = User.objects.filter(
                role__in=["inventory_manager", "company_admin"],
                companies=company,
                is_active=True,
            ).values_list("pk", flat=True)

            send_bulk_notification.delay(
                recipient_ids=list(managers),
                title=f"Low Stock Alert: {product.name}",
                message=(
                    f"{product.sku} — {product.name} is at {product.alert_total_stock} units "
                    f"(reorder point: {product.reorder_point})"
                ),
                notification_type="alert",
                action_url=f"/inventory/products/{product.pk}/",
                company_id=str(company.pk),
            )
            alert_count += 1

    logger.info("Sent low stock alerts for %s products", alert_count)
