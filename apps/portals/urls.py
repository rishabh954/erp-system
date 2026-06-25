from django.urls import path
from . import views

app_name = 'portals'

urlpatterns = [
    # Customer Portal
    path('customer/', views.CustomerPortalView.as_view(), name='customer'),
    path('customer/orders/', views.CustomerOrderListView.as_view(), name='customer_orders'),
    path('customer/orders/<uuid:pk>/', views.CustomerOrderDetailView.as_view(), name='customer_order_detail'),
    path('customer/invoices/', views.CustomerInvoiceListView.as_view(), name='customer_invoices'),
    path('customer/tickets/', views.CustomerTicketListView.as_view(), name='customer_tickets'),
    path('customer/tickets/new/', views.CustomerTicketCreateView.as_view(), name='customer_ticket_create'),
    path('customer/tickets/<uuid:pk>/', views.CustomerTicketDetailView.as_view(), name='customer_ticket_detail'),

    # Vendor & Employee portals (legacy stubs)
    path('vendor/', views.VendorPortalView.as_view(), name='vendor'),
    path('employee/', views.EmployeePortalView.as_view(), name='employee'),
]
