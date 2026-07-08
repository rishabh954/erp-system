from django.urls import path

from . import views

app_name = "portals"

urlpatterns = [
    # Customer Portal
    path("customer/", views.CustomerPortalView.as_view(), name="customer"),
    path(
        "customer/orders/",
        views.CustomerOrderListView.as_view(),
        name="customer_orders",
    ),
    path(
        "customer/orders/<uuid:pk>/",
        views.CustomerOrderDetailView.as_view(),
        name="customer_order_detail",
    ),
    path(
        "customer/invoices/",
        views.CustomerInvoiceListView.as_view(),
        name="customer_invoices",
    ),
    path(
        "customer/payments/",
        views.CustomerPaymentListView.as_view(),
        name="customer_payments",
    ),
    path(
        "customer/tickets/",
        views.CustomerTicketListView.as_view(),
        name="customer_tickets",
    ),
    path(
        "customer/tickets/new/",
        views.CustomerTicketCreateView.as_view(),
        name="customer_ticket_create",
    ),
    path(
        "customer/tickets/<uuid:pk>/",
        views.CustomerTicketDetailView.as_view(),
        name="customer_ticket_detail",
    ),
    path(
        "customer/documents/",
        views.CustomerDocumentListView.as_view(),
        name="customer_documents",
    ),
    path(
        "customer/contracts/",
        views.CustomerContractListView.as_view(),
        name="customer_contracts",
    ),
    path(
        "customer/shipments/",
        views.CustomerShipmentListView.as_view(),
        name="customer_shipments",
    ),
    path(
        "customer/shipments/<uuid:pk>/",
        views.CustomerShipmentDetailView.as_view(),
        name="customer_shipment_detail",
    ),
    path(
        "customer/profile/",
        views.CustomerProfileView.as_view(),
        name="customer_profile",
    ),
    # Vendor Portal
    path("vendor/", views.VendorPortalView.as_view(), name="vendor"),
    path("vendor/orders/", views.VendorOrderListView.as_view(), name="vendor_orders"),
    path(
        "vendor/orders/<uuid:pk>/",
        views.VendorOrderDetailView.as_view(),
        name="vendor_order_detail",
    ),
    path("vendor/bills/", views.VendorBillListView.as_view(), name="vendor_bills"),
    path(
        "vendor/payments/",
        views.VendorPaymentListView.as_view(),
        name="vendor_payments",
    ),
    path("vendor/profile/", views.VendorProfileView.as_view(), name="vendor_profile"),
    # Employee portal
    path("employee/", views.EmployeePortalView.as_view(), name="employee"),
]
