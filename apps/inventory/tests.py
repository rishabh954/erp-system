import pytest
from decimal import Decimal
from django.urls import reverse
from django.utils import timezone
from core.factories import ProductFactory, WarehouseFactory, VendorFactory
from apps.purchase.models import PurchaseOrder, PurchaseOrderLine
from apps.inventory.models import StockRecord, StockMovement, InventoryTransfer
from apps.inventory.services import StockService, TransferService

pytestmark = pytest.mark.django_db

def test_goods_receipt_updates_stock(client, company, user):
    """Test that receiving a Purchase Order properly updates inventory stock."""
    # Create test inventory data
    product = ProductFactory(company=company, name='Test Widget', sku='WGT-001')
    warehouse = WarehouseFactory(company=company, name='Main Warehouse', code='MAIN')
    
    # Create test purchase data
    vendor = VendorFactory(company=company, name='Test Vendor')
    po = PurchaseOrder.objects.create(
        company=company,
        vendor=vendor,
        order_date='2026-06-01',
        status=PurchaseOrder.Status.CONFIRMED,
        number='PO-1001'
    )
    po_line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        product=product,
        description='Test Widget Line',
        quantity=Decimal('10.00'),
        unit_price=Decimal('5.00')
    )
    
    # Setup client authentication
    client.force_login(user)

    # Initial stock should be 0 or nonexistent
    assert StockRecord.objects.filter(product=product).exists() == False
    
    # Submit GRN form via the view
    url = reverse('purchase:order_receive', args=[po.pk])
    response = client.post(url, {
        f'qty_{po_line.pk}': '10',
        f'batch_{po_line.pk}': 'BATCH123',
        'warehouse': warehouse.pk,
        'notes': 'Received fine'
    })
    
    # View redirects on success
    assert response.status_code == 302
    
    # Check stock record was created and updated
    stock_record = StockRecord.objects.get(product=product)
    assert stock_record.quantity_on_hand == Decimal('10.00')
    assert stock_record.warehouse == warehouse


@pytest.fixture
def inventory_services(db, rf, company, user, warehouse, product):
    class MockData(dict):
        def getlist(self, key):
            return self.get(key, [])
            
    # Create another warehouse
    from apps.inventory.models import Warehouse
    warehouse2 = Warehouse.objects.create(
        company=company,
        name='Warehouse 2',
        code='WH2',
        is_active=True
    )
            
    return {
        'company': company,
        'user': user,
        'warehouse': warehouse,
        'warehouse2': warehouse2,
        'product': product,
        'MockData': MockData,
        'stock_service': StockService(user=user, company=company),
        'transfer_service': TransferService(user=user, company=company),
    }

def test_stock_adjustment(inventory_services):
    service = inventory_services['stock_service']
    product = inventory_services['product']
    warehouse = inventory_services['warehouse']
    
    # Adjust stock (add)
    mov = service.adjust_stock(
        product=product,
        warehouse=warehouse,
        qty_input='100.5',
        adjustment_type='add',
        notes='Test add'
    )
    
    stock = StockRecord.objects.get(product=product, warehouse=warehouse)
    assert stock.quantity_on_hand == Decimal('100.5')
    assert mov.quantity == Decimal('100.5')
    assert mov.movement_type == StockMovement.MovementType.ADJUSTMENT
    
    # Adjust stock (remove)
    mov = service.adjust_stock(
        product=product,
        warehouse=warehouse,
        qty_input='20.5',
        adjustment_type='remove',
        notes='Test remove'
    )
    stock.refresh_from_db()
    assert stock.quantity_on_hand == Decimal('80.0')
    assert mov.quantity == Decimal('-20.5')

def test_transfer_service(inventory_services):
    service = inventory_services['transfer_service']
    stock_service = inventory_services['stock_service']
    product = inventory_services['product']
    wh1 = inventory_services['warehouse']
    wh2 = inventory_services['warehouse2']
    
    # Add initial stock
    stock_service.adjust_stock(product, wh1, '50', 'add')
    
    data = inventory_services['MockData']({
        'from_warehouse': wh1.pk,
        'to_warehouse': wh2.pk,
        'transfer_date': timezone.now().date(),
        'product[]': [product.pk],
        'quantity[]': ['10'],
    })
    
    transfer = service.create_transfer(data, inventory_services['user'])
    assert transfer.status == InventoryTransfer.Status.DRAFT
    
    # Process transfer
    service.process_transfer(transfer, 'submit', {}, inventory_services['user'])
    
    # If no workflow intercepts, it might become APPROVED. Let's assume APPROVED for this simple test.
    if transfer.status == InventoryTransfer.Status.PENDING_APPROVAL:
        transfer.status = InventoryTransfer.Status.APPROVED
        transfer.save()
        
    ship_data = inventory_services['MockData']({
        f'qty_sent_{transfer.lines.first().id}': '10'
    })
    service.process_transfer(transfer, 'ship', ship_data, inventory_services['user'])
    
    stock1 = StockRecord.objects.get(product=product, warehouse=wh1)
    assert stock1.quantity_on_hand == Decimal('40') # 50 - 10
    
    recv_data = inventory_services['MockData']({
        f'qty_recv_{transfer.lines.first().id}': '10'
    })
    service.process_transfer(transfer, 'receive', recv_data, inventory_services['user'])
    
    stock2 = StockRecord.objects.get(product=product, warehouse=wh2)
    assert stock2.quantity_on_hand == Decimal('10')
    assert transfer.status == InventoryTransfer.Status.RECEIVED
