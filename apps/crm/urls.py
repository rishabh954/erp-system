from django.urls import path
from .views import (
    LeadListView, LeadDetailView, LeadCreateView, LeadUpdateView, LeadDeleteView,
    LeadUpdateStatusView, LeadConvertView, AddActivityView, PipelineView,
    CustomerListView, CustomerDetailView, CustomerCreateView, CustomerUpdateView, CustomerDeleteView,
    CampaignListView, CampaignCreateView, CampaignDetailView,
    MeetingSchedulerView, OpportunityListView, InteractionListView,
    ContractListView, ContractDetailView, ContractCreateView, CRMDashboardView
)

app_name = 'crm'

urlpatterns = [
    path('dashboard/', CRMDashboardView.as_view(), name='dashboard'),
    
    path('leads/', LeadListView.as_view(), name='leads'),
    path('leads/create/', LeadCreateView.as_view(), name='lead_create'),
    path('leads/<uuid:pk>/', LeadDetailView.as_view(), name='lead_detail'),
    path('leads/<uuid:pk>/edit/', LeadUpdateView.as_view(), name='lead_update'),
    path('leads/<uuid:pk>/delete/', LeadDeleteView.as_view(), name='lead_delete'),
    path('leads/<uuid:pk>/status/', LeadUpdateStatusView.as_view(), name='lead_update_status'),
    path('leads/<uuid:pk>/convert/', LeadConvertView.as_view(), name='lead_convert'),
    path('leads/<uuid:pk>/activity/', AddActivityView.as_view(), name='lead_add_activity'),
    
    path('opportunities/', OpportunityListView.as_view(), name='opportunities'),
    path('pipeline/', PipelineView.as_view(), name='pipeline'),
    
    path('customers/', CustomerListView.as_view(), name='customers'),
    path('customers/create/', CustomerCreateView.as_view(), name='customer_create'),
    path('customers/<uuid:pk>/', CustomerDetailView.as_view(), name='customer_detail'),
    path('customers/<uuid:pk>/edit/', CustomerUpdateView.as_view(), name='customer_update'),
    path('customers/<uuid:pk>/delete/', CustomerDeleteView.as_view(), name='customer_delete'),
    
    path('campaigns/', CampaignListView.as_view(), name='campaigns'),
    path('campaigns/create/', CampaignCreateView.as_view(), name='campaign_create'),
    path('campaigns/<uuid:pk>/', CampaignDetailView.as_view(), name='campaign_detail'),
    
    path('contracts/', ContractListView.as_view(), name='contracts'),
    path('contracts/create/', ContractCreateView.as_view(), name='contract_create'),
    path('contracts/<uuid:pk>/', ContractDetailView.as_view(), name='contract_detail'),
    
    path('interactions/', InteractionListView.as_view(), name='interactions'),
    path('meetings/', MeetingSchedulerView.as_view(), name='meeting_scheduler'),
]
