"""Shared helpers for tenant backup creation and private manifest display."""

import json

from django.db import transaction

from apps.administration.models import BackupRecord


def queue_company_backup(company, user, *, backup_type=BackupRecord.BackupType.FULL, notes=""):
    """Create a tenant backup record and enqueue generation after commit."""
    from apps.administration.tasks import generate_backup

    with transaction.atomic():
        record = BackupRecord.objects.create(
            company=company,
            backup_type=backup_type,
            status=BackupRecord.Status.IN_PROGRESS,
            initiated_by=user,
            notes=notes,
        )
        transaction.on_commit(
            lambda: generate_backup.delay(str(record.pk), str(company.pk))
        )
    return record


def read_backup_manifest(record):
    if record.status != BackupRecord.Status.COMPLETED or not record.file_path:
        return None
    try:
        from apps.administration.tasks import _backup_storage

        with _backup_storage().open(record.file_path, "rb") as backup_file:
            return json.load(backup_file).get("manifest")
    except (OSError, ValueError, TypeError):
        return None
