from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory.models import Product, StockMovement, StockRecord
from apps.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
    MaterialPlan,
    ScrapOrder,
    WorkCenter,
)

pytestmark = pytest.mark.django_db


def test_bom_creation_mo_and_mrp(client, company, user, warehouse):
    client.force_login(user)

    # Create products
    fg = Product.objects.create(
        company=company,
        name="Finished Good",
        sku="FG-01",
        product_type="stockable",
        cost_price=Decimal("100.00"),
        sale_price=Decimal("200.00"),
    )
    comp1 = Product.objects.create(
        company=company,
        name="Component 1",
        sku="COMP-01",
        product_type="stockable",
        cost_price=Decimal("10.00"),
        sale_price=Decimal("20.00"),
    )
    comp2 = Product.objects.create(
        company=company,
        name="Component 2",
        sku="COMP-02",
        product_type="stockable",
        cost_price=Decimal("15.00"),
        sale_price=Decimal("25.00"),
    )

    # Give some stock to comp1 to test MRP shortage calculation
    StockRecord.objects.create(
        product=comp1,
        warehouse=warehouse,
        quantity_on_hand=Decimal("5"),
        quantity_allocated=Decimal("0"),
        quantity_available=Decimal("5"),
    )

    # 1. Test BOM Creation via View
    bom_create_url = reverse("manufacturing:bom_create")

    # Get view first
    response = client.get(bom_create_url)
    assert response.status_code == 200

    response = client.post(
        bom_create_url,
        {
            "product": str(fg.id),
            "quantity": "1",
            "component_id[]": [str(comp1.id), str(comp2.id)],
            "line_quantity[]": ["2", "3"],
            "scrap_percentage[]": ["0", "10"],
        },
    )

    bom = BillOfMaterial.objects.get(product=fg)
    assert bom.lines.count() == 2

    # Detail view
    bom_detail_url = reverse("manufacturing:bom_detail", kwargs={"pk": bom.id})
    resp = client.get(bom_detail_url)
    assert resp.status_code == 200

    # 2. Test MO Creation via View
    mo_create_url = reverse("manufacturing:mo_create")

    resp = client.get(mo_create_url)
    assert resp.status_code == 200

    response = client.post(
        mo_create_url,
        {
            "bom": str(bom.id),
            "warehouse": str(warehouse.id),
            "quantity_to_produce": "5",
            "planned_start_date": "2026-07-07",
            "planned_end_date": "2026-07-10",
        },
    )

    mo = ManufacturingOrder.objects.get(bom=bom)
    assert mo.quantity_to_produce == Decimal("5")
    assert mo.status == "draft"

    mo_detail_url = reverse("manufacturing:mo_detail", kwargs={"pk": mo.id})
    resp = client.get(mo_detail_url)
    assert resp.status_code == 200

    # Confirm MO
    mo_action_url = reverse("manufacturing:mo_action", kwargs={"pk": mo.id})
    client.post(mo_action_url, {"action": "confirm"})
    mo.refresh_from_db()
    assert mo.status == "confirmed"

    # Start MO
    client.post(mo_action_url, {"action": "start"})
    mo.refresh_from_db()
    assert mo.status == "in_progress"

    # 3. Test MRP Explosion
    plan = MaterialPlan.objects.create(
        company=company, name="Test MRP", target_date="2026-07-15"
    )

    # Run via view
    mrp_run_url = reverse("manufacturing:mrp_run", kwargs={"pk": plan.id})
    resp = client.post(mrp_run_url)
    assert resp.status_code == 302

    plan.refresh_from_db()
    assert plan.status == "completed"
    items = plan.items.all()
    assert items.count() == 2

    item1 = items.get(product=comp1)
    # required = 2 * 5 = 10, available = 5, shortage = 5
    assert item1.required_quantity == Decimal("10")
    assert item1.available_quantity == Decimal("5")
    assert item1.shortage == Decimal("5")

    item2 = items.get(product=comp2)
    # required = 3 * 5 = 15, scrap = 1.5, total = 16.5, available = 0, shortage = 16.5
    assert item2.required_quantity == Decimal("16.5")
    assert item2.available_quantity == Decimal("0")
    assert item2.shortage == Decimal("16.5")

    # 4. Test Component Consumption (MO Done)
    client.post(mo_action_url, {"action": "done"})
    mo.refresh_from_db()
    assert mo.status == "done"
    assert mo.quantity_produced == Decimal("5")

    movements_out = StockMovement.objects.filter(
        reference_id=f"MO-{mo.number}", movement_type="production_out"
    )
    assert movements_out.count() == 2

    out_comp1 = movements_out.get(product=comp1)
    assert out_comp1.quantity == Decimal("-10")

    out_comp2 = movements_out.get(product=comp2)
    assert out_comp2.quantity == Decimal("-16.5")

    movements_in = StockMovement.objects.filter(
        reference_id=f"MO-{mo.number}", movement_type="production_in"
    )
    assert movements_in.count() == 1

    in_fg = movements_in.get(product=fg)
    assert in_fg.quantity == Decimal("5")


def test_mo_cancel_and_scrap(client, company, user, warehouse):
    client.force_login(user)

    fg = Product.objects.create(
        company=company, name="Finished Good 2", sku="FG-02", product_type="stockable"
    )
    comp1 = Product.objects.create(
        company=company, name="Component 3", sku="COMP-03", product_type="stockable"
    )
    bom = BillOfMaterial.objects.create(company=company, product=fg, quantity=1)
    BillOfMaterialLine.objects.create(
        bom=bom, component=comp1, quantity=2, scrap_percentage=0
    )

    mo = ManufacturingOrder.objects.create(
        company=company, product=fg, bom=bom, quantity_to_produce=2, warehouse=warehouse
    )

    mo_action_url = reverse("manufacturing:mo_action", kwargs={"pk": mo.id})
    client.post(mo_action_url, {"action": "cancel"})
    mo.refresh_from_db()
    assert mo.status == "cancelled"

    wc = WorkCenter.objects.create(
        company=company,
        name="Assembly Line",
        code="AL-01",
        cost_per_hour=Decimal("50.00"),
    )
    scrap = ScrapOrder.objects.create(
        company=company,
        manufacturing_order=mo,
        work_center=wc,
        product=comp1,
        quantity=Decimal("1"),
        reason="Damaged",
    )

    scrap.mark_done()
    scrap.refresh_from_db()
    assert scrap.status == "done"

    # Verify stock movement for scrap
    movement = StockMovement.objects.get(reference_id=scrap.number)
    assert movement.movement_type == "adjustment_out"
    assert movement.quantity == Decimal("-1")
