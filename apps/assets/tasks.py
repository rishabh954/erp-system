"""
Assets Celery Tasks - Depreciation Processing
"""

import logging
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def process_depreciation():
    """Calculate and record monthly depreciation for all active assets."""
    from apps.assets.models import Asset, DepreciationEntry

    today = timezone.localdate()
    period_start = today.replace(day=1)
    import calendar

    last_day = calendar.monthrange(today.year, today.month)[1]
    period_end = today.replace(day=last_day)

    active_assets = Asset.objects.filter(
        status="active",
        is_deleted=False,
        purchase_date__lte=today,
    ).exclude(depreciation_entries__period_start=period_start)

    created = 0
    for asset in active_assets:
        try:
            annual = asset.calculate_annual_depreciation()
            if annual <= 0:
                continue
            monthly = annual / Decimal("12")

            new_value = max(asset.current_value - monthly, asset.salvage_value)
            actual_dep = asset.current_value - new_value

            if actual_dep <= 0:
                continue

            DepreciationEntry.objects.create(
                company=asset.company,
                asset=asset,
                period_start=period_start,
                period_end=period_end,
                depreciation_amount=actual_dep,
                book_value_before=asset.current_value,
                book_value_after=new_value,
                created_by_id=None,
            )

            asset.current_value = new_value
            asset.accumulated_depreciation += actual_dep
            asset.save(update_fields=["current_value", "accumulated_depreciation"])
            created += 1

        except Exception as e:
            logger.error(f"Depreciation error for asset {asset.pk}: {e}")

    logger.info(f"Depreciation processed for {created} assets")
