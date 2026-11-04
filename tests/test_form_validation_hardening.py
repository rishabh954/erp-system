import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.company.models import Tax
from apps.inventory.models import Warehouse
from apps.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
)
from apps.pos.models import POSOrder, POSPayment, POSSession
from apps.sales.models import Invoice, InvoiceLine, Payment
from core.factories import CompanyFactory, ProductFactory, WarehouseFactory

pytestmark = pytest.mark.django_db


def _post_pos(client, product, **overrides):
    payload = {
        "items": [
            {
                "product_id": str(product.pk),
                "quantity": "2",
                "price": str(product.sale_price),
            }
        ],
        "amount_paid": "20.00",
        "payment_method": "cash",
    }
    payload.update(overrides)
    return client.post(
        reverse("sales:pos_api"),
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_sales_pos_rejects_price_tampering_without_creating_invoice(
    client, user, company
):
    product = ProductFactory(company=company, sale_price=Decimal("10.00"))
    client.force_login(user)

    response = _post_pos(
        client,
        product,
        items=[
            {
                "product_id": str(product.pk),
                "quantity": "2",
                "price": "0.01",
            }
        ],
    )

    assert response.status_code == 400
    assert "price does not match" in response.json()["error"]
    assert not Invoice.objects.filter(company=company).exists()


def test_sales_pos_uses_product_tax_and_caps_cash_payment_at_invoice_total(
    client, user, company
):
    tax = Tax.objects.create(
        company=company,
        name="POS GST",
        rate=Decimal("10"),
        tax_type=Tax.TaxType.PERCENTAGE,
    )
    product = ProductFactory(
        company=company, sale_price=Decimal("10.00"), tax=tax
    )
    client.force_login(user)

    response = _post_pos(client, product, amount_paid="25.00")

    invoice = Invoice.objects.get(company=company)
    line = InvoiceLine.objects.get(invoice=invoice)
    payment = Payment.objects.get(invoice=invoice)
    assert response.status_code == 200
    assert line.tax == tax
    assert line.tax_amount == Decimal("2.00")
    assert invoice.total == Decimal("22.00")
    assert payment.amount == Decimal("22.00")
    assert response.json()["change_due"] == "3.00"


@pytest.mark.parametrize(
    "payment_method,amount",
    [("invalid", "20.00"), ("card", "25.00")],
)
def test_sales_pos_rejects_invalid_payment_values_without_writes(
    client, user, company, payment_method, amount
):
    product = ProductFactory(company=company, sale_price=Decimal("10.00"))
    client.force_login(user)

    response = _post_pos(
        client, product, payment_method=payment_method, amount_paid=amount
    )

    assert response.status_code == 400
    assert not Invoice.objects.filter(company=company).exists()
    assert not Payment.objects.filter(company=company).exists()


def test_sales_pos_rolls_invoice_back_if_payment_creation_fails(
    client, user, company
):
    product = ProductFactory(company=company, sale_price=Decimal("10.00"))
    client.force_login(user)

    with patch(
        "apps.sales.views.Payment.objects.create",
        side_effect=RuntimeError("payment write failed"),
    ):
        response = _post_pos(client, product)

    assert response.status_code == 500
    assert "No sale was saved" in response.json()["error"]
    assert not Invoice.objects.filter(company=company).exists()


def test_bom_rejects_invalid_or_foreign_component_without_partial_parent(
    client, user, company
):
    foreign_company = CompanyFactory(name="Foreign BOM tenant")
    output = ProductFactory(company=company, sku="BOM-OUTPUT")
    foreign_component = ProductFactory(
        company=foreign_company, sku="BOM-FOREIGN-COMPONENT"
    )
    client.force_login(user)

    response = client.post(
        reverse("manufacturing:bom_create"),
        {
            "product": str(output.pk),
            "quantity": "1",
            "component_id[]": [str(foreign_component.pk)],
            "line_quantity[]": ["2"],
            "scrap_percentage[]": ["0"],
        },
    )

    assert response.status_code == 400
    assert BillOfMaterial.objects.filter(company=company).count() == 0
    assert BillOfMaterialLine.objects.count() == 0
    assert b"active component from this company" in response.content


@pytest.mark.parametrize("quantity", ["", "   ", "NaN", "-1", "abc"])
def test_bom_rejects_invalid_quantity_without_writes(
    client, user, company, quantity
):
    output = ProductFactory(company=company, sku=f"BOM-OUT-{len(quantity)}")
    component = ProductFactory(company=company, sku=f"BOM-COMP-{len(quantity)}")
    client.force_login(user)

    response = client.post(
        reverse("manufacturing:bom_create"),
        {
            "product": str(output.pk),
            "quantity": quantity,
            "component_id[]": [str(component.pk)],
            "line_quantity[]": ["1"],
            "scrap_percentage[]": ["0"],
        },
    )

    assert response.status_code == 400
    assert not BillOfMaterial.objects.filter(company=company).exists()
    assert not BillOfMaterialLine.objects.exists()
    assert b"quantity" in response.content


def test_bom_renders_invalid_submission_with_values_preserved(
    client, user, company
):
    output = ProductFactory(company=company, sku="BOM-PRESERVE-OUTPUT")
    ProductFactory(company=company, sku="BOM-PRESERVE-COMP")
    client.force_login(user)
    submitted_quantity = "2.5000"

    response = client.post(
        reverse("manufacturing:bom_create"),
        {
            "product": str(output.pk),
            "quantity": submitted_quantity,
            "component_id[]": [""],
            "line_quantity[]": ["3.2500"],
            "scrap_percentage[]": ["7.5"],
        },
    )

    assert response.status_code == 400
    assert submitted_quantity.encode() in response.content
    assert b"3.2500" in response.content
    assert not BillOfMaterial.objects.filter(company=company).exists()
    assert not BillOfMaterialLine.objects.exists()
def test_mo_rejects_invalid_quantity_and_foreign_warehouse_without_writes(
    client, user, company
):
    product = ProductFactory(company=company, sku="MO-PRODUCT")
    bom = BillOfMaterial.objects.create(
        company=company, product=product, quantity=Decimal("1")
    )
    foreign_company = CompanyFactory(name="Foreign MO tenant")
    foreign_warehouse = WarehouseFactory(company=foreign_company)
    client.force_login(user)

    response = client.post(
        reverse("manufacturing:mo_create"),
        {
            "bom": str(bom.pk),
            "warehouse": str(foreign_warehouse.pk),
            "quantity_to_produce": "0",
        },
    )

    assert response.status_code == 400
    assert not ManufacturingOrder.objects.filter(company=company).exists()
    assert b"greater than zero" in response.content
    assert b"active warehouse from this company" in response.content


def test_mo_rejects_invalid_dates_without_writes(client, user, company):
    product = ProductFactory(company=company, sku="MO-DATE-PRODUCT")
    bom = BillOfMaterial.objects.create(company=company, product=product)
    warehouse = WarehouseFactory(company=company)
    client.force_login(user)

    response = client.post(
        reverse("manufacturing:mo_create"),
        {
            "bom": str(bom.pk),
            "warehouse": str(warehouse.pk),
            "quantity_to_produce": "1",
            "planned_start_date": "2026-04-31",
            "planned_end_date": "2026-04-01",
        },
    )

    assert response.status_code == 400
    assert not ManufacturingOrder.objects.filter(company=company).exists()


def test_pos_checkout_rejects_invalid_price_without_creating_order(
    client, user, company
):
    warehouse = Warehouse.objects.create(company=company, name="Validation Warehouse")
    session = POSSession.objects.create(
        company=company,
        user=user,
        status=POSSession.Status.OPEN,
        warehouse=warehouse,
    )
    product = ProductFactory(company=company, sku="PRICE-VALIDATION-001")
    client.force_login(user)

    response = client.post(
        reverse("pos:api_checkout"),
        data=json.dumps(
            {
                "session_id": str(session.pk),
                "cart": [{"id": str(product.pk), "price": "0.01", "qty": "1"}],
                "payment_method": "cash",
                "tendered": "1.00",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["message"].lower()
    assert not POSPayment.objects.exists()
    assert not POSOrder.objects.exists()
