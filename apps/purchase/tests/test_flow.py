import pytest
from django.urls import reverse
from decimal import Decimal
from apps.purchase.models import PurchaseOrder, GoodsReceipt, Bill, Payment

@pytest.fixture
def purchase_flow_data(vendor, product, warehouse, tax):
    return {
        'vendor': vendor.pk,
        'order_date': '2023-01-01',
        'warehouse': warehouse.pk,
        'payment_terms': '30',
        'product[]': [product.pk],
        'description[]': ['Test Product'],
        'quantity[]': ['10'],
        'unit_price[]': ['100.00'],
        'discount_percent[]': ['0'],
        'tax[]': [tax.pk]
    }

@pytest.mark.django_db
def test_purchase_full_flow(client, user, vendor, product, warehouse, purchase_flow_data):
    client.force_login(user)
    
    # 1. Create Purchase Order
    url = reverse('purchase:order_create')
    response = client.post(url, data=purchase_flow_data)
    assert response.status_code == 302
    
    po = PurchaseOrder.objects.first()
    assert po is not None
    assert po.status == PurchaseOrder.Status.DRAFT
    assert po.lines.count() == 1
    
    # 2. Submit PO for approval
    url = reverse('purchase:order_submit', kwargs={'pk': po.pk})
    response = client.post(url)
    assert response.status_code == 302
    po.refresh_from_db()
    # It might auto-approve if no workflow is set
    assert po.status in [PurchaseOrder.Status.PENDING_APPROVAL, PurchaseOrder.Status.APPROVED]
    
    if po.status == PurchaseOrder.Status.PENDING_APPROVAL:
        # If it needs manual approval, let's just force it for test
        po.status = PurchaseOrder.Status.APPROVED
        po.save()
    
    # 3. Confirm PO
    url = reverse('purchase:order_confirm', kwargs={'pk': po.pk})
    response = client.post(url)
    assert response.status_code == 302
    po.refresh_from_db()
    assert po.status == PurchaseOrder.Status.CONFIRMED
    
    # 4. Receive Goods (Goods Receipt)
    url = reverse('purchase:order_receive', kwargs={'pk': po.pk})
    receipt_data = {
        'warehouse': warehouse.pk,
        'notes': 'Received fine'
    }
    # Add quantity for the line
    line = po.lines.first()
    receipt_data[f'qty_{line.pk}'] = '10'
    receipt_data[f'batch_{line.pk}'] = 'BATCH123'
    
    response = client.post(url, data=receipt_data)
    assert response.status_code == 302
    
    po.refresh_from_db()
    assert po.status == PurchaseOrder.Status.RECEIVED
    receipt = GoodsReceipt.objects.first()
    assert receipt is not None
    assert receipt.status == GoodsReceipt.Status.COMPLETED
    
    # 5. Create Bill from PO
    url = reverse('purchase:po_create_bill', kwargs={'pk': po.pk})
    response = client.post(url)
    assert response.status_code == 302
    
    bill = Bill.objects.first()
    assert bill is not None
    assert bill.status == Bill.Status.DRAFT
    
    # Let's open the bill
    bill.status = Bill.Status.OPEN
    bill.save()
    
    # 6. Record Payment for the Bill
    url = reverse('purchase:bill_record_payment', kwargs={'pk': bill.pk})
    payment_data = {
        'amount': str(bill.balance_due),
        'payment_date': '2023-01-15',
        'method': 'bank_transfer',
        'reference': 'TRX-999'
    }
    response = client.post(url, data=payment_data)
    assert response.status_code == 302
    
    bill.refresh_from_db()
    assert bill.status == Bill.Status.PAID
    assert bill.balance_due == Decimal('0.00')
    
    payment = Payment.objects.first()
    assert payment is not None
    assert payment.amount == bill.total
