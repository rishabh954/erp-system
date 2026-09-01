"""
Tests for API Endpoints & Tenant Isolation in ERP system.
"""
import pytest
from rest_framework_simplejwt.tokens import RefreshToken

from apps.company.models import Company
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
        """Test: GET /api/inventory/products/ filtered by company (JWT Auth)"""
        from apps.inventory.models import Product

        comp2 = Company.objects.create(name="Other Company")
        Product.objects.create(company=company, name="Product 1", sku="P1")
        Product.objects.create(company=comp2, name="Product 2", sku="P2")

        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + jwt_auth)
        response = api_client.get('/api/v1/inventory/products/')
        assert response.status_code == 200

        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) and "results" in data else data
        skus = [p["sku"] for p in results]

        assert "P1" in skus
        assert "P2" not in skus

    def test_crm_customers_filtered_by_company(self, api_client, jwt_auth, company, user):
        """Test: GET /api/v1/crm/customers/ filtered by company (JWT Auth)"""
        from apps.crm.models import Customer
        user.is_superuser = True
        user.save()
        comp2 = Company.objects.create(name="Tenant 2")
        Customer.objects.create(company=company, name="Cust Company 1")
        Customer.objects.create(company=comp2, name="Cust Company 2")

        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + jwt_auth)
        response = api_client.get('/api/v1/crm/customers/')
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) and "results" in data else data
        names = [c["name"] for c in results]

        assert "Cust Company 1" in names
        assert "Cust Company 2" not in names

    def test_hrms_employees_filtered_by_company(self, api_client, jwt_auth, company, user):
        """Test: GET /api/v1/hrms/employees/ filtered by company (JWT Auth)"""
        from django.utils import timezone

        from apps.hrms.models import Employee
        user.is_superuser = True
        user.save()
        comp2 = Company.objects.create(name="Tenant 2 HR")
        today = timezone.now().date()
        Employee.objects.create(company=company, first_name="Emp1", last_name="C1", employee_id="EMP01", joining_date=today)
        Employee.objects.create(company=comp2, first_name="Emp2", last_name="C2", employee_id="EMP02", joining_date=today)

        api_client.credentials(HTTP_AUTHORIZATION='Bearer ' + jwt_auth)
        response = api_client.get('/api/v1/hrms/employees/')
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data) if isinstance(data, dict) and "results" in data else data
        emp_ids = [e["employee_id"] for e in results]

        assert "EMP01" in emp_ids
        assert "EMP02" not in emp_ids
