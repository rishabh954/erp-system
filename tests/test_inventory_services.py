"""
Tests for Inventory Services in ERP system.
"""
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import InventoryTransfer, StockRecord
from apps.inventory.services import StockService, TransferService


@pytest.mark.django_db
class TestInventoryServices:
    def test_receive_stock_increases_stock(self, company, product, warehouse):
        """Test: StockService.receive_stock increases stock"""
        service = StockService(company=company)
        mov = service.receive_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("50.00"),
            unit_cost=Decimal("10.00"),
            reference_type="manual",
            reference_id="ref1"
        )

        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("50.00")
        assert mov.quantity == Decimal("50.00")

    def test_issue_stock_decreases_stock(self, company, product, warehouse):
        """Test: StockService.adjust_stock(remove) decreases stock"""
        service = StockService(company=company)
        service.receive_stock(
            product=product, warehouse=warehouse, qty=Decimal("100.00"), unit_cost=Decimal("10.00"), reference_type="test", reference_id="1"
        )

        mov = service.adjust_stock(product, warehouse, Decimal("20.00"), "remove")
        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("80.00")
        assert mov.quantity == Decimal("-20.00")

    def test_issue_stock_raises_error_if_insufficient_stock(self, company, product, warehouse):
        """Test: issue_stock raises error if insufficient stock"""
        service = StockService(company=company)
        service.receive_stock(
            product=product, warehouse=warehouse, qty=Decimal("10.00"), unit_cost=Decimal("10.00"), reference_type="test", reference_id="1"
        )

        with pytest.raises(ValueError, match="Insufficient stock"):
            service.adjust_stock(product, warehouse, Decimal("20.00"), "remove")

    def test_stock_transfer_between_warehouses(self, company, product, warehouse, user):
        """Test: stock transfer between warehouses"""
        from apps.inventory.models import Warehouse
        warehouse2 = Warehouse.objects.create(company=company, name='Warehouse 2', code='WH2')

        stock_service = StockService(company=company, user=user)
        stock_service.receive_stock(product=product, warehouse=warehouse, qty=Decimal("100.00"), unit_cost=Decimal("10.00"), reference_type="t", reference_id="1")

        transfer_service = TransferService(company=company, user=user)

        data = {
            "from_warehouse": warehouse.id,
            "to_warehouse": warehouse2.id,
            "transfer_date": timezone.now().date(),
            "product[]": [str(product.id)],
            "quantity[]": ["40.00"]
        }
        transfer = transfer_service.create_transfer(data, user)

        transfer = transfer_service.process_transfer(transfer, "submit", {}, user)
        assert transfer.status == InventoryTransfer.Status.APPROVED

        transfer = transfer_service.process_transfer(transfer, "ship", {f"qty_sent_{transfer.lines.first().id}": "40.00"}, user)
        assert transfer.status == InventoryTransfer.Status.IN_TRANSIT

        stock1 = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock1.quantity_on_hand == Decimal("60.00")

        transfer = transfer_service.process_transfer(transfer, "receive", {f"qty_recv_{transfer.lines.first().id}": "40.00"}, user)
        assert transfer.status == InventoryTransfer.Status.RECEIVED

        stock2 = StockRecord.objects.get(product=product, warehouse=warehouse2)
        assert stock2.quantity_on_hand == Decimal("40.00")

    def test_low_stock_alert_triggered_when_below_reorder_level(self, company, product, warehouse):
        """Test: low stock alert triggered when below reorder_level (product.needs_reorder property)"""
        product.reorder_point = Decimal("20.00")
        product.save()

        service = StockService(company=company)
        service.receive_stock(
            product=product, warehouse=warehouse, qty=Decimal("30.00"), unit_cost=Decimal("10.00"), reference_type="test", reference_id="1"
        )
        assert not product.needs_reorder

        service.adjust_stock(product, warehouse, Decimal("15.00"), "remove")
        assert product.needs_reorder
