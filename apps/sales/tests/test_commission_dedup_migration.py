import os
import subprocess
import sys

import pytest
from django.conf import settings


@pytest.mark.django_db
def test_0018_deduplicates_commissions_from_0017_on_fresh_sqlite(tmp_path):
    script = r'''
import uuid
import django
from datetime import date, datetime, timezone
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

django.setup()
executor = MigrationExecutor(connection)
executor.migrate([("sales", "0017_company_scoped_coupon_codes")])
apps = executor.loader.project_state([("sales", "0017_company_scoped_coupon_codes")]).apps
from apps.company.models import Company as CurrentCompany
Customer = apps.get_model("crm", "Customer")
Invoice = apps.get_model("sales", "Invoice")
Commission = apps.get_model("sales", "SalesCommission")

company = CurrentCompany.objects.using("default").create(
    name="Migration Tenant", slug=f"migration-{uuid.uuid4()}"
)
rep_id = uuid.uuid4()
with connection.cursor() as cursor:
    columns = cursor.execute('PRAGMA table_info("auth_users")').fetchall()
    values = {}
    for _cid, name, data_type, not_null, default, primary_key in columns:
        if primary_key:
            values[name] = rep_id.hex
        elif name == "email":
            values[name] = f"migration-{rep_id}@example.test"
        elif name == "username":
            values[name] = f"migration-{rep_id}"
        elif name == "password":
            values[name] = "test-hash"
        elif name == "first_name":
            values[name] = "Rep"
        elif name == "last_name":
            values[name] = "Migration"
        elif not_null and default is None:
            values[name] = 0 if "INT" in data_type.upper() else ""
    names = list(values)
    cursor.execute(
        f'INSERT INTO "auth_users" ({", ".join(chr(34) + name + chr(34) for name in names)}) '
        f'VALUES ({", ".join("%s" for _ in names)})',
        [values[name] for name in names],
    )
customer = Customer.objects.using("default").create(company_id=company.pk, name="Migration Customer")
invoice = Invoice.objects.using("default").create(
    company_id=company.pk, customer_id=customer.pk, invoice_date=date(2025, 1, 1),
    due_date=date(2025, 1, 31), subtotal="10.00", total="10.00"
)
earliest, later = uuid.uuid4(), uuid.uuid4()
common = {"company_id": company.pk, "invoice_id": invoice.pk,
          "sales_rep_id": rep_id, "amount": "1.00"}
Commission.objects.using("default").create(pk=earliest, **common, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
Commission.objects.using("default").create(pk=later, **common, created_at=datetime(2025, 1, 2, tzinfo=timezone.utc))
executor = MigrationExecutor(connection)
executor.migrate([("sales", "0018_salescommission_uniq_sales_commission_invoice_rep")])
apps = executor.loader.project_state([("sales", "0018_salescommission_uniq_sales_commission_invoice_rep")]).apps
Commission = apps.get_model("sales", "SalesCommission")
remaining = list(Commission.objects.filter(
    company_id=company.pk, invoice_id=invoice.pk, sales_rep_id=rep_id
).values_list("pk", flat=True))
assert remaining == [earliest], remaining
'''
    database_path = tmp_path / "commission-migration.sqlite3"
    env = os.environ.copy()
    env.update(
        {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DB_ENGINE": "django.db.backends.sqlite3",
            "DB_NAME": str(database_path),
            "DJANGO_TESTING": "1",
            "DEBUG": "True",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
