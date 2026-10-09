from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0016_salesorder_credit_hold_salesorder_credit_override_by_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="coupon",
            name="code",
            field=models.CharField(db_index=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="productbundle",
            name="code",
            field=models.CharField(max_length=100),
        ),
        migrations.AddConstraint(
            model_name="coupon",
            constraint=models.UniqueConstraint(
                fields=("company", "code"),
                name="uniq_sales_coupon_company_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="productbundle",
            constraint=models.UniqueConstraint(
                fields=("company", "code"),
                name="uniq_sales_bundle_company_code",
            ),
        ),
    ]
