import pytest
from django.urls import reverse

from apps.crm.models import Customer, Lead
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_customer_crud(client, user, company):
    client.force_login(user)

    # Create
    create_url = reverse("crm:customer_create")
    res = client.post(
        create_url,
        {
            "name": "Test Customer CRUD",
            "customer_type": Customer.CustomerType.BUSINESS,
        },
    )
    assert res.status_code == 302
    cust = Customer.objects.filter(name="Test Customer CRUD").first()
    assert cust is not None

    # Read Detail
    detail_url = reverse("crm:customer_detail", kwargs={"pk": cust.pk})
    res = client.get(detail_url)
    assert res.status_code == 200

    # Update
    update_url = reverse("crm:customer_update", kwargs={"pk": cust.pk})
    res = client.post(
        update_url,
        {
            "name": "Test Customer CRUD Updated",
            "customer_type": Customer.CustomerType.BUSINESS,
        },
    )
    assert res.status_code == 302
    cust.refresh_from_db()
    assert cust.name == "Test Customer CRUD Updated"

    # List
    list_url = reverse("crm:customers")
    res = client.get(list_url)
    assert res.status_code == 200
    assert cust in res.context["object_list"]


def test_lead_crud(client, user, company):
    client.force_login(user)

    # Create
    create_url = reverse("crm:lead_create")
    invalid_response = client.post(
        create_url,
        {"name": "Lead With Invalid Email", "email": "invalid-email"},
    )
    assert invalid_response.status_code == 200
    assert invalid_response.context["form"].errors["email"]
    assert b"toast-error" in invalid_response.content
    assert b"Email: Enter a valid email address." in invalid_response.content
    assert b"invalid-feedback d-block" not in invalid_response.content
    assert b"Please correct the following errors" not in invalid_response.content
    assert b'value="Lead With Invalid Email"' in invalid_response.content

    res = client.post(
        create_url,
        {
            "name": "Test Lead CRUD",
            "status": Lead.Status.NEW,
            "probability": 50,
        },
        follow=True,
    )
    assert res.status_code == 200
    assert b"Lead Test Lead CRUD created." in res.content
    lead = Lead.objects.filter(name="Test Lead CRUD").first()
    assert lead is not None
    assert lead.expected_revenue == 0
    notification = Notification.objects.filter(
        recipient=user,
        company=company,
        title="New lead created",
        content_type__model="lead",
        object_id=str(lead.pk),
    ).first()
    assert notification is not None
    assert notification.action_url == reverse(
        "crm:lead_detail", kwargs={"pk": lead.pk}
    )

    status_url = reverse("crm:lead_update_status", kwargs={"pk": lead.pk})
    status_response = client.post(status_url, {"status": Lead.Status.PROPOSAL})
    assert status_response.status_code == 200
    assert status_response.json()["ok"] is True
    lead.refresh_from_db()
    assert lead.status == Lead.Status.PROPOSAL

    # Read Detail
    detail_url = reverse("crm:lead_detail", kwargs={"pk": lead.pk})
    res = client.get(detail_url)
    assert res.status_code == 200

    # Update
    update_url = reverse("crm:lead_update", kwargs={"pk": lead.pk})
    res = client.post(
        update_url,
        {
            "name": "Test Lead CRUD Updated",
            "expected_revenue": "2000.00",
            "status": Lead.Status.NEW,
            "probability": 50,
        },
    )
    assert res.status_code == 302
    lead.refresh_from_db()
    assert lead.name == "Test Lead CRUD Updated"

    # List
    list_url = reverse("crm:leads")
    res = client.get(list_url)
    assert res.status_code == 200
    assert lead in res.context["object_list"]


def test_lead_conversion_reuses_same_company_customer_by_email(
    client, user, company
):
    client.force_login(user)
    session = client.session
    session["active_company_id"] = str(company.pk)
    session.save()

    customer = Customer.objects.create(
        company=company,
        name="Existing Customer",
        email="buyer@example.com",
    )
    lead = Lead.objects.create(
        company=company,
        name="Buyer Lead",
        email="Buyer@Example.com",
    )

    response = client.post(reverse("crm:lead_convert", kwargs={"pk": lead.pk}))

    lead.refresh_from_db()
    assert response.status_code == 302
    assert response.url == reverse("crm:customer_detail", kwargs={"pk": customer.pk})
    assert lead.customer_id == customer.pk
    assert lead.converted_to_customer is True
    assert Customer.objects.filter(company=company, email__iexact="buyer@example.com").count() == 1


def test_lead_won_status_requires_approval_permission():
    from django.test import RequestFactory

    from apps.crm.views import LeadUpdateStatusView

    request = RequestFactory().post("/crm/leads/test/status/", {"status": Lead.Status.WON})

    assert LeadUpdateStatusView().get_required_permission(request) == "crm.approve"


def test_api_lead_conversion_requires_approval_permission():
    from apps.crm.api.views import LeadViewSet

    view = LeadViewSet()
    view.action = "convert_to_customer"

    assert view.get_required_permission() == "crm.approve"


def test_api_lead_conversion_reuses_existing_customer(user, company):
    from rest_framework.test import APIClient

    customer = Customer.objects.create(
        company=company,
        name="Existing API Customer",
        email="api-buyer@example.com",
    )
    lead = Lead.objects.create(
        company=company,
        name="API Buyer Lead",
        email="API-Buyer@Example.com",
    )
    api_client = APIClient()
    api_client.force_authenticate(user=user)

    response = api_client.post(
        f"/api/v1/crm/leads/{lead.pk}/convert_to_customer/",
        {},
        format="json",
        HTTP_X_ACTIVE_COMPANY=str(company.pk),
    )

    lead.refresh_from_db()
    assert response.status_code == 200
    assert response.data["customer_id"] == customer.pk
    assert response.data["customer_reused"] is True
    assert lead.customer_id == customer.pk


def test_api_won_status_creates_customer_through_conversion_service(user, company):
    from rest_framework.test import APIClient

    lead = Lead.objects.create(
        company=company,
        name="Won API Lead",
        email="won-api@example.com",
    )
    api_client = APIClient()
    api_client.force_authenticate(user=user)

    response = api_client.post(
        f"/api/v1/crm/leads/{lead.pk}/update_status/",
        {"status": Lead.Status.WON},
        format="json",
        HTTP_X_ACTIVE_COMPANY=str(company.pk),
    )

    lead.refresh_from_db()
    assert response.status_code == 200
    assert lead.status == Lead.Status.WON
    assert lead.converted_to_customer is True
    assert lead.customer is not None
    assert lead.customer.email == "won-api@example.com"


def test_api_lead_conversion_does_not_accept_create_permission(
    company, db
):
    from rest_framework.test import APIClient

    from apps.authentication.models import ModulePermission, User, UserCompany

    employee = User.objects.create_user(
        "crm-create-only@example.com",
        "password",
        role=User.Role.EMPLOYEE,
        primary_company=company,
    )
    UserCompany.objects.create(
        user=employee,
        company=company,
        role=User.Role.EMPLOYEE,
        is_active=True,
    )
    ModulePermission.objects.update_or_create(
        role=User.Role.EMPLOYEE,
        module="crm",
        defaults={
            "can_read": True,
            "can_create": True,
            "can_update": True,
            "can_approve": False,
        },
    )
    lead = Lead.objects.create(company=company, name="Approval Required Lead")
    api_client = APIClient()
    api_client.force_authenticate(user=employee)

    response = api_client.post(
        f"/api/v1/crm/leads/{lead.pk}/convert_to_customer/",
        {},
        format="json",
        HTTP_X_ACTIVE_COMPANY=str(company.pk),
    )

    assert response.status_code == 403
    assert not Customer.objects.filter(company=company).exists()

    won_response = api_client.post(
        f"/api/v1/crm/leads/{lead.pk}/update_status/",
        {"status": Lead.Status.WON},
        format="json",
        HTTP_X_ACTIVE_COMPANY=str(company.pk),
    )
    assert won_response.status_code == 403
    lead.refresh_from_db()
    assert lead.status == Lead.Status.NEW
    assert not Customer.objects.filter(company=company).exists()
