import pytest
from django.urls import reverse

from apps.administration.models import InstalledApp
from apps.authentication.models import User, UserCompany

pytestmark = pytest.mark.django_db


def test_app_store_loads_and_toggle_enables_then_disables(client, user, company):
    client.force_login(user)
    assert client.get(reverse("administration:app_store")).status_code == 200
    toggle_url = reverse("administration:app_toggle", kwargs={"pk": "crm"})

    response = client.post(toggle_url)
    assert response.status_code == 302
    app = InstalledApp.objects.get(company=company, app_label="crm")
    assert app.is_active

    response = client.post(toggle_url)
    assert response.status_code == 302
    app.refresh_from_db()
    assert not app.is_active


def test_app_toggle_rejects_unknown_label(client, user):
    client.force_login(user)
    response = client.post(
        reverse("administration:app_toggle", kwargs={"pk": "unknown"})
    )
    assert response.status_code == 400


def test_non_admin_cannot_toggle_company_app(client, user, company):
    UserCompany.objects.filter(user=user, company=company).update(role=User.Role.EMPLOYEE)
    client.force_login(user)
    response = client.post(
        reverse("administration:app_toggle", kwargs={"pk": "crm"})
    )
    assert response.status_code == 403
    assert not InstalledApp.objects.filter(company=company, app_label="crm").exists()
