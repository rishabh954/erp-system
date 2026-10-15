import json
import uuid
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.crm.models import Customer
from core.factories import CompanyFactory

pytestmark = pytest.mark.django_db


def backup_file(tmp_path, company_id, objects):
    path = tmp_path / "tenant-backup.json"
    path.write_text(
        json.dumps({
            "manifest": {"company_id": str(company_id), "schema_version": 1},
            "objects": objects,
        }),
        encoding="utf-8",
    )
    return path


def customer_row(company_id, *, pk=None, name="Restored customer"):
    return {
        "model": "crm.customer",
        "pk": str(pk or uuid.uuid4()),
        "fields": {"company": str(company_id), "name": name},
    }


def test_restore_dry_run_reports_counts_without_writing(company, tmp_path):
    row = customer_row(company.pk)
    path = backup_file(tmp_path, company.pk, [row])
    output = StringIO()
    call_command("restore_company_backup", str(path), company=str(company.pk), dry_run=True, stdout=output)
    assert "Dry run validated; no rows were written." in output.getvalue()
    assert "Would load crm.customer: 1" in output.getvalue()
    assert not Customer.objects.filter(pk=row["pk"]).exists()


def test_restore_refuses_manifest_company_mismatch(company, tmp_path):
    path = backup_file(tmp_path, uuid.uuid4(), [])
    with pytest.raises(CommandError, match="does not match"):
        call_command("restore_company_backup", str(path), company=str(company.pk))


def test_restore_refuses_tampered_other_tenant_object(company, tmp_path):
    other = CompanyFactory(name="Foreign backup tenant")
    row = customer_row(other.pk)
    path = backup_file(tmp_path, company.pk, [row])
    with pytest.raises(CommandError, match="not verifiably owned"):
        call_command("restore_company_backup", str(path), company=str(company.pk))
    assert not Customer.objects.filter(pk=row["pk"]).exists()


def test_restore_requires_target_company_to_exist(tmp_path):
    company_id = uuid.uuid4()
    path = backup_file(tmp_path, company_id, [])
    with pytest.raises(CommandError, match="must already exist"):
        call_command("restore_company_backup", str(path), company=str(company_id))
