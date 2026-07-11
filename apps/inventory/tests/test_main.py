from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.inventory.models import InventoryTransfer, StockMovement, StockRecord
from apps.inventory.services import StockService, TransferService
from apps.purchase.models import PurchaseOrder, PurchaseOrderLine
from core.factories import ProductFactory, VendorFactory, WarehouseFactory

pytestmark = pytest.mark.django_db


def test_goods_receipt_updates_stock(client, company, user):
    """Test that receiving a Purchase Order properly updates inventory stock."""
    # Create test inventory data
    product = ProductFactory(company=company, name="Test Widget", sku="WGT-001")
    warehouse = WarehouseFactory(company=company, name="Main Warehouse", code="MAIN")

    # Create test purchase data
    vendor = VendorFactory(company=company, name="Test Vendor")
    po = PurchaseOrder.objects.create(
        company=company,
        vendor=vendor,
        order_date="2026-06-01",
        status=PurchaseOrder.Status.CONFIRMED,
        number="PO-1001",
    )
    po_line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        product=product,
        description="Test Widget Line",
        quantity=Decimal("10.00"),
        unit_price=Decimal("5.00"),
    )

    # Setup client authentication
    client.force_login(user)

    # Initial stock should be 0 or nonexistent
    assert StockRecord.objects.filter(product=product).exists() == False

    # Submit GRN form via the view
    url = reverse("purchase:order_receive", args=[po.pk])
    response = client.post(
        url,
        {
            f"qty_{po_line.pk}": "10",
            f"batch_{po_line.pk}": "BATCH123",
            "warehouse": warehouse.pk,
            "notes": "Received fine",
        },
    )

    # View redirects on success
    assert response.status_code == 302

    # Check stock record was created and updated
    stock_record = StockRecord.objects.get(product=product)
    assert stock_record.quantity_on_hand == Decimal("10.00")
    assert stock_record.warehouse == warehouse


def test_product_list_view_n_plus_one(client, user, company):
    """Test that ProductListView does not suffer from N+1 queries when accessing total_stock."""
    client.force_login(user)
    user.role = "company_admin"
    user.save()

    # Create multiple products (use a larger number to prove O(1))
    for i in range(15):
        p = ProductFactory(company=company, name=f"Product {i}")
        warehouse = WarehouseFactory(company=company, name=f"WH {i}")
        StockRecord.objects.create(
            company=company,
            product=p,
            warehouse=warehouse,
            quantity_on_hand=Decimal("10.0"),
            average_cost=Decimal("5.0"),
        )
    
    # Pre-fetch the view once to warm up any caches
    client.get(reverse("inventory:products"))

    from django.test.utils import CaptureQueriesContext
    from django.db import connection

    # With the annotation fix, this should only take a small constant number of queries
    # rather than scaling linearly with the number of products
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(reverse("inventory:products"))
        assert response.status_code == 200
    
    # If N+1 was present, 15 products * 2 queries = 30+ extra queries.
    # The baseline is around 19 queries for auth, session, context processors, etc.
    assert len(ctx.captured_queries) < 25, f"Too many queries ({len(ctx.captured_queries)})"


@pytest.fixture
def inventory_services(db, rf, company, user, warehouse, product):
    from core.factories import CustomerFactory, VendorFactory

    vendor = VendorFactory(company=company, name="Test Vendor")
    customer = CustomerFactory(company=company, name="Test Customer")

    class MockData(dict):
        def getlist(self, key):
            return self.get(key, [])

    # Create another warehouse
    from apps.inventory.models import Warehouse

    warehouse2 = Warehouse.objects.create(
        company=company, name="Warehouse 2", code="WH2", is_active=True
    )

    return {
        "company": company,
        "user": user,
        "warehouse": warehouse,
        "warehouse2": warehouse2,
        "product": product,
        "vendor": vendor,
        "customer": customer,
        "MockData": MockData,
        "stock_service": StockService(user=user, company=company),
        "transfer_service": TransferService(user=user, company=company),
    }


def test_stock_adjustment(inventory_services):
    service = inventory_services["stock_service"]
    product = inventory_services["product"]
    warehouse = inventory_services["warehouse"]

    # Adjust stock (add)
    mov = service.adjust_stock(
        product=product,
        warehouse=warehouse,
        qty_input="100.5",
        adjustment_type="add",
        notes="Test add",
    )

    stock = StockRecord.objects.get(product=product, warehouse=warehouse)
    assert stock.quantity_on_hand == Decimal("100.5")
    assert mov.quantity == Decimal("100.5")
    assert mov.movement_type == StockMovement.MovementType.ADJUSTMENT

    # Adjust stock (remove)
    mov = service.adjust_stock(
        product=product,
        warehouse=warehouse,
        qty_input="20.5",
        adjustment_type="remove",
        notes="Test remove",
    )
    stock.refresh_from_db()
    assert stock.quantity_on_hand == Decimal("80.0")
    assert mov.quantity == Decimal("-20.5")


def test_transfer_service(inventory_services):
    service = inventory_services["transfer_service"]
    stock_service = inventory_services["stock_service"]
    product = inventory_services["product"]
    wh1 = inventory_services["warehouse"]
    wh2 = inventory_services["warehouse2"]

    # Add initial stock
    stock_service.adjust_stock(product, wh1, "50", "add")

    data = inventory_services["MockData"](
        {
            "from_warehouse": wh1.pk,
            "to_warehouse": wh2.pk,
            "transfer_date": timezone.now().date(),
            "product[]": [product.pk],
            "quantity[]": ["10"],
        }
    )

    transfer = service.create_transfer(data, inventory_services["user"])
    assert transfer.status == InventoryTransfer.Status.DRAFT

    # Process transfer
    service.process_transfer(transfer, "submit", {}, inventory_services["user"])

    # If no workflow intercepts, it might become APPROVED. Let's assume APPROVED for this simple test.
    if transfer.status == InventoryTransfer.Status.PENDING_APPROVAL:
        transfer.status = InventoryTransfer.Status.APPROVED
        transfer.save()

    ship_data = inventory_services["MockData"](
        {f"qty_sent_{transfer.lines.first().id}": "10"}
    )
    service.process_transfer(transfer, "ship", ship_data, inventory_services["user"])

    stock1 = StockRecord.objects.get(product=product, warehouse=wh1)
    assert stock1.quantity_on_hand == Decimal("40")  # 50 - 10

    recv_data = inventory_services["MockData"](
        {f"qty_recv_{transfer.lines.first().id}": "10"}
    )
    service.process_transfer(transfer, "receive", recv_data, inventory_services["user"])

    stock2 = StockRecord.objects.get(product=product, warehouse=wh2)
    assert stock2.quantity_on_hand == Decimal("10")
    assert transfer.status == InventoryTransfer.Status.RECEIVED


@pytest.mark.django_db
def test_reservation_blocks_oversell(inventory_services):
    from apps.inventory.models import StockRecord
    from apps.sales.models import SalesOrder, SalesOrderLine
    from apps.sales.services import SalesOrderService

    company = inventory_services["company"]
    user = inventory_services["user"]
    product = inventory_services["product"]
    wh = inventory_services["warehouse"]

    # Initialize physical stock = 10
    StockRecord.objects.filter(company=company, product=product, warehouse=wh).delete()
    StockRecord.objects.filter(company=company, product=product).delete()
    for w in [wh, inventory_services["warehouse2"]]:
        StockRecord.objects.create(
            company=company,
            product=product,
            warehouse=w,
            quantity_on_hand=Decimal("10"),
            quantity_reserved=0,
        )

    # Order 1 wants 8
    so1 = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-01",
        number="SO-1",
    )
    SalesOrderLine.objects.create(
        sales_order=so1,
        product=product,
        quantity=Decimal("8"),
        unit_price=Decimal("10"),
    )

    so_service = SalesOrderService(company=company, user=user)
    so_service.confirm_order(so1)

    # Find which warehouse was used
    stock = StockRecord.objects.get(product=product, quantity_reserved__gt=0)
    assert stock.quantity_reserved == Decimal("8")
    assert stock.quantity_available == Decimal("2")

    # Order 2 wants 5
    so2 = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-02",
        number="SO-2",
    )
    SalesOrderLine.objects.create(
        sales_order=so2,
        product=product,
        quantity=Decimal("5"),
        unit_price=Decimal("10"),
    )

    with pytest.raises(ValueError) as excinfo:
        so_service.confirm_order(so2)
    assert "Insufficient stock" in str(excinfo.value)


@pytest.mark.django_db
def test_reservation_released_on_shipment(inventory_services):
    from apps.inventory.models import DeliveryOrder, DeliveryOrderLine, StockRecord
    from apps.sales.models import SalesOrder, SalesOrderLine
    from apps.sales.services import SalesOrderService

    company = inventory_services["company"]
    user = inventory_services["user"]
    product = inventory_services["product"]
    wh = inventory_services["warehouse"]

    StockRecord.objects.filter(company=company, product=product).delete()
    for w in [wh, inventory_services["warehouse2"]]:
        StockRecord.objects.create(
            company=company,
            product=product,
            warehouse=w,
            quantity_on_hand=Decimal("10"),
            quantity_reserved=0,
        )

    so = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-01",
        number="SO-3",
    )
    SalesOrderLine.objects.create(
        sales_order=so, product=product, quantity=Decimal("4"), unit_price=Decimal("10")
    )

    so_service = SalesOrderService(company=company, user=user)
    so_service.confirm_order(so)

    stock = StockRecord.objects.get(product=product, quantity_reserved__gt=0)
    active_wh = stock.warehouse
    assert stock.quantity_reserved == Decimal("4")

    # Create Delivery Order
    do = DeliveryOrder.objects.create(
        company=company,
        sales_order=so,
        warehouse=active_wh,
        status=DeliveryOrder.Status.READY,
    )
    DeliveryOrderLine.objects.create(
        delivery_order=do,
        product=product,
        quantity_ordered=Decimal("4"),
        quantity_shipped=Decimal("4"),
    )

    do.ship(user)

    stock.refresh_from_db()
    assert stock.quantity_reserved == Decimal("0")
    assert stock.quantity_on_hand == Decimal("6")


@pytest.mark.django_db
def test_reservation_released_on_cancellation(inventory_services):
    from apps.inventory.models import StockRecord
    from apps.sales.models import SalesOrder, SalesOrderLine
    from apps.sales.services import SalesOrderService

    company = inventory_services["company"]
    user = inventory_services["user"]
    product = inventory_services["product"]
    wh = inventory_services["warehouse"]

    StockRecord.objects.filter(company=company, product=product).delete()
    for w in [wh, inventory_services["warehouse2"]]:
        StockRecord.objects.create(
            company=company,
            product=product,
            warehouse=w,
            quantity_on_hand=Decimal("10"),
            quantity_reserved=0,
        )

    so = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-01",
        number="SO-4",
    )
    SalesOrderLine.objects.create(
        sales_order=so, product=product, quantity=Decimal("4"), unit_price=Decimal("10")
    )

    so_service = SalesOrderService(company=company, user=user)
    so_service.confirm_order(so)

    stock = StockRecord.objects.get(product=product, quantity_reserved__gt=0)
    assert stock.quantity_reserved == Decimal("4")

    so_service.cancel_order(so)

    stock.refresh_from_db()
    assert stock.quantity_reserved == Decimal("0")
    assert stock.quantity_on_hand == Decimal("10")


@pytest.mark.django_db
def test_lot_tracked_product_requires_batch(inventory_services):
    from apps.inventory.models import (
        DeliveryOrder,
        DeliveryOrderLine,
        Product,
        StockRecord,
    )
    from apps.sales.models import SalesOrder

    company = inventory_services["company"]
    user = inventory_services["user"]
    wh = inventory_services["warehouse"]

    product = inventory_services["product"]
    product.tracking_method = Product.TrackingMethod.LOT
    product.save()

    StockRecord.objects.filter(company=company, product=product, warehouse=wh).delete()
    StockRecord.objects.create(
        company=company,
        product=product,
        warehouse=wh,
        quantity_on_hand=Decimal("10"),
        quantity_reserved=0,
    )

    so = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-01",
        number="SO-5",
    )
    do = DeliveryOrder.objects.create(
        company=company, sales_order=so, warehouse=wh, status=DeliveryOrder.Status.READY
    )
    DeliveryOrderLine.objects.create(
        delivery_order=do,
        product=product,
        quantity_ordered=Decimal("4"),
        quantity_shipped=Decimal("4"),
    )

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc:
        do.ship(user)
    assert "requires a lot/batch number to ship" in str(exc.value)


@pytest.mark.django_db
def test_serial_tracked_product_requires_matching_serial_count(inventory_services):
    from apps.inventory.models import (
        DeliveryOrder,
        DeliveryOrderLine,
        Product,
        StockRecord,
    )
    from apps.sales.models import SalesOrder

    company = inventory_services["company"]
    user = inventory_services["user"]
    wh = inventory_services["warehouse"]

    product = inventory_services["product"]
    product.tracking_method = Product.TrackingMethod.SERIAL
    product.save()

    StockRecord.objects.filter(company=company, product=product, warehouse=wh).delete()
    StockRecord.objects.create(
        company=company,
        product=product,
        warehouse=wh,
        quantity_on_hand=Decimal("10"),
        quantity_reserved=0,
    )

    so = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-01",
        number="SO-6",
    )
    do = DeliveryOrder.objects.create(
        company=company, sales_order=so, warehouse=wh, status=DeliveryOrder.Status.READY
    )
    # Ship 4, but only provide 2 serial numbers
    DeliveryOrderLine.objects.create(
        delivery_order=do,
        product=product,
        quantity_ordered=Decimal("4"),
        quantity_shipped=Decimal("4"),
        serial_numbers=["SN-1", "SN-2"],
    )

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as exc:
        do.ship(user)
    assert "requires exactly 4 serial numbers" in str(exc.value)


@pytest.mark.django_db
def test_serial_tracked_product_ships_successfully_with_correct_serials(
    inventory_services,
):
    from apps.inventory.models import (
        DeliveryOrder,
        DeliveryOrderLine,
        Product,
        StockMovement,
        StockRecord,
    )
    from apps.sales.models import SalesOrder

    company = inventory_services["company"]
    user = inventory_services["user"]
    wh = inventory_services["warehouse"]

    product = inventory_services["product"]
    product.tracking_method = Product.TrackingMethod.SERIAL
    product.save()

    StockRecord.objects.filter(company=company, product=product, warehouse=wh).delete()
    StockRecord.objects.create(
        company=company,
        product=product,
        warehouse=wh,
        quantity_on_hand=Decimal("10"),
        quantity_reserved=0,
    )

    so = SalesOrder.objects.create(
        company=company,
        customer=inventory_services["customer"],
        order_date="2026-01-01",
        number="SO-7",
    )
    do = DeliveryOrder.objects.create(
        company=company, sales_order=so, warehouse=wh, status=DeliveryOrder.Status.READY
    )
    # Ship 2 with 2 serial numbers
    DeliveryOrderLine.objects.create(
        delivery_order=do,
        product=product,
        quantity_ordered=Decimal("2"),
        quantity_shipped=Decimal("2"),
        serial_numbers=["SN-9", "SN-10"],
    )

    do.ship(user)

    stock = StockRecord.objects.get(product=product, warehouse=wh)
    assert stock.quantity_on_hand == Decimal("8")

    mov = StockMovement.objects.get(
        reference_type="DeliveryOrder", reference_id=str(do.id)
    )
    assert mov.serial_numbers == ["SN-9", "SN-10"]
