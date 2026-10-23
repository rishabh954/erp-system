# Phase 0 Test and Command Report

Reviewed 2026-10-23 against branch `main`, baseline commit `c133c539cc2eed5b86f6466e302093f411ba0ad0`.

## Environment

- Python: 3.12.14, using the bundled runtime at `C:\Users\OM\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe` with `venv\Lib\site-packages` on `PYTHONPATH`.
- Django: 5.2.16.
- Database/test settings: `DEBUG=True`, `DB_ENGINE=django.db.backends.sqlite3`, `DJANGO_TESTING=1`.
- A test-only placeholder `REDIS_PASSWORD` was provided because settings initialization requires it. No production credential was used.
- `venv\Scripts\python.exe` could not run because its configured base Python executable is missing on this workstation.

## Tests

Focused notification regression suite:

```text
python -m pytest apps/notifications/tests/test_tenant_notifications.py -q --no-cov -o addopts="--nomigrations"
10 passed, 0 failed, 0 skipped, 22 warnings in 6.26s
```

Final full suite, run in the background with stdout/stderr redirected to files and polled to completion:

```text
python -m pytest -q --no-cov -o addopts="--nomigrations"
4904 passed, 0 failed, 1 skipped, 4832 warnings in 289.87s (0:04:49)
```

The skip is `SequenceGeneratorConcurrencyTest.test_concurrent_sequence_generation_prevents_duplicates`; its decorator explicitly skips SQLite because SQLite does not support the required `select_for_update` concurrency behavior. The warnings include Django/DRF deprecations, local staticfiles warnings, and unordered-queryset pagination warnings from the route smoke test.

## Django and migration checks

- `manage.py check`: **exit 0**, no system-check issues.
- `manage.py makemigrations --check --dry-run`: **exit 0**, `No changes detected`.
- Fresh temporary SQLite database, `manage.py migrate --noinput`: **exit 0**, all migrations applied, including `notifications.0004_preference_company_scope` and `sales.0018`; default permissions/currencies seeded.
- Existing workspace database, `manage.py migrate --check`: **exit 1**. Read-only `showmigrations sales` confirms `sales.0018_salescommission_uniq_sales_commission_invoice_rep` is unapplied. It was not applied to the existing database.
- `manage.py check --deploy --fail-level ERROR --settings config.settings`: **exit 0 with 99 warnings** in the recorded production-like check. Warnings included API schema-generation warnings and HTTPS/security-cookie warnings under the non-TLS audit configuration.
- `git diff --check`: clean.

## Not verified

- PostgreSQL migrations, constraints, locking, and full-suite behavior.
- Live Redis and Celery worker/scheduler, retry, and failure-recovery behavior.
- Real email/SMS/WhatsApp/push-provider delivery.
- Full production backup/media restore drill.
- Exhaustive endpoint-by-endpoint tenant authorization, detail/edit/delete page coverage, or end-to-end readiness of HRMS payroll, POS, manufacturing, projects, helpdesk, and AI.

The SQLite suite is evidence for this test configuration only; it does not certify production readiness.
