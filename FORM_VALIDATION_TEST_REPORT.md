# Form validation test report

## Commands and results

Python used: the bundled Codex runtime at `C:\Users\OM\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`, with the project virtualenv `site-packages` on `PYTHONPATH`. The checked-in `venv\Scripts\python.exe` launcher points at a missing base interpreter on this workstation, so it could not be used.

Environment: `DEBUG=True`, SQLite (`DB_ENGINE=django.db.backends.sqlite3`), `DJANGO_TESTING=1`.

Focused regression and app suites:

```text
pytest tests/test_company_creation.py apps/inventory/tests apps/purchase/tests apps/sales/tests -q --no-cov -o addopts=--nomigrations
64 passed, 0 failed, 0 skipped
```

The full repository suite was run with:

```text
pytest -q --no-cov -o addopts=--nomigrations
```

The earlier validation run's first attempt reported 4,893 passed, 1 failed, 1 skipped. Its single failure was `tests/test_e2e_walkthrough.py::SmokeTest::test_end_to_end_walkthrough`, because the product category created by that established workflow is inactive. Product creation was adjusted to permit a non-deleted category owned by the active company, while continuing to reject cross-company categories. The later full suite completed with 4,904 passed, 0 failed, and 1 skipped; see the authoritative current evidence in [PHASE_0_TEST_REPORT.md](PHASE_0_TEST_REPORT.md).

## Regression coverage added

- Company setup: blank names and malformed/inactive currency references do not create company or membership rows.
- Product creation: whitespace name/SKU and a foreign-company category are rejected without creating a product.
- Warehouse creation: a branch from another company is rejected without creating a warehouse.
- Vendor creation: blank name, invalid vendor type, and malformed payment terms are rejected without creating a vendor. Existing valid create/update tests remain in the targeted suite.
- Invoice service: missing lines, a foreign-company customer, and a non-positive line quantity are rejected before creating an invoice.

## Coverage limits and unverified forms

The full suite exercises broad existing workflows but does not establish exhaustive required-field validation across every form. See the UNVERIFIED inventory in `FORM_VALIDATION_AUDIT.md`. No PostgreSQL-specific behavior, browser JavaScript behavior, or complete DRF/AJAX invalid-input matrix was verified by this SQLite pytest run.

No schema or migration changes were made, so `makemigrations --check` and fresh database migration checks were not run as part of this validation task.

## Current validation-hardening pass

The following results are from the current code state and supersede any older test totals above for this pass:

| Validation | Command / scope | Result |
|---|---|---|
| Focused regressions | `pytest tests/test_form_validation_hardening.py apps/manufacturing/tests/test_bom.py apps/pos/tests/test_views.py tests/test_business_logic.py -q --no-cov -o addopts=--nomigrations` with temporary SQLite | 24 passed, 0 failed |
| Affected CRUD and compatibility tests | `pytest tests/test_e2e_walkthrough.py apps/crm/tests/test_views.py apps/assets/tests/test_views.py apps/documents/tests/test_views.py -q --no-cov -o addopts=--nomigrations` with temporary SQLite | 9 passed, 0 failed |
| Full suite | `pytest -q --no-cov -o addopts=--nomigrations` with temporary SQLite | 4,960 passed, 0 failed, 1 skipped; 4,891 warnings; 5m16s |
| Django checks | `manage.py check` with temporary SQLite | No issues identified |
| Migration drift | `manage.py makemigrations --check --dry-run` with temporary SQLite | No changes detected |
| Ruff and whitespace | Ruff on changed Python files and `git diff --check` | All checks passed. |

The full suite covers the repository's existing tests plus the focused manufacturing/POS regressions, but it does not establish that every ERP form has an exhaustive invalid-input matrix. An earlier full-suite run had one failure because the legacy walkthrough omitted `customer_type`; the customer form now preserves its model default, the focused walkthrough passes, and the final full-suite run is green. The coverage boundary and remaining unverified modules are listed in `FORM_VALIDATION_AUDIT.md`. No database models or migrations were changed.

### Files changed in this pass

- `apps/accounting/services.py`
- `apps/accounting/statement_views.py`
- `apps/accounting/views.py`
- `apps/assets/forms.py`
- `apps/assets/views.py`
- `apps/assets/tests/test_views.py`
- `apps/crm/forms.py`
- `apps/crm/views.py`
- `apps/documents/forms.py`
- `apps/documents/views.py`
- `apps/documents/tests/test_views.py`
- `apps/hrms/validation.py`
- `apps/hrms/services.py`
- `apps/hrms/views.py`
- `apps/inventory/api/views.py`
- `apps/inventory/services.py`
- `apps/manufacturing/views.py`
- `apps/pos/views.py`
- `apps/sales/views.py`
- `templates/manufacturing/boms/form.html`
- `templates/manufacturing/orders/form.html`
- `templates/sales/pos.html`
- `tests/test_form_validation_hardening.py`

The audit documentation was also updated. Administration and project helper modules found to have no callers were removed rather than counted as validation coverage.

`ERP_SYSTEM_AUDIT.md` was already untracked in the worktree and was not modified as part of this pass.

## Remaining work

The repository-wide audit remains incomplete; untraced apps and operations are listed in [FORM_VALIDATION_AUDIT.md](FORM_VALIDATION_AUDIT.md). The bounded follow-up below covers the project/task creation and time-log paths, customer portal ticket/profile paths, and helpdesk ticket/service paths only.

## Bounded follow-up: projects, portals, and helpdesk

| Validation | Command / scope | Result |
|---|---|---|
| Focused app tests | `$env:DB_HOST='sqlite'; $env:DB_NAME=':memory:'; .\venv\Scripts\python.exe -m pytest apps\projects\tests\test_views.py apps\portals\tests\test_multitenancy.py apps\helpdesk\tests.py -q --no-cov -o addopts=--nomigrations` | 37 passed, 0 failed, 86 warnings, 27.76s |
| Django system check | `manage.py check` with temporary SQLite | No issues identified. |
| Ruff | `ruff check` on the changed Python files listed below | All checks passed. |
| Whitespace | `git diff --check` on the changed app files and both shared validation reports | Passed; Git emitted only the configured LF-to-CRLF notices for the two Markdown reports. |

Regression coverage includes missing/whitespace and invalid choices, malformed or out-of-range numeric inputs, foreign-company customer/project/category/assignee choices, preservation of portal/project defaults, and no partial writes on invalid submissions. No model or migration changes were made.

### Files changed in this bounded follow-up

- `apps/projects/forms.py`
- `apps/projects/views.py`
- `apps/projects/tests/test_views.py`
- `apps/portals/forms.py`
- `apps/portals/views.py`
- `apps/portals/tests/test_multitenancy.py`
- `apps/helpdesk/forms.py`
- `apps/helpdesk/views.py`
- `apps/helpdesk/services.py`
- `apps/helpdesk/tests.py`
- `FORM_VALIDATION_AUDIT.md`
- `FORM_VALIDATION_TEST_REPORT.md`

## Bounded follow-up: company, analytics, notifications (2026-11-04)

Focused command (temporary SQLite, migrations disabled):

```powershell
$env:DB_HOST='sqlite'; $env:DB_NAME=':memory:'; $env:DJANGO_TESTING='1'
.\venv\Scripts\python.exe -m pytest `
  apps\company\tests.py `
  apps\company\tests\test_write_validation.py `
  apps\company\tests\test_tasks.py `
  apps\analytics\tests.py `
  apps\analytics\test_security.py `
  apps\analytics\test_write_validation.py `
  apps\notifications\tests\test_tenant_notifications.py `
  -q --tb=short --no-cov -o addopts=--nomigrations
```

Result: **59 passed, 0 failed, 63 warnings, 24.89s**. This includes the reported `TimezoneTests.test_invalid_timezone_rejected_in_form`; invalid settings now return before saving and include the expected `Invalid timezone` message.

| Validation | Result |
|---|---|
| Ruff on all six modified Python files | All checks passed. |
| `manage.py check` with temporary SQLite | No issues identified. |
| `manage.py makemigrations --check --dry-run` | No changes detected. |
| Scoped `git diff --check` | Passed; only Git LF-to-CRLF notices were emitted. |

Coverage in this batch includes company setup/settings, tenant-scoped branch/department/tax relations, currency and exchange-rate decimals/dates, report field/filter/module validation, schedule choices/recipients, export/preview input validation, and notification preference checkbox/tenant scoping. The new invalid-input regressions assert no parent, preference, schedule, or execution-log writes as applicable. No schema or migration files changed.

### Files changed in this bounded follow-up

- `apps/company/views.py`
- `apps/company/tests/test_write_validation.py`
- `apps/analytics/views.py`
- `apps/analytics/test_write_validation.py`
- `apps/notifications/views.py`
- `apps/notifications/tests/test_tenant_notifications.py`
- `FORM_VALIDATION_AUDIT.md`
- `FORM_VALIDATION_TEST_REPORT.md`

This was not a full repository test run. Remaining unverified scope is recorded in `FORM_VALIDATION_AUDIT.md`: exhaustive company update/delete and optional-field matrices; analytics read-only pagination/legacy report-query parsing and full field-path coverage; and notification provider service/task payload validation.

## Final validation pass: remaining app paths and auth/AI

The final combined targeted regression batch exercised the new and affected validation paths across AI, authentication, company, analytics, notifications, projects, portals, helpdesk, purchase, workflow, and the previous hardening regressions:

```powershell
$env:DB_HOST='sqlite'; $env:DB_NAME=':memory:'
.\venv\Scripts\python.exe -m pytest `
  apps\ai\tests.py `
  apps\authentication\tests\test_validation.py `
  apps\company\tests.py apps\company\tests\test_write_validation.py `
  apps\analytics\tests.py apps\analytics\test_security.py `
  apps\analytics\test_write_validation.py `
  apps\notifications\tests\test_tenant_notifications.py `
  apps\projects\tests\test_views.py `
  apps\portals\tests\test_multitenancy.py apps\helpdesk\tests.py `
  tests\test_scoped_lookups.py `
  apps\purchase\tests\test_write_validation.py `
  apps\purchase\tests\test_views.py apps\purchase\tests\test_flow.py `
  apps\workflow\tests\test_write_validation.py apps\workflow\tests\test_views.py `
  tests\test_view_coverage.py tests\test_form_validation_hardening.py `
  -q --no-cov -o addopts=--nomigrations
```

Result: **217 passed, 0 failed, 309 warnings, 5 subtests passed**. The final full repository run completed with **5,084 passed, 0 failed, 1 skipped, 5,052 warnings, 5 subtests passed** in 385.60 seconds.

Additional verification: `manage.py check` reported no issues; `manage.py makemigrations --check --dry-run` reported no changes; Ruff passed on the changed Python file set after fixing lint findings; `git diff --check` passed. No migrations were generated.

This is not evidence that every form in the ERP has complete validation. The verified paths and remaining gaps are recorded in `FORM_VALIDATION_AUDIT.md`. In particular, administration write forms, several dashboards/AJAX/API endpoints, provider/background-task inputs, and untraced operations in accounting, CRM, sales, inventory, HRMS, manufacturing, projects, portals, helpdesk, documents, assets, and workflow still require individual validation matrices.

### Additional files changed in the final bounded pass

- `apps/ai/forms.py`
- `apps/ai/validators.py`
- `apps/ai/views.py`
- `apps/ai/tests.py`
- `apps/authentication/forms.py`
- `apps/authentication/views.py`
- `apps/authentication/api/serializers.py`
- `apps/authentication/api/views.py`
- `apps/authentication/tests/test_validation.py`
- `apps/company/tests/test_write_validation.py`
- `apps/analytics/test_write_validation.py`
- `apps/purchase/tests/test_write_validation.py`
- `apps/workflow/tests/test_write_validation.py`
- `apps/projects/forms.py`
- `apps/portals/forms.py`
- `apps/helpdesk/forms.py`
