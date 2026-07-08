from datetime import date
from decimal import Decimal

import pytest

from apps.authentication.models import UserCompany
from apps.company.models import Currency, Tax
from core.factories import CompanyFactory, UserFactory


@pytest.fixture
def company(db):
    return CompanyFactory()

@pytest.fixture
def user(db, company):
    from apps.authentication.models import User
    user = UserFactory(primary_company=company, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.create(user=user, company=company, role=User.Role.COMPANY_ADMIN)
    return user

@pytest.fixture
def currency(db):
    currency, created = Currency.objects.get_or_create(
        code='USD',
        defaults={
            'name': 'US Dollar',
            'symbol': '$',
            'is_base': True
        }
    )
    return currency

@pytest.fixture
def tax(db, company):
    return Tax.objects.create(
        company=company,
        name='Standard Tax',
        rate=10.00
    )

@pytest.fixture
def product(db, company):
    from apps.inventory.models import Product
    return Product.objects.create(
        company=company,
        name='Test Product',
        sku='TEST-001',
        product_type='stockable',
        cost_price=Decimal('50.00'),
        sale_price=Decimal('100.00')
    )

@pytest.fixture
def warehouse(db, company):
    from apps.inventory.models import Warehouse
    return Warehouse.objects.create(
        company=company,
        name='Main Warehouse',
        code='MAIN'
    )

@pytest.fixture
def vendor(db, company):
    from apps.purchase.models import Vendor
    return Vendor.objects.create(
        company=company,
        name='Test Vendor',
        email='vendor@test.com'
    )

@pytest.fixture
def department(db, company):
    from apps.company.models import Department
    return Department.objects.create(
        company=company,
        name='Test Department',
        code='DEPT-01'
    )

@pytest.fixture
def employee(db, company, user, department):
    from apps.hrms.models import Employee
    return Employee.objects.create(
        company=company,
        user=user,
        department=department,
        employee_id='EMP-001',
        first_name='John',
        last_name='Doe',
        joining_date=date.today()
    )

