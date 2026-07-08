import pytest
from django.urls import reverse
from django.utils import timezone
from apps.pos.models import POSSession
from apps.inventory.models import Product, ProductCategory, Warehouse

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
    session = POSSession.objects.create(
        company=pos_company,
        user=pos_user_with_create,
        status=POSSession.Status.OPEN,
        warehouse=warehouse
    )
    
    response = client.post(url, data={"cart": [], "payment_method": "cash", "tendered": "0"}, content_type="application/json")
    
    # Since cart is empty, the view should return 400 Bad Request, proving it passed the 403 check
    assert response.status_code == 400
    assert response.json()['message'] == "Cart is empty."
