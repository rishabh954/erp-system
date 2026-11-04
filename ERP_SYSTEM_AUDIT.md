# ERP System Audit

**Audit date:** 2026-11-04  
**Repository:** `rishabh954/erp-system`  
**Disposition:** **Not production-certified.** The system has substantial, test-covered functionality, but material tenant, financial, and audit-control risks remain. The initial audit was read-only; subsequent approved security remediations are recorded in Section 12.

## 1. Executive summary

The repository is a single Django project with **22 installed ERP applications**, a shared `core/` layer, Django templates, web routes, and both `/api/` and `/api/v1/` API surfaces. The `apps/` tree contains 438 Python files, including migrations and tests. The implemented functionality is materially broader than a menu-only prototype: CRM, sales, procurement, inventory, accounting, HRMS, manufacturing, workflow, portals, notifications, reporting, assets, projects, and help desk all have models and/or request handlers.

However, the presence of those modules does not establish end-to-end ERP automation. Most business journeys consist of independently callable transitions and still require an operator, a configured workflow, or an external provider. Several findings directly affect data confidentiality or financial correctness:

1. Authenticated dashboard responses are cached without a tenant/user cache key on four API endpoints.
2. Dashboard authorization uses the active tenant, while dashboard data is selected using the user's primary tenant.
3. POS accepts the unit price supplied by the browser and does not post an accounting entry.
4. Purchase-order creation and inventory-transfer services accept relationship IDs without consistently validating that all referenced records belong to the service's company.
5. Purchase-order creation and update calculate discounts differently; tax lookup errors can be converted into a tax-free line.
6. Payment processing does not serialize concurrent payments against an invoice; payment and journal idempotency depend on a check-then-create sequence.
7. Activity audit logging is best-effort and can fail without rolling back or blocking the business operation.

There are no findings that make every module unusable, and several controls are already present: company-scoped querysets and permissions, tenant-aware API relation fields, financial check constraints in core sales models, journal-posting locks, workflow transition tests, and restore-suppression logic. The test suite also passes in the SQLite environment described below. Those strengths do not resolve the specific gaps above.

**No module is classified as fully implemented and end-to-end verified.** Narrow behaviors have test evidence, but full production journeys, PostgreSQL concurrency, external integrations, and tenant-aware cache behavior have not been established.

## 2. Scope, evidence, and limitations

### Inspected

- Installed app list and root web/API URL includes in `config/settings.py` and `config/urls.py`.
- App source inventory: models, views, services, tasks, signals, API serializers/views/URLs, forms, migrations, and test files across all 22 apps.
- Shared models, tenancy resolution, middleware, permissions, service helpers, and API tenant mixins/fields under `core/`.
- Representative business paths for sales, purchasing, inventory, accounting, POS, HRMS, manufacturing, workflow, audit, notifications, portals, dashboards, and analytics.
- Existing documentation including `README.md`, installation and operations guides, accounting posting notes, production/audit reports, notification audit, and duplicate-functionality audit.
- Root, app, and core tests. A fresh SQLite database was also migrated using the repository's migrations.

### Verification results

| Check | Result | Interpretation |
|---|---|---|
| `py manage.py check` | Passed; no issues | Django's ordinary system checks passed in the current environment. |
| `py manage.py makemigrations --check --dry-run` | Passed; no changes detected | No model/migration drift was reported. |
| Fresh temporary SQLite `py manage.py migrate --noinput` | Passed | The checked-in migration chain applied to SQLite. PostgreSQL migration behavior remains unverified. |
| Full pytest run with default PostgreSQL configuration | **4,475 passed; 466 errors** | Errors were test-database setup failures: PostgreSQL returned `permission denied to create database`. These are environment/setup errors, not 466 demonstrated assertion failures. |
| Full pytest run with temporary SQLite and `--create-db` | **4,940 passed; 0 failed; 1 skipped; 0 errors** | 4,941 tests were collected. The SQLite run used `--nomigrations` from `pytest.ini`, so it did not test migrations; the separate fresh-database migration check did. |
| Coverage from SQLite run | **74%** (23,729 statements) | Aggregate `apps`/`core` coverage; this is not workflow-completeness coverage. |
| Warnings from SQLite run | **4,853** | Includes dependency/framework and API-schema warnings; review and reduce before release. |
| `py manage.py check --deploy` with audit-only secure environment variables | Exited 0; 95 non-security warnings; no `security.*` check IDs | This validates configuration paths with throwaway values, not the actual production environment or credentials. |

`core/tests/test_concurrency.py` explicitly skips its `select_for_update` concurrency case on SQLite. PostgreSQL is therefore required for meaningful concurrency and locking acceptance tests.

### Documentation reconciliation

Several repository audit documents are historical snapshots, not a current certification. For example, `FINAL_PRODUCTION_CERTIFICATION.md` reports an earlier total of 4,904 passing tests; the run in this audit discovered 4,941. Earlier claims about missing health endpoints, notification service/push preference, and company-role authorization also do not match current source. Current code has health routes, a tenant-aware `NotificationService`, a push preference flag, and `User.has_module_permission()` derives ordinary-user permissions from the active `UserCompany` role. Retain the useful historical work, but date and reconcile its claims before treating it as current evidence.

## 3. Module-by-module implementation classification

Categories: **1** fully implemented and verified; **2** partially implemented; **3** UI exists but backend is incomplete; **4** backend exists but UI is incomplete; **5** missing; **6** broken/failing path identified; **7** duplicate or unnecessary/inert functionality identified. A category describes the inspected implementation, not a product roadmap commitment.

| Module / feature | Classification | What is present and what remains unverified or missing |
|---|---|---|
| Dashboard | **2** | CEO, HR, Sales, and Finance API views and multiple web dashboards exist in `apps/dashboard/views.py`. Dashboard data accuracy, active-tenant selection, and authenticated cache isolation need correction and regression tests. No dedicated `apps/dashboard` test files were inventoried. |
| CRM and Leads | **2** | Lead, activity, territory, campaign, scoring/assignment, and customer conversion surfaces exist in `apps/crm/`. Lead-to-cash is not demonstrated as a single automated journey. |
| Customers | **2** | Customer records, APIs, CRM views, and customer portal exist. Portal and service relation boundaries need tests at all entry points. |
| Sales and Quotations | **2** | Quotation, approval/rejection, conversion, sales-order, delivery, returns, and invoice/payment services exist. Approval and fulfillment remain distinct transitions; full collection/reconciliation journey is not verified. |
| Orders, Invoices, and Payments | **2** | Models, web/API routes, services, financial posting hooks, and tests exist. Concurrent payment and duplicate-posting protections are not database-serialized end to end. |
| Purchase and Vendors | **2** | Vendor, request, order, RFQ/bid, receipt, bill, payment, and matching models/services/routes exist. Most transitions are staff initiated; request-to-payment automation is not verified. |
| RFQ and Purchase Orders | **2 / 6** | RFQ/bid and purchase-order workflow exist. Purchase-order edit has a confirmed discount-total discrepancy; service relationship validation and tax error handling need correction. |
| GRN and Supplier Bills | **2** | Goods receipts, three-way matching, bills, and accounting posting paths exist. Live receipt-to-bill-to-payment reconciliation is unverified. |
| Inventory and Warehouses | **2** | Products, variants, warehouses, stock records, movements, reservations, and low-stock notifications exist. Reorder automation stops at alerts; no verified automatic purchase-request creation. |
| Stock Movements and Transfers | **2** | Stock adjustment, receipt, delivery, and transfer services exist and use transactions/locks in selected paths. Service-level tenant relation checks and PostgreSQL contention tests are incomplete. |
| Accounting and Finance | **2** | Chart of accounts, journals, financial reports, fixed assets, depreciation, bank statements, and auto-journal helpers exist. Period close, full bank reconciliation, all source postings, and production concurrency are not certified. |
| GST and Taxation | **2 / 5** | Tax rates/groups, tax return records, and invoice e-invoicing/TDS fields exist. A stored tax return/e-invoice field is not evidence of filing or regulatory-provider integration. No verified end-to-end filing workflow. |
| HRMS and Payroll | **2** | Employee, attendance, leave, expenses, payroll, payslips, and scheduled attendance/payroll tasks exist. Statutory calculation, approval, salary settlement, and end-to-end payroll-to-ledger/payment are not certified. |
| Manufacturing and MRP | **2** | BOMs, routings, work centers, work orders, material plans, and production completion exist. Planner review and shop-floor input remain; no complete automated demand-to-procurement-to-produced-stock journey. |
| BOM and Work Orders | **2** | BOM lines and routing-generated work orders are implemented. Actual yield, scrap/quality sign-off, and full cost accounting are not verified across production. |
| Quality and Costing | **5 / 2** | No dedicated quality application or demonstrated inspection/hold/release workflow. `Product.needs_qa`, receipt accepted/rejected quantities, and average-cost fields provide only partial building blocks. |
| POS | **2 / 5** | Two POS routes support session display and checkout; checkout writes POS order/payment and stock movement. Price is client-controlled; tax and accounting posting are absent from this flow; returns/refunds are not exposed as a POS workflow. |
| Projects | **2** | Projects, tasks, milestones/sprints, time logs, risks, and tracking automation exist. No complete finance/resource-planning integration was demonstrated. |
| Help Desk | **2** | Tickets, replies, knowledge base, SLA task and customer ticket portal exist. Full escalation/provider delivery and SLA reporting are not certified. |
| Documents | **2** | Document categories, versions, approval, upload, download, and customer listing exist. Retention, malware scanning, and production storage/access-control behavior were not verified. |
| Assets | **2** | Assets, maintenance, depreciation entries and scheduled depreciation exist. Accounting and physical-inventory reconciliation remain operationally unverified. |
| Employee Portal | **2** | An employee dashboard route exists, but it is a limited portal surface rather than a verified complete employee self-service workflow. |
| Customer and Vendor Portals | **2** | Portal routes cover customer orders/invoices/tickets/documents/contracts/shipments and vendor orders/bills/payments. External-user onboarding, authorization, and full portal mutation flows need broader tests. |
| Workflow Center | **2** | Definitions, steps, triggers, approvals, delegation/escalation, notification templates, and idempotency tests exist. Automation depends on configured definitions and human approvals; not every business transition invokes the engine. |
| Enterprise Audit Center | **2** | `AuditEvent`, audit service/redaction/hash helpers and views exist alongside legacy `ActivityLog`/`AuditLog`. Coverage is not guaranteed for every write, and legacy service logging is best effort. |
| Notifications | **2 / 5** | Central service, preferences, in-app notifications, delivery logs and task wrappers exist. External provider delivery is configuration-dependent; the `push` branch stores a notification row rather than proving device push delivery. |
| Reports and Analytics | **2** | Saved/custom/scheduled reports, exports, preview, and data APIs exist. Data API materializes the full result before slicing; quick export accepts an unbounded limit; failures can appear as empty output. |
| Administration and Integrations | **2 / 3** | API keys, integrations/webhooks, app toggles, imports/exports, backups and administration routes exist. `ApprovalMatrix` has CRUD UI but no runtime approval consumer found. External integrations and disaster recovery are not live-tested. |
| API / Authentication / Company | **2** | JWT/API-key/session auth, company membership/selection, health endpoints, and module APIs exist. There are parallel legacy and versioned API surfaces; complete per-endpoint permission and tenant testing is still needed. |
| AI | **2** | Optional LLM/OCR/forecasting/recommendation services and UI/task surfaces exist. Requires provider configuration and was not verified against live credentials or production data. |

## 4. Critical and major findings

No finding below is labeled Critical because the audit did not establish a universal compromise or confirmed production incident. The following **High** items should be resolved before production certification.

### AUD-01 — Authenticated dashboard API responses can be shared across tenants/users

- **Severity / confidence:** High / 9 of 10.
- **Files and symbols:** `apps/dashboard/views.py`, `CEODashboardAPIView.get` (around lines 56–58), `HRDashboardAPIView.get` (313–315), `SalesDashboardAPIView.get` (393–395), and `FinanceDashboardAPIView.get` (454–456).
- **Problem:** Each endpoint applies Django `cache_page(15 minutes)` to authenticated company data, without a cache key explicitly scoped to the authenticated user and active company. The response is not demonstrated to vary on authorization or the active-company header. A shared cache can serve one tenant's cached dashboard response to another caller requesting the same URL.
- **Business/security impact:** Confidential employee, sales, finance, and company KPIs may be disclosed across tenants/users.
- **Recommended solution:** Remove shared page caching for authenticated responses or cache the computed payload under a key containing the validated user/company/permission context and relevant query parameters. Mark responses private where appropriate.
- **Required tests:** Two users/companies request the same endpoint/period in both orders; assert each gets only their own company data and switching the active-company header cannot reuse another tenant's entry. Exercise the configured production cache backend.

### AUD-02 — Dashboard permission context and data context disagree

- **Severity / confidence:** High / 8 of 10.
- **Files and symbols:** `apps/dashboard/views.py`, the four API view `get()` methods listed in AUD-01; permission evaluation is in `core/permissions.py::HasModulePermission`.
- **Problem:** Permission checks call `get_active_company(request)`, but the dashboard APIs query `request.user.primary_company`. When a multi-company user selects a different active tenant, authorization and displayed data refer to different companies.
- **Business/security impact:** A role granted dashboard access in one tenant may cause the endpoint to return primary-tenant data, which that role may not be entitled to view; users can also see stale/wrong-company KPIs.
- **Recommended solution:** Resolve the active company once after authentication and use that validated company consistently for both authorization and every dashboard query/cache key.
- **Required tests:** Multi-company users with different role permissions and distinct seeded data; cover absent, valid, and unauthorized active-company selections.

### AUD-03 — POS checkout trusts a browser-supplied unit price and omits tax/accounting posting

- **Severity / confidence:** High / 9 of 10.
- **Files and symbols:** `apps/pos/views.py::POSCheckoutAPIView.post` (around lines 118–174); `apps/pos/models.py::POSOrderLine` and `POSPayment`.
- **Problem:** The checkout total and persisted line price are calculated from `item["price"]` supplied by the client. The code checks only that price is non-negative; it does not re-derive the authorized price from `Product.sale_price` or a company price list, nor apply tax/discount rules. The checkout writes POS records and inventory movement but has no POS accounting/journal call in this flow.
- **Business impact:** A caller with checkout access can undercharge by changing the request price; sales tax and accounting revenue/inventory/COGS can be omitted from the ledger.
- **Recommended solution:** Treat product/price-list data as authoritative on the server; model authorized price overrides with explicit permission/audit reason; calculate tax/discounts using shared sales logic; post a balanced, idempotent journal entry within the checkout transaction.
- **Required tests:** Tampered and negative prices, permitted price overrides, tax rounding, stock rollback, payment method validation, and balanced/idempotent POS journal postings.

### AUD-04 — Business services do not consistently enforce company ownership of foreign-key inputs

- **Severity / confidence:** High / 8 of 10.
- **Files and symbols:** `apps/purchase/services.py::PurchaseOrderService.create_order` (around lines 137–143 and 196); `apps/inventory/services.py::TransferService.create_transfer` (around lines 313–354); related company-scoped models in `apps/purchase/models.py` and `apps/inventory/models.py`.
- **Problem:** Purchase order creation assigns submitted vendor, purchase request, contract, warehouse, and product IDs directly. Transfer creation assigns submitted warehouse IDs and creates lines from raw product IDs. The service company is attached to the new parent, but these company-owned related rows are not all loaded through a `company=self.company` queryset before saving. Django foreign keys alone do not enforce same-company ownership.
- **Business impact:** A forged or stale relation ID may create records whose parent company conflicts with vendor/product/warehouse/contract ownership, corrupting tenant isolation, stock ledgers, reporting, and accounting.
- **Recommended solution:** Validate every company-owned related record at the service boundary (including each line), reject mismatches with explicit validation errors, and add database constraints where the schema can enforce them. Do not rely solely on UI select options.
- **Required tests:** Cross-company vendor, product, request, contract, warehouse, currency/tax, and transfer endpoint/service submissions; verify no parent, line, movement, or audit side effect is committed.

### AUD-05 — Purchase-order update overstates discounted totals; tax lookup failures can silently remove tax

- **Severity / confidence:** High / 9 of 10.
- **Files and symbols:** `apps/purchase/services.py::PurchaseOrderService.create_order` and `update_order` (around lines 187–220 and 238–307).
- **Problem:** Creation sums discounted taxable values into the header (`subtotal += taxable`), while update sums the pre-discount amount (`subtotal += sub`) and does not populate the header discount amount in the same way. Editing a draft can therefore increase its total relative to creating the same order. Both paths also catch broad exceptions during tax lookup/computation, log a warning, clear the tax ID, and continue with a tax-free line. The logic is duplicated and diverges.
- **Business impact:** Incorrect supplier commitments and payable totals; a transient database or malformed tax error may silently produce an under-taxed purchase order.
- **Recommended solution:** Extract one shared line parser/calculator used by create and update; persist subtotal, discount, tax and total with a single documented convention; reject invalid/unavailable tax IDs rather than falling back to zero tax. Narrow exception handling to expected validation errors.
- **Required tests:** Create vs edit parity for discounts and taxes, malformed/missing tax ID, tax-provider/database exception, rounding, and no partial mutation when validation fails.

### AUD-06 — Concurrent payments can over-apply an invoice and race journal idempotency

- **Severity / confidence:** High / 8 of 10.
- **Files and symbols:** `apps/sales/services.py::PaymentService.record_payment` (around lines 938–955) and `SalesService.process_payment` (around lines 289–310); `apps/sales/models.py::Invoice.update_balance` and `Payment.save` (around lines 372–388 and 485–500); `apps/accounting/models.py::JournalEntry`.
- **Problem:** Payment services do not lock/reload the invoice before checking available balance. `Invoice.update_balance()` aggregates payments then writes the invoice balance without serializing competing payments. `Payment.save()` and `Invoice.save()` use “journal reference exists?” followed by create/post, but journal references are not protected by a demonstrated unique constraint.
- **Business impact:** Concurrent payment requests can record an aggregate payment greater than the invoice total while leaving a stale balance; retries/concurrent saves can create duplicate journal entries or mismatched receivables.
- **Recommended solution:** Lock the invoice row before validating and recording a payment, enforce amount not greater than outstanding balance according to documented policy, and make source-document posting idempotency a database-enforced invariant. Keep payment, balance update, and journal posting atomic.
- **Required tests:** PostgreSQL concurrent payments at/over remaining balance, retry of identical payment, simultaneous invoice posting, rollback on journal failure, and ledger-to-payment reconciliation.

### AUD-07 — Activity audit writes can fail without failing the business transaction

- **Severity / confidence:** High / 8 of 10.
- **Files and symbols:** `core/services.py::BaseService.log_activity` (around lines 93–117); `core/middleware.py::AuditLogMiddleware` (around lines 36–44); `apps/administration/services/audit.py::AuditService`.
- **Problem:** `log_activity()` catches all exceptions from `ActivityLog.objects.create`, emits a warning, and lets the business operation continue. `AuditLogMiddleware` currently only forwards the request/response; it does not create an audit event. The separate `AuditService` and `AuditEvent` implementation is not shown to be a transactional, universal audit path for all mutations.
- **Business impact:** Finance, approval, and administrative state changes can persist without a durable audit record, weakening incident response and compliance evidence.
- **Recommended solution:** Define which events require mandatory audit. For those events, write the audit record in the same transaction or use a durable outbox with monitored retry; surface audit-storage failure instead of success-shaped continuation. Keep best-effort behavior only for explicitly non-compliance telemetry.
- **Required tests:** Simulate audit database failure for critical mutations and verify either transaction rollback or durable outbox/retry; test actor/company/resource attribution and secret redaction across web/API/task paths.

## 5. Other significant bugs and security findings

### AUD-08 — Analytics exports permit spreadsheet formula payloads and unbounded report materialization

- **Severity / confidence:** Medium / 8 of 10.
- **Files and symbols:** `apps/analytics/services.py::export_csv` (around lines 197–205) and `get_data` (172–191); `apps/analytics/views.py::QuickExportView.get` (around lines 320–336) and `ReportDataAPIView.get` (around lines 373–390).
- **Problem:** CSV cells are passed directly to `csv.DictWriter`, so user-controlled text beginning with spreadsheet formula markers is not neutralized. Quick export accepts a client-provided `limit` without a maximum. The report data API calls `get_data(..., limit=None)`, loads every matching record into a Python list, then paginates that list in memory. `get_data` catches broad exceptions and returns `[]`, which makes invalid query/sort failures appear as successful empty reports.
- **Business/performance impact:** Spreadsheet formula execution on opening exported files; memory/latency exhaustion on large tenants; incorrect reports silently presented as empty.
- **Recommended solution:** Neutralize formula-leading cells on CSV export; enforce bounded server-side page/row limits; paginate at the queryset level; log and return explicit validation/error responses for invalid fields, filters, and query failures.
- **Required tests:** Formula marker values in CSV, huge/negative limits, large query pagination, invalid sort/filter, and database failure must not return success-shaped empty data.

### AUD-09 — Custom-role RBAC and approval-matrix configuration are not connected to runtime enforcement

- **Severity / confidence:** Medium / 9 of 10.
- **Files and symbols:** `apps/authentication/models.py::User.has_module_permission`, `Role`, `Permission`, and `ModulePermission` (around lines 167–185 and 255–323); `apps/authentication/api/views.py::RoleViewSet`; `apps/administration/models.py::ApprovalMatrix` and its CRUD views; `apps/workflow/engine.py`.
- **Problem:** Runtime authorization looks up `ModulePermission` using the active `UserCompany.role` string. The separate company-owned `Role`/`Permission` models and Role API do not appear in that effective permission lookup, so custom role configuration is not shown to grant/restrict runtime module actions. Separately, `ApprovalMatrix` has CRUD UI/storage but no in-repository workflow consumer; active approvals use the workflow engine.
- **Business impact:** Administrators may believe custom roles or amount thresholds are enforced when the code path actually uses a different permissions/approval mechanism.
- **Recommended solution:** Choose and document one authoritative RBAC model and one approval-routing source. Wire the chosen model through assignment and authorization or clearly deprecate the inert configuration after confirming no external clients depend on it.
- **Required tests:** End-to-end create/assign/revoke custom role then access each module; configure amount thresholds and verify they affect actual purchase/sales approvals; test tenant isolation.

### AUD-10 — Tracked rotated application log is a potential privacy exposure

- **Severity / confidence:** Medium / 10 of 10 that it is tracked; contents not inspected.
- **File:** `logs/erp.log.1` (tracked; approximately 10 MB). `config/settings.py` configures log fields including user ID, company ID, client IP and request path.
- **Problem:** A rotated runtime log is committed to the repository. Its contents were deliberately not read or reproduced during this audit; therefore exposure of any specific credential or personal data is **not asserted**.
- **Business/security impact:** Historic user/company identifiers, IP addresses, request paths, or exception data may be distributed through clones, forks, and backups if present in the file.
- **Recommended solution:** Review the artifact in a controlled environment, remove/scrub it from repository history if it contains sensitive data, rotate any exposed credentials if found, and keep runtime logs/backups excluded from source control.
- **Required tests/checks:** Repository history and secret-scanning review; verify `.gitignore` and CI do not re-add runtime logs. The tracked empty `config/google_credentials.json` was also observed, but it is 0 bytes and no credential is evidenced there.

### AUD-11 — Purchase service validation and audit/event coverage is inconsistent

- **Severity / confidence:** Medium / 8 of 10.
- **Files and symbols:** `apps/purchase/services.py::PurchaseRequestService.create_request/update_request`; `PurchaseOrderService.create_order/update_order`; `core/services.py::BaseService.log_activity`.
- **Problem:** Repeated line parsing indexes parallel submitted arrays independently and does not consistently validate equal lengths, positive quantities, finite values, or relation ownership in the service. In multiple operations broad exception handling converts failures to warnings/fallback behavior. This is the same duplicated logic that caused AUD-05.
- **Business impact:** Malformed requests may produce partial or incorrect purchase documents; failures can be difficult to detect and reconcile.
- **Recommended solution:** Reuse validated forms/serializers or a shared domain parser at service boundaries; preserve transactional rollback and explicit error responses.
- **Required tests:** Missing/misaligned form rows, negative/zero/infinite values, invalid IDs, concurrent updates, and failure injection.

## 6. Duplicate and unnecessary functionality

These are consolidation candidates, not deletion instructions. Do not remove any surface until product and client compatibility are confirmed.

| Candidate | Evidence | Audit conclusion / next step |
|---|---|---|
| Two RBAC models | `Role`/`Permission` alongside enum-valued `UserCompany.role` and `ModulePermission` | Runtime `has_module_permission` consumes `ModulePermission`; clarify the canonical model before extending or removing either. See AUD-09. |
| `ApprovalMatrix` versus workflow definitions | Administration has create/list/delete UI; repository search found no runtime consumer. `WorkflowEngine` is used by active document flows. | ApprovalMatrix appears inert/unfinished rather than a second functioning approval engine. Confirm product use and external integrations before deprecation. |
| Duplicate purchase-order line calculations | `PurchaseOrderService.create_order` and `.update_order` repeat row parsing/tax/discount logic and disagree on header subtotal. | Consolidate the calculation to correct the existing defect, not as a speculative cleanup. See AUD-05. |
| Unused invoice-total helper | `SalesOrderService.calculate_invoice_totals()` has no in-repository call site; `Invoice.recalculate_totals()` independently computes persisted header totals. | Confirm external callers; retain until compatibility is known, then remove or make it the single shared calculator. |
| Parallel API surfaces | `/api/` generic serializers/viewsets coexist with `/api/v1/` per-app APIs and their serializers. | Some overlap is likely legacy compatibility; map clients and document a preferred version before deprecating. |
| Audit records | `ActivityLog`, administration audit records, and `AuditEvent` are distinct storage paths with overlapping event concepts. | Keep separate records only where their purposes and retention differ; define a central event contract and source mapping. |
| Notification entry points | `NotificationService` has compatibility aliases and task wrappers; producers call the central service in many places. | No second notification framework was established. Do not duplicate or replace it without tracing older direct producers. |

## 7. Automation verification

“Automated” below means that code exists for a segment; it does not mean the entire business process is hands-free or production-certified.

| Requested workflow | Status from source inspection | Manual step / gap |
|---|---|---|
| Lead → Customer → Quotation → Sales Order → Invoice → Payment | **Partial** | CRM conversion, quotation approvals/conversion, invoice creation, and payment recording exist as separate operations. Qualification, approvals, collection, and full customer-to-ledger journey are not demonstrated as one automated flow. |
| Purchase Request → Approval → RFQ → Purchase Order → GRN → Vendor Bill → Payment | **Partial** | Request/approval, RFQ/bid, PO, receipt, bill, and payment services exist. Approval/workflow configuration, vendor selection, receiving, bill approval, and settlement remain operator-controlled. |
| Sales → Stock Reservation → Delivery → Stock Deduction | **Partial** | Sales order confirmation reserves stock; delivery service deducts stock and releases reservation. Full workflow invocation, partial shipments, retries, and PostgreSQL concurrency are not certified end to end. |
| Stock Reorder → Purchase Request | **Not automated** | Low-stock task sends alerts; no confirmed automatic purchase-request creation was found. Procurement decision/creation remains manual. |
| Invoice → Journal Entry → Receivable | **Partially automated** | Invoice save posts an auto-journal for SENT/PARTIAL/PAID statuses. Verify posting under retries, concurrent status changes, and all invoice/credit-note pathways. |
| Payment → Reconciliation → Journal Entry | **Partial** | Completed payment save invokes journal posting. Bank statement models and lines exist, but payment matching/reconciliation remains a separate operational flow and was not verified as automatic. |
| Employee Attendance → Payroll → Salary Payment | **Partial** | Scheduled attendance and payroll task/service paths exist. Payroll approval/statutory review and salary payment/provider/bank execution are not automatically demonstrated. |
| BOM → Material Planning → Work Order → Production → Finished Goods | **Partial** | MRP computes shortages, routing can generate work orders, and manufacturing completion posts inventory movements. Planning does not establish automatic purchasing; actual yield, quality release, and full accounting are not verified. |
| POS Sale → Inventory Update → Accounting Entry | **Partial / broken accounting gap** | Checkout creates POS order/payment and stock movement. It does not derive trusted pricing, apply tax, or create an accounting entry in the checkout path. |
| Approval → Notification → Audit Event | **Partial** | Workflow actions and notifications exist, but the workflow engine is not demonstrated as a universal approval path and central audit-event emission is not guaranteed for every transition. |

## 8. Database and architecture problems

1. **Tenant integrity is largely application-enforced.** `CompanyScoped` makes a company mandatory on the parent record, but ordinary foreign keys do not enforce that a customer, vendor, product, warehouse, tax, account, or user relation belongs to the same company. Service-level checks are therefore essential; AUD-04 identifies concrete gaps.
2. **Transaction and row-locking practices are uneven.** Journal posting, workflow transitions, MRP execution, and some stock operations use `transaction.atomic`/`select_for_update`; not all state changes and payment paths do. A passing SQLite suite does not prove PostgreSQL locking behavior.
3. **Financial invariants are not uniformly database-enforced.** Sales documents include several amount/line constraints and sequence uniqueness, but constraints are not consistent across POS, procurement, stock, and all related-tenant relationships. Model `save()` does not automatically call `full_clean()`.
4. **Auto-journal idempotency is not uniformly database-enforced.** Several producers use a source reference and an existence check. A unique constraint or locked source-document transition is needed to prevent two concurrent checks from both creating entries.
5. **The service layer is inconsistent.** Some modules centralize domain transitions; others perform calculation/state changes in model `save()`, views, tasks, or duplicated service methods. This complicates transaction scope, audit guarantees, and API/web behavioral parity.
6. **Migration evidence is partial.** Model drift check and fresh SQLite migration passed. PostgreSQL-specific migration, index, constraint, and lock behavior was not run. The ordinary pytest command disables migrations.

## 9. Performance and operational risks

- **Unbounded report materialization:** `ReportDataAPIView` fetches all matching rows and then slices in Python; QuickExport accepts a user-supplied limit without an observed upper bound. Large tenants can cause high memory use and slow responses (AUD-08).
- **Dashboard cache safety precedes cache tuning:** a 15-minute shared cache may improve performance, but the key must be tenant/user-safe before use on authenticated data (AUD-01).
- **No workload evidence:** no production-like query plans, large-tenant load test, PostgreSQL pool/load profile, or broker/provider throughput run was available. Treat index/performance claims in historical docs as candidates, not verified bottlenecks.
- **Operational dependencies remain unverified:** Redis, Celery workers/beat, email/SMS/WhatsApp/push providers, webhooks, backup storage, and restore under production conditions were not exercised.
- **API schema warnings:** deployment checks emitted 95 non-security warnings, many from schema generation. Review and resolve schema inaccuracies before treating the OpenAPI contract as authoritative.

## 10. Test audit

### Executed results

- **Discovered:** 4,941
- **SQLite full suite:** 4,940 passed; 0 failed; 1 skipped; 0 errors; 4,853 warnings; 74% aggregate coverage.
- **PostgreSQL-configured attempt:** 4,475 passed and 466 errors because the database role could not create the test database. It is not valid to report that run as a clean pass.
- **Migration check:** no pending model-generated migrations; fresh SQLite migration chain completed successfully.
- **Django checks:** standard `check` passed; `check --deploy` exited successfully with audit-only settings and no Django `security.*` warning IDs. This does not certify deployed settings.

The one skipped test is the concurrency test in `core/tests/test_concurrency.py`, which skips `select_for_update` concurrency on SQLite. Existing tests cover many isolated transitions (`tests/test_sales_workflow.py`, `tests/test_purchase_workflow.py`, `tests/test_inventory_services.py`, `tests/test_financial_flows.py`, `tests/test_hrms.py`, `tests/test_e2e_walkthrough.py`, `apps/pos/tests/test_views.py`, and workflow reliability tests). The full-suite audit pass did not cover POS price-tampering/accounting, concurrent PostgreSQL payment behavior, a cross-company service-relation matrix, or purchase discount-edit parity. Follow-up tests for the dashboard, workflow API, analytics exports, and company-specific project visibility are recorded in Section 12.

## 11. Prioritized implementation roadmap

### P0 — Security and financial integrity (before production)

1. **Partially remediated in Section 12:** remove unsafe authenticated dashboard caches and use the validated active company for dashboard API, search, calendar, and page queries. Other security and financial-integrity work remains.
2. Derive POS prices/taxes on the server; add authorized discount/override handling and atomic balanced POS accounting.
3. Validate every company-owned foreign key at purchase, transfer, stock, and API service boundaries.
4. Unify PO create/update calculations; fail closed on invalid tax references and cover discounts/tax rounding.
5. Serialize invoice payments on PostgreSQL; validate outstanding amount; enforce idempotent journal posting at database/source-transition level.
6. Define mandatory audit events and make critical audit persistence durable and observable.
7. Review tracked `logs/erp.log.1`; purge/rotate credentials if any sensitive data is found.

### P1 — Complete business workflows

8. Add documented end-to-end journeys for lead-to-cash and request-to-supplier-payment, including human approval and exception handling.
9. Connect low-stock alerts to an approved replenishment/purchase-request process.
10. Define payment reconciliation and close workflows; test receivables/payables and source journals end to end.
11. Close POS return/refund, external push delivery, employee self-service, GST filing, and quality inspection gaps or explicitly scope them out.
12. Validate MRP/production actual yield, scrap, quality release, costing, and finished-goods accounting.

### P2 — Architecture, evidence, and maintainability

13. Resolve the authoritative RBAC/custom-role model and retire or wire the unused `ApprovalMatrix`.
14. Map `/api/` legacy consumers to `/api/v1/`; document compatibility and permissions.
15. Reconcile `ActivityLog`, `AuditLog`, and `AuditEvent` retention, ownership, and source contracts.
16. Bound and queryset-paginate report data; neutralize CSV formula cells; surface report failures explicitly.
17. Add PostgreSQL CI/integration coverage for migrations, locks, tenant integrity, and payment/stock concurrency; resolve repeated warnings.
18. Run production-like Redis/Celery/provider tests and perform a timed backup/restore drill before changing the certification status.

**Initial audit completion:** no application code, migrations, or settings were modified during the audit. Approved security fixes are documented below; the ERP remains not production-certified.

## 12. Approved security remediation follow-up

The following changes were made after approval to fix the identified security findings. This is a focused remediation, not a complete implementation of every security and RBAC requirement in the broader Section 2 request.

| Finding | Remediation | Files |
|---|---|---|
| Authenticated dashboard responses could cross users/tenants through shared page caching; dashboard data used the primary company instead of the validated active company. | Removed the four shared cache decorators. CEO, HR, Sales, Finance, global search, calendar, and dashboard page queries now resolve the tenant with `get_active_company`; unavailable tenant context is denied by API responses rather than returning company-less data. | `apps/dashboard/views.py` |
| Several visibility and action checks used global `User.role` instead of the active company membership role; lead forms used the primary company for related choices. | Updated affected project, helpdesk, CRM, purchase-request, sales-commission, and leave-request checks to use `get_role_for_company(self.company())`. Leave-request owner lookup and lead form user/campaign choices are constrained to the active company. | `apps/projects/views.py`, `apps/helpdesk/views.py`, `apps/crm/views.py`, `apps/purchase/views.py`, `apps/sales/views.py`, `apps/hrms/views.py` |
| Workflow instance API returned an unscoped `WorkflowInstance.objects.all()` queryset. | Applied the existing `TenantScopedViewSetMixin` to the read-only viewset, retaining its `workflow.read` permission while restricting list and detail lookups to the active company. | `apps/workflow/api/urls.py` |
| Saved-report and quick exports required only analytics read permission. | Changed both export endpoints to require `analytics.export`; non-export users are denied while users granted export permission retain access. | `apps/analytics/views.py` |

### Verification

- Added regression coverage in `tests/test_security_hardening.py` for sequential dashboard requests to different active companies, workflow API list/detail isolation, analytics export denial/allowance, and company-specific project visibility.
- Ran `tests/test_security_hardening.py`, `tests/test_active_company.py`, and `tests/test_scoped_lookups.py` using temporary SQLite: **19 passed, 0 failed**.
- `python manage.py check`: **passed**, no issues.
- No model or migration changes were made.
- The default PostgreSQL-configured test attempt could not create its test database due to database-role permissions; this was an environment error, not a passing PostgreSQL test.

### Remaining risks and scope limits

- These changes do not certify the ERP as secure and do not implement or verify the full Section 2 checklist. Other tenant-sensitive routes, serializers, exports, background tasks, document/file access, and approval flows still require a complete follow-up audit and test matrix.
- The user role choices still do not provide every requested built-in role (including Department Manager, Accountant, Sales Executive, Auditor), and the company-scoped custom `Role`/`Permission` models are not wired into the active authorization path. The existing RBAC architecture remains inconsistent in this area; no second role system or database migration was introduced here.
- Tenant-aware dashboard caching was removed rather than reintroduced with a tenant-and-user cache key. This prioritizes confidentiality but may reduce dashboard performance.
- The targeted test subset passed; the full suite and PostgreSQL-specific isolation/concurrency behavior were not rerun during this remediation.
