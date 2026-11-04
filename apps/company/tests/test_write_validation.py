import pytest
from django.test import Client
from django.urls import reverse

from apps.authentication.models import User, UserCompany
from apps.company.models import (
    Branch,
    Company,
    Currency,
    Department,
    ExchangeRate,
    FiscalYear,
    Tax,
    TaxGroup,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def company_admin_client():
    company = Company.objects.create(name="Validation Tenant")
    user = User.objects.create_superuser(
        email="company-validation@example.com",
        password="test-password",
        first_name="Validation",
        last_name="Admin",
    )
    UserCompany.objects.create(
        user=user, company=company, role=User.Role.COMPANY_ADMIN, is_active=True
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["active_company_id"] = str(company.pk)
    session.save()
    return client, company


def test_settings_invalid_fiscal_date_do_not_save_any_fields(company_admin_client):
    client, company = company_admin_client
    response = client.post(
        reverse("company:settings"),
        {"name": "Changed Name", "timezone": "UTC", "fiscal_year_start": "02-31"},
    )

    company.refresh_from_db()
    assert response.status_code == 302
    assert company.name == "Validation Tenant"
    assert company.fiscal_year_start == "01-01"


def test_settings_reject_invalid_language_without_partial_save(company_admin_client):
    client, company = company_admin_client
    response = client.post(
        reverse("company:settings"),
        {
            "name": "Changed Name",
            "timezone": "UTC",
            "fiscal_year_start": "01-01",
            "language": "xx",
        },
    )

    company.refresh_from_db()
    assert response.status_code == 302
    assert company.name == "Validation Tenant"
    assert company.language == "en"


def test_company_create_rejects_bad_choice_without_creating_company(db):
    user = User.objects.create_user(
        email="new-company-owner@example.com",
        password="test-password",
        first_name="New",
        last_name="Owner",
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        reverse("company:create"),
        {
            "name": "Invalid Company",
            "company_type": "not-a-company-type",
            "fiscal_year_start": "01-01",
            "timezone": "UTC",
        },
    )

    user.refresh_from_db()
    assert response.status_code == 200
    assert "company_type" in response.context["errors"]
    assert not Company.objects.filter(name="Invalid Company").exists()
    assert user.primary_company is None


def test_company_create_preserves_default_values(db):
    user = User.objects.create_user(
        email="default-company-owner@example.com",
        password="test-password",
        first_name="Default",
        last_name="Owner",
    )
    client = Client()
    client.force_login(user)

    response = client.post(reverse("company:create"), {"name": "Default Company"})

    user.refresh_from_db()
    company = Company.objects.get(name="Default Company")
    assert response.status_code == 302
    assert company.company_type == Company.CompanyType.LLC
    assert company.timezone == "UTC"
    assert company.fiscal_year_start == "01-01"
    assert user.primary_company == company


def test_branch_rejects_manager_without_active_company_membership(company_admin_client):
    client, company = company_admin_client
    foreign_company = Company.objects.create(name="Other Tenant")
    foreign_user = User.objects.create_user(
        email="foreign-manager@example.com",
        password="test-password",
        first_name="Foreign",
        last_name="Manager",
    )
    UserCompany.objects.create(
        user=foreign_user,
        company=foreign_company,
        role=User.Role.EMPLOYEE,
        is_active=True,
    )

    response = client.post(
        reverse("company:branch_create"),
        {"name": "Branch", "code": "BR", "manager": str(foreign_user.pk)},
    )

    assert response.status_code == 302
    assert not Branch.objects.filter(company=company).exists()


def test_department_rejects_foreign_branch_without_creating_department(company_admin_client):
    client, company = company_admin_client
    foreign_company = Company.objects.create(name="Other Branch Tenant")
    foreign_branch = Branch.objects.create(
        company=foreign_company, name="Foreign Branch", code="FB"
    )

    response = client.post(
        reverse("company:department_create"),
        {
            "name": "Finance",
            "code": "FIN",
            "branch": str(foreign_branch.pk),
        },
    )

    assert response.status_code == 302
    assert not Department.objects.filter(company=company).exists()


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [("2026-02-30", "2026-12-31"), ("2026-12-31", "2026-01-01")],
)
def test_fiscal_year_rejects_invalid_or_reversed_dates(
    company_admin_client, start_date, end_date
):
    client, company = company_admin_client
    response = client.post(
        reverse("company:fiscal_year_create"),
        {
            "name": "FY 2026",
            "start_date": start_date,
            "end_date": end_date,
            "is_current": "on",
        },
    )

    assert response.status_code == 302
    assert not FiscalYear.objects.filter(company=company).exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "US", "name": "Invalid", "decimal_places": "2"},
        {"code": "USD", "name": "Invalid", "decimal_places": "2.5"},
        {"code": "USD", "name": "Invalid", "decimal_places": "9"},
    ],
)
def test_currency_rejects_invalid_code_or_decimal_places(company_admin_client, payload):
    client, _ = company_admin_client
    before = set(Currency.objects.values_list("pk", flat=True))
    response = client.post(reverse("company:currency_create"), payload)

    assert response.status_code == 302
    assert set(Currency.objects.values_list("pk", flat=True)) == before


def test_currency_create_normalizes_code_and_keeps_decimal_default(company_admin_client):
    client, _ = company_admin_client
    response = client.post(
        reverse("company:currency_create"),
        {"code": "czz", "name": "Validation Currency"},
    )

    currency = Currency.objects.get(code="CZZ")
    assert response.status_code == 302
    assert currency.decimal_places == 2


def test_exchange_rate_rejects_nonfinite_decimal(company_admin_client):
    client, _ = company_admin_client
    source = Currency.objects.create(code="AAA", name="Source", symbol="$")
    target = Currency.objects.create(code="BBB", name="Target", symbol="B")

    response = client.post(
        reverse("company:exchange_rate_create"),
        {
            "from_currency": str(source.pk),
            "to_currency": str(target.pk),
            "rate": "NaN",
            "effective_date": "2026-01-01",
        },
    )

    assert response.status_code == 302
    assert not ExchangeRate.objects.exists()


def test_exchange_rate_accepts_valid_decimal_and_date(company_admin_client):
    client, _ = company_admin_client
    source = Currency.objects.create(code="EAA", name="Source", symbol="A")
    target = Currency.objects.create(code="EAB", name="Target", symbol="B")

    response = client.post(
        reverse("company:exchange_rate_create"),
        {
            "from_currency": str(source.pk),
            "to_currency": str(target.pk),
            "rate": "1.250000",
            "effective_date": "2026-01-01",
        },
    )

    exchange_rate = ExchangeRate.objects.get(from_currency=source, to_currency=target)
    assert response.status_code == 302
    assert str(exchange_rate.rate) == "1.250000"
    assert exchange_rate.effective_date.isoformat() == "2026-01-01"


def test_tax_rejects_foreign_tenant_group_without_writing(company_admin_client):
    client, company = company_admin_client
    foreign_company = Company.objects.create(name="Tax Group Tenant")
    foreign_group = TaxGroup.objects.create(
        company=foreign_company, name="Foreign tax group"
    )

    response = client.post(
        reverse("company:tax_create"),
        {
            "name": "VAT",
            "rate": "20.0000",
            "tax_type": Tax.TaxType.PERCENTAGE,
            "tax_group": str(foreign_group.pk),
        },
    )

    assert response.status_code == 302
    assert not Tax.objects.filter(company=company).exists()


@pytest.mark.parametrize(
    ("rate", "tax_type"),
    [
        ("1.23456", Tax.TaxType.PERCENTAGE),
        ("100.0001", Tax.TaxType.PERCENTAGE),
        ("10.0000", "invalid"),
    ],
)
def test_tax_rejects_invalid_decimal_or_choice_without_writing(
    company_admin_client, rate, tax_type
):
    client, company = company_admin_client
    response = client.post(
        reverse("company:tax_create"),
        {"name": "Invalid tax", "rate": rate, "tax_type": tax_type},
    )

    assert response.status_code == 302
    assert not Tax.objects.filter(company=company).exists()


def test_invitation_rejects_invalid_role_without_creating_user(company_admin_client):
    client, _ = company_admin_client

    response = client.post(
        reverse("company:user_invite"),
        {"email": "new-hire@example.com", "role": "super_admin"},
    )

    assert response.status_code == 302
    assert not User.objects.filter(email="new-hire@example.com").exists()
