from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0006_encrypt_totp_secret"),
    ]

    operations = [
        migrations.AddField(
            model_name="modulepermission",
            name="can_consolidate",
            field=models.BooleanField(default=False),
        ),
    ]
