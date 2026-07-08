from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.notifications.views import NotificationViewSet

app_name = "api_notifications"
router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
urlpatterns = [path("", include(router.urls))]
