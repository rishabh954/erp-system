from django.urls import path
from . import views
from .views import (
    GoodsReceiptListView, GoodsReceiptDetailView, GoodsReceiptCreateView,
    VendorListView, VendorDetailView, VendorCreateView,
    PurchaseRequestListView, PurchaseRequestCreateView, PurchaseRequestDetailView,
    ApprovePurchaseRequestView, PurchaseOrderListView, PurchaseOrderCreateView,
    PurchaseOrderDetailView, RFQListView, RFQDetailView, VendorBidListView, VendorBidDetailView,
    PurchaseDashboardView, VendorEvaluateView
)
app_name = 'purchase'
urlpatterns = [
    path('dashboard/', PurchaseDashboardView.as_view(), name='dashboard'),
    path('vendors/', VendorListView.as_view(), name='vendors'),
    path('vendors/create/', VendorCreateView.as_view(), name='vendor_create'),
    path('vendors/<uuid:pk>/', VendorDetailView.as_view(), name='vendor_detail'),
    path('vendors/<uuid:pk>/evaluate/', VendorEvaluateView.as_view(), name='vendor_evaluate'),
    path('requests/', PurchaseRequestListView.as_view(), name='requests'),
    path('requests/create/', PurchaseRequestCreateView.as_view(), name='request_create'),
    path('requests/<uuid:pk>/', PurchaseRequestDetailView.as_view(), name='request_detail'),
    path('requests/<uuid:pk>/action/', ApprovePurchaseRequestView.as_view(), name='request_action'),
    path('orders/', PurchaseOrderListView.as_view(), name='orders'),
    path('orders/create/', PurchaseOrderCreateView.as_view(), name='order_create'),
    path('orders/<uuid:pk>/', PurchaseOrderDetailView.as_view(), name='order_detail'),
    # Bills & Payments
    path('pos/<uuid:pk>/create-bill/', views.CreateBillFromPOView.as_view(), name='po_create_bill'),
    path('bills/', views.BillListView.as_view(), name='bills'),
    path('bills/<uuid:pk>/', views.BillDetailView.as_view(), name='bill_detail'),
    path('bills/<uuid:pk>/record-payment/', views.RecordVendorPaymentView.as_view(), name='bill_record_payment'),
    path('receipts/', GoodsReceiptListView.as_view(), name='receipts'),
    path('receipts/<uuid:pk>/', GoodsReceiptDetailView.as_view(), name='receipt_detail'),
    path('orders/<uuid:pk>/receive/', GoodsReceiptCreateView.as_view(), name='order_receive'),
    
    # Enterprise Purchase
    path('rfqs/', RFQListView.as_view(), name='rfqs'),
    path('rfqs/<uuid:pk>/', RFQDetailView.as_view(), name='rfq_detail'),
    path('bids/', VendorBidListView.as_view(), name='bids'),
    path('bids/<uuid:pk>/', VendorBidDetailView.as_view(), name='bid_detail'),
]
