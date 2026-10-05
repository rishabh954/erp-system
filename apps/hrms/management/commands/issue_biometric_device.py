import hashlib
import secrets

from django.core.management.base import BaseCommand

from apps.company.models import Company
from apps.hrms.models import BiometricDevice


class Command(BaseCommand):
    help = "Create a tenant-scoped biometric device credential and print the raw key once."

    def add_arguments(self, parser):
        parser.add_argument("--company-id", required=True)
        parser.add_argument("--device-id", required=True)

    def handle(self, *args, **options):
        company = Company.objects.get(pk=options["company_id"])
        raw_key = secrets.token_urlsafe(32)
        device, created = BiometricDevice.objects.update_or_create(
            company=company,
            device_id=options["device_id"],
            defaults={
                "key_hash": hashlib.sha256(raw_key.encode("utf-8")).hexdigest(),
                "is_active": True,
            },
        )
        if not created:
            self.stdout.write(
                self.style.WARNING(
                    f"Updated existing biometric device '{device.device_id}' for {company.name}."
                )
            )
        self.stdout.write(self.style.SUCCESS(f"Raw key: {raw_key}"))
        self.stdout.write(
            "Store this value in the device and do not print it again."
        )
