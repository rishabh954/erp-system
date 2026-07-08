from django.urls import path

from .views import POSCheckoutAPIView, POSIndexView

app_name = "pos"
urlpatterns = [
    path("", POSIndexView.as_view(), name="index"),
    path("api/checkout/", POSCheckoutAPIView.as_view(), name="api_checkout"),
]
