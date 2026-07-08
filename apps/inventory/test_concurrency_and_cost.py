from decimal import Decimal

import pytest

from apps.inventory.models import StockRecord
from apps.inventory.services import StockService
from core.factories import ProductFactory, WarehouseFactory

pytestmark = pytest.mark.django_db(transaction=True)


def test_receive_stock_weighted_average_cost(company, user):
    """Test that receiving stock correctly calculates weighted average cost."""
    product = ProductFactory(
        company=company,
        name="Average Cost Widget",
        sku="WGT-AVG",
        cost_price=Decimal("10.00"),
    )
    warehouse = WarehouseFactory(company=company, name="Main Warehouse", code="MAIN")
    service = StockService(user=user, company=company)

    # 1st Receipt: 10 units @ 10.00
    service.receive_stock(
        product=product,
        warehouse=warehouse,
        qty=Decimal("10.00"),
        unit_cost=Decimal("10.00"),
        reference_type="GRN",
        reference_id="1",
        user=user,
    )

    stock = StockRecord.objects.get(product=product, warehouse=warehouse)
    assert stock.quantity_on_hand == Decimal("10.00")
    assert stock.average_cost == Decimal("10.00")

    # 2nd Receipt: 10 units @ 20.00.
    # New average should be: ((10*10) + (10*20)) / 20 = 15.00
    service.receive_stock(
        product=product,
        warehouse=warehouse,
        qty=Decimal("10.00"),
        unit_cost=Decimal("20.00"),
        reference_type="GRN",
        reference_id="2",
        user=user,
    )

    stock.refresh_from_db()
    assert stock.quantity_on_hand == Decimal("20.00")
    assert stock.average_cost == Decimal("15.00")


def test_adjust_stock_negative_guard(company, user):
    """Test that adjusting stock below zero raises ValueError."""
    product = ProductFactory(
        company=company, name="Guard Widget", sku="WGT-GRD", cost_price=Decimal("10.00")
    )
    warehouse = WarehouseFactory(company=company, name="Main Warehouse", code="MAIN")
    service = StockService(user=user, company=company)

    # Receive 5 units
    service.receive_stock(
        product=product,
        warehouse=warehouse,
        qty=Decimal("5.00"),
        unit_cost=Decimal("10.00"),
        reference_type="GRN",
        reference_id="1",
    )

    # Try to remove 6 units
    with pytest.raises(ValueError, match="Insufficient stock"):
        service.adjust_stock(
            product=product,
            warehouse=warehouse,
            qty_input="6.00",
            adjustment_type="remove",
            notes="Test remove",
        )
