"""
Assets Celery Tasks - Depreciation Processing
"""

import logging
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def process_depreciation():
    """Calculate and record monthly depreciation for all active assets."""
    from apps.assets.models import Asset, DepreciationEntry
    from apps.company.models import Company

    today = timezone.localdate()
    period_start = today.replace(day=1)
    import calendar

    last_day = calendar.monthrange(today.year, today.month)[1]
    period_end = today.replace(day=last_day)

    created = 0
    for company in Company.objects.filter(status="active", is_deleted=False):
        asset_ids = Asset.objects.filter(
            company=company,
            status=Asset.Status.ACTIVE,
            is_deleted=False,
            purchase_date__lte=today,
        ).values_list("pk", flat=True)

        for asset_id in asset_ids:
            try:
                with transaction.atomic():
                    asset = (
                        Asset.objects.select_for_update()
                        .filter(
                            company=company,
                            pk=asset_id,
                            status=Asset.Status.ACTIVE,
                            is_deleted=False,
                            purchase_date__lte=today,
                        )
                        .first()
                    )
                    if asset is None or DepreciationEntry.objects.filter(
                        company=company,
                        asset=asset,
                        period_start=period_start,
                    ).exists():
                        continue

                    annual = asset.calculate_annual_depreciation()
                    if annual <= 0:
                        continue
                    monthly = annual / Decimal("12")

                    new_value = max(
                        asset.current_value - monthly, asset.salvage_value
                    )
                    actual_dep = asset.current_value - new_value
                    if actual_dep <= 0:
                        continue

                    DepreciationEntry.objects.create(
                        company=company,
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
                    asset.save(
                        update_fields=["current_value", "accumulated_depreciation"]
                    )
                    created += 1
            except Exception:
                logger.exception("Depreciation error for asset %s", asset_id)

    logger.info("Depreciation processed for %s assets", created)
    return created
