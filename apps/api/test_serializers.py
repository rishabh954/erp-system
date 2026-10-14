import pytest
from django.test import RequestFactory
from rest_framework.exceptions import ValidationError

from apps.api.serializers import ErpSalesOrderSerializer
from apps.authentication.models import User, UserCompany
from apps.crm.models import Customer
from apps.company.models import Company

pytestmark = pytest.mark.django_db


def test_sales_order_serializer_rejects_customer_from_another_company():
    company_a = Company.objects.create(name="Serializer Tenant A")
    company_b = Company.objects.create(name="Serializer Tenant B")
    user = User.objects.create_user(
        email="serializer-tenant-a@example.com",
        password="test-password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_a,
    )
    UserCompany.objects.create(
        user=user,
        company=company_a,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    customer_a = Customer.objects.create(company=company_a, name="Tenant A Customer")
    customer_b = Customer.objects.create(company=company_b, name="Tenant B Customer")

    request = RequestFactory().post("/api/v1/sales/orders/")
    request.user = user
    request.session = {}
    serializer = ErpSalesOrderSerializer(context={"request": request})

    assert serializer.fields["customer"].run_validation(customer_a.pk) == customer_a
    with pytest.raises(ValidationError):
        serializer.fields["customer"].run_validation(customer_b.pk)


def test_purchase_order_serializer_rejects_vendor_from_another_company():
    from apps.api.serializers import ErpPurchaseOrderSerializer
    from apps.purchase.models import Vendor

    company_a = Company.objects.create(name="Purchase Tenant A")
    company_b = Company.objects.create(name="Purchase Tenant B")
    user = User.objects.create_user(
        email="po-tenant-a@example.com",
        password="test-password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_a,
    )
    UserCompany.objects.create(
        user=user,
        company=company_a,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    vendor_a = Vendor.objects.create(company=company_a, name="Vendor A")
    vendor_b = Vendor.objects.create(company=company_b, name="Vendor B")

    request = RequestFactory().post("/api/v1/purchase/orders/")
    request.user = user
    request.session = {}
    serializer = ErpPurchaseOrderSerializer(context={"request": request})

    assert serializer.fields["vendor"].run_validation(vendor_a.pk) == vendor_a
    with pytest.raises(ValidationError):
        serializer.fields["vendor"].run_validation(vendor_b.pk)


def test_stock_record_serializer_rejects_product_and_warehouse_from_another_company():
    from apps.inventory.api.serializers import StockRecordSerializer
    from apps.inventory.models import Product, Warehouse

    company_a = Company.objects.create(name="Inventory Tenant A")
    company_b = Company.objects.create(name="Inventory Tenant B")
    user = User.objects.create_user(
        email="inv-tenant-a@example.com",
        password="test-password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_a,
    )
    UserCompany.objects.create(
        user=user,
        company=company_a,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    product_a = Product.objects.create(company=company_a, name="Product A", sku="SKU-A")
    product_b = Product.objects.create(company=company_b, name="Product B", sku="SKU-B")
    wh_a = Warehouse.objects.create(company=company_a, name="WH A")
    wh_b = Warehouse.objects.create(company=company_b, name="WH B")

    request = RequestFactory().post("/api/v1/inventory/stock-records/")
    request.user = user
    request.session = {}
    serializer = StockRecordSerializer(context={"request": request})

    assert serializer.fields["product"].run_validation(product_a.pk) == product_a
    with pytest.raises(ValidationError):
        serializer.fields["product"].run_validation(product_b.pk)

    assert serializer.fields["warehouse"].run_validation(wh_a.pk) == wh_a
    with pytest.raises(ValidationError):
        serializer.fields["warehouse"].run_validation(wh_b.pk)
