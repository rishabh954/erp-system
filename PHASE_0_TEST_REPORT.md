# Phase 0 Test Report

## Focused regression tests

Executed with the repository virtualenv's site-packages through the available Python 3.12 runtime because the virtualenv's configured base interpreter path is missing. The full-suite process wrote stdout and stderr to separate files under `%TEMP%` and was polled until completion.

Focused test command used the bundled Python executable with `PYTHONPATH=venv\Lib\site-packages`, `DEBUG=True`, `DB_ENGINE=django.db.backends.sqlite3`, `DB_NAME=db.sqlite3`, and `DJANGO_TESTING=1`, followed by the test paths listed in the invocation.

**Result: 27 passed, 0 failed.** The Python executable in `venv\Scripts\python.exe` could not start because its configured base interpreter (`C:\Users\OM\AppData\Local\Programs\Python\Python312\python.exe`) is unavailable; the bundled Python 3.12 runtime with the venv site-packages was used instead.

## Full suite

Command: `python -m pytest -q --no-cov -o addopts="--nomigrations"` with `DEBUG=True`, `DB_ENGINE=django.db.backends.sqlite3`, `DB_NAME=C:\Users\OM\Documents\GitHub\erp-system\db.sqlite3`, `DJANGO_TESTING=1`, and `PYTHONPATH=venv\Lib\site-packages`, executed via the available bundled Python 3.12. It was launched in a hidden background process with stdout/stderr files under `%TEMP%` and polled to completion.

**Final result: 4,885 passed, 0 failed, 1 skipped, 4,816 warnings in 385.07 seconds (6:25).** The existing SQLite-only concurrency skip remains. Warnings include Django/DRF deprecations, missing local staticfiles directory, and an unordered Warehouse pagination warning from the route smoke test.

## Migration checks

- `manage.py makemigrations --check --dry-run`: **No changes detected**.
- Fresh SQLite `manage.py migrate --noinput`: **succeeded (exit 0)**; all migrations applied, default module permissions/currencies seeded.
- `git diff --check`: clean.
- `python -m compileall -q` on changed Python files: succeeded.
- `docker compose -f docker-compose.prod.yml config --quiet` with temporary non-production placeholder values: completed; Docker emitted a local config access warning and warned that Compose's top-level `version` key is obsolete.
- `manage.py check --deploy --fail-level ERROR --settings config.settings` with `DEBUG=False` and explicit test-only configuration: exit 0; Django reported 99 warnings, including API schema generation and HTTPS-related warnings because SSL redirect was disabled for this check. These warnings were not suppressed and need deployment-owner review.

## Full suite and infrastructure tests

- PostgreSQL, live Redis, and Celery worker integration: not executed in this local pass; CI configuration was updated but has not been run by this task.
- Restore timing, media recovery, and backup integrity drill: not verified.

SQLite-only test results do not certify PostgreSQL behavior.
