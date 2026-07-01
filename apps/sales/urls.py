"""Sales Web URLs"""
from django.urls import path
from .views import (
    QuotationListView, QuotationDetailView, QuotationCreateView,
    QuotationUpdateView, QuotationDeleteView,
    QuotationSendView, QuotationConvertToSOView, QuotationRejectView, QuotationApproveView,
    SalesOrderListView, SalesOrderDetailView,
    SalesOrderCreateView, SalesOrderUpdateView, SalesOrderDeleteView, SalesOrderCancelView,
    CreateInvoiceFromSOView, CreateDeliveryFromSOView,
    InvoiceListView, InvoiceDetailView,
    InvoiceCreateView, InvoiceUpdateView, InvoiceDeleteView,
    InvoicePDFView, RecordPaymentView, InvoiceGeneratePaymentLinkView,
    PaymentListView,
    PriceListListView, PriceListDetailView,
    SubscriptionListView, SubscriptionDetailView, SubscriptionCreateView, SubscriptionUpdateView, SubscriptionGenerateInvoiceView,
    CreditNoteListView, CreditNoteDetailView,
    SalesCommissionListView, SalesCommissionPayView,
    SalesDashboardView, POSView, POSAPIView
)
app_name = 'sales'
urlpatterns = [
    path('quotations/', QuotationListView.as_view(), name='quotations'),
    path('quotations/create/', QuotationCreateView.as_view(), name='quotation_create'),
    path('quotations/<uuid:pk>/', QuotationDetailView.as_view(), name='quotation_detail'),
    path('quotations/<uuid:pk>/edit/', QuotationUpdateView.as_view(), name='quotation_update'),
    path('quotations/<uuid:pk>/delete/', QuotationDeleteView.as_view(), name='quotation_delete'),
    path('quotations/<uuid:pk>/send/', QuotationSendView.as_view(), name='quotation_send'),
    path('quotations/<uuid:pk>/approve/', QuotationApproveView.as_view(), name='quotation_approve'),
    path('quotations/<uuid:pk>/convert/', QuotationConvertToSOView.as_view(), name='quotation_convert'),
    path('quotations/<uuid:pk>/reject/', QuotationRejectView.as_view(), name='quotation_reject'),
    path('orders/', SalesOrderListView.as_view(), name='orders'),
    path('orders/create/', SalesOrderCreateView.as_view(), name='order_create'),
    
    # Enterprise Sales
    path('dashboard/', SalesDashboardView.as_view(), name='dashboard'),
    path('pos/', POSView.as_view(), name='pos'),
    path('pos/api/', POSAPIView.as_view(), name='pos_api'),
    
    path('price-lists/', PriceListListView.as_view(), name='price_lists'),
    path('price-lists/<uuid:pk>/', PriceListDetailView.as_view(), name='price_list_detail'),
    
    path('subscriptions/', SubscriptionListView.as_view(), name='subscriptions'),
    path('subscriptions/create/', SubscriptionCreateView.as_view(), name='subscription_create'),
    path('subscriptions/<uuid:pk>/', SubscriptionDetailView.as_view(), name='subscription_detail'),
    path('subscriptions/<uuid:pk>/edit/', SubscriptionUpdateView.as_view(), name='subscription_update'),
    path('subscriptions/<uuid:pk>/invoice/', SubscriptionGenerateInvoiceView.as_view(), name='subscription_invoice'),
    
    path('credit-notes/', CreditNoteListView.as_view(), name='credit_notes'),
    path('credit-notes/<uuid:pk>/', CreditNoteDetailView.as_view(), name='credit_note_detail'),
    path('commissions/', SalesCommissionListView.as_view(), name='commissions'),
    path('commissions/<uuid:pk>/pay/', SalesCommissionPayView.as_view(), name='commission_pay'),
    path('orders/<uuid:pk>/', SalesOrderDetailView.as_view(), name='order_detail'),
    path('orders/<uuid:pk>/edit/', SalesOrderUpdateView.as_view(), name='order_update'),
    path('orders/<uuid:pk>/delete/', SalesOrderDeleteView.as_view(), name='order_delete'),
    path('orders/<uuid:pk>/cancel/', SalesOrderCancelView.as_view(), name='order_cancel'),
    path('orders/<uuid:pk>/invoice/', CreateInvoiceFromSOView.as_view(), name='order_invoice'),
    path('orders/<uuid:pk>/delivery/', CreateDeliveryFromSOView.as_view(), name='order_delivery'),
    path('invoices/', InvoiceListView.as_view(), name='invoices'),
    path('invoices/create/', InvoiceCreateView.as_view(), name='invoice_create'),
    path('invoices/<uuid:pk>/', InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoices/<uuid:pk>/payment-link/', InvoiceGeneratePaymentLinkView.as_view(), name='invoice_payment_link'),
    path('invoices/<uuid:pk>/edit/', InvoiceUpdateView.as_view(), name='invoice_update'),
    path('invoices/<uuid:pk>/delete/', InvoiceDeleteView.as_view(), name='invoice_delete'),
    path('invoices/<uuid:pk>/pdf/', InvoicePDFView.as_view(), name='invoice_pdf'),
    path('invoices/<uuid:pk>/payment/', RecordPaymentView.as_view(), name='invoice_payment'),
    path('payments/', PaymentListView.as_view(), name='payments'),
]
