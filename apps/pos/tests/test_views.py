from decimal import Decimal

import pytest
from django.urls import reverse

from apps.inventory.models import Product, StockMovement, Warehouse
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
