import pytest
from decimal import Decimal
from django.utils import timezone
from apps.manufacturing.models import BillOfMaterial, BillOfMaterialLine, ManufacturingOrder, MaterialPlan
from apps.manufacturing.services import MRPService
from apps.inventory.models import StockRecord

@pytest.fixture
def mfg_setup(db, company, product, warehouse):
    # Need a component product
    from apps.inventory.models import Product
    component = Product.objects.create(
        company=company,
        name='Raw Material',
        sku='RAW-001',
        product_type='stockable',
        cost_price=Decimal('10.00'),
        sale_price=Decimal('20.00')
    )
    
    # Create BOM
    bom = BillOfMaterial.objects.create(
        company=company,
        product=product,
        quantity=Decimal('1.00')
    )
    BillOfMaterialLine.objects.create(
        bom=bom,
        component=component,
        quantity=Decimal('2.00')
    )
    
    return {
        'company': company,
        'finished_product': product,
        'component': component,
        'bom': bom,
        'warehouse': warehouse
    }

@pytest.mark.django_db
def test_mrp_service(mfg_setup):
    company = mfg_setup['company']
    bom = mfg_setup['bom']
    component = mfg_setup['component']
    warehouse = mfg_setup['warehouse']
    
    # Create MO for 5 finished products
    mo = ManufacturingOrder.objects.create(
        company=company,
        product=mfg_setup['finished_product'],
        bom=bom,
        quantity_to_produce=Decimal('5.00'),
        status=ManufacturingOrder.Status.CONFIRMED,
        planned_start_date=timezone.now().date()
    )
    
    # Add 3 components to stock (need 10)
    StockRecord.objects.create(
        company=company,
        product=component,
        warehouse=warehouse,
        quantity_on_hand=Decimal('3.00')
    )
    
    # Create Material Plan
    plan = MaterialPlan.objects.create(
        company=company,
        name='Test Plan',
        target_date=timezone.now().date() + timezone.timedelta(days=7)
    )
    
    # Run MRP
    plan = MRPService.run_mrp(plan.id)
    
    assert plan.status == MaterialPlan.Status.COMPLETED
    assert plan.items.count() == 1
    
    item = plan.items.first()
    assert item.product == component
    assert item.required_quantity == Decimal('10.00') # 5 * 2
    assert item.available_quantity == Decimal('3.00')
    assert item.shortage == Decimal('7.00')
