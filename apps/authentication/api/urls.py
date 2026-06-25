"""Authentication API URLs"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LoginAPIView, LogoutAPIView, UserViewSet, RoleViewSet, ModulePermissionViewSet, ActivityLogViewSet

app_name = 'api_auth'

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('roles', RoleViewSet, basename='role')
router.register('module-permissions', ModulePermissionViewSet, basename='module-permission')
router.register('activity-logs', ActivityLogViewSet, basename='activity-log')

urlpatterns = [
    path('login/', LoginAPIView.as_view(), name='login'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('', include(router.urls)),
]
