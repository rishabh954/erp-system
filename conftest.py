import pytest
from core.factories import CompanyFactory, UserFactory
from apps.authentication.models import UserCompany
from apps.company.models import Currency, Tax
from decimal import Decimal

@pytest.fixture
def company(db):
    return CompanyFactory()

@pytest.fixture
def user(db, company):
    user = UserFactory(primary_company=company)
    UserCompany.objects.create(user=user, company=company)
    return user

@pytest.fixture
def currency(db):
    return Currency.objects.create(
        code='USD',
        name='US Dollar',
        symbol='$',
        is_base=True
    )

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
