"""
CRM Lead Source: add 'blog' choice
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("crm", "0009_company_scoped_identifier_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="source",
            field=models.CharField(
                blank=True,
                choices=[
                    ("web", "Website"),
                    ("referral", "Referral"),
                    ("social", "Social Media"),
                    ("email", "Email Campaign"),
                    ("cold_call", "Cold Call"),
                    ("event", "Event"),
                    ("blog", "Blog"),
                    ("other", "Other"),
                ],
                max_length=20,
            ),
        ),
    ]
