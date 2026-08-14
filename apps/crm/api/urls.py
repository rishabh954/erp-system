from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.crm.api.views import (
    CampaignViewSet,
    ContractViewSet,
    CustomerViewSet,
    LeadActivityViewSet,
    LeadViewSet,
)

app_name = "api_crm"
router = DefaultRouter()
router.register(r"leads", LeadViewSet, basename="lead")
router.register(r"campaigns", CampaignViewSet, basename="campaign")
router.register(r"contracts", ContractViewSet, basename="contract")
router.register(r"customers", CustomerViewSet, basename="customer")
router.register(r"activities", LeadActivityViewSet, basename="activity")

urlpatterns = [path("", include(router.urls))]
