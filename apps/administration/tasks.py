from io import StringIO

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import call_command
from django.db import transaction


@shared_task
def generate_backup(record_id, company_id):
    from apps.administration.models import BackupRecord

    record = BackupRecord.objects.filter(pk=record_id, company_id=company_id).first()
    if record is None:
        return
    try:
        output = StringIO()
        call_command(
            "dumpdata",
            exclude=["contenttypes", "auth.permission"],
            indent=2,
            stdout=output,
        )
        name = f"backups/{company_id}/{record_id}.json"
        saved_name = default_storage.save(name, ContentFile(output.getvalue().encode()))
        with transaction.atomic():
            record = BackupRecord.objects.select_for_update().get(
                pk=record_id, company_id=company_id
            )
            record.file_path = saved_name
            record.file_size = default_storage.size(saved_name)
            record.status = BackupRecord.Status.COMPLETED
            record.save(update_fields=["file_path", "file_size", "status"])
    except Exception as exc:
        with transaction.atomic():
            BackupRecord.objects.filter(pk=record_id, company_id=company_id).update(
                status=BackupRecord.Status.FAILED, notes=str(exc)[:2000]
            )
