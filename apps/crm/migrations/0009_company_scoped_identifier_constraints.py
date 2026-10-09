from django.db import migrations, models


def repair_company_identifiers(apps, schema_editor):
    database = schema_editor.connection.alias

    for model_name, field_name, prefix in (
        ("Lead", "number", "LD"),
        ("Customer", "customer_code", "CUST"),
    ):
        model = apps.get_model("crm", model_name)
        manager = model._base_manager.using(database)
        company_ids = manager.values_list("company_id", flat=True).distinct()

        for company_id in company_ids.iterator():
            records = list(
                manager.filter(company_id=company_id)
                .order_by("created_at", "pk")
                .values_list("pk", field_name)
            )
            prefix_start = f"{prefix}-"
            highest_suffix = 0
            for _, value in records:
                if value and value.startswith(prefix_start):
                    suffix = value[len(prefix_start) :]
                    if suffix.isascii() and suffix.isdecimal():
                        highest_suffix = max(highest_suffix, int(suffix))

            seen = set()
            duplicates = []
            for record_id, value in records:
                if value and value not in seen:
                    seen.add(value)
                else:
                    duplicates.append(record_id)

            next_suffix = highest_suffix + 1
            for record_id in duplicates:
                candidate = f"{prefix}-{next_suffix:05d}"
                while candidate in seen:
                    next_suffix += 1
                    candidate = f"{prefix}-{next_suffix:05d}"
                manager.filter(pk=record_id).update(
                    **{field_name: candidate}
                )
                seen.add(candidate)
                next_suffix += 1


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0008_alter_lead_number"),
    ]

    operations = [
        migrations.RunPython(repair_company_identifiers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="lead",
            constraint=models.UniqueConstraint(
                fields=("company", "number"),
                name="uniq_crm_lead_company_number",
            ),
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                fields=("company", "customer_code"),
                name="uniq_crm_customer_company_code",
            ),
        ),
    ]
