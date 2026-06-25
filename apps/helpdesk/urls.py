from django.urls import path
from .views import TicketListView, TicketDetailView, TicketCreateView, AddReplyView
app_name = 'helpdesk'
urlpatterns = [
    path('tickets/', TicketListView.as_view(), name='tickets'),
    path('tickets/create/', TicketCreateView.as_view(), name='ticket_create'),
    path('tickets/<uuid:pk>/', TicketDetailView.as_view(), name='ticket_detail'),
    path('tickets/<uuid:pk>/reply/', AddReplyView.as_view(), name='ticket_reply'),
]
