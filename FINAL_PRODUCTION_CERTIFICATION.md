# Production Certification

## Certification status

**Not certified.** The available evidence is insufficient to declare this ERP production ready.

## Verified

- The latest full SQLite test run completed with 4,904 passed, 0 failed, and 1 skipped.
- `makemigrations --check --dry-run` reports no model changes without migrations, and a fresh temporary SQLite database migrated successfully.
- The existing workspace database has an unapplied `sales.0018_salescommission_uniq_sales_commission_invoice_rep`; no migration was applied to it during this audit.

These results are evidence for the current local SQLite run only; they do not establish PostgreSQL, Redis, Celery, or production behavior.

## Not verified

- PostgreSQL migrations, constraints, locking, and full-suite behavior.
- Redis availability and runtime behavior.
- Celery broker, workers, retries, scheduled jobs, and task failure recovery.
- HRMS payroll, POS, manufacturing, projects, helpdesk, and AI functionality.
- Complete smoke coverage of detail, edit, and delete pages.
- Production backup and restore.
- OAuth integrations with configured provider credentials.

## Remaining release work

Run the full suite and migration checks against PostgreSQL on the release commit. Verify Redis and Celery in a production-like environment. Complete route and module smoke tests, including tenant isolation, and exercise backup restoration before issuing a production certification.
