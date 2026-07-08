import pytest
from django.test import Client, override_settings
from django.urls import reverse

from apps.authentication.models import User, UserCompany
from apps.company.models import Company, Currency

pytestmark = pytest.mark.django_db


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
def test_company_create_view_get():
    """Test GET request to company creation view."""
    client = Client()

    # Create user with NO primary company
    user = User.objects.create_user(
        email="newuser@example.com",
        password="password123",
        first_name="New",
        last_name="User",
    )

    client.login(email="newuser@example.com", password="password123")
    url = reverse("company:create")

    response = client.get(url)
    assert response.status_code == 200
    assert "company/company_create.html" in [t.name for t in response.templates]


def test_company_create_view_post():
    """Test POST request successfully creates company and assigns role."""
    client = Client()

    # Currency already seeded by conftest
    user = User.objects.create_user(
        email="founder@example.com",
        password="password123",
        first_name="Founder",
        last_name="CEO",
    )

    client.login(email="founder@example.com", password="password123")
    url = reverse("company:create")

    data = {
        "name": "Acme Corp",
        "legal_name": "Acme Corporation Inc.",
        "company_type": "LLC",
        "industry": "Software",
        "fiscal_year_start": "01-01",
        "timezone": "America/New_York",
        "default_currency": Currency.objects.first().id,
    }

    response = client.post(url, data)

    # Should redirect to dashboard
    assert response.status_code == 302
    assert response.url == reverse("dashboard:index")

    # Verify company was created
    company = Company.objects.filter(name="Acme Corp").first()
    assert company is not None
    assert company.timezone == "America/New_York"

    # Verify UserCompany mapping created
    uc = UserCompany.objects.get(user=user, company=company)
    assert uc.role == "company_admin"

    # Verify user primary company updated
    user.refresh_from_db()
    assert user.primary_company == company


def test_company_create_view_redirects_if_already_has_company():
    """Test GET and POST redirect if user already has a primary company."""
    client = Client()

    company = Company.objects.create(name="Existing Company", timezone="UTC")
    user = User.objects.create_user(
        email="existing@example.com", password="password123", primary_company=company
    )

    client.login(email="existing@example.com", password="password123")
    url = reverse("company:create")

    # GET should redirect
    response = client.get(url)
    assert response.status_code == 302
    assert response.url == reverse("dashboard:index")

    # POST should also redirect without creating a new company
    response = client.post(url, {"name": "Another Company"})
    assert response.status_code == 302
    assert response.url == reverse("dashboard:index")
    assert not Company.objects.filter(name="Another Company").exists()
