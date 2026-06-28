from django.urls import path
from . import views
from .views import (
    VendorListView, VendorDetailView, VendorCreateView, VendorUpdateView, VendorDeleteView,
    VendorEvaluateView, PurchaseDashboardView,
    PurchaseRequestListView, PurchaseRequestCreateView, PurchaseRequestDetailView,
    PurchaseRequestUpdateView, PurchaseRequestDeleteView, ApprovePurchaseRequestView,
    PurchaseOrderListView, PurchaseOrderCreateView, PurchaseOrderDetailView,
    PurchaseOrderUpdateView, PurchaseOrderDeleteView,
    CreateBillFromPOView, BillListView, BillDetailView, BillUpdateView, BillDeleteView, RecordVendorPaymentView,
    GoodsReceiptListView, GoodsReceiptDetailView, GoodsReceiptCreateView, GoodsReceiptUpdateView, GoodsReceiptDeleteView,
    RFQListView, RFQDetailView, RFQCreateView, RFQUpdateView, RFQDeleteView,
    VendorBidListView, VendorBidDetailView, VendorBidCreateView, VendorBidActionView
)
from .portal_views import (
    VendorPortalDashboardView, VendorPortalRFQListView, VendorPortalRFQDetailView, VendorPortalBidCreateView
)

app_name = 'purchase'

urlpatterns = [
    path('dashboard/', PurchaseDashboardView.as_view(), name='dashboard'),
    
    # Vendors
    path('vendors/', VendorListView.as_view(), name='vendors'),
    path('vendors/create/', VendorCreateView.as_view(), name='vendor_create'),
    path('vendors/<uuid:pk>/', VendorDetailView.as_view(), name='vendor_detail'),
    path('vendors/<uuid:pk>/update/', VendorUpdateView.as_view(), name='vendor_update'),
    path('vendors/<uuid:pk>/delete/', VendorDeleteView.as_view(), name='vendor_delete'),
    path('vendors/<uuid:pk>/evaluate/', VendorEvaluateView.as_view(), name='vendor_evaluate'),
    
    # Requests
    path('requests/', PurchaseRequestListView.as_view(), name='requests'),
    path('requests/create/', PurchaseRequestCreateView.as_view(), name='request_create'),
    path('requests/<uuid:pk>/', PurchaseRequestDetailView.as_view(), name='request_detail'),
    path('requests/<uuid:pk>/update/', PurchaseRequestUpdateView.as_view(), name='request_update'),
    path('requests/<uuid:pk>/delete/', PurchaseRequestDeleteView.as_view(), name='request_delete'),
    path('requests/<uuid:pk>/action/', ApprovePurchaseRequestView.as_view(), name='request_action'),
    
    # Orders
    path('orders/', PurchaseOrderListView.as_view(), name='orders'),
    path('orders/create/', PurchaseOrderCreateView.as_view(), name='order_create'),
    path('orders/<uuid:pk>/', PurchaseOrderDetailView.as_view(), name='order_detail'),
    path('orders/<uuid:pk>/update/', PurchaseOrderUpdateView.as_view(), name='order_update'),
    path('orders/<uuid:pk>/delete/', PurchaseOrderDeleteView.as_view(), name='order_delete'),
    path('orders/<uuid:pk>/receive/', GoodsReceiptCreateView.as_view(), name='order_receive'),
    
    # Bills & Payments
    path('pos/<uuid:pk>/create-bill/', CreateBillFromPOView.as_view(), name='po_create_bill'),
    path('bills/', BillListView.as_view(), name='bills'),
    path('bills/<uuid:pk>/', BillDetailView.as_view(), name='bill_detail'),
    path('bills/<uuid:pk>/update/', BillUpdateView.as_view(), name='bill_update'),
    path('bills/<uuid:pk>/delete/', BillDeleteView.as_view(), name='bill_delete'),
    path('bills/<uuid:pk>/record-payment/', RecordVendorPaymentView.as_view(), name='bill_record_payment'),
    
    # Receipts
    path('receipts/', GoodsReceiptListView.as_view(), name='receipts'),
    path('receipts/<uuid:pk>/', GoodsReceiptDetailView.as_view(), name='receipt_detail'),
    path('receipts/<uuid:pk>/update/', GoodsReceiptUpdateView.as_view(), name='receipt_update'),
    path('receipts/<uuid:pk>/delete/', GoodsReceiptDeleteView.as_view(), name='receipt_delete'),
    
    # Enterprise Purchase (RFQs and Bids)
    path('rfqs/', RFQListView.as_view(), name='rfqs'),
    path('rfqs/create/', RFQCreateView.as_view(), name='rfq_create'),
    path('rfqs/<uuid:pk>/', RFQDetailView.as_view(), name='rfq_detail'),
    path('rfqs/<uuid:pk>/update/', RFQUpdateView.as_view(), name='rfq_update'),
    path('rfqs/<uuid:pk>/delete/', RFQDeleteView.as_view(), name='rfq_delete'),
    
    path('bids/', VendorBidListView.as_view(), name='bids'),
    path('bids/create/', VendorBidCreateView.as_view(), name='bid_create'),
    path('bids/<uuid:pk>/', VendorBidDetailView.as_view(), name='bid_detail'),
    path('bids/<uuid:pk>/action/', VendorBidActionView.as_view(), name='bid_action'),
    
    # Vendor Portal
    path('portal/', VendorPortalDashboardView.as_view(), name='portal_dashboard'),
    path('portal/rfqs/', VendorPortalRFQListView.as_view(), name='portal_rfqs'),
    path('portal/rfqs/<uuid:pk>/', VendorPortalRFQDetailView.as_view(), name='portal_rfq_detail'),
    path('portal/rfqs/<uuid:rfq_pk>/bid/', VendorPortalBidCreateView.as_view(), name='portal_bid_create'),
]
