from decimal import Decimal

import pytest

from apps.company.models import Company
from apps.inventory.models import Product, StockMovement, Warehouse
from apps.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
)


@pytest.mark.django_db
def test_manufacturing_completion_rejects_cross_company_warehouse(company):
    foreign_company = Company.objects.create(name="Foreign warehouse tenant")
    foreign_warehouse = Warehouse.objects.create(
        company=foreign_company,
        name="Foreign warehouse",
        code="FOREIGN-WH",
    )
    finished = Product.objects.create(
        company=company,
        name="Finished item",
        sku="FG-SCOPE",
    )
    component = Product.objects.create(
        company=company,
        name="Component",
        sku="COMP-SCOPE",
    )
    bom = BillOfMaterial.objects.create(company=company, product=finished)
    BillOfMaterialLine.objects.create(
        bom=bom, component=component, quantity=Decimal("1")
    )
    order = ManufacturingOrder.objects.create(
        company=company,
        product=finished,
        bom=bom,
        quantity_to_produce=Decimal("1"),
        quantity_produced=Decimal("0"),
        warehouse=foreign_warehouse,
        status=ManufacturingOrder.Status.IN_PROGRESS,
    )

    with pytest.raises(ValueError, match="relations must belong to its company"):
        order.mark_done()

    order.refresh_from_db()
    assert order.status == ManufacturingOrder.Status.IN_PROGRESS
    assert not StockMovement.objects.filter(
        company=company, reference_id=f"MO-{order.number}"
    ).exists()
