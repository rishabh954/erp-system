"""Workflow REST API URLs"""

from django.urls import include, path
from rest_framework import serializers, viewsets
from rest_framework.routers import DefaultRouter

from apps.workflow.models import WorkflowInstance
from core.permissions import HasModulePermission

app_name = "api_workflow"


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowInstance
        fields = "__all__"


class WorkflowInstanceViewSet(viewsets.ReadOnlyModelViewSet):
    required_permission = "workflow.read"
    permission_classes = [HasModulePermission]
    queryset = WorkflowInstance.objects.all()
    serializer_class = WorkflowInstanceSerializer


router = DefaultRouter()
router.register("instances", WorkflowInstanceViewSet, basename="instance")
urlpatterns = [path("", include(router.urls))]
