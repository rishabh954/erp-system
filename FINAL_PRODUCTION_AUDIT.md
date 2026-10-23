# ERP Automation Audit and Production Readiness

**Status: not certified for production.** This is a code and SQLite regression-test review. A passing application test suite does not prove live broker, provider, or PostgreSQL behavior.

## Automation gap matrix

| Process | Current classification and implementation evidence | Manual work or dependency remaining | Regression evidence | Priority |
|---|---|---|---|---|
| CRM lead-to-cash | **Partially automated.** CRM leads, scoring, customer/order conversion and sales services exist (`apps/crm/`, `apps/sales/services.py`, `apps/crm/signals.py`). | Human qualification and approval remain; no verified end-to-end journey from lead through settled payment, accounting and notification. | CRM and sales workflow tests; no full journey test identified. | High |
| Sales quotation-to-payment | **Partially automated.** Quotation/order/invoice/payment services and overdue-invoice task exist (`apps/sales/services.py`, `apps/sales/tasks.py`). Sales returns now reject single-line and cumulative over-returns at approval. | Approval, collection follow-up and reconciliation remain operational steps; no full browser/API-to-ledger workflow or concurrent PostgreSQL run verified. | `tests/test_sales_workflow.py`, `tests/test_sales_overdue_task.py`. | High |
| Purchase request-to-supplier-payment | **Partially automated.** Purchase order, receipt, bill and payment code exists (`apps/purchase/`). | No end-to-end request/approval/receipt/bill/payment reconciliation demonstrated; supplier actions and payment execution require staff and configured accounting/bank data. | Existing purchase tests; no end-to-end automation proof in this audit. | High |
| Inventory replenishment and transfers | **Partially automated.** Reorder/low-stock and stock transfer services/tasks exist (`apps/inventory/`, `apps/inventory/tasks.py`); low-stock aggregation is company-scoped. | A person must review and approve replenishment; transfer operations need operational confirmation. Live scheduled execution and concurrent stock contention remain unverified. | `tests/test_inventory_low_stock_task.py`, inventory and POS tests. | High |
| Accounting and automatic journals | **Partially automated.** Sales and other services post journals through accounting services (`apps/accounting/services.py` and module services). | Period close, exception review, reconciliation and tax sign-off remain manual. Accounting correctness was not proven for every source document or under PostgreSQL concurrency. | Accounting and sales journal tests; no full audit of every posting trigger. | Critical |
| HRMS attendance, leave and payroll | **Partially automated; focused task/service reliability tested.** Attendance automation and guarded payroll processing exist (`apps/hrms/tasks.py`, `apps/hrms/services.py`, `apps/hrms/views.py`). | Payroll approval, statutory checks and payslip delivery require configured policy/provider operations. Full end-to-end payroll has not been certified. | `tests/test_hrms_auto_attendance_task.py`, `apps/hrms/tests/test_payroll_task_reliability.py`. | Critical |
| Manufacturing, BOM, MRP and production | **Partially automated; focused tenant and idempotency checks added.** MRP planning and production completion exist (`apps/manufacturing/services.py`, `apps/manufacturing/models.py`). | Planner review and shop-floor confirmation remain. Full order-to-stock-to-accounting production flow, PostgreSQL locking and live scheduling are unverified. | `apps/manufacturing/tests/test_mrp_company_scope.py`, `test_manufacturing_completion_scope.py`, `test_bom.py`. | High |
| POS sales, returns and accounting | **Partially automated checkout; POS returns not implemented/verified.** Checkout creates order/payment and uses stock service (`apps/pos/views.py`). | POS return/refund processing is not available as an identified POS workflow; any return handling requires a separate, verified process. Terminal/provider and end-to-end accounting behavior are unverified. | `apps/pos/tests/test_views.py`; sales return coverage does not establish POS return support. | High |
| Workflow approvals and escalations | **Partially automated.** State transitions, notifications and escalation tasks exist (`apps/workflow/engine.py`, `apps/workflow/tasks.py`). | Organizations must configure definitions, approvers and escalation policies; human approval remains. Live beat/broker delivery and recovery are unverified. | `tests/test_workflow_transition_idempotency.py`, `test_workflow_escalation_reliability.py`, `test_workflow_notification_task_tenant_scope.py`. | High |
| Notifications and scheduled jobs | **Partially automated; selected tasks hardened.** Tenant-aware notification service and scheduled producers exist across `apps/notifications/` and app task modules. | Provider credentials, worker/beat deployment, queues, monitoring, delivery retries and operational alerting must be configured and tested in the target environment. | `NOTIFICATION_SYSTEM_AUDIT.md`, task-specific tests listed above. | High |
| Reports, dashboards and exception management | **Partially implemented; not verified end to end.** Reporting and dashboard code exists across analytics and business apps. | Scheduled report delivery, completeness, exception ownership and recovery processes require review and operational setup. | No comprehensive report/dashboard smoke and data-accuracy suite was verified in this pass. | Medium |

## Changes verified in this audit sequence

Targeted reliability changes and regression tests were added for scheduled accounting, asset, company, CRM, helpdesk, HRMS, inventory, manufacturing, notifications, POS checkout, projects, sales and workflow paths. These include tenant-scoped queries, safer retry/idempotency behavior, serialization around selected state transitions, payroll period guards and the sales return quantity cap. See the tests named in the matrix and repository test files for exact coverage. These focused fixes do not constitute an end-to-end certification of the listed processes.

## Open production blockers and verification limits

- HRMS payroll, POS, manufacturing, projects, helpdesk and AI workflows have not been certified end to end.
- POS return/refund processing is not verified as an implemented workflow.
- Detail, edit and delete pages and every API tenant authorization boundary have not all been exhaustively reviewed.
- PostgreSQL behavior, including migration behavior, constraints, row locking, isolation and concurrent requests, has not been verified.
- Redis connectivity/cache behavior, Celery broker connectivity, workers, beat schedules, retries, monitoring and failure recovery have not been exercised against live infrastructure.
- Email, SMS, WhatsApp, push, bank/payment and OAuth provider delivery/callbacks were not verified with production credentials.
- Production backup/restore and disaster recovery have not been exercised.
- Human approvals, reconciliation, payroll/legal controls and operational exception handling remain necessary where company policy requires them.

## Phased implementation plan

1. **Critical integrity:** validate company ownership at every business boundary; verify accounting postings, payment/refund idempotency and payroll safeguards against PostgreSQL with concurrency tests.
2. **Operational recovery:** deploy and exercise Redis/Celery/beat; add observable failure alerts and retry/replay procedures; perform a production-like backup/restore drill.
3. **End-to-end journeys:** build realistic workflow tests for lead-to-cash, purchase-to-payment, inventory transfer/replenishment, payroll approval, manufacturing, POS accounting/returns and helpdesk/project automations.
4. **Route and security coverage:** systematically test authenticated list/detail/create/edit/delete/API routes for permissions, company scoping and state-changing method protections.
5. **Release evidence:** record exact PostgreSQL, Redis, Celery and provider versions/configuration and run release acceptance checks before certification.

No deployment, push, or destructive database change was performed as part of this audit sequence.
