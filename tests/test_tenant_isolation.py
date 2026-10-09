from datetime import date

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import ModulePermission, UserCompany
from apps.company.models import Department
from apps.crm.models import Customer, Lead
from apps.hrms.models import Employee
from apps.inventory.models import Product
from apps.projects.models import Project
from apps.purchase.models import PurchaseOrder, Vendor
from apps.sales.models import SalesOrder
from apps.workflow.models import WorkflowAction, WorkflowDefinition, WorkflowInstance
from core.factories import CompanyFactory, UserFactory
from core.tenancy import get_active_company

pytestmark = pytest.mark.django_db


def _add_membership(user, company, role):
    return UserCompany.objects.create(
        user=user, company=company, role=role, is_active=True
    )


def test_foreign_tenant_records_cannot_be_read_updated_deleted_or_approved(
    client, user, company
):
    company_a = company
    company_b = CompanyFactory(name="Tenant Isolation B")
    user_a = user
    user_a.role = user_a.Role.COMPANY_ADMIN
    user_a.save(update_fields=["role"])
    UserCompany.objects.update_or_create(
        user=user_a,
        company=company_a,
        defaults={"role": user_a.Role.COMPANY_ADMIN, "is_active": True},
    )
    user_b = UserFactory(primary_company=company_b, role=user_a.Role.COMPANY_ADMIN)
    _add_membership(user_b, company_b, user_b.Role.COMPANY_ADMIN)

    customer = Customer.objects.create(
        company=company_b, name="Foreign Customer", email="foreign@example.test"
    )
    lead = Lead.objects.create(company=company_b, name="Foreign Lead")
    order = SalesOrder.objects.create(
        company=company_b, customer=customer, order_date=date.today()
    )
    vendor = Vendor.objects.create(company=company_b, name="Foreign Vendor")
    purchase_order = PurchaseOrder.objects.create(
        company=company_b,
        vendor=vendor,
        order_date=date.today(),
        expected_delivery=date.today(),
    )
    project = Project.objects.create(company=company_b, name="Foreign Project")
    product = Product.objects.create(
        company=company_b, name="Foreign Product", sku="TENANT-B-001"
    )
    department = Department.objects.create(
        company=company_b, name="Foreign Department", code="TB"
    )
    employee = Employee.objects.create(
        company=company_b,
        user=user_b,
        department=department,
        employee_id="TENANT-B-EMP",
        first_name="Foreign",
        last_name="Employee",
        joining_date=date.today(),
    )

    client.force_login(user_a)
    detail_urls = (
        reverse("crm:customer_detail", kwargs={"pk": customer.pk}),
        reverse("crm:lead_detail", kwargs={"pk": lead.pk}),
        reverse("sales:order_detail", kwargs={"pk": order.pk}),
        reverse("purchase:vendor_detail", kwargs={"pk": vendor.pk}),
        reverse("purchase:order_detail", kwargs={"pk": purchase_order.pk}),
        reverse("projects:detail", kwargs={"pk": project.pk}),
        reverse("inventory:product_detail", kwargs={"pk": product.pk}),
        reverse("hrms:employee_detail", kwargs={"pk": employee.pk}),
    )
    for url in detail_urls:
        assert client.get(url).status_code == 404, url

    assert (
        client.post(
            reverse("crm:customer_update", kwargs={"pk": customer.pk}),
            {"name": "Tampered Customer"},
        ).status_code
        == 404
    )
    assert (
        client.post(reverse("crm:customer_delete", kwargs={"pk": customer.pk})).status_code
        == 404
    )

    api_client = APIClient()
    token = RefreshToken.for_user(user_a).access_token
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {token}",
        HTTP_X_ACTIVE_COMPANY=str(company_a.pk),
    )
    customer_list = api_client.get("/api/v1/crm/customers/")
    assert customer_list.status_code == 200
    assert b"Foreign Customer" not in customer_list.content

    customer_detail = f"/api/v1/crm/customers/{customer.pk}/"
    assert api_client.get(customer_detail).status_code == 404
    assert api_client.patch(
        customer_detail, {"name": "Tampered API Customer"}, format="json"
    ).status_code == 404
    assert api_client.delete(customer_detail).status_code == 404

    customer.refresh_from_db()
    assert customer.name == "Foreign Customer"
    assert not customer.is_deleted

    definition = WorkflowDefinition.objects.create(
        company=company_b, name="Foreign Approval", trigger_model="Customer"
    )
    instance = WorkflowInstance.objects.create(
        company=company_b,
        definition=definition,
        content_type=ContentType.objects.get_for_model(Customer),
        object_id=str(customer.pk),
        initiated_by=user_b,
    )
    approve_url = reverse("workflow:action_api", kwargs={"instance_id": instance.pk})
    approval_response = client.post(approve_url, {"action": "approve"})
    assert approval_response.status_code in {302, 403, 404}
    assert not WorkflowAction.objects.filter(instance=instance).exists()
    instance.refresh_from_db()
    assert instance.status != WorkflowInstance.Status.APPROVED


def test_one_user_gets_the_role_for_the_selected_company(company):
    company_a = company
    company_b = CompanyFactory(name="Role Tenant B")
    user = UserFactory(primary_company=company_a)
    _add_membership(user, company_a, user.Role.EMPLOYEE)
    _add_membership(user, company_b, user.Role.COMPANY_ADMIN)

    employee_permission, _ = ModulePermission.objects.get_or_create(
        role=user.Role.EMPLOYEE, module="crm"
    )
    employee_permission.can_read = False
    employee_permission.save(update_fields=["can_read"])
    admin_permission, _ = ModulePermission.objects.get_or_create(
        role=user.Role.COMPANY_ADMIN, module="crm"
    )
    admin_permission.can_read = True
    admin_permission.save(update_fields=["can_read"])

    request_factory = RequestFactory()
    request_a = request_factory.get(
        "/", HTTP_X_ACTIVE_COMPANY=str(company_a.pk)
    )
    request_a.user = user
    request_b = request_factory.get(
        "/", HTTP_X_ACTIVE_COMPANY=str(company_b.pk)
    )
    request_b.user = user

    assert get_active_company(request_a) == company_a
    assert get_active_company(request_b) == company_b
    assert not user.has_module_permission("crm", "read", company=company_a)
    assert user.has_module_permission("crm", "read", company=company_b)
