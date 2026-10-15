from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounting.models import Account, JournalEntry, JournalItem
from apps.purchase.models import (
    Bill, BillLine, GoodsReceipt, GoodsReceiptLine, Payment, PurchaseOrder,
    PurchaseOrderLine,
)
from apps.purchase.services import PurchaseOrderService


@pytest.fixture
def purchase_flow_data(vendor, product, warehouse, tax):
    return {
        "vendor": vendor.pk,
        "order_date": "2023-01-01",
        "warehouse": warehouse.pk,
        "payment_terms": "30",
        "product[]": [product.pk],
        "description[]": ["Test Product"],
        "quantity[]": ["1.25"],
        "unit_price[]": ["100.00"],
        "discount_percent[]": ["0"],
        "tax[]": [tax.pk],
    }


@pytest.mark.django_db
def test_purchase_full_flow(
    client, user, vendor, product, warehouse, purchase_flow_data
):
    client.force_login(user)

    # 1. Create Purchase Order
    url = reverse("purchase:order_create")
    response = client.post(url, data=purchase_flow_data)
    assert response.status_code == 302

    po = PurchaseOrder.objects.first()
    assert po is not None
    assert po.status == PurchaseOrder.Status.DRAFT
    assert po.lines.count() == 1

    # 2. Submit PO for approval
    url = reverse("purchase:order_submit", kwargs={"pk": po.pk})
    response = client.post(url)
    assert response.status_code == 302
    po.refresh_from_db()
    # It might auto-approve if no workflow is set
    assert po.status in [
        PurchaseOrder.Status.PENDING_APPROVAL,
        PurchaseOrder.Status.APPROVED,
    ]

    if po.status == PurchaseOrder.Status.PENDING_APPROVAL:
        # If it needs manual approval, let's just force it for test
        po.status = PurchaseOrder.Status.APPROVED
        po.save()

    # 3. Confirm PO
    url = reverse("purchase:order_confirm", kwargs={"pk": po.pk})
    response = client.post(url)
    assert response.status_code == 302
    po.refresh_from_db()
    assert po.status == PurchaseOrder.Status.CONFIRMED

    # 4. Receive Goods (Goods Receipt)
    url = reverse("purchase:order_receive", kwargs={"pk": po.pk})
    receipt_data = {"warehouse": warehouse.pk, "notes": "Received fine"}
    # Add quantity for the line
    line = po.lines.first()
    receipt_data[f"qty_{line.pk}"] = "1.25"
    receipt_data[f"batch_{line.pk}"] = "BATCH123"

    response = client.post(url, data=receipt_data)
    assert response.status_code == 302

    po.refresh_from_db()
    assert po.status == PurchaseOrder.Status.RECEIVED
    receipt = GoodsReceipt.objects.first()
    assert receipt is not None
    assert receipt.status == GoodsReceipt.Status.COMPLETED
    receipt_entry = JournalEntry.objects.get(
        company=po.company, reference=f"GRN: {receipt.number}"
    )
    assert receipt_entry.status == JournalEntry.Status.POSTED
    grni_account = Account.objects.get(company=po.company, code="2105")
    receipt_grni = receipt_entry.items.get(account=grni_account)
    assert receipt_grni.credit == Decimal("125.00")

    # 5. Create Bill from PO
    url = reverse("purchase:po_create_bill", kwargs={"pk": po.pk})
    response = client.post(url)
    assert response.status_code == 302

    bill = Bill.objects.first()
    assert bill is not None
    assert bill.status == Bill.Status.DRAFT
    assert BillLine.objects.get(bill=bill).quantity == Decimal("1.25")

    # Let's open the bill
    bill.status = Bill.Status.OPEN
    bill.save()
    bill_entry = JournalEntry.objects.get(
        company=po.company, reference=f"BILL: {bill.number}"
    )
    assert bill_entry.status == JournalEntry.Status.POSTED
    assert bill_entry.items.get(account=grni_account).debit == Decimal("125.00")
    grni_balance = JournalItem.objects.filter(
        account=grni_account,
        journal_entry__company=po.company,
        journal_entry__source_id=str(po.pk),
        journal_entry__status=JournalEntry.Status.POSTED,
    )
    assert sum(item.credit - item.debit for item in grni_balance) == Decimal("0")

    # 6. Record Payment for the Bill
    url = reverse("purchase:bill_record_payment", kwargs={"pk": bill.pk})
    payment_data = {
        "amount": str(bill.balance_due),
        "payment_date": "2023-01-15",
        "method": "bank_transfer",
        "reference": "TRX-999",
    }
    response = client.post(url, data=payment_data)
    assert response.status_code == 302

    bill.refresh_from_db()
    assert bill.status == Bill.Status.PAID
    assert bill.balance_due == Decimal("0.00")

    payment = Payment.objects.first()
    assert payment is not None
    assert payment.amount == bill.total


@pytest.mark.django_db
def test_goods_receipt_rejects_foreign_warehouse(company, user, vendor):
    from core.factories import CompanyFactory
    from apps.inventory.models import Warehouse

    other_company = CompanyFactory()
    foreign_warehouse = Warehouse.objects.create(
        company=other_company, name="Foreign", code="FOREIGN"
    )
    order = PurchaseOrder.objects.create(
        company=company, vendor=vendor, order_date="2025-01-01"
    )
    with pytest.raises(ValueError, match="Warehouse not found for this company"):
        PurchaseOrderService(company=company).create_goods_receipt(
            order, {"warehouse": str(foreign_warehouse.pk)}, user
        )
    assert not GoodsReceipt.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_goods_receipt_caps_quantity_and_allows_partial_receipts(
    company, user, vendor, warehouse, product
):
    order = PurchaseOrder.objects.create(
        company=company, vendor=vendor, order_date="2025-01-01"
    )
    line = PurchaseOrderLine.objects.create(
        purchase_order=order, product=product, description="Test",
        quantity=Decimal("10"), unit_price=Decimal("1"),
    )
    service = PurchaseOrderService(company=company)
    with pytest.raises(ValueError, match="remaining ordered quantity is 10"):
        service.create_goods_receipt(
            order, {"warehouse": str(warehouse.pk), f"qty_{line.pk}": "25"}, user
        )
    line.refresh_from_db()
    assert line.qty_received == 0
    service.create_goods_receipt(
        order, {"warehouse": str(warehouse.pk), f"qty_{line.pk}": "4"}, user
    )
    line.refresh_from_db()
    assert line.qty_received == 4
    service.create_goods_receipt(
        order, {"warehouse": str(warehouse.pk), f"qty_{line.pk}": "6"}, user
    )
    line.refresh_from_db()
    assert line.qty_received == 10
    assert GoodsReceiptLine.objects.filter(po_line=line).count() == 2
