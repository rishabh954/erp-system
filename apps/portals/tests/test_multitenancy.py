from datetime import date

import pytest
from django.urls import reverse

from apps.authentication.models import User, UserCompany
from apps.crm.models import Customer
from apps.helpdesk.models import Ticket, TicketCategory, TicketReply
from apps.purchase.models import PurchaseOrder, Vendor
from apps.sales.models import SalesOrder
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def company_b():
    return CompanyFactory(name="Company B")


@pytest.fixture
def customer_a(company):
    user = UserFactory(
        email="cust_a@test.com",
        primary_company=company,
        role=User.Role.CUSTOMER_PORTAL,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.CUSTOMER_PORTAL,
        is_active=True,
    )
    return Customer.objects.create(company=company, name="Customer A", portal_user=user)


@pytest.fixture
def customer_b(company_b):
    user = UserFactory(
        email="cust_b@test.com",
        primary_company=company_b,
        role=User.Role.CUSTOMER_PORTAL,
    )
    UserCompany.objects.create(
        user=user,
        company=company_b,
        role=User.Role.CUSTOMER_PORTAL,
        is_active=True,
    )
    return Customer.objects.create(
        company=company_b, name="Customer B", portal_user=user
    )


@pytest.fixture
def vendor_a(company):
    user = UserFactory(
        email="vendor_a@test.com",
        primary_company=company,
        role=User.Role.CUSTOMER_PORTAL,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.CUSTOMER_PORTAL,
        is_active=True,
    )
    return Vendor.objects.create(
        company=company, name="Vendor A", portal_user=user, email="vendor_a@test.com"
    )


@pytest.fixture
def vendor_b(company_b):
    user = UserFactory(
        email="vendor_b@test.com",
        primary_company=company_b,
        role=User.Role.CUSTOMER_PORTAL,
    )
    UserCompany.objects.create(
        user=user,
        company=company_b,
        role=User.Role.CUSTOMER_PORTAL,
        is_active=True,
    )
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


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   ", "description": "Problem"},
        {"title": "Problem", "description": "  "},
        {"title": "Problem", "description": "Details", "priority": "urgent?"},
    ],
)
def test_customer_ticket_rejects_invalid_input_without_writes(
    client, customer_a, company, payload
):
    client.force_login(customer_a.portal_user)
    before = Ticket.objects.filter(company=company).count()

    response = client.post(reverse("portals:customer_ticket_create"), payload)

    assert response.status_code == 302
    assert Ticket.objects.filter(company=company).count() == before


def test_customer_ticket_rejects_foreign_category_without_writes(
    client, customer_a, company, company_b
):
    client.force_login(customer_a.portal_user)
    foreign_category = TicketCategory.objects.create(
        company=company_b, name="Other company category", sla_hours=8
    )
    before = Ticket.objects.filter(company=company).count()

    response = client.post(
        reverse("portals:customer_ticket_create"),
        {
            "title": "Support request",
            "description": "Details",
            "category": str(foreign_category.pk),
        },
    )

    assert response.status_code == 302
    assert Ticket.objects.filter(company=company).count() == before


def test_customer_ticket_uses_portal_default_and_company_category(
    client, customer_a, company
):
    client.force_login(customer_a.portal_user)
    category = TicketCategory.objects.create(
        company=company, name="Customer support", sla_hours=12
    )

    response = client.post(
        reverse("portals:customer_ticket_create"),
        {
            "title": "Support request",
            "description": "Details",
            "category": str(category.pk),
        },
    )

    ticket = Ticket.objects.get(company=company, customer=customer_a)
    assert response.status_code == 302
    assert ticket.category == category
    assert ticket.priority == Ticket.Priority.MEDIUM
    assert ticket.source == Ticket.Source.PORTAL


def test_customer_ticket_reply_is_atomic_and_ignores_whitespace(
    client, customer_a, company
):
    client.force_login(customer_a.portal_user)
    ticket = Ticket.objects.create(
        company=company,
        customer=customer_a,
        requester=customer_a.portal_user,
        title="Existing",
        description="Details",
        status=Ticket.Status.RESOLVED,
    )

    response = client.post(
        reverse("portals:customer_ticket_detail", kwargs={"pk": ticket.pk}),
        {"content": "   "},
    )

    ticket.refresh_from_db()
    assert response.status_code == 302
    assert not TicketReply.objects.filter(ticket=ticket).exists()
    assert ticket.status == Ticket.Status.RESOLVED


def test_customer_profile_rejects_oversized_values_without_partial_write(
    client, customer_a
):
    customer_a.phone = "555-0100"
    customer_a.address_line1 = "Existing address"
    customer_a.save(update_fields=["phone", "address_line1"])
    client.force_login(customer_a.portal_user)

    response = client.post(
        reverse("portals:customer_profile"),
        {"phone": "1" * 31, "billing_address": "New address"},
    )

    customer_a.refresh_from_db()
    assert response.status_code == 302
    assert customer_a.phone == "555-0100"
    assert customer_a.address_line1 == "Existing address"
