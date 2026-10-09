import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("company", "0007_intercompanysettlement_intercompanytransaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="SequenceCounter",
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
                ("prefix", models.CharField(max_length=50)),
                ("last_value", models.PositiveBigIntegerField(default=0)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sequence_counters",
                        to="company.company",
                    ),
                ),
            ],
            options={
                "db_table": "company_sequence_counters",
            },
        ),
        migrations.AddConstraint(
            model_name="sequencecounter",
            constraint=models.UniqueConstraint(
                fields=("company", "prefix"),
                name="uniq_company_sequence_prefix",
            ),
        ),
    ]
