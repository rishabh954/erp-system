import pytest
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.inventory.models import (
    StockRecord, StockMovement, DeliveryOrder, DeliveryOrderLine,
    Product
)
from apps.inventory.services import DeliveryService, StockService
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.sales.services import SalesOrderService
from apps.company.models import Company, Branch
from apps.authentication.models import User

@pytest.fixture
def setup_data(db):
    company = Company.objects.create(name='Test Company')
    branch = Branch.objects.create(name='Main Branch', company=company)
    user = User.objects.create_user(email='test@example.com', password='password', first_name='Test', last_name='User', primary_company=company)
    
    from apps.inventory.models import Warehouse, Product, ProductCategory
    warehouse = Warehouse.objects.create(company=company, name='Main Warehouse', is_active=True)
    category = ProductCategory.objects.create(company=company, name='Electronics')
    
    # Tracked Product
    product_tracked = Product.objects.create(
        company=company, sku='TRK-01', name='Tracked Item', 
        category=category, cost_price=Decimal('100.00'),
        tracking_method=Product.TrackingMethod.LOT
    )
    
    # Normal Product
    product_normal = Product.objects.create(
        company=company, sku='NRM-01', name='Normal Item', 
        category=category, cost_price=Decimal('50.00')
    )
    
    from apps.crm.models import Customer
    customer = Customer.objects.create(company=company, name='Test Customer')
    
    return {
        'company': company,
        'user': user,
        'warehouse': warehouse,
        'product_tracked': product_tracked,
        'product_normal': product_normal,
        'customer': customer
    }


@pytest.mark.django_db
def test_sales_order_reservation_lifecycle(setup_data):
    """Test SO confirm reserves stock and delivery releases it."""
    company = setup_data['company']
    user = setup_data['user']
    product = setup_data['product_normal']
    warehouse = setup_data['warehouse']
    customer = setup_data['customer']
    
    # Add initial stock
    StockService(user=user, company=company).receive_stock(
        product=product, warehouse=warehouse, qty=Decimal('100'),
        unit_cost=Decimal('50'), reference_type='Initial', reference_id='0'
    )
    
    # Create SO
    order = SalesOrder.objects.create(
        company=company, customer=customer, order_date=timezone.now().date()
    )
    SalesOrderLine.objects.create(
        sales_order=order, product=product, quantity=Decimal('20'), unit_price=Decimal('60'), description='Test'
    )
    
    # Confirm SO (should reserve 20)
    SalesOrderService(user=user, company=company).confirm_order(order)
    
    stock = StockRecord.objects.get(product=product, warehouse=warehouse)
    assert stock.quantity_reserved == Decimal('20')
    assert stock.quantity_available == Decimal('80')
    assert stock.quantity_on_hand == Decimal('100')
    
    # Create Delivery and Ship
    delivery = DeliveryOrder.objects.create(
        company=company, sales_order=order, warehouse=warehouse, status=DeliveryOrder.Status.READY
    )
    DeliveryOrderLine.objects.create(
        delivery_order=delivery, product=product, quantity_ordered=Decimal('20'), quantity_shipped=Decimal('20')
    )
    
    DeliveryService(user=user, company=company).ship_delivery(delivery, user)
    
    stock.refresh_from_db()
    assert stock.quantity_reserved == Decimal('0')
    assert stock.quantity_on_hand == Decimal('80')
    assert stock.quantity_available == Decimal('80')

@pytest.mark.django_db
def test_sales_order_cancellation_releases_reservation(setup_data):
    company = setup_data['company']
    user = setup_data['user']
    product = setup_data['product_normal']
    warehouse = setup_data['warehouse']
    customer = setup_data['customer']
    
    order = SalesOrder.objects.create(
        company=company, customer=customer, order_date=timezone.now().date()
    )
    SalesOrderLine.objects.create(
        sales_order=order, product=product, quantity=Decimal('30'), unit_price=Decimal('60'), description='Test'
    )
    
    StockService(user=user, company=company).receive_stock(
        product=product, warehouse=warehouse, qty=Decimal('50'), unit_cost=Decimal('50'),
        reference_type='Initial', reference_id='INV-INIT-1'
    )
    
    SalesOrderService(user=user, company=company).confirm_order(order)
    stock = StockRecord.objects.get(product=product, warehouse=warehouse)
    assert stock.quantity_reserved == Decimal('30')
    
    SalesOrderService(user=user, company=company).cancel_order(order)
    stock.refresh_from_db()
    assert stock.quantity_reserved == Decimal('0')

@pytest.mark.django_db
def test_lot_serial_validation(setup_data):
    """Ensure tracked products require batch/serial on shipment."""
    company = setup_data['company']
    user = setup_data['user']
    product = setup_data['product_tracked']
    warehouse = setup_data['warehouse']
    customer = setup_data['customer']
    
    StockService(user=user, company=company).receive_stock(
        product=product, warehouse=warehouse, qty=Decimal('10'),
        unit_cost=Decimal('100'), reference_type='Initial', reference_id='0'
    )
    
    order = SalesOrder.objects.create(
        company=company, customer=customer, order_date=timezone.now().date(), status=SalesOrder.Status.CONFIRMED
    )
    
    # Needs 5 tracked
    delivery = DeliveryOrder.objects.create(
        company=company, sales_order=order, warehouse=warehouse, status=DeliveryOrder.Status.READY
    )
    line = DeliveryOrderLine.objects.create(
        delivery_order=delivery, product=product, quantity_ordered=Decimal('5'), quantity_shipped=Decimal('5')
    )
    
    service = DeliveryService(user=user, company=company)
    
    # Missing batch number -> ValidationError
    with pytest.raises(ValidationError):
        service.ship_delivery(delivery, user)
        
    # Provide batch number -> Success
    line.batch_number = 'LOT123'
    line.save()
    service.ship_delivery(delivery, user)
    
    stock = StockRecord.objects.get(product=product, warehouse=warehouse)
    assert stock.quantity_on_hand == Decimal('5')
