import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0006_encrypt_totp_secret"),
        ("company", "0001_initial"),
        ("hrms", "0006_alter_expenseclaim_number_alter_leaverequest_number_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BiometricDevice",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("device_id", models.CharField(max_length=100)),
                ("key_hash", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="%(app_label)s_%(class)s_set",
                        to="company.company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created",
                        to="authentication.user",
                    ),
                ),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_deleted",
                        to="authentication.user",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated",
                        to="authentication.user",
                    ),
                ),
            ],
            options={
                "db_table": "hrms_biometric_devices",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="biometricdevice",
            constraint=models.UniqueConstraint(
                fields=("company", "device_id"),
                name="uniq_hrms_biometric_device_company_device",
            ),
        ),
    ]
