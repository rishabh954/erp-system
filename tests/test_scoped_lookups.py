from unittest.mock import Mock, patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.http import Http404
from django.test import RequestFactory

from apps.analytics.models import (
    CustomReport,
    SavedReport,
    ScheduledReport,
)
from apps.analytics.views import GenerateReportAPIView, ReportsMixin
from apps.authentication.models import UserCompany
from apps.company.models import Company
from apps.helpdesk.models import TicketCategory
from apps.helpdesk.views import TicketCreateView
from apps.hrms.models import SalaryStructure
from apps.hrms.views import EmployeeSalaryCreateView
from apps.workflow.engine import WorkflowEngine
from apps.workflow.models import WorkflowAction, WorkflowDefinition, WorkflowInstance
from apps.workflow.views import WorkflowActionAPIView
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


def request_for(user, company, method="get", path="/", data=None):
    factory = RequestFactory()
    request = getattr(factory, method)(path, data=data or {})
    request.user = user
    request.company = company
    return request


def test_saved_and_scheduled_reports_are_scoped_to_active_company_and_owner(
    user, company
):
    other_company = CompanyFactory()
    other_user = UserFactory(primary_company=company)
    UserCompany.objects.create(user=other_user, company=company)
    UserCompany.objects.create(user=user, company=other_company)

    owned = SavedReport.objects.create(
        name="Owned",
        module=SavedReport.Module.INVOICES,
        created_by=user,
        company=company,
    )
    public = SavedReport.objects.create(
        name="Public",
        module=SavedReport.Module.INVOICES,
        created_by=other_user,
        company=company,
        is_public=True,
    )
    SavedReport.objects.create(
        name="Foreign public",
        module=SavedReport.Module.INVOICES,
        created_by=user,
        company=other_company,
        is_public=True,
    )
    legacy_personal = SavedReport.objects.create(
        name="Legacy personal",
        module=SavedReport.Module.INVOICES,
        created_by=user,
    )
    ScheduledReport.objects.create(
        report=owned,
        frequency=ScheduledReport.Frequency.DAILY,
        recipients="owner@example.test",
        created_by=user,
    )
    ScheduledReport.objects.create(
        report=public,
        frequency=ScheduledReport.Frequency.DAILY,
        recipients="owner@example.test",
        created_by=user,
    )

    view = ReportsMixin()
    view.request = request_for(user, company)
    report_ids = set(view.get_saved_reports().values_list("pk", flat=True))
    assert report_ids == {owned.pk, public.pk, legacy_personal.pk}
    assert set(view.get_scheduled_reports().values_list("report_id", flat=True)) == {
        owned.pk,
        public.pk,
    }


def test_custom_report_lookup_is_limited_to_its_owner(user, company):
    other = UserFactory(primary_company=CompanyFactory())
    report = CustomReport.objects.create(
        name="Private",
        module_source="sales",
        group_by_field="status",
        aggregate_field="id",
        created_by=other,
    )
    request = request_for(
        user, company, path=f"/analytics/api/generate/?report_id={report.pk}"
    )

    with pytest.raises(Http404):
        GenerateReportAPIView().get(request)


def test_workflow_action_cannot_load_another_company_instance(user, company):
    other_company = CompanyFactory()
    definition = WorkflowDefinition.objects.create(
        company=other_company, name="Other", trigger_model="Lead"
    )
    instance = WorkflowInstance.objects.create(
        company=other_company,
        definition=definition,
        content_type=ContentType.objects.get_for_model(Company),
        object_id=str(other_company.pk),
        initiated_by=user,
    )
    request = request_for(
        user,
        company,
        method="post",
        path=f"/workflow/actions/{instance.pk}/",
        data={"action": "approve"},
    )
    request._messages = Mock()

    response = WorkflowActionAPIView().post(request, instance_id=instance.pk)

    assert response.status_code == 302
    assert not WorkflowAction.objects.filter(instance=instance).exists()


def test_workflow_delegatee_must_belong_to_instance_company(user, company):
    foreign_company = CompanyFactory()
    foreign_user = UserFactory(primary_company=foreign_company)
    UserCompany.objects.create(user=foreign_user, company=foreign_company)
    definition = WorkflowDefinition.objects.create(
        company=company, name="Local", trigger_model="Lead"
    )
    instance = WorkflowInstance.objects.create(
        company=company,
        definition=definition,
        content_type=ContentType.objects.get_for_model(Company),
        object_id=str(company.pk),
        initiated_by=user,
    )
    request = request_for(
        user,
        company,
        method="post",
        path=f"/workflow/actions/{instance.pk}/",
        data={"action": "delegate", "delegatee_id": str(foreign_user.pk)},
    )
    request._messages = Mock()

    with (
        patch.object(WorkflowEngine, "get_pending_approvers", return_value=[user]),
        patch.object(WorkflowEngine, "delegate") as delegate,
    ):
        response = WorkflowActionAPIView().post(request, instance_id=instance.pk)

    assert response.status_code == 302
    delegate.assert_not_called()


def test_helpdesk_rejects_ticket_category_from_another_company(user, company):
    foreign_company = CompanyFactory()
    category = TicketCategory.objects.create(
        company=foreign_company, name="Foreign category"
    )
    request = request_for(
        user,
        company,
        method="post",
        path="/helpdesk/tickets/create/",
        data={
            "title": "Ticket",
            "description": "Description",
            "category": str(category.pk),
        },
    )

    view = TicketCreateView()
    view.setup(request)
    with pytest.raises(Http404):
        view.post(request)


def test_salary_assignment_rejects_foreign_salary_structure(
    user, company, employee, currency
):
    foreign_company = CompanyFactory()
    structure = SalaryStructure.objects.create(
        company=foreign_company, name="Foreign salary"
    )
    request = request_for(
        user,
        company,
        method="post",
        path=f"/hrms/employees/{employee.pk}/salary/",
        data={
            "salary_structure": str(structure.pk),
            "currency": str(currency.pk),
            "basic_salary": "1000.00",
            "effective_from": "2026-01-01",
        },
    )

    view = EmployeeSalaryCreateView()
    view.setup(request)
    with pytest.raises(Http404):
        view.post(request, pk=employee.pk)


def test_saved_report_company_is_a_company_foreign_key():
    assert SavedReport._meta.get_field("company").remote_field.model is Company
