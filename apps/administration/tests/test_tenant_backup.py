import json
import os
import subprocess
import sys
import textwrap
import uuid
from unittest.mock import patch

import pytest
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
from apps.purchase.models import PurchaseOrder, PurchaseOrderLine, Vendor
from apps.sales.models import Invoice, InvoiceLine
from apps.accounting.models import JournalEntry, JournalItem
from core.factories import AccountFactory, JournalFactory
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

    with override_settings(MEDIA_ROOT=str(tmp_path / "media"), PRIVATE_BACKUP_ROOT=tmp_path / "private"):
        generate_backup.run(str(record.pk), str(company.pk))
        record.refresh_from_db()
        assert record.status == BackupRecord.Status.COMPLETED
        from apps.administration.tasks import _backup_storage

        payload = json.loads(_backup_storage().open(record.file_path).read())

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
    for obj in payload["objects"]:
        assert not any(
            marker in field.lower()
            for field in obj.get("fields", {})
            for marker in ("password", "secret", "token", "credential", "api_key", "totp")
        )


def test_company_admin_cannot_download_another_companies_backup(client, company, user, tmp_path):
    from django.core.files.base import ContentFile

    other = CompanyFactory(name="Other tenant")
    record = BackupRecord.objects.create(
        company=other,
        backup_type=BackupRecord.BackupType.FULL,
        status=BackupRecord.Status.COMPLETED,
        file_path="backups/private.json",
    )
    with override_settings(PRIVATE_BACKUP_ROOT=tmp_path / "private"):
        from apps.administration.tasks import _backup_storage

        _backup_storage().save(record.file_path, ContentFile(b"private"))
        client.force_login(user)
        response = client.get(reverse("administration:backup_download", kwargs={"pk": record.pk}))
    assert response.status_code == 404


def test_backup_manifest_matches_export_and_file_is_private(company, user, tmp_path):
    from apps.administration.tasks import _backup_storage, generate_backup

    record = BackupRecord.objects.create(
        company=company, backup_type=BackupRecord.BackupType.FULL,
        status=BackupRecord.Status.IN_PROGRESS, initiated_by=user,
    )
    with override_settings(MEDIA_ROOT=str(tmp_path / "media"), PRIVATE_BACKUP_ROOT=tmp_path / "private"):
        generate_backup.run(str(record.pk), str(company.pk))
        record.refresh_from_db()
        payload = json.loads(_backup_storage().open(record.file_path).read())
        assert not (tmp_path / "media" / record.file_path).exists()
        assert _backup_storage().exists(record.file_path)
    assert payload["manifest"]["company_id"] == str(company.pk)
    actual = {}
    for row in payload["objects"]:
        actual[row["model"]] = actual.get(row["model"], 0) + 1
    assert {model: count for model, count in payload["manifest"]["model_counts"].items() if count} == actual
    assert "unresolved_models" in payload["manifest"]


def test_backup_includes_company_owned_child_lines_and_keeps_foreign_keys(company, user, tmp_path):
    from datetime import date
    from apps.administration.tasks import serialize_company_backup

    customer = Customer.objects.create(company=company, name="Backup Customer")
    invoice = Invoice.objects.create(
        company=company, customer=customer, invoice_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31), total="12.00",
    )
    invoice_line = InvoiceLine.objects.create(
        invoice=invoice, description="Invoice line", quantity=1, unit_price=12,
    )
    account = AccountFactory(company=company)
    journal = JournalFactory(company=company)
    entry = JournalEntry.objects.create(company=company, journal=journal, date=date(2026, 1, 1))
    item = JournalItem.objects.create(
        journal_entry=entry, account=account, description="Ledger line", debit=12,
    )
    vendor = Vendor.objects.create(company=company, name="Backup Vendor")
    purchase_order = PurchaseOrder.objects.create(
        company=company, vendor=vendor, order_date=date(2026, 1, 1),
    )
    po_line = PurchaseOrderLine.objects.create(
        purchase_order=purchase_order, description="PO line", quantity=1, unit_price=12,
    )
    other_company = CompanyFactory(name="Another backup tenant")
    other_customer = Customer.objects.create(company=other_company, name="Foreign customer")
    other_invoice = Invoice.objects.create(
        company=other_company, customer=other_customer, invoice_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
    )
    other_line = InvoiceLine.objects.create(
        invoice=other_invoice, description="Foreign child line", quantity=1, unit_price=9,
    )
    payload = json.loads(serialize_company_backup(str(company.pk)))
    objects = {row["model"]: row for row in payload["objects"]}
    rows = payload["objects"]
    for model, pk in (
        ("sales.invoiceline", str(invoice_line.pk)),
        ("accounting.journalitem", str(item.pk)),
        ("purchase.purchaseorderline", str(po_line.pk)),
    ):
        assert any(row["model"] == model and row["pk"] == pk for row in rows)
    assert not any(row["pk"] == str(other_line.pk) for row in rows)
    line_data = next(row for row in rows if row["pk"] == str(invoice_line.pk))
    assert line_data["fields"]["invoice"] == str(invoice.pk)
    journal_data = next(row for row in rows if row["pk"] == str(item.pk))
    assert journal_data["fields"]["journal_entry"] == str(entry.pk)
    po_data = next(row for row in rows if row["pk"] == str(po_line.pk))
    assert po_data["fields"]["purchase_order"] == str(purchase_order.pk)

    # Exercise the documented restore prerequisite in a separately migrated database.
    restore_labels = {
        "crm.customer", "sales.invoice", "sales.invoiceline", "accounting.account",
        "accounting.journal", "accounting.journalentry", "accounting.journalitem",
    }
    restore_objects = [row for row in rows if row["model"] in restore_labels]
    restore_file = tmp_path / "restore-payload.json"
    restore_file.write_text(json.dumps({
        "manifest": {"company_id": str(company.pk), "schema_version": 1},
        "objects": restore_objects,
    }), encoding="utf-8")
    restore_db = tmp_path / "restore.sqlite3"
    restore_script = r'''
import json, os, uuid, django
django.setup()
from django.core.management import call_command
from apps.company.models import Company
from apps.authentication.models import User
from apps.sales.models import Invoice, InvoiceLine
from apps.accounting.models import JournalItem
call_command("migrate", interactive=False, verbosity=0)
payload = json.load(open(os.environ["BACKUP_PAYLOAD"], encoding="utf-8"))
company_id = os.environ["BACKUP_COMPANY_ID"]
Company.objects.create(pk=company_id, name="Restored prerequisite", slug="restored-prerequisite")
user_ids = set()
for row in payload["objects"]:
    model = django.apps.apps.get_model(row["model"])
    for field in model._meta.concrete_fields:
        if field.is_relation and field.related_model is User:
            value = row.get("fields", {}).get(field.name)
            if value:
                user_ids.add(str(value))
for user_id in user_ids:
    User.objects.create(pk=user_id, email=f"{user_id}@restore.test", username=f"restore-{user_id}", first_name="Restore", last_name="User", password="!", primary_company_id=company_id)
call_command("restore_company_backup", os.environ["BACKUP_PAYLOAD"], company=company_id)
invoice = Invoice.objects.get(company_id=company_id)
line = InvoiceLine.objects.get(invoice=invoice)
item = JournalItem.objects.select_related("journal_entry", "account").get(description="Ledger line")
assert line.invoice_id == invoice.pk and item.journal_entry.company_id == uuid.UUID(company_id)
'''
    env = os.environ.copy()
    env.update({
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "DB_ENGINE": "django.db.backends.sqlite3",
        "DB_NAME": str(restore_db),
        "DJANGO_TESTING": "1",
        "DEBUG": "True",
        "BACKUP_PAYLOAD": str(restore_file),
        "BACKUP_COMPANY_ID": str(company.pk),
    })
    restored = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(restore_script)], cwd=__import__("django").conf.settings.BASE_DIR,
        env=env, capture_output=True, text=True, timeout=180,
    )
    assert restored.returncode == 0, restored.stdout + restored.stderr


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


@pytest.mark.django_db(transaction=True)
def test_backup_restore_create_queues_once_and_runs_to_completion(client, company, user):
    from apps.administration.tasks import generate_backup

    client.force_login(user)

    def run_task(record_id, company_id):
        generate_backup.run(record_id, company_id)

    with patch("apps.administration.tasks.generate_backup.delay", side_effect=run_task) as queue:
        response = client.post(
            reverse("administration:backup_restore"),
            {"action": "create", "backup_type": "full", "notes": "requested"},
        )
    assert response.status_code == 302
    record = BackupRecord.objects.get(company=company, notes="requested")
    assert record.status == BackupRecord.Status.COMPLETED
    queue.assert_called_once_with(str(record.pk), str(company.pk))


@pytest.mark.django_db
def test_stale_backup_command_fails_only_old_in_progress_records(company, user):
    from datetime import timedelta
    from django.core.management import call_command
    from django.utils import timezone

    other = CompanyFactory(name="Other stale tenant")
    stale = BackupRecord.objects.create(company=company, initiated_by=user)
    recent = BackupRecord.objects.create(company=company, initiated_by=user)
    foreign_stale = BackupRecord.objects.create(company=other, initiated_by=None)
    BackupRecord.objects.filter(pk__in=[stale.pk, foreign_stale.pk]).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    call_command("fail_stale_backups", stdout=__import__("io").StringIO())
    stale.refresh_from_db()
    recent.refresh_from_db()
    foreign_stale.refresh_from_db()
    assert stale.status == BackupRecord.Status.FAILED
    assert "more than one hour" in stale.notes
    assert foreign_stale.status == BackupRecord.Status.FAILED
    assert recent.status == BackupRecord.Status.IN_PROGRESS
