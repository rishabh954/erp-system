from django.db import migrations, models
import hashlib


def hash_existing_keys(apps, schema_editor):
    APIKey = apps.get_model("administration", "APIKey")
    alias = schema_editor.connection.alias
    for item in APIKey.objects.using(alias).all().iterator():
        if len(item.key) == 64 and all(
            character in "0123456789abcdef" for character in item.key
        ):
            continue
        item.key_prefix = item.key[:12]
        item.key = hashlib.sha256(item.key.encode()).hexdigest()
        item.save(using=alias, update_fields=["key", "key_prefix"])


class Migration(migrations.Migration):
    dependencies = [("administration", "0007_rename_admin_audit__compan_3a1c5d_idx_admin_audit_company_09511d_idx_and_more")]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="key_prefix",
            field=models.CharField(blank=True, editable=False, max_length=12),
        ),
        migrations.RunPython(hash_existing_keys, migrations.RunPython.noop),
    ]
