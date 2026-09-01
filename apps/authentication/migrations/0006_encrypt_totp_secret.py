"""
Migration: widen totp_secret from max_length=32 to max_length=500.

EncryptedCharField.deconstruct() returns the base CharField path so this
migration only widens the column.  Existing plain-text values are returned
as-is by the field (the decrypt path falls through for non-Fernet strings),
so the migration is fully backward-compatible.  They will be encrypted the
next time each user's 2FA settings are saved.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0005_modulepermission_can_manage_users"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="totp_secret",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
