"""Workflow REST API URLs"""

from django.urls import include, path
from rest_framework import viewsets
from rest_framework.routers import DefaultRouter

from apps.workflow.models import WorkflowInstance
from core.api.fields import TenantModelSerializer
from core.api.mixins import TenantScopedViewSetMixin

app_name = "api_workflow"


class WorkflowInstanceSerializer(TenantModelSerializer):
    class Meta:
        model = WorkflowInstance
        fields = "__all__"


class WorkflowInstanceViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "workflow.read"
    queryset = WorkflowInstance.objects.all()
    serializer_class = WorkflowInstanceSerializer


router = DefaultRouter()
router.register("instances", WorkflowInstanceViewSet, basename="instance")
urlpatterns = [path("", include(router.urls))]
