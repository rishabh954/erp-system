import pytest
from django.urls import reverse
from datetime import date
from decimal import Decimal

from apps.crm.models import Customer, Lead
from apps.sales.models import SalesOrder
from apps.purchase.models import Vendor, PurchaseOrder
from apps.projects.models import Project
from apps.inventory.models import Product, Warehouse
from apps.hrms.models import Employee
from apps.company.models import Department

pytestmark = pytest.mark.django_db

@pytest.fixture
def company_a(company):
    return company

@pytest.fixture
def company_b():
    from core.factories import CompanyFactory
    return CompanyFactory(name='Company B')

@pytest.fixture
def user_a(user):
    return user

def test_multitenant_boundary(client, user_a, company_a, company_b):
    # Log in as user from Company A
    client.force_login(user_a)

    # 1. Customer (CRM)
    cust_b = Customer.objects.create(
        company=company_b, name='Cust B', email='cust@b.com'
    )
    res = client.get(reverse('crm:customer_detail', kwargs={'pk': cust_b.pk}))
    assert res.status_code == 404

    # 2. Lead (CRM)
    lead_b = Lead.objects.create(
        company=company_b, name='Lead B', expected_revenue=0
    )
    res = client.get(reverse('crm:lead_detail', kwargs={'pk': lead_b.pk}))
    assert res.status_code == 404

    # 3. SalesOrder (Sales)
    so_b = SalesOrder.objects.create(
        company=company_b, customer=cust_b, order_date=date.today()
    )
    res = client.get(reverse('sales:order_detail', kwargs={'pk': so_b.pk}))
    assert res.status_code == 404

    # 4. Vendor (Purchase)
    vend_b = Vendor.objects.create(
        company=company_b, name='Vendor B'
    )
    res = client.get(reverse('purchase:vendor_detail', kwargs={'pk': vend_b.pk}))
    assert res.status_code == 404

    # 5. PurchaseOrder (Purchase)
    po_b = PurchaseOrder.objects.create(
        company=company_b, vendor=vend_b, date=date.today(), expected_date=date.today()
    )
    res = client.get(reverse('purchase:order_detail', kwargs={'pk': po_b.pk}))
    assert res.status_code == 404

    # 6. Project
    proj_b = Project.objects.create(
        company=company_b, name='Proj B'
    )
    res = client.get(reverse('projects:project_detail', kwargs={'pk': proj_b.pk}))
    assert res.status_code == 404

    # 7. Product (Inventory)
    prod_b = Product.objects.create(
        company=company_b, name='Prod B', sku='B-001', product_type='stockable',
        cost_price=Decimal('10'), sale_price=Decimal('20')
    )
    res = client.get(reverse('inventory:product_detail', kwargs={'pk': prod_b.pk}))
    assert res.status_code == 404

    # 8. Employee (HRMS)
    dept_b = Department.objects.create(
        company=company_b, name='Dept B', code='DB'
    )
    from core.factories import UserFactory
    user_b = UserFactory(email='emp_b@test.com', primary_company=company_b)
    emp_b = Employee.objects.create(
        company=company_b, user=user_b, department=dept_b,
        employee_id='E-002', first_name='John', last_name='B', joining_date=date.today()
    )
    res = client.get(reverse('hrms:employee_detail', kwargs={'pk': emp_b.pk}))
    assert res.status_code == 404
