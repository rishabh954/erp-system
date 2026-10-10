import json
from datetime import date

import pytest
from django.test import RequestFactory

from apps.analytics.models import CustomReport
from apps.analytics.views import GenerateReportAPIView
from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.crm.models import Customer
from apps.sales.models import SalesOrder

pytestmark = pytest.mark.django_db


def test_report_builder_scopes_rows_to_active_company():
    company_a = Company.objects.create(name="Report Tenant A")
    company_b = Company.objects.create(name="Report Tenant B")
    user = User.objects.create_user(
        email="report-tenant-a@example.com",
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
    customer_a = Customer.objects.create(company=company_a, name="Report Customer A")
    customer_b = Customer.objects.create(company=company_b, name="Report Customer B")
    SalesOrder.objects.create(
        company=company_a,
        customer=customer_a,
        order_date=date.today(),
        status=SalesOrder.Status.CONFIRMED,
        total=125,
    )
    SalesOrder.objects.create(
        company=company_b,
        customer=customer_b,
        order_date=date.today(),
        status=SalesOrder.Status.DRAFT,
        total=900,
    )
    report = CustomReport.objects.create(
        name="Tenant-scoped sales",
        module_source="sales",
        chart_type="bar",
        group_by_field="status",
        aggregate_field="total",
        aggregate_function="sum",
        created_by=user,
    )

    request = RequestFactory().get(
        "/analytics/generate/", {"report_id": str(report.pk)}
    )
    request.user = user
    request.session = {}
    response = GenerateReportAPIView.as_view()(request)

    assert response.status_code == 200
    assert json.loads(response.content) == {
        "labels": [SalesOrder.Status.CONFIRMED],
        "values": [125.0],
        "chart_type": report.chart_type,
        "name": report.name,
    }


def test_report_builder_rejects_relational_or_nonexistent_fields():
    company = Company.objects.create(name="Report Validation Tenant")
    user = User.objects.create_user(
        email="report-validation@example.com",
        password="test-password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    report = CustomReport.objects.create(
        name="Invalid report",
        module_source="sales",
        chart_type="bar",
        group_by_field="customer__name",
        aggregate_field="total",
        aggregate_function="sum",
        created_by=user,
    )
    request = RequestFactory().get(
        "/analytics/generate/", {"report_id": str(report.pk)}
    )
    request.user = user
    request.session = {}

    response = GenerateReportAPIView.as_view()(request)

    assert response.status_code == 400
