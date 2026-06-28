"""Workflow REST API URLs"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework import viewsets, serializers
from apps.workflow.models import WorkflowInstance

app_name = 'api_workflow'


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowInstance
        fields = '__all__'


class WorkflowInstanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = WorkflowInstance.objects.all()
    serializer_class = WorkflowInstanceSerializer


router = DefaultRouter()
router.register('instances', WorkflowInstanceViewSet, basename='instance')
urlpatterns = [path('', include(router.urls))]
