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

## Follow-up automation reliability work (2026-10-23)

The repository received additional narrowly scoped reliability fixes and regression tests after the baseline above. They cover selected accounting, asset depreciation, company, CRM, helpdesk, HRMS payroll/attendance, inventory low-stock, manufacturing MRP/completion, notification, POS checkout, project, sales overdue/return and workflow task paths. See the current source changes and named test modules referenced in `FINAL_PRODUCTION_AUDIT.md` for scope. The tests improve coverage of those paths but do not establish full end-to-end readiness for the modules.

### Final verification for this follow-up

- Full suite, run in the background with output captured and polled to completion, using `DEBUG=True`, SQLite, `DJANGO_TESTING=1`, and `--no-cov -o addopts=--nomigrations`: **4,935 passed, 0 failed, 1 skipped, 4,843 warnings in 338.32s (0:05:38)**.
- The skipped test remains the SQLite concurrency test for sequence generation; SQLite cannot verify the required `select_for_update` concurrency behavior.
- Focused sales return regression tests: **7 passed**. They cover over-return rejection and cumulative approval limits.
- `manage.py makemigrations --check --dry-run`: **exit 0, `No changes detected`**.
- Fresh Windows-temp SQLite database, `manage.py migrate --noinput`: **exit 0**; all migrations applied, including `sales.0018_salescommission_uniq_sales_commission_invoice_rep`, followed by default permission and currency seeding.
- `git diff --check`: clean (Git emitted only line-ending normalization notices for changed files).

This run remains SQLite-only. PostgreSQL locking/concurrency, live Redis/Celery workers and beat, external providers and production restore remain unverified as detailed in `FINAL_PRODUCTION_AUDIT.md`.

## Duplicate-functionality audit follow-up (2026-10-23)

- Focused HRMS leave API/service tests: **15 passed** (`tests/test_hrms.py apps/hrms/tests/test_views.py`).
- Full suite after the HRMS leave approval consolidation: **4,937 passed, 0 failed, 1 skipped, 4,847 warnings in 291.66s (0:04:51)**.
- `manage.py check`: **exit 0**, no issues.
- `manage.py makemigrations --check --dry-run`: **exit 0**, `No changes detected`.
- No schema change was made; fresh migration was not rerun for this follow-up. The prior fresh SQLite migration succeeded as recorded above.

See `DUPLICATE_FUNCTIONALITY_AUDIT.md` for the findings, retained candidates, and evidence limitations. No PostgreSQL, live Redis/Celery, provider or external consumer behavior is certified by these tests.

### API/web state-transition consolidation (2026-10-23)

- Focused sales quotation tests: **6 passed**. They cover shared approval behavior, API/web approver parity, rejected-state handling, company scoping, and denial when the caller lacks approval permission.
- Full suite after the HRMS and Sales API/web consolidations: **4,940 passed, 0 failed, 1 skipped, 4,853 warnings in 355.48s (0:05:55)**. The run used `DEBUG=True`, SQLite, `DJANGO_TESTING=1`, and `--no-cov -o addopts=--nomigrations`.
- `manage.py check`: **exit 0**, no issues.
- `manage.py makemigrations --check --dry-run`: **exit 0**, `No changes detected`.
- `git diff --check`: clean, with line-ending normalization notices only.
- The skip remains the SQLite concurrency test described above. No schema changed, so a fresh migration was not rerun for this code-only follow-up.

PostgreSQL locking/concurrency, live Redis/Celery behavior, provider integrations and external API clients remain unverified.
