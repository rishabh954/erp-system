import pytest
from django.urls import reverse

from apps.manufacturing.models import (
    ManufacturingOrder,
    Routing,
    RoutingOperation,
    WorkCenter,
)

pytestmark = pytest.mark.django_db


def test_manufacturing_views(client, company, user, warehouse):
    client.force_login(user)

    # Work centers
    wc1 = WorkCenter.objects.create(company=company, name="WC1", code="WC1")
    resp = client.get(reverse("manufacturing:work_centers"))
    assert resp.status_code == 200
    assert "WC1" in str(resp.content)

    # Routings
    r1 = Routing.objects.create(company=company, name="R1", code="R1")
    RoutingOperation.objects.create(
        routing=r1, work_center=wc1, name="Op1", sequence=10, duration_minutes=60
    )
    resp = client.get(reverse("manufacturing:routings"))
    assert resp.status_code == 200
    assert "R1" in str(resp.content)

    # BOMs
    resp = client.get(reverse("manufacturing:boms"))
    assert resp.status_code == 200

    # Orders
    resp = client.get(reverse("manufacturing:orders"))
    assert resp.status_code == 200

    # Scrap
    resp = client.get(reverse("manufacturing:scrap_orders"))
    assert resp.status_code == 200

    # Downtime
    resp = client.get(reverse("manufacturing:downtime_logs"))
    assert resp.status_code == 200

    # Work Orders
    resp = client.get(reverse("manufacturing:work_orders"))
    assert resp.status_code == 200

    # QC
    resp = client.get(reverse("manufacturing:quality_checks"))
    assert resp.status_code == 200

    # Costing
    resp = client.get(reverse("manufacturing:production_costings"))
    assert resp.status_code == 200

    # Dashboard
    resp = client.get(reverse("manufacturing:dashboard"))
    assert resp.status_code == 200

    # Maintenance
    resp = client.get(reverse("manufacturing:maintenance_list"))
    assert resp.status_code == 200

    # MRP list
    resp = client.get(reverse("manufacturing:mrp_list"))
    assert resp.status_code == 200


def test_work_order_actions(client, company, user, warehouse, product):
    client.force_login(user)

    from apps.manufacturing.models import BillOfMaterial, WorkOrder

    bom = BillOfMaterial.objects.create(company=company, product=product, quantity=1)

    mo = ManufacturingOrder.objects.create(
        company=company, product=product, bom=bom, quantity_to_produce=1
    )

    wc1 = WorkCenter.objects.create(company=company, name="WC1", code="WC1")
    wo = WorkOrder.objects.create(
        company=company, manufacturing_order=mo, work_center=wc1, name="WO1"
    )

    # List
    assert client.get(reverse("manufacturing:work_orders")).status_code == 200

    # Detail
    assert (
        client.get(
            reverse("manufacturing:work_order_detail", kwargs={"pk": wo.id})
        ).status_code
        == 200
    )

    # Start
    client.post(reverse("manufacturing:work_order_start", kwargs={"pk": wo.id}))
    wo.refresh_from_db()
    assert wo.status == "in_progress"

    # Complete
    client.post(reverse("manufacturing:work_order_complete", kwargs={"pk": wo.id}))
    wo.refresh_from_db()
    assert wo.status == "done"
