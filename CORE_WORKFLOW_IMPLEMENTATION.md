# Core Business Workflow Implementation

This document details the enterprise-grade business workflows implemented in the ERP system, unifying Sales, Purchase, Inventory, and Accounting into seamless transactional lifecycles.

## 1. Sales Workflow: Quote to Cash

**Process Flow:**
`Quotation -> Sales Order -> Delivery Order -> Invoice -> Payment -> Customer Ledger`

### Key Implementations
- **Credit Control Automation:** 
  - Real-time credit evaluation on `SalesOrderService.confirm_order`.
  - Orders exceeding the customer limit or with overdue invoices are automatically placed on `PENDING_APPROVAL` with `credit_hold = True`.
  - Manager override via `CreditControlService.override_credit_hold()` with mandatory documented reasoning.
- **Stock Reservation & Delivery State Machine:**
  - `start_picking` -> `start_packing` -> `ship_delivery` -> `mark_delivered`.
  - Prevents shipping without sufficient stock or skipping the packing stage.
- **Auto-Invoicing and Accounting:**
  - `InvoiceService` enforces idempotency (no duplicate journals).
  - Invoices automatically post journal entries debiting Accounts Receivable and crediting Sales Revenue.
- **Sales Returns:**
  - Return creation allows marking items as `resellable` (restocks inventory) or `defective` (written off).
  - Return approval automatically generates and posts a `CreditNote` reducing the customer's outstanding balance.

## 2. Purchase Workflow: Procure to Pay

**Process Flow:**
`Purchase Order -> Goods Receipt (GRN) -> Vendor Bill -> Payment -> Vendor Ledger`

### Key Implementations
- **Goods Receipt (GRN):**
  - Partial or full GRNs are supported. Stock is dynamically incremented upon GRN creation.
  - PO status automatically transitions to `PARTIAL` or `RECEIVED` based on remaining unfulfilled quantities.
- **Three-Way Matching:**
  - The `ThreeWayMatchingService` verifies Vendor Bills against the original Purchase Order and corresponding Goods Receipts.
  - Discrepancies (price mismatch or quantity billed > quantity received) flag the Bill as `MISMATCH`.
  - Override requires explicit managerial action with reasoning (`override_mismatch`).
- **Vendor Ledger Integration:**
  - Vendor bills auto-post journals debiting Inventory/Expenses and crediting Accounts Payable.
  - Payments dynamically debit Accounts Payable, ensuring accurate vendor outstanding balances in real-time.

## 3. System-Wide Business Rules

- **Multi-Tenant Isolation:** All workflows, documents, and journals are strictly bound to the active user's company context, enforced at the ORM model level (`CompanyScoped`).
- **Atomic Transactions:** Critical transition methods (like confirming orders, creating bills, or processing payments) use `@transaction.atomic` to prevent partial data writes in case of validation errors or network failures.
- **Sequence Generation:** Robust, concurrent-safe generation for SO, PO, INV, GRN, and PAY document numbers.
