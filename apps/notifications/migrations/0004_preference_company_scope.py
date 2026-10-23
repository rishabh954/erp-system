from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0003_notificationpreference_push_enabled"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="notificationpreference",
            unique_together={("user", "company", "notification_type")},
        ),
    ]
