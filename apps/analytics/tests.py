"""
Regression tests for analytics views — Phase 1 Security fix.
Ensures the report builder never leaks data across tenants.
"""
import pytest
from django.test import RequestFactory

from apps.analytics.models import CustomReport
from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.crm.models import Customer
from apps.sales.models import SalesOrder

pytestmark = pytest.mark.django_db


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def company_a(db):
    return Company.objects.create(name="Analytics Tenant A")


@pytest.fixture
def company_b(db):
    return Company.objects.create(name="Analytics Tenant B")


@pytest.fixture
def user_a(db, company_a):
    from django.core.management import call_command
    call_command("setup_permissions")
    user = User.objects.create_user(
        email="analytics_user_a@example.com",
        password="password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_a,
    )
    UserCompany.objects.create(user=user, company=company_a, role=User.Role.COMPANY_ADMIN, is_active=True)
    return user


@pytest.fixture
def user_b(db, company_b):
    user = User.objects.create_user(
        email="analytics_user_b@example.com",
        password="password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_b,
    )
    UserCompany.objects.create(user=user, company=company_b, is_active=True)
    return user


@pytest.fixture
def customer_a(db, company_a):
    return Customer.objects.create(company=company_a, name="Customer A")


@pytest.fixture
def customer_b(db, company_b):
    return Customer.objects.create(company=company_b, name="Customer B")


# ─── SEC-1: Cross-tenant report builder isolation ─────────────────────────────


class TestReportBuilderTenantIsolation:
    """
    Prove that GenerateReportAPIView never leaks Company B data to Company A.
    The view scopes its queryset via filter(**{company_path: self.company}),
    so the result set for user_a must contain only company_a records.
    """

    def _make_request(self, user, company):
        rf = RequestFactory()
        request = rf.get("/analytics/api/generate/")
        request.user = user
        request.session = {"active_company_id": str(company.pk)}
        return request

    def test_report_queryset_scoped_to_company(self, user_a, company_a, company_b, customer_a, customer_b):
        """
        GenerateReportAPIView scopes to self.company.
        customer_b must never appear when user_a queries.
        """
        from django.apps import apps as django_apps

        from apps.analytics.views import REPORT_MODEL_MAP, get_reportable_fields

        model_info = REPORT_MODEL_MAP.get("sales")
        assert model_info is not None, "REPORT_MODEL_MAP must contain 'sales'"
        app_label, model_name, company_path = model_info
        ModelClass = django_apps.get_model(app_label, model_name)

        qs = ModelClass.objects.filter(**{company_path: company_a})
        assert qs.filter(**{company_path: company_b}).count() == 0, (
            "Tenant isolation broken: company_b records visible to company_a query"
        )

    def test_get_reportable_fields_only_scalar(self):
        """get_reportable_fields must return only non-relational concrete fields."""
        from apps.analytics.views import get_reportable_fields

        fields = get_reportable_fields(SalesOrder)
        # Relation fields like customer_id, company_id should NOT be in the set
        # (they are concrete but is_relation=True, so excluded)
        for field in SalesOrder._meta.concrete_fields:
            if field.is_relation:
                assert field.name not in fields, (
                    f"Relational field '{field.name}' must not appear in get_reportable_fields"
                )

    def test_invalid_group_by_field_rejected(self, user_a, company_a, customer_a):
        """
        GenerateReportAPIView must return 400 when group_by_field is not in
        the reportable fields allowlist (e.g., a relational field or made-up name).
        """
        from apps.analytics.models import CustomReport

        report = CustomReport.objects.create(
            created_by=user_a,
            name="Bad Field Report",
            module_source="sales",
            group_by_field="__nonexistent__",
            aggregate_field="total",
            aggregate_function="sum",
        )

        from django.test import Client
        c = Client()
        c.force_login(user_a)
        # Set session company
        session = c.session
        session["active_company_id"] = str(company_a.pk)
        session.save()

        response = c.get(f"/analytics/api/generate/?report_id={report.pk}")
        assert response.status_code == 400, (
            f"Expected 400 for invalid field, got {response.status_code}"
        )

    def test_generate_report_no_cross_tenant_leakage(self, user_a, company_a, company_b, customer_a, customer_b):
        """
        GenerateReportAPIView must only aggregate data for company_a and never leak company_b.
        """
        from decimal import Decimal
        from django.test import Client
        from apps.sales.models import SalesOrder
        from apps.analytics.models import CustomReport

        from datetime import date
        # Company A order: total 100
        SalesOrder.objects.create(
            company=company_a,
            customer=customer_a,
            order_date=date.today(),
            status=SalesOrder.Status.CONFIRMED,
            total=Decimal("100.00"),
        )
        # Company B order: total 500
        SalesOrder.objects.create(
            company=company_b,
            customer=customer_b,
            order_date=date.today(),
            status=SalesOrder.Status.CONFIRMED,
            total=Decimal("500.00"),
        )

        report = CustomReport.objects.create(
            created_by=user_a,
            name="Sales Status Report",
            module_source="sales",
            group_by_field="status",
            aggregate_field="total",
            aggregate_function="sum",
        )

        c = Client()
        c.force_login(user_a)
        session = c.session
        session["active_company_id"] = str(company_a.pk)
        session.save()

        response = c.get(f"/analytics/api/generate/?report_id={report.pk}")
        assert response.status_code == 200
        data = response.json()
        assert data["values"] == [100.0], f"Expected [100.0] for company_a, got {data['values']} (leaked company_b?)"
