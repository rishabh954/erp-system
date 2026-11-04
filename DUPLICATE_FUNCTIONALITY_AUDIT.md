# Duplicate Functionality and Unnecessary Code Audit

**Inspection date:** 2026-10-23  
**Repository:** `rishabh954/erp-system`  
**Branch / commit inspected:** `main` / `bd2472f74b8c653c1b3a4f7753c79a7085e405ac`  
**Working tree at inspection:** contained the prior HRMS leave consolidation and its audit/test-report edits; no unrelated changes were present.  
**Scope:** read-only source, URL, template, task, migration and test inspection before the one narrow consolidation documented under DF-01. No database fields, models, URLs, templates or migrations were removed.

## Executive summary

The ERP has 22 app directories, a shared `core/` layer, `config/`, and 54 app test files. Static inventory found multiple legitimately similar concepts: sales receivables and purchase payables, document snapshots and calculated headers, stock balance caches and movement ledgers, and three audit records with different purposes. Similar names alone do not justify consolidation.

Two confirmed implementation duplications affected state transitions. HRMS API leave approval independently changed the request status and omitted balance updates and activity logging. Sales quotation approval had separate web/API transitions, with the API accepting rejected quotations and the web path not recording the approver. Both now use shared domain services with regression coverage.

Two additional cleanup candidates are documented but retained: `ApprovalMatrix` has UI and storage but no runtime consumer in the inspected repository, and `SalesOrderService.calculate_invoice_totals` has no in-repository caller while duplicating persisted invoice recalculation. Both may be externally consumed or represent unfinished configured functionality, so removal needs compatibility/product evidence.

Notification producers use several thin entry points, but those entry points mostly delegate to the existing `NotificationService`; the workflow engine also uses that service for in-app, email and WhatsApp delivery. No second notification framework was found. Avoid replacing the existing wrappers until their compatibility use is established.

## Inventory inspected

The repository has these 22 Django app directories:

`accounting`, `administration`, `ai`, `analytics`, `api`, `assets`, `authentication`, `company`, `crm`, `dashboard`, `documents`, `helpdesk`, `hrms`, `inventory`, `manufacturing`, `notifications`, `portals`, `pos`, `projects`, `purchase`, `sales`, and `workflow`.

Inventory covered app configs and their registration/import paths; concrete model modules and migrations; web and API URL configurations, views, serializers and forms; templates and `{% url %}` references; model signals; Celery tasks and configured schedules; management commands; service modules; shared `core/` models/services/middleware; and app tests. A repository-wide static search and call-site review was used for candidate duplicate names. It cannot reveal calls made by untracked external clients, runtime-generated imports, or production data/configuration.

Key shared entry points include `core.models.CompanyScoped`, `core.services.BaseService` (including notification/email delegation and sequence generation), `apps.notifications.services.NotificationService`, `apps.workflow.engine.WorkflowEngine`, and `apps.accounting.services.AutoJournalService`.

## Findings

### DF-01 — HRMS leave approval has two implementations

- **Severity:** High (business state consistency). **Confidence:** High. **Status:** Confirmed duplicate behavior.
- **Implementation A:** `apps/hrms/services.py:169`, `LeaveService.process_leave`, used by `apps/hrms/views.py:637` from `LeaveApproveView`.
- **Implementation B:** `apps/hrms/api/views.py:141` and `:155`, `LeaveRequestViewSet.approve` and `.reject`, update the same `LeaveRequest` directly.
- **Evidence:** both endpoints act on pending leave requests. The service writes `approved_at`, updates the matching `LeaveBalance` (`used` and `pending`), and calls `log_activity`. The API approval writes only `status` and `approved_by`; API rejection sets `approved_by` and reason but does not use the service's audit path. Both are registered public entry points, so the behavior is not dead code.
- **Action:** Consolidate API approve/reject through `LeaveService`, preserving response shape and permission behavior. Keep API queryset ownership checks; have the service receive the active company. Add API regression tests for balance updates, audit activity, rejection and tenant isolation.
- **Files:** `apps/hrms/api/views.py`, `apps/hrms/services.py` only if service ownership validation must be strengthened, `apps/hrms/tests/`.
- **Risk:** Service currently accepts a model instance and assumes the caller has scoped it. Keep API lookup scoped and avoid changing the service's public result/response contract.

### DF-09 — Sales quotation approval had divergent web and API transitions

- **Severity:** High (approval integrity and permission consistency). **Confidence:** High. **Status:** Confirmed duplicate behavior; consolidated.
- **Implementation A:** `apps/sales/views.py:254`, `QuotationApproveView`, rejected converted/rejected quotations but wrote only `status`.
- **Implementation B:** `apps/sales/api/views.py:286`, `QuotationViewSet.approve`, set `approved_by` but had no status guard. Its generic POST permission mapping also required `sales.create`, while the web route requires `sales.approve`.
- **Authoritative implementation:** `apps/sales/services.py` `QuotationService.approve_quotation` now locks and reloads the quotation within `self.company`, applies the existing web rule against converted/rejected states, and records `approved_by`. Web and API call it. The API action maps `send`, `approve` and `convert_to_order` to the same `sales.approve` permission used by the web actions.
- **Action:** Consolidate and preserve both route contracts; done. API returns a 400 for invalid state and 403 without approval permission. Web keeps redirect/message behavior.
- **Files:** `apps/sales/services.py`, `apps/sales/views.py`, `apps/sales/api/views.py`, `tests/test_view_coverage.py`.
- **Regression coverage:** web approval records approver; API approval records same state/approver; rejected quotation cannot be approved through API; create-only user is denied; existing cross-company web test remains.
- **Risk:** The API status guard now matches the existing web rule; clients that previously approved rejected/converted quotations will receive a 400. That prior behavior bypassed the web workflow's explicit restriction.

### DF-02 — ApprovalMatrix is an unused runtime configuration path that overlaps workflow configuration

- **Severity:** Medium. **Confidence:** High for no in-repository execution consumer; medium for product-level obsolescence. **Status:** Confirmed inert at runtime, potentially unfinished/legacy feature.
- **Implementation A:** `apps/administration/models.py:156`, `ApprovalMatrix`, stores document type, amount thresholds and approver. `apps/administration/views.py:364` and `:398` provide company-scoped listing/create/delete UI.
- **Implementation B:** `apps/workflow/models.py:21` and `apps/workflow/engine.py:28` provide company-owned definitions, trigger conditions, steps, approvers, routing and workflow execution.
- **Evidence:** repository search finds `ApprovalMatrix` referenced by its model, migration and CRUD views only. Purchase orders trigger `WorkflowEngine` (`apps/purchase/views.py:673`); inventory transfers also trigger it (`apps/inventory/services.py:377`). No execution code reads `ApprovalMatrix`. The workflow engine is therefore the active generic approval path; `ApprovalMatrix` appears to promise configurable threshold approval but does not route documents.
- **Action:** Keep both data and UI pending product-owner review. If `ApprovalMatrix` is confirmed obsolete, plan a deprecation notice and staged removal; do not delete its table or existing company configuration in this audit.
- **Files:** Potential future work in `apps/administration/models.py`, `apps/administration/views.py`, `apps/administration/urls.py`, its template and migrations; no removal performed.
- **Regression tests required before removal:** configuration export/data migration validation, route/template reference checks, and workflow threshold behavior tests if the active workflow is intended to replace it.

### DF-03 — Invoice total calculation has an unreferenced duplicate helper

- **Severity:** Low. **Confidence:** High for no in-repository call site; medium for external compatibility. **Status:** Confirmed overlapping implementation; deletion uncertain.
- **Implementation A:** `apps/sales/services.py:270`, `SalesService.calculate_invoice_totals`, computes subtotal, tax, discount and total from invoice lines and returns a dict without saving.
- **Implementation B:** `apps/sales/models.py:339`, `Invoice.recalculate_totals`, computes and persists the same four totals, then updates the invoice balance.
- **Evidence:** whole-repository Python search finds only the helper definition for `calculate_invoice_totals`; application callers use `Invoice.recalculate_totals` (for example `apps/sales/services.py:916` and sales views). No API caller was found in the inspected source.
- **Action:** Keep for now because it is a public service method and its read-only return shape differs from the model method. Confirm SDK/plugin consumers first; then either deprecate it or have it delegate to a pure calculation helper shared with `Invoice.recalculate_totals`.
- **Files:** `apps/sales/services.py`, `apps/sales/models.py`, affected tests if confirmed safe.
- **Risk:** External integrations may import the method. A refactor must preserve Decimal semantics and must not invoke balance updates or journal posting unexpectedly.

### DF-04 — Notification creation has multiple wrappers, but no second framework

- **Severity:** Low. **Confidence:** High. **Status:** Similar entry points; behavior mostly centralized.
- **Implementation A:** `apps/notifications/services.py:15` defines the authoritative `NotificationService`, including company resolution, active-membership checks, per-company channel preferences, logs/provider handoff and restore guards.
- **Implementation B:** `core/services.py:119` exposes `BaseService.send_notification`/`send_email`; `apps/notifications/services.py:193` and `:230` expose compatibility aliases; `apps/notifications/tasks.py:88` exposes the Celery bulk entry point. Workflow and module producers call these APIs.
- **Evidence:** `BaseService` delegates to `NotificationService`; the bulk task filters eligible users and delegates to `NotificationService.send_bulk`; workflow engine in-app/email/WhatsApp branches also call `NotificationService`. Direct `Notification.objects.create` in production code is confined to `NotificationService` in this scan.
- **Action:** Keep wrappers, aliases and task boundaries. Prefer `NotificationService` in new producers. Do not rewrite workflow channel handling without tests for configured templates, channel preferences, delivery logs, task timing and restore suppression.
- **Files:** `apps/notifications/services.py`, `apps/notifications/tasks.py`, `apps/workflow/engine.py`, `core/services.py`, module task producers.
- **Regression tests required for any later consolidation:** recipient membership, company preferences, each channel/log, retry behavior, delivery enqueue timing and `is_restoring()` suppression.

### DF-05 — Similar payment models are distinct ledgers

- **Severity:** Informational. **Confidence:** High. **Status:** Not a duplicate; preserve.
- **Implementation A:** `apps/sales/models.py:442` `Payment` belongs to a customer invoice and represents accounts receivable.
- **Implementation B:** `apps/purchase/models.py:569` `Payment` belongs to a vendor bill and represents accounts payable; `apps/pos/models.py:84` `POSPayment` is the tender record for a POS order/session.
- **Evidence:** distinct foreign keys, services (`apps/sales/services.py`, `apps/purchase/services.py`), workflows and accounting posting paths.
- **Action:** Keep separate models and service boundaries. A shared abstract field mixin could reduce declarations later, but should only be considered if it does not obscure different posting, refund and reconciliation rules.
- **Regression tests:** retain sales, purchase and POS payment/accounting and tenant-isolation suites.

### DF-06 — Audit models serve different retention and subject scopes

- **Severity:** Informational. **Confidence:** High. **Status:** Not a duplicate; preserve.
- **Implementation A:** `apps/administration/models.py:523` `AuditEvent` is the central event/security record with actor type, correlation, request metadata, risk, result and hash-chain fields; written through `apps/administration/services/audit.py`.
- **Implementation B:** `apps/administration/models.py:647` `AuditLog` is field-level model change history produced by administration signals; `apps/accounting/models.py:600` `AuditLog` records journal-entry lifecycle actions.
- **Evidence:** distinct fields, producers, views and query use; restore tests assert administration audit row preservation. Accounting log is tied to a specific journal entry and action.
- **Action:** Keep all three until retention, integrity and consumer requirements are reconciled. Consider naming clarification only through a compatibility migration.
- **Regression tests:** audit signal, audit chain, journal audit and restore round-trip tests.

### DF-07 — Repeated amount and stock fields are denormalized operational values, not proven duplicates

- **Severity:** Medium. **Confidence:** High that values serve different read/write roles; exact freshness guarantees need continued review. **Status:** Preserve with integrity tests.
- **Implementation A:** line-level amounts and header totals appear on quotations, sales orders, invoices, purchase orders, bills and POS orders (e.g. `apps/sales/models.py:32, 73, 99, 159, 208, 234, 294, 339`; `apps/purchase/models.py:267, 308, 350, 467, 482`; `apps/pos/models.py:50, 78`).
- **Implementation B:** `Invoice.amount_paid`/`balance_due` and bill equivalents are materialized from completed payment rows; `StockRecord.quantity_on_hand` is the current balance while `StockMovement` is its event ledger (`apps/inventory/models.py:281, 324`).
- **Evidence:** models recalculate headers from lines; payment save paths update balances; stock services update balance records and write movement rows. These values support filtering/reporting and historical accounting operations.
- **Action:** Do not remove fields. Audit all write paths for consistency and add/retain reconciliation tests; consolidate calculation internals only after mapping every caller and rounding rule.
- **Regression tests:** total/tax/discount/rounding, partial/full payment and ledger reconciliation; stock movement vs on-hand/reserved balance checks.

### DF-08 — Document lifecycle approval and Workflow Center have overlapping capability but separate contracts

- **Severity:** Low. **Confidence:** Medium. **Status:** Overlapping but independently required unless product policy says otherwise.
- **Implementation A:** `apps/documents/models.py:31` has document-specific lifecycle states; `apps/documents/views.py:226` directly approves a document.
- **Implementation B:** `apps/workflow/engine.py:28` can approve generic company documents using content types, configured steps, history, delegation and escalation.
- **Evidence:** Document approval route is registered (`apps/documents/urls.py:20`); search shows no automatic call from `DocumentApproveView` into `WorkflowEngine`. Generic workflow behavior has separate config and action history.
- **Action:** Preserve both until the document policy and workflow integration expectation are specified. If generic approval should govern documents, integrate it behind existing routes and test lifecycle/history compatibility before removing direct approval.
- **Files:** Potential future change in `apps/documents/views.py`, `apps/workflow/engine.py` and document/workflow tests.

## Model and field review

No duplicate database field or model was removed. The repeated names `company`, `created_at`, `updated_at`, `status`, `amount`, `total`, `balance_due` and `quantity` are used across distinct tenant records and business lifecycles. In particular:

- Header totals persist line aggregates for document list/report/accounting use; `amount_paid` and `balance_due` persist payment-derived state.
- `StockRecord` represents current stock, and `StockMovement` represents historical events. Both are required for efficient balance reads and traceability, subject to reconciliation.
- `Document.file`/current version and `DocumentVersion` history preserve distinct current and historical artifacts.
- `company` on a business record is tenant ownership, not duplication of a related customer/vendor/product's company; both are important for tenant isolation.

Proving a field is unused requires checking migration history, queryset/filter use, forms/serializers, templates, APIs, reports, admin, raw SQL, restore, and external consumers. This pass did not find sufficient evidence to drop a persisted field safely.

## Module-by-module audit

| Module | Layers found and reviewed | Duplicate/overlap outcome |
|---|---|---|
| Accounting | models, services, views, API, tasks, signals/tests | Journal auto-posting and journal-specific audit log are separate from central audit; payment postings differ by source document. Verify posting idempotency and reconciliation broadly; no safe consolidation found. |
| Administration | models, services, views, URLs, signals, tasks, commands, templates/tests | `ApprovalMatrix` is inert runtime config (DF-02); central AuditEvent and field-level AuditLog differ (DF-06). |
| AI | models, services, views, API/task paths/tests | Similar reporting/assistant operations are distinct entry points; no confirmed duplicate removal based on inspected call sites. Live provider/config flows remain unverified. |
| Analytics | models, services, views, API, tasks and tests | Report execution/export surfaces overlap by purpose but serve previews, saved reports, exports and schedules; preserve until endpoint equivalence is demonstrated. |
| API | models, serializers, viewsets, URLs and tests | Reuses domain models; parallel web/API workflows create consistency risk, exemplified by HRMS leave (DF-01). Keep public routes/contracts. |
| Assets | models, views, tasks, services/tests | Depreciation task is distinct scheduled operation; no duplicated fixed-asset workflow confirmed. |
| Authentication | models, services, views, API, tasks/tests | Session, JWT, role/permission and 2FA paths cover different auth contexts; preserve. |
| Company | models, services, views, API, tasks/tests | Tenant, branch, settings and sequence configuration have distinct responsibilities. |
| CRM | models, views, tasks, notifications and API/tests | Lead scoring/notifications feed sales; no redundant CRM/Sales entity proven. |
| Dashboard | views, URLs, templates/API | Aggregates multiple modules; repeated metrics should be checked against source queries, but no duplicate business model identified. |
| Documents | models, views, API, URLs, validators/tests | Document lifecycle overlaps generic approval capability (DF-08); version history is required. |
| Helpdesk | models, services, views, tasks, API/tests | SLA task and ticket service act on different lifecycle operations; no safe deletion identified. |
| HRMS | models, services, views, API, tasks/tests | Duplicate API/web leave action is DF-01; payroll, attendance and leave are separate processes. |
| Inventory | models, services, views, API, tasks/signals/tests | Stock balance and movement ledger are complementary; transfers/adjustments/reservations have distinct audit purposes. |
| Manufacturing | models, services, views/tests | BOM, material plan, MO, work order and quality checks are linked stages, not duplicates. |
| Notifications | models, services, tasks, views, API/tests | Centralized delivery service with wrappers/producers (DF-04); retain preferences, membership and delivery logs. |
| Portals | views, URLs, templates/tests | Customer/vendor portal views are external-facing role-specific workflows; overlaps internal records but not interchangeable. |
| POS | models, views, templates/tests | POS order/tender is channel-specific; do not merge into invoice/payment models without accounting/refund semantics. |
| Projects | models, services, views, tasks, API/tests | Project `Task` and workflow approval tasks have different ownership/state; no duplicate entity proven. |
| Purchase | models, services, views, portal/API/tests | Vendor payments and purchase receipts/bills are payables; not duplicates of sales receivables. |
| Sales | models, services, views, API/tasks/tests | Quotation approval drift is DF-09; invoice totals helper is DF-03; quote/order/invoice/payment/return are distinct lifecycle records. |
| Workflow | models, engine, views, API, tasks/tests | Generic configurable workflow is active; overlaps ApprovalMatrix and document-specific approval as covered above. |

## Suspected duplicates requiring more evidence

| Candidate | Current classification | Evidence still required |
|---|---|---|
| `ApprovalMatrix` vs `WorkflowDefinition` | Inert stored configuration with overlapping intent (DF-02), not proven safely removable | Product owner decision; tenant data inventory; external API/plugin usage; migration/deprecation plan. |
| `SalesOrderService.calculate_invoice_totals` vs `Invoice.recalculate_totals` | Unreferenced in-repo helper with overlapping calculation (DF-03) | External consumer search, intended read-only API use, Decimal/rounding contract. |
| Direct approval fields/transitions on business models vs generic workflow actions | Similar approval concepts, often with source-specific state and approval history | Map every state machine, signal and accounting side effect per model. Do not replace with generic workflow without preserving those contracts. |
| Duplicate CRUD view patterns across apps | Repeated structure, not proven redundant behavior | Compare permission rules, form validation, audit, transaction, company scoping, response and API compatibility route by route. |
| Model totals/balances vs line/payment/stock ledger values | Materialized/derived values with possible drift risk | Exhaustive write-path inventory and production reconciliation results. |

## Unused and obsolete code review

- **Confirmed no in-repository call site:** `SalesService.calculate_invoice_totals` (`apps/sales/services.py:270`). It remains a public method with a documented intended API use and may have external callers, so this is a removal candidate, not authorized deletion.
- **Confirmed no runtime consumer in inspected source:** `ApprovalMatrix` configuration (`apps/administration/models.py:156`). CRUD routes/templates expose it, so it is not unreachable UI or safely deletable data.
- No other file/model/route/task/template is declared dead in this report. A zero textual call-site result alone is insufficient when signals, Celery registration, URL inclusion, management command discovery, template references, app config imports or external integrations may provide dynamic entry points.

## Remediation plan

1. **Completed narrow consolidations:** route HRMS API leave approve/reject through `LeaveService.process_leave` and both sales quotation approval routes through `QuotationService.approve_quotation`; preserve API response and permission contracts, company scope, history fields and existing redirect behavior. Both transitions lock and reload company-owned rows. No migrations or URL removals.
2. **Product decision:** confirm whether Approval Matrix should be retired or wired to the generic workflow engine. Do not migrate/delete records until owners approve the behavioral replacement.
3. **Compatibility decision:** confirm whether `calculate_invoice_totals` is part of an external integration contract. If no consumer, deprecate/remove with a direct regression test and release note; otherwise retain or delegate to a tested shared calculation.
4. **Integrity verification:** map and test all sales/purchase totals, discounts, tax rounding, payment balances, stock records/movements and journal postings before considering shared calculation helpers.
5. **Workflow mapping:** document source-document state transitions and side effects before consolidating approvals or document lifecycle actions.
6. **Dead-code follow-up:** build automated URL/template/import/task registration checks, then review candidates with runtime/configuration evidence and retain backward-compatible routes until clients are known.

## Verification and limits

- Focused HRMS leave API/service tests: **15 passed** (`tests/test_hrms.py apps/hrms/tests/test_views.py`). Focused sales quotation tests after the second consolidation: **6 passed**.
- Full suite after both HRMS and Sales API/web state-transition consolidations, run in the background with output captured and polled to completion: **4,940 passed, 0 failed, 1 skipped, 4,853 warnings in 355.48s (0:05:55)** using `DEBUG=True`, SQLite, `DJANGO_TESTING=1`, and `--no-cov -o addopts=--nomigrations`.
- `manage.py check`: **exit 0**, no issues.
- `manage.py makemigrations --check --dry-run`: **exit 0**, `No changes detected`.
- `git diff --check`: clean (Git reports line-ending normalization only).
- No migration, URL, persisted field, model, template, task or broad deletion was introduced in this remediation. The quotation API retains its response shape. A fresh migrate was not rerun for this audit because there are no schema changes; the previously recorded fresh SQLite migration evidence is in `PHASE_0_TEST_REPORT.md`.

This pass began with read-only inspection and implemented only the confirmed HRMS and Sales approval consolidations after writing the findings and plan. No claims are made about PostgreSQL, Redis/Celery live services, provider integrations, raw SQL consumers, or external API clients.
