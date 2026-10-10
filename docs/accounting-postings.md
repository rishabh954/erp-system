# Inventory-related accounting postings

Goods receipt records inventory at the purchase-order line's net unit cost and
debits Inventory while crediting Goods Received Not Invoiced (GRNI). When the
purchase bill is posted, it debits GRNI for the received value and credits
Accounts Payable; any billed value not yet received is expensed. This clears the
receipt accrual without recording the same purchase cost twice.

Shipment posts the stock movements' absolute total cost as a debit to COGS and a
credit to Inventory. Each delivery journal uses `DEL: <delivery number>` as its
reference so retries do not post the inventory cost again.
