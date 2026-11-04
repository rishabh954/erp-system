from unittest.mock import patch

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.urls import reverse
from django.views.generic.edit import FormMixin
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.analytics.models import SavedReport
from apps.authentication.models import ModulePermission, UserCompany
from apps.company.models import Company
from apps.crm.models import Campaign, Customer
from apps.crm.views import LeadCreateView
from apps.dashboard.views import SalesDashboardAPIView
from apps.projects.models import Project
from apps.projects.views import ProjectListView
from apps.workflow.api.urls import WorkflowInstanceViewSet
from apps.workflow.models import WorkflowDefinition, WorkflowInstance
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


def _set_role_permission(role, module, **permissions):
    permission, _ = ModulePermission.objects.get_or_create(
        role=role, module=module
    )
    for action, allowed in permissions.items():
        setattr(permission, f"can_{action}", allowed)
    permission.save()


def test_sales_dashboard_uses_active_company_and_does_not_share_cached_responses():
    company_a = CompanyFactory(name="Dashboard Tenant A")
    company_b = CompanyFactory(name="Dashboard Tenant B")
    user = UserFactory(
        primary_company=company_a,
        role="company_admin",
    )
    UserCompany.objects.create(
        user=user, company=company_a, role="employee", is_active=True
    )
    UserCompany.objects.create(
        user=user, company=company_b, role="company_admin", is_active=True
    )
    _set_role_permission("employee", "dashboard", read=True)
    _set_role_permission("company_admin", "dashboard", read=True)
    Customer.objects.create(company=company_a, name="Tenant A Customer")
    Customer.objects.create(company=company_b, name="Tenant B Customer 1")
    Customer.objects.create(company=company_b, name="Tenant B Customer 2")

    factory = APIRequestFactory()
    view = SalesDashboardAPIView.as_view()

    def get_dashboard(company):
        request = factory.get(
            "/dashboard/sales/",
            HTTP_X_ACTIVE_COMPANY=str(company.pk),
        )
        force_authenticate(request, user=user)
        return view(request)

    response_b = get_dashboard(company_b)
    response_a = get_dashboard(company_a)

    assert response_b.status_code == 200
    assert response_b.data["kpis"]["total_customers"] == 2
    assert response_a.status_code == 200
    assert response_a.data["kpis"]["total_customers"] == 1


def test_workflow_api_only_lists_and_retrieves_active_company_instances(user, company):
    foreign_company = CompanyFactory(name="Workflow Foreign Tenant")
    local_definition = WorkflowDefinition.objects.create(
        company=company, name="Local Workflow", trigger_model="Customer"
    )
    foreign_definition = WorkflowDefinition.objects.create(
        company=foreign_company, name="Foreign Workflow", trigger_model="Customer"
    )
    content_type = ContentType.objects.get_for_model(Company)
    local_instance = WorkflowInstance.objects.create(
        company=company,
        definition=local_definition,
        content_type=content_type,
        object_id=str(company.pk),
        initiated_by=user,
    )
    foreign_instance = WorkflowInstance.objects.create(
        company=foreign_company,
        definition=foreign_definition,
        content_type=content_type,
        object_id=str(foreign_company.pk),
        initiated_by=user,
    )
    _set_role_permission(user.Role.COMPANY_ADMIN, "workflow", read=True)

    factory = APIRequestFactory()
    list_request = factory.get(
        "/workflow/instances/",
        HTTP_X_ACTIVE_COMPANY=str(company.pk),
    )
    force_authenticate(list_request, user=user)
    list_response = WorkflowInstanceViewSet.as_view({"get": "list"})(list_request)

    detail_request = factory.get(
        f"/workflow/instances/{foreign_instance.pk}/",
        HTTP_X_ACTIVE_COMPANY=str(company.pk),
    )
    force_authenticate(detail_request, user=user)
    detail_response = WorkflowInstanceViewSet.as_view({"get": "retrieve"})(
        detail_request, pk=foreign_instance.pk
    )

    assert list_response.status_code == 200
    instances = list_response.data.get("results", list_response.data)
    assert {item["id"] for item in instances} == {str(local_instance.pk)}
    assert detail_response.status_code == 404


def test_read_only_analytics_role_cannot_use_either_export_endpoint(
    client, company
):
    user = UserFactory(primary_company=company, role="company_admin")
    UserCompany.objects.create(
        user=user, company=company, role="employee", is_active=True
    )
    _set_role_permission("employee", "analytics", read=True, export=False)
    report = SavedReport.objects.create(
        name="Private export",
        module=SavedReport.Module.INVOICES,
        columns=["number"],
        created_by=user,
        company=company,
    )
    client.force_login(user)

    saved_report_response = client.get(
        reverse(
            "analytics:report_export",
            kwargs={"pk": report.pk, "fmt": "csv"},
        )
    )
    quick_export_response = client.get(
        reverse("analytics:quick_export", kwargs={"fmt": "csv"})
    )

    assert saved_report_response.status_code == 403
    assert quick_export_response.status_code == 403

    permission = ModulePermission.objects.get(role="employee", module="analytics")
    permission.can_export = True
    permission.save(update_fields=["can_export"])
    assert (
        client.get(
            reverse(
                "analytics:report_export",
                kwargs={"pk": report.pk, "fmt": "csv"},
            )
        ).status_code
        == 200
    )
    assert (
        client.get(reverse("analytics:quick_export", kwargs={"fmt": "csv"})).status_code
        == 200
    )


def test_global_admin_role_does_not_grant_project_visibility_in_employee_company(
    company,
):
    user = UserFactory(primary_company=company, role="company_admin")
    UserCompany.objects.create(
        user=user, company=company, role="employee", is_active=True
    )
    project = Project.objects.create(company=company, name="Unassigned project")
    request = RequestFactory().get("/")
    request.user = user
    request.company = company

    view = ProjectListView()
    view.request = request

    assert not view.get_queryset().filter(pk=project.pk).exists()


def test_lead_form_choices_use_active_company_instead_of_primary_company():
    primary_company = CompanyFactory(name="Lead Form Primary Tenant")
    active_company = CompanyFactory(name="Lead Form Active Tenant")
    user = UserFactory(
        primary_company=primary_company,
        role="company_admin",
    )
    UserCompany.objects.create(
        user=user, company=primary_company, role="company_admin", is_active=True
    )
    UserCompany.objects.create(
        user=user, company=active_company, role="company_admin", is_active=True
    )
    sales_user_primary = UserFactory(
        primary_company=primary_company,
        role="employee",
    )
    UserCompany.objects.create(
        user=sales_user_primary,
        company=primary_company,
        role="employee",
        is_active=True,
    )
    sales_user_active = UserFactory(
        primary_company=active_company,
        role="employee",
    )
    UserCompany.objects.create(
        user=sales_user_active,
        company=active_company,
        role="employee",
        is_active=True,
    )
    primary_campaign = Campaign.objects.create(
        company=primary_company, name="Primary campaign"
    )
    active_campaign = Campaign.objects.create(
        company=active_company, name="Active campaign"
    )

    view = LeadCreateView()
    view.request = RequestFactory().get("/")
    view.request.user = user
    view.request.company = active_company

    with patch.object(FormMixin, "get_context_data", return_value={}):
        context = view.get_context_data()

    assert {sales_user.pk for sales_user in context["sales_users"]} == {
        user.pk,
        sales_user_active.pk,
    }
    assert list(context["campaigns"]) == [active_campaign]
    assert primary_campaign not in context["campaigns"]
