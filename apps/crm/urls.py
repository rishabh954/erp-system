from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    LeadListView, LeadDetailView, LeadCreateView, LeadUpdateView, LeadDeleteView,
    LeadUpdateStatusView, LeadConvertView, LeadToggleOpportunityView, AddActivityView, PipelineView,
    CustomerListView, CustomerDetailView, CustomerCreateView, CustomerUpdateView, CustomerDeleteView,
    CampaignListView, CampaignCreateView, CampaignDetailView, CampaignReportView,
    MeetingSchedulerView, OpportunityListView, InteractionListView,
    ContractListView, ContractDetailView, ContractCreateView, ContractUpdateView, ContractDeleteView, ContractReportView, CRMDashboardView
)
from .views_setup import (
    TerritoryListView, TerritoryCreateView, TerritoryUpdateView, TerritoryDeleteView,
    LeadAssignmentRuleListView, LeadAssignmentRuleCreateView, LeadAssignmentRuleUpdateView, LeadAssignmentRuleDeleteView,
    SalesTargetListView, SalesTargetCreateView, SalesTargetUpdateView, SalesTargetDeleteView
)
from .api.views import LeadViewSet, CustomerViewSet, ContractViewSet

router = DefaultRouter()
router.register(r'leads', LeadViewSet, basename='api-leads')
router.register(r'customers', CustomerViewSet, basename='api-customers')
router.register(r'contracts', ContractViewSet, basename='api-contracts')

app_name = 'crm'

urlpatterns = [
    path('api/', include(router.urls)),
    path('dashboard/', CRMDashboardView.as_view(), name='dashboard'),
    
    path('leads/', LeadListView.as_view(), name='leads'),
    path('leads/create/', LeadCreateView.as_view(), name='lead_create'),
    path('leads/<uuid:pk>/', LeadDetailView.as_view(), name='lead_detail'),
    path('leads/<uuid:pk>/edit/', LeadUpdateView.as_view(), name='lead_update'),
    path('leads/<uuid:pk>/delete/', LeadDeleteView.as_view(), name='lead_delete'),
    path('leads/<uuid:pk>/status/', LeadUpdateStatusView.as_view(), name='lead_update_status'),
    path('leads/<uuid:pk>/convert/', LeadConvertView.as_view(), name='lead_convert'),
    path('leads/<uuid:pk>/toggle-opportunity/', LeadToggleOpportunityView.as_view(), name='lead_toggle_opportunity'),
    path('leads/<uuid:pk>/activity/', AddActivityView.as_view(), name='lead_add_activity'),
    
    path('opportunities/', OpportunityListView.as_view(), name='opportunities'),
    path('pipeline/', PipelineView.as_view(), name='pipeline'),
    
    path('customers/', CustomerListView.as_view(), name='customers'),
    path('customers/create/', CustomerCreateView.as_view(), name='customer_create'),
    path('customers/<uuid:pk>/', CustomerDetailView.as_view(), name='customer_detail'),
    path('customers/<uuid:pk>/edit/', CustomerUpdateView.as_view(), name='customer_update'),
    path('customers/<uuid:pk>/delete/', CustomerDeleteView.as_view(), name='customer_delete'),
    
    path('campaigns/', CampaignListView.as_view(), name='campaigns'),
    path('campaigns/report/', CampaignReportView.as_view(), name='campaign_report'),
    path('campaigns/create/', CampaignCreateView.as_view(), name='campaign_create'),
    path('campaigns/<uuid:pk>/', CampaignDetailView.as_view(), name='campaign_detail'),
    
    path('contracts/', ContractListView.as_view(), name='contracts'),
    path('contracts/report/', ContractReportView.as_view(), name='contract_report'),
    path('contracts/create/', ContractCreateView.as_view(), name='contract_create'),
    path('contracts/<uuid:pk>/', ContractDetailView.as_view(), name='contract_detail'),
    path('contracts/<uuid:pk>/edit/', ContractUpdateView.as_view(), name='contract_update'),
    path('contracts/<uuid:pk>/delete/', ContractDeleteView.as_view(), name='contract_delete'),
    
    path('interactions/', InteractionListView.as_view(), name='interactions'),
    path('meetings/', MeetingSchedulerView.as_view(), name='meeting_scheduler'),
    
    # Setup - Sales Team Management
    path('setup/territories/', TerritoryListView.as_view(), name='territory_list'),
    path('setup/territories/create/', TerritoryCreateView.as_view(), name='territory_create'),
    path('setup/territories/<uuid:pk>/edit/', TerritoryUpdateView.as_view(), name='territory_update'),
    path('setup/territories/<uuid:pk>/delete/', TerritoryDeleteView.as_view(), name='territory_delete'),
    
    path('setup/rules/', LeadAssignmentRuleListView.as_view(), name='rule_list'),
    path('setup/rules/create/', LeadAssignmentRuleCreateView.as_view(), name='rule_create'),
    path('setup/rules/<uuid:pk>/edit/', LeadAssignmentRuleUpdateView.as_view(), name='rule_update'),
    path('setup/rules/<uuid:pk>/delete/', LeadAssignmentRuleDeleteView.as_view(), name='rule_delete'),
    
    path('setup/targets/', SalesTargetListView.as_view(), name='target_list'),
    path('setup/targets/create/', SalesTargetCreateView.as_view(), name='target_create'),
    path('setup/targets/<uuid:pk>/edit/', SalesTargetUpdateView.as_view(), name='target_update'),
    path('setup/targets/<uuid:pk>/delete/', SalesTargetDeleteView.as_view(), name='target_delete'),
]
