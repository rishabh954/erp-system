"""
Inventory Celery Tasks
"""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def send_low_stock_alerts():
    """Alert inventory managers about products below reorder point."""
    from apps.inventory.models import Product, StockRecord
    from apps.authentication.models import User
    from apps.notifications.tasks import send_bulk_notification
    from django.db.models import Sum, F

    low_stock = Product.objects.filter(
        is_active=True, is_deleted=False,
        product_type='stockable',
    ).annotate(
        total_stock=Sum('stock_records__quantity_on_hand')
    ).filter(total_stock__lte=F('reorder_point'))

    for product in low_stock:
        from apps.company.models import Company
        company = product.company
        managers = User.objects.filter(
            role__in=['inventory_manager', 'company_admin'],
            companies=company,
            is_active=True,
        ).values_list('pk', flat=True)

        send_bulk_notification.delay(
            recipient_ids=list(managers),
            title=f'Low Stock Alert: {product.name}',
            message=(
                f'{product.sku} — {product.name} is at {product.total_stock} units '
                f'(reorder point: {product.reorder_point})'
            ),
            notification_type='alert',
            action_url=f'/inventory/products/{product.pk}/',
            company_id=str(company.pk),
        )

    logger.info(f'Sent low stock alerts for {low_stock.count()} products')
