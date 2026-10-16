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

The first full run reported 4,893 passed, 1 failed, 1 skipped. Its single failure was `tests/test_e2e_walkthrough.py::SmokeTest::test_end_to_end_walkthrough`, because the product category created by that established workflow is inactive. Product creation was adjusted to permit a non-deleted category owned by the active company, while continuing to reject cross-company categories. A final full run is in progress; its final counts will replace this section before delivery.

## Regression coverage added

- Company setup: blank names and malformed/inactive currency references do not create company or membership rows.
- Product creation: whitespace name/SKU and a foreign-company category are rejected without creating a product.
- Warehouse creation: a branch from another company is rejected without creating a warehouse.
- Vendor creation: blank name, invalid vendor type, and malformed payment terms are rejected without creating a vendor. Existing valid create/update tests remain in the targeted suite.
- Invoice service: missing lines, a foreign-company customer, and a non-positive line quantity are rejected before creating an invoice.

## Coverage limits and unverified forms

The full suite exercises broad existing workflows but does not establish exhaustive required-field validation across every form. See the UNVERIFIED inventory in `FORM_VALIDATION_AUDIT.md`. No PostgreSQL-specific behavior, browser JavaScript behavior, or complete DRF/AJAX invalid-input matrix was verified by this SQLite pytest run.

No schema or migration changes were made, so `makemigrations --check` and fresh database migration checks were not run as part of this validation task.
