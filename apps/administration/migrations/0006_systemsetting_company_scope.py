import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0005_auditevent"),
        ("company", "0008_sequencecounter"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemsetting",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="system_settings",
                to="company.company",
            ),
        ),
        migrations.AlterField(
            model_name="systemsetting",
            name="key",
            field=models.CharField(db_index=True, max_length=200),
        ),
        migrations.AddConstraint(
            model_name="systemsetting",
            constraint=models.UniqueConstraint(
                fields=("company", "key"),
                name="uniq_admin_setting_company_key",
            ),
        ),
    ]
