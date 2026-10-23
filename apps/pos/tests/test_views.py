from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.company.models import Company
from apps.inventory.models import Product, StockMovement, StockRecord, Warehouse
from apps.pos.models import POSOrder, POSPayment, POSSession


@pytest.mark.django_db
def test_pos_checkout_permissions(client, pos_company, pos_user_with_read, pos_user_with_create):
    """
    Test that pos.read is denied and pos.create is allowed on POSCheckoutAPIView
    """
    # 1. Test user with ONLY pos.read
    client.force_login(pos_user_with_read)

    # We don't even need a full payload, just check if we hit 403 Forbidden vs 400 Bad Request
    url = reverse('pos:api_checkout')
    response = client.post(url, data={"cart": [], "payment_method": "cash", "tendered": "0"}, content_type="application/json")

    assert response.status_code == 403, "User with only pos.read should get 403 Forbidden"

    # 2. Test user with pos.create
    client.force_login(pos_user_with_create)

    # First, setup required data for a successful or 400 checkout (meaning it passes permission check)
    # The view checks for an OPEN POSSession
    warehouse = Warehouse.objects.create(company=pos_company, name="Test Warehouse")
    POSSession.objects.create(
        company=pos_company,
        user=pos_user_with_create,
        status=POSSession.Status.OPEN,
        warehouse=warehouse
    )

    response = client.post(url, data={"cart": [], "payment_method": "cash", "tendered": "0"}, content_type="application/json")

    # Since cart is empty, the view should return 400 Bad Request, proving it passed the 403 check
    assert response.status_code == 400
    assert response.json()['message'] == "Cart is empty."


@pytest.mark.django_db
def test_pos_checkout_preserves_decimal_amounts(
    client, pos_company, pos_user_with_create
):
    warehouse = Warehouse.objects.create(company=pos_company, name="Decimal Warehouse")
    session = POSSession.objects.create(
        company=pos_company,
        user=pos_user_with_create,
        status=POSSession.Status.OPEN,
        warehouse=warehouse,
    )
    product = Product.objects.create(
        company=pos_company,
        name="Decimal Product",
        sku="DECIMAL-001",
        cost_price="0.01",
        sale_price="0.10",
    )
    StockRecord.objects.create(
        company=pos_company, product=product, warehouse=warehouse, quantity_on_hand=10
    )
    client.force_login(pos_user_with_create)

    response = client.post(
        reverse("pos:api_checkout"),
        data={
            "session_id": str(session.pk),
            "cart": [{"id": str(product.pk), "price": "0.10", "qty": "3"}],
            "payment_method": "cash",
            "tendered": "0.30",
        },
        content_type="application/json",
    )

    order = POSOrder.objects.get(session=session)
    line = order.lines.get()
    payment = POSPayment.objects.get(order=order)
    movement = StockMovement.objects.get(reference_id=str(order.pk))
    assert response.status_code == 200
    assert order.subtotal == Decimal("0.30")
    assert line.quantity == Decimal("3")
    assert line.subtotal == Decimal("0.30")
    assert payment.tendered == Decimal("0.30")
    assert payment.change == Decimal("0.00")
    assert movement.quantity == Decimal("-3")
    assert (
        StockRecord.objects.get(
            product=product, warehouse=warehouse
        ).quantity_on_hand
        == Decimal("7")
    )


@pytest.mark.django_db
def test_pos_checkout_rolls_back_sale_when_stock_movement_fails(
    client, pos_company, pos_user_with_create
):
    warehouse = Warehouse.objects.create(company=pos_company, name="Failure Warehouse")
    session = POSSession.objects.create(
        company=pos_company,
        user=pos_user_with_create,
        status=POSSession.Status.OPEN,
        warehouse=warehouse,
    )
    product = Product.objects.create(
        company=pos_company,
        name="Failure Product",
        sku="FAIL-001",
        cost_price="1.00",
        sale_price="2.00",
    )
    stock = StockRecord.objects.create(
        company=pos_company, product=product, warehouse=warehouse, quantity_on_hand=5
    )
    client.force_login(pos_user_with_create)

    with patch(
        "apps.inventory.models.StockMovement.save",
        side_effect=RuntimeError("inventory write failed"),
    ):
        response = client.post(
            reverse("pos:api_checkout"),
            data={
                "session_id": str(session.pk),
                "cart": [{"id": str(product.pk), "price": "2.00", "qty": "1"}],
                "payment_method": "cash",
                "tendered": "2.00",
            },
            content_type="application/json",
        )

    assert response.status_code == 500
    assert not POSOrder.objects.filter(session=session).exists()
    assert not POSPayment.objects.filter(order__session=session).exists()
    stock.refresh_from_db()
    assert stock.quantity_on_hand == Decimal("5")
    assert not StockMovement.objects.filter(reference_type="POSOrder").exists()


@pytest.mark.django_db
def test_pos_checkout_rejects_session_from_another_company(
    client, pos_company, pos_user_with_create
):
    other_company = Company.objects.create(name="Other POS Company")
    other_warehouse = Warehouse.objects.create(
        company=other_company, name="Other Warehouse"
    )
    foreign_session = POSSession.objects.create(
        company=other_company,
        user=pos_user_with_create,
        status=POSSession.Status.OPEN,
        warehouse=other_warehouse,
    )
    product = Product.objects.create(
        company=pos_company,
        name="Tenant Product",
        sku="TENANT-001",
        cost_price="1.00",
        sale_price="2.00",
    )
    client.force_login(pos_user_with_create)

    response = client.post(
        reverse("pos:api_checkout"),
        data={
            "session_id": str(foreign_session.pk),
            "cart": [{"id": str(product.pk), "price": "2.00", "qty": "1"}],
            "payment_method": "cash",
            "tendered": "2.00",
        },
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not POSOrder.objects.exists()
    assert not POSPayment.objects.exists()
