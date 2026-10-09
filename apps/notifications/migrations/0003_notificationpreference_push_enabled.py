from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_smslog_whatsapplog_notificationpreference"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="push_enabled",
            field=models.BooleanField(default=False),
        ),
    ]
