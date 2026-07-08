from decimal import Decimal

import pytest
from django.utils import timezone

from apps.inventory.models import InventoryTransfer, Product, StockMovement, StockRecord
from apps.inventory.services import (
    InventoryAnalyticsService,
    StockService,
    TransferService,
)


@pytest.fixture
def to_warehouse(db, company):
    from apps.inventory.models import Warehouse

    return Warehouse.objects.create(
        company=company, name="Second Warehouse", code="SEC"
    )


@pytest.mark.django_db
class TestMovements:
    def test_receive_stock(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        mov = service.receive_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("100.00"),
            unit_cost=Decimal("45.00"),
            reference_type="PO",
            reference_id="PO-001",
        )
        assert mov.movement_type == StockMovement.MovementType.RECEIPT
        assert mov.quantity == Decimal("100.00")
        assert mov.unit_cost == Decimal("45.00")

        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("100.00")
        assert stock.average_cost == Decimal("45.00")

    def test_adjust_stock_set(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        service.receive_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("50.00"),
            unit_cost=Decimal("10.00"),
            reference_type="PO",
            reference_id="1",
        )

        mov = service.adjust_stock(
            product=product,
            warehouse=warehouse,
            qty_input=Decimal("30.00"),
            adjustment_type="set",
            notes="Found less",
        )

        assert mov.movement_type == StockMovement.MovementType.ADJUSTMENT
        assert mov.quantity == Decimal("-20.00")

        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("30.00")

    def test_adjust_stock_add(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        mov = service.adjust_stock(
            product=product,
            warehouse=warehouse,
            qty_input=Decimal("10.00"),
            adjustment_type="add",
            notes="Found more",
        )

        assert mov.movement_type == StockMovement.MovementType.ADJUSTMENT
        assert mov.quantity == Decimal("10.00")

        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("10.00")

    def test_adjust_stock_remove(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        service.receive_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("50.00"),
            unit_cost=Decimal("10.00"),
            reference_type="PO",
            reference_id="1",
        )
        mov = service.adjust_stock(
            product=product,
            warehouse=warehouse,
            qty_input=Decimal("10.00"),
            adjustment_type="remove",
            notes="Lost",
        )

        assert mov.movement_type == StockMovement.MovementType.ADJUSTMENT
        assert mov.quantity == Decimal("-10.00")

        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("40.00")

    def test_adjust_stock_insufficient(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        with pytest.raises(ValueError, match="Insufficient stock"):
            service.adjust_stock(
                product=product,
                warehouse=warehouse,
                qty_input=Decimal("10.00"),
                adjustment_type="remove",
                notes="Lost",
            )

    def test_reserve_and_release_stock(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        service.receive_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("50.00"),
            unit_cost=Decimal("10.00"),
            reference_type="PO",
            reference_id="1",
        )

        # Reserve stock
        stock = service.reserve_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("20.00"),
            reference_type="SO",
            reference_id="1",
        )
        assert stock.quantity_reserved == Decimal("20.00")
        assert stock.quantity_available == Decimal("30.00")

        # Release reservation
        stock = service.release_reservation(
            product=product,
            warehouse=warehouse,
            qty=Decimal("10.00"),
            reference_type="SO",
            reference_id="1",
        )
        assert stock.quantity_reserved == Decimal("10.00")
        assert stock.quantity_available == Decimal("40.00")

    def test_reserve_stock_insufficient(self, company, user, product, warehouse):
        service = StockService(company=company, user=user)
        with pytest.raises(ValueError, match="Cannot reserve"):
            service.reserve_stock(
                product=product,
                warehouse=warehouse,
                qty=Decimal("20.00"),
                reference_type="SO",
                reference_id="1",
            )

    def test_validate_tracking_requirements(self, company, user, product):
        service = StockService(company=company, user=user)
        # Test LOT tracking
        product.tracking_method = Product.TrackingMethod.LOT
        product.save()
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="requires a lot/batch number"):
            service.validate_tracking_requirements(product=product, batch_number="")

        # Valid LOT
        service.validate_tracking_requirements(product=product, batch_number="B123")

        # Test SERIAL tracking
        product.tracking_method = Product.TrackingMethod.SERIAL
        product.save()
        with pytest.raises(ValidationError, match="requires serial number"):
            service.validate_tracking_requirements(product=product, serial_numbers=[])

        # Valid SERIAL
        service.validate_tracking_requirements(product=product, serial_numbers=["S123"])

    def test_transfer_workflow(self, company, user, product, warehouse, to_warehouse):
        stock_service = StockService(company=company, user=user)
        stock_service.receive_stock(
            product=product,
            warehouse=warehouse,
            qty=Decimal("100.00"),
            unit_cost=Decimal("10.00"),
            reference_type="PO",
            reference_id="1",
        )

        transfer_service = TransferService(company=company, user=user)
        from django.http import QueryDict

        data = QueryDict(mutable=True)
        data.update(
            {
                "from_warehouse": warehouse.id,
                "to_warehouse": to_warehouse.id,
                "transfer_date": "2023-01-01",
            }
        )
        data.setlist("product[]", [str(product.id)])
        data.setlist("quantity[]", ["40"])

        # 1. Create Transfer
        transfer = transfer_service.create_transfer(data, user)
        assert transfer.status == InventoryTransfer.Status.DRAFT

        # 2. Submit Transfer
        transfer = transfer_service.process_transfer(transfer, "submit", {}, user)
        assert transfer.status == InventoryTransfer.Status.APPROVED

        # 3. Ship Transfer
        ship_data = QueryDict(mutable=True)
        ship_data.update({f"qty_sent_{transfer.lines.first().id}": "40"})
        transfer = transfer_service.process_transfer(transfer, "ship", ship_data, user)
        assert transfer.status == InventoryTransfer.Status.IN_TRANSIT

        stock = StockRecord.objects.get(product=product, warehouse=warehouse)
        assert stock.quantity_on_hand == Decimal("60.00")

        # 4. Receive Transfer
        receive_data = QueryDict(mutable=True)
        receive_data.update({f"qty_recv_{transfer.lines.first().id}": "40"})
        transfer = transfer_service.process_transfer(
            transfer, "receive", receive_data, user
        )
        assert transfer.status == InventoryTransfer.Status.RECEIVED

        stock_to = StockRecord.objects.get(product=product, warehouse=to_warehouse)
        assert stock_to.quantity_on_hand == Decimal("40.00")

    def test_transfer_same_warehouse(self, company, user, warehouse):
        transfer_service = TransferService(company=company, user=user)
        from django.http import QueryDict

        data = QueryDict(mutable=True)
        data.update(
            {
                "from_warehouse": warehouse.id,
                "to_warehouse": warehouse.id,
                "transfer_date": "2023-01-01",
            }
        )
        with pytest.raises(
            ValueError, match="Source and destination warehouses cannot be the same"
        ):
            transfer_service.create_transfer(data, user)

    def test_transfer_no_lines(self, company, user, warehouse, to_warehouse):
        transfer_service = TransferService(company=company, user=user)
        from django.http import QueryDict

        data = QueryDict(mutable=True)
        data.update(
            {
                "from_warehouse": warehouse.id,
                "to_warehouse": to_warehouse.id,
                "transfer_date": "2023-01-01",
            }
        )
        # Empty products
        data.setlist("product[]", [])
        with pytest.raises(
            ValueError, match="must have at least one valid product line"
        ):
            transfer_service.create_transfer(data, user)

    def test_transfer_cancel(self, company, user, product, warehouse, to_warehouse):
        transfer_service = TransferService(company=company, user=user)
        from django.http import QueryDict

        data = QueryDict(mutable=True)
        data.update(
            {
                "from_warehouse": warehouse.id,
                "to_warehouse": to_warehouse.id,
                "transfer_date": "2023-01-01",
            }
        )
        data.setlist("product[]", [str(product.id)])
        data.setlist("quantity[]", ["40"])

        transfer = transfer_service.create_transfer(data, user)
        assert transfer.status == InventoryTransfer.Status.DRAFT

        transfer = transfer_service.process_transfer(transfer, "cancel", {}, user)
        assert transfer.status == InventoryTransfer.Status.CANCELLED

    def test_compute_abc_analysis(self, company, product, warehouse):
        # Create usage for product
        mov = StockMovement.objects.create(
            company=company,
            product=product,
            warehouse=warehouse,
            movement_type=StockMovement.MovementType.DELIVERY,
            quantity=Decimal("-100.00"),
            unit_cost=Decimal("50.00"),
            total_cost=Decimal("-5000.00"),
            movement_date=timezone.now().date(),
            stock_after=Decimal("0"),
        )

        InventoryAnalyticsService.compute_abc_analysis(company)
        product.refresh_from_db()
        assert product.abc_classification == "A"
