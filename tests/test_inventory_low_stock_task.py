from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.company.models import Company
from apps.inventory.models import Product, StockRecord, Warehouse


@pytest.mark.django_db
def test_low_stock_alerts_only_aggregate_stock_from_product_company():
    from apps.inventory.tasks import send_low_stock_alerts
    from apps.notifications.tasks import send_bulk_notification

    company_a = Company.objects.create(name="Low Stock A")
    company_b = Company.objects.create(name="Low Stock B")
    product_a = Product.objects.create(
        company=company_a,
        name="Tenant A Product",
        sku="A-LOW",
        reorder_point=Decimal("10"),
    )
    product_b = Product.objects.create(
        company=company_b,
        name="Tenant B Product",
        sku="B-OK",
        reorder_point=Decimal("10"),
    )
    warehouse_b = Warehouse.objects.create(
        company=company_b, name="Tenant B Warehouse", code="B-WH"
    )
    # Deliberately inconsistent tenant ownership: corrupted/cross-tenant stock
    # must not make company A's product appear healthy.
    StockRecord.objects.create(
        company=company_b,
        product=product_a,
        warehouse=warehouse_b,
        quantity_on_hand=Decimal("50"),
    )
    StockRecord.objects.create(
        company=company_b,
        product=product_b,
        warehouse=warehouse_b,
        quantity_on_hand=Decimal("50"),
    )

    with patch.object(send_bulk_notification, "delay") as queue_notification:
        send_low_stock_alerts.run()

    assert queue_notification.call_count == 1
    payload = queue_notification.call_args.kwargs
    assert payload["company_id"] == str(company_a.pk)
    assert payload["action_url"] == f"/inventory/products/{product_a.pk}/"
