import pytest
from django.urls import reverse
from apps.purchase.models import Vendor, PurchaseRequest, RequestForQuotation, VendorBid

@pytest.mark.django_db
def test_vendor_views(client, user, company):
    client.force_login(user)
    
    # List
    url = reverse('purchase:vendors')
    response = client.get(url)
    assert response.status_code == 200
    
    # Create
    url = reverse('purchase:vendor_create')
    data = {
        'name': 'Test Vendor',
        'vendor_type': 'supplier',
        'email': 'vendor@test.com',
        'payment_terms': 30,
    }
    response = client.post(url, data=data)
    assert response.status_code == 302
    
    vendor = Vendor.objects.filter(name='Test Vendor').first()
    assert vendor is not None
    
    # Detail
    url = reverse('purchase:vendor_detail', kwargs={'pk': vendor.pk})
    response = client.get(url)
    assert response.status_code == 200
    
    # Update
    url = reverse('purchase:vendor_update', kwargs={'pk': vendor.pk})
    data['name'] = 'Updated Vendor'
    response = client.post(url, data=data)
    assert response.status_code == 302
    vendor.refresh_from_db()
    assert vendor.name == 'Updated Vendor'

@pytest.mark.django_db
def test_purchase_request_views(client, user, company, product):
    client.force_login(user)
    
    # Create
    url = reverse('purchase:request_create')
    data = {
        'title': 'Test PR',
        'priority': 'high',
        'product[]': [product.pk],
        'description[]': ['Test Item'],
        'quantity[]': [5],
        'estimated_unit_price[]': [10.0]
    }
    response = client.post(url, data=data)
    assert response.status_code == 302
    
    pr = PurchaseRequest.objects.first()
    assert pr is not None
    assert pr.title == 'Test PR'
    
    # Detail
    url = reverse('purchase:request_detail', kwargs={'pk': pr.pk})
    response = client.get(url)
    assert response.status_code == 200

    # Submit action
    url = reverse('purchase:request_action', kwargs={'pk': pr.pk})
    response = client.post(url, data={'action': 'submit'})
    assert response.status_code == 302
    pr.refresh_from_db()
    assert pr.status == 'submitted'
    
    # Approve action
    response = client.post(url, data={'action': 'approve'})
    assert response.status_code == 302
    pr.refresh_from_db()
    assert pr.status == 'approved'

@pytest.mark.django_db
def test_rfq_and_bid_views(client, user, company, vendor, product):
    client.force_login(user)
    
    # Create RFQ
    url = reverse('purchase:rfq_create')
    data = {
        'title': 'Test RFQ',
        'deadline': '2023-12-31',
        'product[]': [product.pk],
        'quantity[]': [10],
        'description[]': ['Test']
    }
    response = client.post(url, data=data)
    assert response.status_code == 302
    
    rfq = RequestForQuotation.objects.first()
    assert rfq is not None
    
    # Detail RFQ
    url = reverse('purchase:rfq_detail', kwargs={'pk': rfq.pk})
    response = client.get(url)
    assert response.status_code == 200

    # Submit Bid for RFQ
    # VendorBidCreateView needs rfq query param on GET
    url = reverse('purchase:bid_create')
    response = client.get(url + f'?rfq={rfq.pk}')
    assert response.status_code == 200
    
    # Post bid
    data = {
        'rfq': rfq.pk,
        'vendor': vendor.pk,
        'price[]': [50.0]
    }
    # Wait, the bid create view logic expects 'rfq' and 'vendor' and 'price[]'
    response = client.post(url, data=data)
    assert response.status_code == 302
    
    bid = VendorBid.objects.first()
    assert bid is not None
    
    # Detail Bid
    url = reverse('purchase:bid_detail', kwargs={'pk': bid.pk})
    response = client.get(url)
    assert response.status_code == 200

    # Accept Bid
    url = reverse('purchase:bid_action', kwargs={'pk': bid.pk})
    response = client.post(url, data={'action': 'accept'})
    assert response.status_code == 302
    bid.refresh_from_db()
    assert bid.status == VendorBid.Status.ACCEPTED
