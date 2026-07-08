import pytest
from django.urls import reverse

from apps.crm.models import Customer, Lead

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
    list_url = reverse("crm:customer_list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert cust in res.context["object_list"]


def test_lead_crud(client, user, company):
    client.force_login(user)

    # Create
    create_url = reverse("crm:lead_create")
    res = client.post(
        create_url,
        {
            "name": "Test Lead CRUD",
            "expected_revenue": "1000.00",
            "status": Lead.Status.NEW,
        },
    )
    assert res.status_code == 302
    lead = Lead.objects.filter(name="Test Lead CRUD").first()
    assert lead is not None

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
        },
    )
    assert res.status_code == 302
    lead.refresh_from_db()
    assert lead.name == "Test Lead CRUD Updated"

    # List
    list_url = reverse("crm:lead_list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert lead in res.context["object_list"]
