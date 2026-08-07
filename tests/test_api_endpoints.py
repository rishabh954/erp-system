"""
Tests for API Endpoints in ERP system.
"""
import pytest
from rest_framework_simplejwt.tokens import RefreshToken
from apps.sales.models import Invoice

@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()

@pytest.fixture
def jwt_auth(user):
    refresh = RefreshToken.for_user(user)
    return str(refresh.access_token)

@pytest.mark.django_db
class TestAPIEndpoints:
    def test_unauthenticated_api_access_returns_401(self, api_client):
        """Test: unauthenticated API access returns 401"""
        response = api_client.get('/api/v1/sales/invoices/')
        assert response.status_code == 401

    def test_get_invoices_returns_200_with_jwt_auth(self, api_client, jwt_auth, company):
        """Test: GET /api/sales/invoices/ returns 200 with JWT auth"""
        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + jwt_auth)
        response = api_client.get('/api/v1/sales/invoices/')
        assert response.status_code == 200
        
    def test_post_invoices_creates_invoice(self, api_client, jwt_auth, company, currency):
        """Test: POST /api/sales/invoices/ creates invoice"""
        from apps.crm.models import Customer
        customer = Customer.objects.create(company=company, name="Test Customer")
        
        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + jwt_auth)
        data = {
            "customer": customer.id,
            "currency": currency.id,
            "status": "draft",
            "invoice_date": "2024-01-01",
            "due_date": "2024-01-31"
        }
        response = api_client.post('/api/v1/sales/invoices/', data, format='json')
        assert response.status_code == 201
        assert Invoice.objects.filter(company=company, customer=customer).exists()

    def test_get_products_filtered_by_company(self, api_client, jwt_auth, company, user):
        """Test: GET /api/inventory/products/ filtered by company"""
        from apps.company.models import Company
        from apps.inventory.models import Product
        
        comp2 = Company.objects.create(name="Other Company")
        p1 = Product.objects.create(company=company, name="Product 1", sku="P1")
        p2 = Product.objects.create(company=comp2, name="Product 2", sku="P2")
        
        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + jwt_auth)
        response = api_client.get('/api/v1/inventory/products/')
        assert response.status_code == 200
        
        data = response.json()
        
        results = data.get("results", data) if isinstance(data, dict) and "results" in data else data
        skus = [p["sku"] for p in results]
        
        assert "P1" in skus
        assert "P2" not in skus
