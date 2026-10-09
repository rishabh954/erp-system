import pytest
from django.urls import reverse

from apps.administration.models import SystemSetting
from apps.authentication.models import ModulePermission, User, UserCompany
from apps.company.models import Company
from core.factories import UserFactory

pytestmark = pytest.mark.django_db


def _set_admin_permissions(role, **permissions):
    defaults = {
        "can_read": True,
        "can_create": False,
        "can_update": False,
        "can_delete": False,
        "can_approve": False,
    }
    defaults.update(permissions)
    return ModulePermission.objects.update_or_create(
        role=role, module="administration", defaults=defaults
    )[0]


def test_signup_attaches_user_to_requested_tenant(client, monkeypatch):
    company = Company.objects.create(name="Signup tenant")
    monkeypatch.setattr(
        "apps.authentication.views.AuthService.send_email_verification",
        lambda self, user, request: None,
    )

    response = client.post(
        reverse("auth:register"),
        {
            "first_name": "New",
            "last_name": "Member",
            "email": "new-member@example.com",
            "password1": "ValidPassword123!",
            "password2": "ValidPassword123!",
            "tenant_slug": company.slug,
        },
    )

    assert response.status_code == 302
    user = User.objects.get(email="new-member@example.com")
    membership = UserCompany.objects.get(user=user, company=company)
    assert user.is_active is False
    assert user.primary_company == company
    assert membership.role == User.Role.EMPLOYEE
    assert membership.is_active is False


def test_signup_rejects_unknown_tenant_slug(client):
    response = client.post(
        reverse("auth:register"),
        {
            "first_name": "New",
            "last_name": "Member",
            "email": "unknown-tenant@example.com",
            "password1": "ValidPassword123!",
            "password2": "ValidPassword123!",
            "tenant_slug": "not-a-company",
        },
    )

    assert response.status_code == 200
    assert not User.objects.filter(email="unknown-tenant@example.com").exists()


def test_admin_post_requires_write_permission(client, user, company):
    setting = SystemSetting.objects.create(
        company=company, key="company_name", value="Original"
    )
    _set_admin_permissions(
        User.Role.COMPANY_ADMIN, can_read=True, can_update=False
    )
    client.force_login(user)

    denied = client.post(
        reverse("administration:system_settings"),
        {"action": "update", "setting_company_name": "Changed"},
    )
    setting.refresh_from_db()
    assert denied.status_code in (302, 403)
    assert setting.value == "Original"

    _set_admin_permissions(User.Role.COMPANY_ADMIN, can_read=True, can_update=True)
    allowed = client.post(
        reverse("administration:system_settings"),
        {"action": "update", "setting_company_name": "Changed"},
    )
    setting.refresh_from_db()
    assert allowed.status_code == 302
    assert setting.value == "Changed"


def test_approval_activates_tenant_membership_and_rejection_retains_user(
    client, user, company
):
    _set_admin_permissions(
        User.Role.COMPANY_ADMIN,
        can_read=True,
        can_approve=True,
        can_delete=True,
    )
    pending_user = UserFactory(
        email="pending@example.com", primary_company=company, is_active=False
    )
    membership = UserCompany.objects.create(
        user=pending_user,
        company=company,
        role=User.Role.EMPLOYEE,
        is_active=False,
    )
    rejected_user = UserFactory(
        email="rejected@example.com", primary_company=company, is_active=False
    )
    UserCompany.objects.create(
        user=rejected_user,
        company=company,
        role=User.Role.EMPLOYEE,
        is_active=False,
    )
    client.force_login(user)

    approve = client.post(
        reverse("administration:pending_approvals_action", kwargs={"pk": pending_user.pk}),
        {"action": "approve"},
    )
    reject = client.post(
        reverse(
            "administration:pending_approvals_action", kwargs={"pk": rejected_user.pk}
        ),
        {"action": "reject"},
    )

    pending_user.refresh_from_db()
    membership.refresh_from_db()
    rejected_user.refresh_from_db()
    assert approve.status_code == 302
    assert pending_user.is_active is True
    assert membership.is_active is True
    assert reject.status_code == 302
    assert User.objects.filter(pk=rejected_user.pk).exists()
    assert rejected_user.is_active is False
    assert rejected_user.is_rejected is True
    pending_response = client.get(reverse("administration:pending_approvals"))
    assert rejected_user not in pending_response.context["pending_users"]
