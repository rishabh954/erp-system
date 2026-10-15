import json
from unittest.mock import patch

import pytest
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse

from apps.administration.models import (
    APIKey,
    BackupRecord,
    EmailConfig,
    Integration,
    WebhookEndpoint,
)
from apps.authentication.models import User, UserCompany
from apps.crm.models import Customer
from apps.purchase.models import Vendor
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_company_backup_contains_only_safe_company_data(company, user, tmp_path):
    from apps.administration.tasks import generate_backup

    other = CompanyFactory(name="Other tenant")
    Customer.objects.create(company=company, name="A Customer", email="a@example.test")
    Customer.objects.create(company=other, name="B Customer", email="b@example.test")
    Vendor.objects.create(company=other, name="B Vendor", email="vendor-b@example.test")
    other_user = UserFactory(
        primary_company=other,
        email="other-user@example.test",
        password="NeverExportThisPassword",
    )
    other_user.totp_secret = "private-totp-secret"
    other_user.save(update_fields=["totp_secret"])
    EmailConfig.objects.create(
        company=company,
        host="smtp.example.test",
        username="mailer",
        password="smtp-private-password",
        from_email="mailer@example.test",
    )
    APIKey.objects.create(
        company=company,
        name="private key",
        key="a" * 64,
        key_prefix="erp_private",
        created_by=user,
    )
    WebhookEndpoint.objects.create(
        company=company,
        name="private hook",
        url="https://hooks.example.test/",
        secret="webhook-private-secret",
        events=["*"],
    )
    Integration.objects.create(
        company=company,
        name="private OAuth",
        provider="test",
        integration_type=Integration.IntegrationType.CUSTOM,
        credentials={"access_token": "oauth-private-token"},
    )
    record = BackupRecord.objects.create(
        company=company,
        backup_type=BackupRecord.BackupType.FULL,
        status=BackupRecord.Status.IN_PROGRESS,
        initiated_by=user,
    )

    with override_settings(MEDIA_ROOT=str(tmp_path)):
        generate_backup.run(str(record.pk), str(company.pk))
        record.refresh_from_db()
        assert record.status == BackupRecord.Status.COMPLETED
        payload = json.loads(default_storage.open(record.file_path).read())

    serialized = json.dumps(payload)
    assert "A Customer" in serialized
    assert "b@example.test" not in serialized
    assert "B Vendor" not in serialized
    assert "other-user@example.test" not in serialized
    assert "NeverExportThisPassword" not in serialized
    assert "private-totp-secret" not in serialized
    assert "smtp-private-password" not in serialized
    assert "a" * 64 not in serialized
    assert "webhook-private-secret" not in serialized
    assert "oauth-private-token" not in serialized
    assert "password" not in serialized.lower()
    assert "secret" not in serialized.lower()
    assert "token" not in serialized.lower()


def test_company_admin_cannot_download_another_companies_backup(client, company, user, tmp_path):
    from django.core.files.base import ContentFile

    other = CompanyFactory(name="Other tenant")
    record = BackupRecord.objects.create(
        company=other,
        backup_type=BackupRecord.BackupType.FULL,
        status=BackupRecord.Status.COMPLETED,
        file_path="backups/private.json",
    )
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        default_storage.save(record.file_path, ContentFile(b"private"))
        client.force_login(user)
        response = client.get(reverse("administration:backup_download", kwargs={"pk": record.pk}))
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_backup_request_queues_only_the_active_tenant(client, company, user):
    other = CompanyFactory(name="Other active tenant")
    UserCompany.objects.create(
        user=user, company=other, role=User.Role.COMPANY_ADMIN, is_active=True
    )
    session = client.session
    session["active_company_id"] = str(other.pk)
    session.save()
    client.force_login(user)

    with patch("apps.administration.tasks.generate_backup.delay") as queue:
        response = client.post(reverse("administration:backup_run_now"))
    assert response.status_code == 302
    record = BackupRecord.objects.get(company=other)
    queue.assert_called_once_with(str(record.pk), str(other.pk))
    assert record.company_id != company.pk
