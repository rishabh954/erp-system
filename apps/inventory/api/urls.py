from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BarcodeScanViewSet,
    InventoryTransferViewSet,
    ProductViewSet,
    StockMovementViewSet,
    StockRecordViewSet,
    WarehouseViewSet,
)

app_name = "api_inventory"

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("stock-records", StockRecordViewSet, basename="stock-record")
router.register("movements", StockMovementViewSet, basename="movement")
router.register("transfers", InventoryTransferViewSet, basename="transfer")
router.register("barcode", BarcodeScanViewSet, basename="barcode-scan")

urlpatterns = [path("", include(router.urls))]
