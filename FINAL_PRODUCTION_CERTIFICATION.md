# Production Certification

## Certification status

**Not certified.** The available evidence is insufficient to declare this ERP production ready.

## Verified

- The project reports 4,797 passing tests in its configured SQLite test environment.
- The project reports that migration consistency checks are clean.

These results are reported baseline evidence and do not certify the changes in the current audit until the relevant tests and migration checks are rerun.

## Not verified

- PostgreSQL migrations, constraints, locking, and full-suite behavior.
- Redis availability and runtime behavior.
- Celery broker, workers, retries, scheduled jobs, and task failure recovery.
- HRMS payroll, POS, manufacturing, projects, helpdesk, and AI functionality.
- Complete smoke coverage of detail, edit, and delete pages.
- Production backup and restore.
- OAuth integrations with configured provider credentials.

## Remaining release work

Run the full suite and migration checks against the release commit. Verify PostgreSQL, Redis, and Celery in a production-like environment. Complete route and module smoke tests, including tenant isolation, and exercise backup restoration before issuing a production certification.
