import django.db.models.deletion
from django.db import migrations, models


def assign_unambiguous_companies(apps, schema_editor):
    SavedReport = apps.get_model("analytics", "SavedReport")
    UserCompany = apps.get_model("authentication", "UserCompany")
    database = schema_editor.connection.alias

    for report in SavedReport.objects.using(database).all().iterator():
        company_ids = list(
            UserCompany.objects.using(database)
            .filter(user_id=report.created_by_id, is_active=True)
            .values_list("company_id", flat=True)[:2]
        )
        if len(company_ids) == 1:
            SavedReport.objects.using(database).filter(pk=report.pk).update(
                company_id=company_ids[0]
            )


class Migration(migrations.Migration):

    dependencies = [
        ("analytics", "0002_alter_customreport_aggregate_field_and_more"),
        ("authentication", "0007_modulepermission_can_consolidate"),
        ("company", "0007_intercompanysettlement_intercompanytransaction"),
    ]

    operations = [
        migrations.RenameField(
            model_name="savedreport",
            old_name="company_id",
            new_name="legacy_company_id",
        ),
        migrations.AddField(
            model_name="savedreport",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="saved_reports",
                to="company.company",
            ),
        ),
        migrations.RunPython(
            assign_unambiguous_companies, migrations.RunPython.noop
        ),
        migrations.RemoveField(
            model_name="savedreport",
            name="legacy_company_id",
        ),
    ]
