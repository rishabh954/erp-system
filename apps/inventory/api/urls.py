from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProductViewSet, WarehouseViewSet, StockRecordViewSet,
    StockMovementViewSet, InventoryTransferViewSet
)

app_name = 'api_inventory'

router = DefaultRouter()
router.register('products', ProductViewSet, basename='product')
router.register('warehouses', WarehouseViewSet, basename='warehouse')
router.register('stock-records', StockRecordViewSet, basename='stock-record')
router.register('movements', StockMovementViewSet, basename='movement')
router.register('transfers', InventoryTransferViewSet, basename='transfer')

urlpatterns = [
    path('', include(router.urls))
]
