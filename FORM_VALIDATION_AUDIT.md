# Form validation audit

## Scope and method

This is a source-trace audit, not a claim that every ERP form and API has been exhaustively exercised. The initial pass searched app views, services, templates, forms, serializers, and tests, then traced the company, product, warehouse, vendor, quotation, sales order, and invoice write paths named by the request. Server-side behavior is the deciding evidence; HTML `required` attributes alone do not establish validation.

## Verified findings

| Form / module | Template | View and persistence path | Required business fields / validation observed | Invalid input behavior and tests | Status / recommended fix |
|---|---|---|---|---|---|
| Company setup | `templates/company/company_create.html` | `apps/company/views.py:CompanyCreateView.post` -> Company, UserCompany, User | Name, choice values, active currency, fiscal-year month/day and timezone are now validated server-side. | Invalid input re-renders errors and writes nothing; linked rows are created atomically. New tests cover blank name, bad currency and valid create. | PARTIAL. Core validation regression is covered; not all optional fields and timezone/fiscal-year edge cases have dedicated tests. |
| Product create | `templates/inventory/products/form.html` | `apps/inventory/views.py:ProductCreateView.post` -> Product | Name/SKU are trimmed and required; product type is checked; numeric inputs must be finite and non-negative; category is tenant scoped and non-deleted; brand/UOM/tax are tenant scoped and active. | Invalid inputs do not create products; summary errors are rendered and name/SKU retained. Tests cover whitespace and foreign category. | PARTIAL. Other invalid decimals, malformed IDs, all related types and successful POST are not covered by new regression cases. |
| Warehouse create/update | `templates/inventory/warehouses/list.html` | `apps/inventory/views.py:WarehouseCreateView.post`, `WarehouseUpdateView.post` -> Warehouse | Name/code required and trimmed; branch and manager must have active membership in the active company. | Invalid selection shows a message and does not write. Test covers cross-company branch on create. | PARTIAL. Manager, update, malformed IDs, and field-value preservation remain untested; errors use the list/modal message flow. |
| Vendor create/update | `templates/purchase/vendors/form.html` | `apps/purchase/views.py:VendorCreateView.post`, `VendorUpdateView.post` -> Vendor | Name trimmed/required; type checked against choices; payment terms bounded to the field range; currency must be active. | Invalid create/update re-renders with messages; regression covers invalid create and existing tests cover valid create/update. | PARTIAL. Currency and invalid update cases lack dedicated tests; some optional submitted values are not yet repopulated. |
| Quotation create/update | `templates/sales/quotations/form.html` | `apps/sales/views.py:QuotationCreateView` / `QuotationUpdateView` -> `QuotationService` and lines | Customer must belong to company; at least one line is required; description can be inherited from a selected product; quantity must be positive, price non-negative, discount 0–100; non-deleted product and active tax are company scoped; parallel arrays are checked. Update is atomic. | Existing sales workflow tests pass; direct InvoiceService tests cover missing rows, foreign customer and bad quantity. | PARTIAL. No equivalent create/update regression matrix for quote and order; invalid view errors still use generic messaging and submitted line values are not restored. |
| Sales order create/update | `templates/sales/orders/form.html` | `apps/sales/views.py:SalesOrderCreateView` / `SalesOrderUpdateView` -> `SalesOrderService` and lines | Uses shared tenant and line validation; also accepts the existing legacy `lines-N-*` POST shape. Inactive but non-deleted same-company products remain usable in this path for existing historical workflows. Update is atomic. | Existing order/invoice workflow test and end-to-end walkthrough passed. | PARTIAL. No dedicated invalid order regression tests or field-level re-rendering. |
| Invoice create/update | `templates/sales/invoices/form.html` | `apps/sales/views.py:InvoiceCreateView` / `InvoiceUpdateView` -> `InvoiceService` and lines | Customer and non-deleted product/active tax are company scoped; at least one line required; quantity, price, discount and parallel rows validated. Update is atomic and rolls back on caught persistence errors. | Added tests verify missing rows, foreign customer, malformed quantity leave no parent; existing flow tests passed. | PARTIAL. Invalid date, line ID formats, and update rollback are not covered; errors are not yet rendered next to fields and POST values are not restored. |

## Broader inventory and unverified coverage

The repository has three app-level `forms.py` files (`apps/ai/forms.py`, `apps/crm/forms.py`, `apps/authentication/forms.py`); many other write paths parse `request.POST` directly. A broad search identified forms and API endpoints across accounting, administration, assets, authentication, CRM, documents, helpdesk, HRMS, inventory, manufacturing, purchase, sales, and workflow. This pass did not trace every field, JavaScript/AJAX path, serializer, or model constraint in those modules, so these remain **UNVERIFIED** rather than PASS:

- Other inventory forms: categories, transfers, stock counts, movements, warehouse/bin/location and WMS flows.
- Purchase requests, RFQs, bids, orders, goods receipts, bills, and supplier portal forms.
- Other sales forms: payments, returns, subscriptions, shipments, and approval/action workflows.
- CRM customer, lead, activity, and portal forms.
- Accounting journal, account, bank, tax, and reconciliation forms.
- HRMS employee, leave, attendance, payroll, and recruiting forms.
- Manufacturing, project, asset, helpdesk, document, workflow, notification, and administration forms.
- DRF endpoints and AJAX submissions outside the directly traced paths.

These are follow-up audit items. No claim is made that this initial focused implementation closes validation gaps in untraced forms.
