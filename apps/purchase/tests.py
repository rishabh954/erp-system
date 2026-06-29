import pytest
from django.utils import timezone
from decimal import Decimal

from apps.purchase.services import (
    PurchaseRequestService,
    PurchaseOrderService,
    PaymentService,
    RFQService,
    VendorBidService
)
from apps.purchase.models import (
    PurchaseRequest, PurchaseOrder, Bill, Payment,
    RequestForQuotation, VendorBid
)
from apps.purchase.models import GoodsReceipt

@pytest.fixture
def purchase_services(db, rf, company, user, vendor, product, warehouse, currency, tax):
    class MockData(dict):
        def getlist(self, key):
            return self.get(key, [])
            
    return {
        'company': company,
        'user': user,
        'vendor': vendor,
        'product': product,
        'warehouse': warehouse,
        'currency': currency,
        'tax': tax,
        'MockData': MockData,
        'pr_service': PurchaseRequestService(user=user, company=company),
        'po_service': PurchaseOrderService(user=user, company=company),
        'payment_service': PaymentService(user=user, company=company),
        'rfq_service': RFQService(user=user, company=company),
        'bid_service': VendorBidService(user=user, company=company),
    }

@pytest.mark.django_db
def test_purchase_request_service(purchase_services):
    pr_service = purchase_services['pr_service']
    data = purchase_services['MockData']({
        'title': 'Test PR',
        'department': '',
        'required_by': '',
        'priority': 'high',
        'notes': 'Test notes',
        'product[]': [purchase_services['product'].pk],
        'description[]': ['Test product'],
        'quantity[]': ['10'],
        'estimated_unit_price[]': ['15.00']
    })
    
    pr = pr_service.create_request(data, purchase_services['user'])
    assert pr.pk is not None
    assert pr.title == 'Test PR'
    assert pr.priority == 'high'
    assert pr.lines.count() == 1
    assert pr.estimated_cost == Decimal('150.00')
    
    update_data = purchase_services['MockData']({
        'title': 'Updated PR',
        'department': '',
        'required_by': '',
        'priority': 'urgent',
        'notes': '',
        'product[]': [purchase_services['product'].pk],
        'description[]': ['Test product 2'],
        'quantity[]': ['20'],
        'estimated_unit_price[]': ['20.00']
    })
    
    pr = pr_service.update_request(pr, update_data)
    assert pr.title == 'Updated PR'
    assert pr.priority == 'urgent'
    assert pr.estimated_cost == Decimal('400.00')

@pytest.mark.django_db
def test_purchase_order_and_bill_service(purchase_services):
    po_service = purchase_services['po_service']
    data = purchase_services['MockData']({
        'vendor': purchase_services['vendor'].pk,
        'order_date': timezone.now().date(),
        'payment_terms': '30',
        'product[]': [purchase_services['product'].pk],
        'description[]': ['Test item'],
        'quantity[]': ['5'],
        'unit_price[]': ['100.00'],
        'discount_percent[]': ['10'],
        'tax[]': [purchase_services['tax'].pk]
    })
    
    po = po_service.create_order(data, purchase_services['user'])
    assert po.pk is not None
    assert po.lines.count() == 1
    # 5 * 100 = 500, discount 10% = 50, taxable = 450
    # tax rate 10% = 45. total = 495
    assert po.subtotal == Decimal('450.00')
    assert po.tax_amount == Decimal('45.00')
    assert po.total == Decimal('495.00')
    assert po.balance_due == Decimal('495.00')

    # Update PO
    po_service.update_order(po, data)
    
    # Confirm PO
    po.status = PurchaseOrder.Status.CONFIRMED
    po.save()

    # Receive PO in test
    for line in po.lines.all():
        line.qty_received = line.quantity
        line.save(update_fields=['qty_received'])

    # Create bill
    bill = po_service.create_bill(po)
    assert bill.pk is not None
    assert bill.total == po.total
    assert bill.status == Bill.Status.DRAFT
    
@pytest.mark.django_db
def test_rfq_and_bid_service(purchase_services):
    rfq_service = purchase_services['rfq_service']
    bid_service = purchase_services['bid_service']
    
    rfq_data = purchase_services['MockData']({
        'title': 'Need laptops',
        'deadline': timezone.now().date(),
        'product[]': [purchase_services['product'].pk],
        'quantity[]': ['10'],
        'description[]': ['Laptops']
    })
    
    rfq = rfq_service.create_rfq(rfq_data, purchase_services['user'])
    assert rfq.pk is not None
    assert rfq.lines.count() == 1
    
    bid_data = purchase_services['MockData']({
        'vendor': purchase_services['vendor'].pk,
        'price[]': ['1200.00'],
    })
    
    bid = bid_service.create_bid(rfq, bid_data)
    assert bid.pk is not None
    assert bid.status == VendorBid.Status.PENDING
    assert bid.total_amount == Decimal('12000.00')
    
    # Accept bid
    po = bid_service.accept_bid(bid, purchase_services['user'])
    assert po.pk is not None
    assert po.vendor == purchase_services['vendor']
    assert po.total == Decimal('12000.00')
    
    bid.refresh_from_db()
    rfq.refresh_from_db()
    assert bid.status == VendorBid.Status.ACCEPTED
    assert rfq.status == RequestForQuotation.Status.CLOSED
