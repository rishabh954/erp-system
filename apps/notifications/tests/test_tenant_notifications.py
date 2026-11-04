import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authentication.models import ModulePermission, User, UserCompany
from apps.company.models import Company
from apps.notifications.models import Notification, NotificationPreference
from apps.notifications.services import NotificationService
from core.restore_context import restoring

pytestmark = pytest.mark.django_db


def make_multitenant_admin():
    company_a = Company.objects.create(name="Notification Primary")
    company_b = Company.objects.create(name="Notification Active")
    user = User.objects.create_user(
        email="notification-admin@example.com",
        password="test-password",
        first_name="Notify",
        last_name="Admin",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_a,
    )
    UserCompany.objects.create(
        user=user, company=company_a, role=User.Role.COMPANY_ADMIN, is_active=True
    )
    UserCompany.objects.create(
        user=user, company=company_b, role=User.Role.COMPANY_ADMIN, is_active=True
    )
    permission, _ = ModulePermission.objects.get_or_create(
        role=User.Role.COMPANY_ADMIN, module="notifications"
    )
    permission.can_read = True
    permission.can_update = True
    permission.save(update_fields=["can_read", "can_update"])
    return user, company_a, company_b


def activate_company(client, company):
    session = client.session
    session["active_company_id"] = str(company.pk)
    session.save()


def test_notification_api_list_and_counts_use_active_company():
    user, company_a, company_b = make_multitenant_admin()
    Notification.objects.create(
        company=company_a, recipient=user, title="Primary", message="A"
    )
    Notification.objects.create(
        company=company_b, recipient=user, title="Active", message="B"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(
        reverse("api_notifications:notification-list"),
        HTTP_X_ACTIVE_COMPANY=str(company_b.pk),
    )
    assert response.status_code == 200
    assert [item["title"] for item in response.data["results"]] == ["Active"]

    count = client.get(
        reverse("api_notifications:notification-unread-count"),
        HTTP_X_ACTIVE_COMPANY=str(company_b.pk),
    )
    assert count.status_code == 200
    assert count.data["count"] == 1


def test_notification_api_mark_all_read_only_changes_active_company():
    user, company_a, company_b = make_multitenant_admin()
    primary_notification = Notification.objects.create(
        company=company_a, recipient=user, title="Primary", message="A"
    )
    active_notification = Notification.objects.create(
        company=company_b, recipient=user, title="Active", message="B"
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        reverse("api_notifications:notification-mark-all-read"),
        HTTP_X_ACTIVE_COMPANY=str(company_b.pk),
    )

    assert response.status_code == 200
    primary_notification.refresh_from_db()
    active_notification.refresh_from_db()
    assert primary_notification.is_read is False
    assert active_notification.is_read is True


def test_notification_api_mark_all_read_requires_update_permission():
    user, company_a, company_b = make_multitenant_admin()
    permission = ModulePermission.objects.get(
        role=User.Role.COMPANY_ADMIN, module="notifications"
    )
    permission.can_create = True
    permission.can_update = False
    permission.save(update_fields=["can_create", "can_update"])
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        reverse("api_notifications:notification-mark-all-read"),
        HTTP_X_ACTIVE_COMPANY=str(company_b.pk),
    )

    assert response.status_code == 403


def test_mark_read_cannot_change_notification_from_another_company(client):
    user, company_a, company_b = make_multitenant_admin()
    notification = Notification.objects.create(
        company=company_a, recipient=user, title="Private A", message="A"
    )
    client.force_login(user)
    activate_company(client, company_b)

    response = client.post(reverse("notifications:mark_read", args=[notification.pk]))
    assert response.status_code == 404
    notification.refresh_from_db()
    assert not notification.is_read


def test_notification_preferences_are_separate_per_active_company(client):
    user, company_a, company_b = make_multitenant_admin()
    NotificationPreference.objects.create(
        company=company_a,
        user=user,
        notification_type=Notification.NotificationType.INFO,
        email_enabled=False,
    )
    client.force_login(user)
    activate_company(client, company_b)

    response = client.get(reverse("notifications:preferences"))
    assert response.status_code == 200
    assert set(response.context["preferences"].values_list("company_id", flat=True)) == {company_b.pk}
    assert NotificationPreference.objects.filter(user=user, company=company_b).exists()


def test_notification_preference_update_only_changes_active_company(client):
    user, company_a, company_b = make_multitenant_admin()
    primary_preference = NotificationPreference.objects.create(
        company=company_a,
        user=user,
        notification_type=Notification.NotificationType.INFO,
        email_enabled=True,
    )
    client.force_login(user)
    activate_company(client, company_b)
    response = client.get(reverse("notifications:preferences"))
    active_preference = response.context["preferences"].get(
        notification_type=Notification.NotificationType.INFO
    )

    response = client.post(
        reverse("notifications:preferences"),
        {f"email_{active_preference.pk}": "on"},
    )

    assert response.status_code == 200
    primary_preference.refresh_from_db()
    active_preference.refresh_from_db()
    assert primary_preference.email_enabled is True
    assert active_preference.email_enabled is True


def test_notification_preferences_reject_non_checkbox_values_without_writing(client):
    user, _, company = make_multitenant_admin()
    preference = NotificationPreference.objects.create(
        company=company,
        user=user,
        notification_type=Notification.NotificationType.INFO,
        email_enabled=False,
    )
    client.force_login(user)
    activate_company(client, company)

    response = client.post(
        reverse("notifications:preferences"),
        {f"email_{preference.pk}": "true"},
    )

    preference.refresh_from_db()
    assert response.status_code == 302
    assert preference.email_enabled is False
    assert NotificationPreference.objects.filter(user=user, company=company).count() == 1


def test_notification_preferences_reject_foreign_tenant_row_without_writing(client):
    user, company_a, company_b = make_multitenant_admin()
    foreign_preference = NotificationPreference.objects.create(
        company=company_a,
        user=user,
        notification_type=Notification.NotificationType.INFO,
        email_enabled=False,
    )
    client.force_login(user)
    activate_company(client, company_b)

    response = client.post(
        reverse("notifications:preferences"),
        {f"email_{foreign_preference.pk}": "on"},
    )

    foreign_preference.refresh_from_db()
    assert response.status_code == 302
    assert foreign_preference.email_enabled is False
    assert not NotificationPreference.objects.filter(user=user, company=company_b).exists()


def test_bulk_task_drops_recipients_without_active_company_membership(monkeypatch):
    user, company_a, company_b = make_multitenant_admin()
    outsider = User.objects.create_user(
        email="notification-outsider@example.com",
        password="test-password",
        first_name="Other",
        last_name="Tenant",
    )
    from apps.notifications.tasks import send_bulk_notification

    recipients = []

    def capture(**kwargs):
        recipients.extend(kwargs["recipients"])
        return []

    monkeypatch.setattr("apps.notifications.services.NotificationService.send_bulk", capture)
    send_bulk_notification.run(
        recipient_ids=[user.pk, outsider.pk],
        title="Scoped",
        message="Only members",
        company_id=str(company_b.pk),
    )
    assert recipients == [user]


def test_notification_service_rejects_recipient_outside_company():
    user, company_a, company_b = make_multitenant_admin()
    outsider = User.objects.create_user(
        email="notification-outsider-direct@example.com",
        password="test-password",
        first_name="Other",
        last_name="Tenant",
    )

    created = NotificationService.send(
        recipient=outsider,
        title="Scoped",
        message="Should not cross tenants",
        channels=["in_app"],
        company=company_b,
    )

    assert created == []
    assert not Notification.objects.filter(company=company_b, recipient=outsider).exists()


def test_push_channel_respects_disabled_preference():
    user, company_a, company_b = make_multitenant_admin()
    NotificationPreference.objects.create(
        company=company_b,
        user=user,
        notification_type=Notification.NotificationType.INFO,
        push_enabled=False,
    )

    created = NotificationService.send(
        recipient=user,
        title="No push",
        message="Preference disabled",
        channels=["push"],
        company=company_b,
    )

    assert created == []
    assert not Notification.objects.filter(company=company_b, recipient=user).exists()


def test_sms_and_whatsapp_helpers_do_not_write_during_restore():
    user, company_a, company_b = make_multitenant_admin()

    with restoring():
        sms_log = NotificationService.send_sms(
            user, "Do not send", company=company_b
        )
        whatsapp_log = NotificationService.send_whatsapp(
            user, "template", company=company_b
        )

    assert sms_log is None
    assert whatsapp_log is None
