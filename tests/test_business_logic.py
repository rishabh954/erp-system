import json
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory.models import Product
from apps.sales.models import Invoice

pytestmark = pytest.mark.django_db


def test_product_creation_preserves_decimal_prices(client, user, company):
    client.force_login(user)

    response = client.post(
        reverse("inventory:product_create"),
        {
            "sku": "DECIMAL-PRODUCT",
            "name": "Decimal Product",
            "product_type": "stockable",
            "cost_price": "0.10",
            "sale_price": "0.30",
            "min_stock_level": "1.25",
            "reorder_point": "2.50",
            "reorder_quantity": "3.75",
        },
    )

    product = Product.objects.get(company=company, sku="DECIMAL-PRODUCT")
    assert response.status_code == 302
    assert product.cost_price == Decimal("0.10")
    assert product.sale_price == Decimal("0.30")
    assert product.min_stock_level == Decimal("1.25")
    assert product.reorder_point == Decimal("2.50")
    assert product.reorder_quantity == Decimal("3.75")


def test_sales_pos_api_preserves_decimal_totals(client, user, company, currency):
    product = Product.objects.create(
        company=company,
        name="Decimal POS Product",
        sku="DECIMAL-POS",
        cost_price="0.01",
        sale_price="0.10",
    )
    client.force_login(user)

    response = client.post(
        reverse("sales:pos_api"),
        data=json.dumps(
            {
                "items": [
                    {
                        "product_id": str(product.pk),
                        "quantity": "3",
                        "price": "0.10",
                    }
                ],
                "amount_paid": "0.30",
                "payment_method": "cash",
            }
        ),
        content_type="application/json",
    )

    invoice = Invoice.objects.get(pk=response.json()["invoice_id"])
    assert response.status_code == 200
    assert invoice.total == Decimal("0.30")
    assert response.json()["invoice_total"] == "0.30"
    assert response.json()["amount_paid"] == "0.30"
    assert response.json()["change_due"] == "0.00"


def test_sales_dashboard_omits_untracked_profit_estimates(client, user):
    client.force_login(user)

    response = client.get(reverse("sales:dashboard"))

    assert response.status_code == 200
    assert "profit_analysis" not in response.context
    assert "margin_analysis" not in response.context
    assert b"Estimated Profit" not in response.content
    assert b"Avg Margin" not in response.content
