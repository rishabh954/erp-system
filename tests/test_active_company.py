from unittest.mock import Mock

import pytest
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.request import Request

from apps.authentication.models import ModulePermission, User, UserCompany
from apps.crm.models import Lead
from apps.workflow.engine import WorkflowEngine
from apps.workflow.models import WorkflowDefinition, WorkflowInstance
from core.api.mixins import TenantScopedViewSetMixin
from core.factories import CompanyFactory, UserFactory
from core.tenancy import get_active_company

pytestmark = pytest.mark.django_db


def drf_request(path="/", user=None, **headers):
    request = RequestFactory().get(path, **headers)
    request.user = user
    wrapped = Request(request)
    wrapped._user = user
    return wrapped


def test_active_company_uses_session_and_validates_membership():
    company_a = CompanyFactory()
    company_b = CompanyFactory()
    user = UserFactory(primary_company=company_a)
    UserCompany.objects.create(user=user, company=company_a)
    UserCompany.objects.create(user=user, company=company_b)

    request = drf_request(user=user)
    request._request.session = {"active_company_id": str(company_b.pk)}
    assert get_active_company(request) == company_b

    request._request.session = {"active_company_id": str(CompanyFactory().pk)}
    assert get_active_company(request) is None


def test_active_company_resolves_after_drf_authentication():
    company_a = CompanyFactory()
    company_b = CompanyFactory()
    user = UserFactory(primary_company=company_a)
    UserCompany.objects.create(user=user, company=company_a)
    UserCompany.objects.create(user=user, company=company_b)

    request = drf_request(user=user, HTTP_X_ACTIVE_COMPANY=str(company_b.pk))
    assert get_active_company(request) == company_b


def test_permissions_use_role_for_active_company():
    company_a = CompanyFactory()
    company_b = CompanyFactory()
    user = UserFactory(primary_company=company_a, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.create(user=user, company=company_a, role=User.Role.EMPLOYEE)
    UserCompany.objects.create(user=user, company=company_b, role=User.Role.COMPANY_ADMIN)
    employee_permission, _ = ModulePermission.objects.get_or_create(
        role=User.Role.EMPLOYEE, module="crm"
    )
    employee_permission.can_create = False
    employee_permission.save(update_fields=["can_create"])
    admin_permission, _ = ModulePermission.objects.get_or_create(
        role=User.Role.COMPANY_ADMIN, module="crm"
    )
    admin_permission.can_create = True
    admin_permission.save(update_fields=["can_create"])

    assert not user.has_module_permission("crm", "create", company=company_a)
    assert user.has_module_permission("crm", "create", company=company_b)


def test_consolidated_queryset_requires_dedicated_permission():
    class LeadViewSet(TenantScopedViewSetMixin, GenericAPIView):
        queryset = Lead.objects.all()
        required_permission = "crm.read"

    parent = CompanyFactory()
    child = CompanyFactory(parent=parent)
    user = UserFactory(primary_company=parent)
    UserCompany.objects.create(user=user, company=parent, role=User.Role.EMPLOYEE)
    Lead.objects.create(company=parent, name="Parent lead")
    Lead.objects.create(company=child, name="Child lead")

    view = LeadViewSet()
    view.request = drf_request(
        "/?consolidated=true", user, HTTP_X_ACTIVE_COMPANY=str(parent.pk)
    )
    with pytest.raises(PermissionDenied):
        view.get_queryset()

    permission, _ = ModulePermission.objects.get_or_create(
        role=User.Role.EMPLOYEE, module="crm"
    )
    permission.can_consolidate = True
    permission.save(update_fields=["can_consolidate"])
    view.request = drf_request(
        "/?consolidated=true", user, HTTP_X_ACTIVE_COMPANY=str(parent.pk)
    )
    assert set(view.get_queryset().values_list("company_id", flat=True)) == {
        parent.pk,
        child.pk,
    }


def test_tenant_scoped_create_uses_validated_active_company():
    company = CompanyFactory()
    user = UserFactory(primary_company=company)
    UserCompany.objects.create(user=user, company=company)
    view = TenantScopedViewSetMixin()
    view.request = drf_request(user=user)
    serializer = Mock()
    serializer.Meta.model = Lead

    view.perform_create(serializer)

    serializer.save.assert_called_once_with(company=company)


def test_workflow_admin_override_uses_company_membership_role():
    company = CompanyFactory()
    other_company = CompanyFactory()
    user = UserFactory(primary_company=other_company, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.create(user=user, company=company, role=User.Role.EMPLOYEE)
    UserCompany.objects.create(
        user=user, company=other_company, role=User.Role.COMPANY_ADMIN
    )
    definition = WorkflowDefinition.objects.create(
        company=company, name="Approval", trigger_model="Lead"
    )
    instance = WorkflowInstance.objects.create(
        company=company,
        definition=definition,
        content_type=ContentType.objects.get_for_model(Lead),
        object_id="1",
        initiated_by=user,
        status=WorkflowInstance.Status.PENDING,
    )

    with pytest.raises(PermissionError, match="not authorised"):
        WorkflowEngine.approve(instance, user)


def test_invalid_uuid_active_company_fails_closed():
    company = CompanyFactory()
    user = UserFactory(primary_company=company)
    UserCompany.objects.create(user=user, company=company)

    request = drf_request(user=user, HTTP_X_ACTIVE_COMPANY="not-a-uuid")
    assert get_active_company(request) is None
