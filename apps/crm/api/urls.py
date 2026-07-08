from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.crm.api.views import CampaignViewSet, ContractViewSet, LeadViewSet

app_name = "api_crm"
router = DefaultRouter()
router.register(r"leads", LeadViewSet, basename="lead")
router.register(r"campaigns", CampaignViewSet, basename="campaign")
router.register(r"contracts", ContractViewSet, basename="contract")
# Add more as needed based on views.py

urlpatterns = [path("", include(router.urls))]
