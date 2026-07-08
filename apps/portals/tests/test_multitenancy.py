from datetime import date

import pytest
from django.urls import reverse

from apps.crm.models import Customer
from apps.purchase.models import PurchaseOrder, Vendor
from apps.sales.models import SalesOrder
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def company_b():
    return CompanyFactory(name="Company B")


@pytest.fixture
def customer_a(company):
    user = UserFactory(email="cust_a@test.com", primary_company=company)
    return Customer.objects.create(company=company, name="Customer A", portal_user=user)


@pytest.fixture
def customer_b(company_b):
    user = UserFactory(email="cust_b@test.com", primary_company=company_b)
    return Customer.objects.create(
        company=company_b, name="Customer B", portal_user=user
    )


@pytest.fixture
def vendor_a(company):
    user = UserFactory(email="vendor_a@test.com", primary_company=company)
    return Vendor.objects.create(
        company=company, name="Vendor A", portal_user=user, email="vendor_a@test.com"
    )


@pytest.fixture
def vendor_b(company_b):
    user = UserFactory(email="vendor_b@test.com", primary_company=company_b)
    return Vendor.objects.create(
        company=company_b, name="Vendor B", portal_user=user, email="vendor_b@test.com"
    )


def test_customer_portal_isolation(client, company, company_b, customer_a, customer_b):
    order_a = SalesOrder.objects.create(
        company=company,
        customer=customer_a,
        order_date=date.today(),
        status=SalesOrder.Status.CONFIRMED,
    )

    order_b = SalesOrder.objects.create(
        company=company_b,
        customer=customer_b,
        order_date=date.today(),
        status=SalesOrder.Status.CONFIRMED,
    )

    # Login as customer_a
    client.force_login(customer_a.portal_user)

    # Check lists
    url_list = reverse("portals:customer_orders")
    response = client.get(url_list)
    assert response.status_code == 200
    assert order_a in response.context["orders"]
    assert order_b not in response.context["orders"]

    # Check detail views
    url_detail_a = reverse("portals:customer_order_detail", kwargs={"pk": order_a.pk})
    response_a = client.get(url_detail_a)
    assert response_a.status_code == 200

    url_detail_b = reverse("portals:customer_order_detail", kwargs={"pk": order_b.pk})
    response_b = client.get(url_detail_b)
    assert response_b.status_code == 404


def test_vendor_portal_isolation(client, company, company_b, vendor_a, vendor_b):
    po_a = PurchaseOrder.objects.create(
        company=company,
        vendor=vendor_a,
        order_date=date.today(),
        expected_delivery=date.today(),
        status=PurchaseOrder.Status.CONFIRMED,
    )

    po_b = PurchaseOrder.objects.create(
        company=company_b,
        vendor=vendor_b,
        order_date=date.today(),
        expected_delivery=date.today(),
        status=PurchaseOrder.Status.CONFIRMED,
    )

    # Login as vendor_a
    client.force_login(vendor_a.portal_user)

    # Check lists
    url_list = reverse("portals:vendor_orders")
    response = client.get(url_list)
    assert response.status_code == 200
    assert po_a in response.context["orders"]
    assert po_b not in response.context["orders"]

    # Check detail views
    url_detail_a = reverse("portals:vendor_order_detail", kwargs={"pk": po_a.pk})
    response_a = client.get(url_detail_a)
    assert response_a.status_code == 200

    url_detail_b = reverse("portals:vendor_order_detail", kwargs={"pk": po_b.pk})
    response_b = client.get(url_detail_b)
    assert response_b.status_code == 404
