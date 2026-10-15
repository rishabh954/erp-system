from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.administration.models import BackupRecord
from apps.company.models import Company


class Command(BaseCommand):
    help = "Mark company backups stuck in progress for over one hour as failed."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=1)
        failed = 0
        for company_id in Company.objects.values_list("pk", flat=True).iterator():
            with transaction.atomic():
                failed += BackupRecord.objects.filter(
                    company_id=company_id,
                    status=BackupRecord.Status.IN_PROGRESS,
                    created_at__lt=cutoff,
                ).update(
                    status=BackupRecord.Status.FAILED,
                    notes="Marked failed because backup remained in progress for more than one hour.",
                )
        self.stdout.write(f"Marked {failed} stale backup(s) as failed.")
