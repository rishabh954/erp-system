from django.urls import path, include
from rest_framework.routers import DefaultRouter
from apps.workflow.views import WorkflowInstanceViewSet
app_name = 'api_workflow'
router = DefaultRouter()
router.register('instances', WorkflowInstanceViewSet, basename='instance')
urlpatterns = [path('', include(router.urls))]
