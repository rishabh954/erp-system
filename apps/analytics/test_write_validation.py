import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.analytics.models import SavedReport, ScheduledReport
from apps.authentication.models import User, UserCompany
from apps.company.models import Company

pytestmark = pytest.mark.django_db


@pytest.fixture
def analytics_client():
    company = Company.objects.create(name="Analytics Validation Tenant")
    user = User.objects.create_superuser(
        email="analytics-validation@example.com",
        password="test-password",
        first_name="Analytics",
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
    return client, company, user


def test_report_builder_rejects_bad_module_and_fields_without_writing(analytics_client):
    client, company, _ = analytics_client

    response = client.post(
        reverse("analytics:builder"),
        {
            "name": "Bad report",
            "module": "unknown",
            "columns": "status,total",
        },
    )
    assert response.status_code == 302
    assert not SavedReport.objects.filter(company=company).exists()

    response = client.post(
        reverse("analytics:builder"),
        {
            "name": "Bad field report",
            "module": "sales_orders",
            "columns": "status,customer__password",
        },
    )
    assert response.status_code == 302
    assert not SavedReport.objects.filter(company=company).exists()


@pytest.mark.parametrize(
    "filters_json",
    ["not-json", "[]", '{"total": {"gt": 1}}', '{"missing_field": 1}'],
)
def test_report_builder_rejects_bad_filters_without_writing(
    analytics_client, filters_json
):
    client, company, _ = analytics_client
    response = client.post(
        reverse("analytics:builder"),
        {
            "name": "Bad filter report",
            "module": "sales_orders",
            "columns": "status,total",
            "filters_json": filters_json,
        },
    )

    assert response.status_code == 302
    assert not SavedReport.objects.filter(company=company).exists()


def test_report_builder_preserves_omitted_defaults(analytics_client):
    client, company, user = analytics_client
    response = client.post(
        reverse("analytics:builder"),
        {
            "name": "Valid report",
            "module": "sales_orders",
            "columns": "status,total",
        },
    )

    report = SavedReport.objects.get(company=company, created_by=user)
    assert response.status_code == 302
    assert report.filters == {}
    assert report.sort_by == "-created_at"
    assert report.chart_type == SavedReport.ChartType.NONE
    assert report.is_public is False


def test_report_builder_accepts_account_module_choice(analytics_client):
    client, company, user = analytics_client
    response = client.post(
        reverse("analytics:builder"),
        {
            "name": "Accounts report",
            "module": SavedReport.Module.ACCOUNTS,
            "columns": "code,name",
        },
    )

    assert response.status_code == 302
    assert SavedReport.objects.filter(
        company=company, created_by=user, module=SavedReport.Module.ACCOUNTS
    ).exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"frequency": "yearly", "export_format": "pdf", "recipients": "a@example.com"},
        {"frequency": "monthly", "export_format": "exe", "recipients": "a@example.com"},
        {"frequency": "monthly", "export_format": "pdf", "recipients": "not-an-email"},
        {"frequency": "monthly", "export_format": "pdf", "recipients": ""},
    ],
)
def test_schedule_rejects_bad_choice_or_recipient_without_writing(
    analytics_client, payload
):
    client, company, user = analytics_client
    report = SavedReport.objects.create(
        name="Schedule test",
        module=SavedReport.Module.SALES_ORDERS,
        columns=["status", "total"],
        created_by=user,
        company=company,
    )

    response = client.post(
        reverse("analytics:schedule_report", args=[report.pk]), payload
    )

    assert response.status_code == 302
    assert not ScheduledReport.objects.filter(report=report).exists()


def test_schedule_preserves_default_frequency_and_format(analytics_client):
    client, company, user = analytics_client
    report = SavedReport.objects.create(
        name="Default schedule",
        module=SavedReport.Module.SALES_ORDERS,
        columns=["status", "total"],
        created_by=user,
        company=company,
    )

    response = client.post(
        reverse("analytics:schedule_report", args=[report.pk]),
        {"recipients": "reports@example.com"},
    )

    schedule = ScheduledReport.objects.get(report=report)
    assert response.status_code == 302
    assert schedule.frequency == ScheduledReport.Frequency.MONTHLY
    assert schedule.export_format == ScheduledReport.ExportFormat.PDF


def test_export_rejects_invalid_format_without_execution_log(analytics_client):
    client, company, user = analytics_client
    report = SavedReport.objects.create(
        name="Export test",
        module=SavedReport.Module.SALES_ORDERS,
        columns=["status", "total"],
        created_by=user,
        company=company,
    )

    response = client.get(
        reverse("analytics:report_export", args=[report.pk, "unknown"])
    )

    assert response.status_code == 400
    from apps.analytics.models import ReportExecution

    assert not ReportExecution.objects.filter(report=report).exists()


@pytest.mark.parametrize(
    "query",
    [
        {"module": "unknown"},
        {"module": "sales_orders", "columns": "status,total", "limit": "1.5"},
        {"module": "sales_orders", "columns": "status,total", "limit": "10001"},
    ],
)
def test_quick_export_rejects_invalid_query_values(analytics_client, query):
    client, _, _ = analytics_client

    response = client.get(reverse("analytics:quick_export", args=["csv"]), query)

    assert response.status_code == 400


def test_preview_rejects_non_integer_limit_without_saving_report(analytics_client):
    client, company, _ = analytics_client

    response = client.post(
        reverse("analytics:api_preview"),
        data=json.dumps(
            {
                "module": "sales_orders",
                "columns": ["status", "total"],
                "preview_limit": "25",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not SavedReport.objects.filter(company=company).exists()
