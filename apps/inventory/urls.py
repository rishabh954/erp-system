from django.urls import path
from .views import (
    ProductListView, ProductDetailView, ProductCreateView,
    WarehouseListView, WarehouseCreateView, WarehouseUpdateView, WarehouseDeleteView,
    StockMovementListView, StockAdjustmentView,
    InventoryReportsView, ProductCategoryAjaxCreateView, ProductCategoryListView,
    ProductCategoryCreateView, ProductCategoryUpdateView, ProductCategoryDeleteView,
    TransferListView, TransferCreateView, TransferDetailView, TransferActionView,
    DeliveryOrderListView, DeliveryOrderDetailView, ShipDeliveryView,
    ReorderRuleListView, ReorderRuleDetailView,
    PickListListView, PickListDetailView, ShipmentListView, LotBatchListView,
    LandedCostListView, LotBatchDetailView, SerialNumberListView, SerialNumberDetailView
)
app_name = 'inventory'
urlpatterns = [
    path('products/', ProductListView.as_view(), name='products'),
    path('products/create/', ProductCreateView.as_view(), name='product_create'),
    path('products/<uuid:pk>/', ProductDetailView.as_view(), name='product_detail'),
    path('categories/', ProductCategoryListView.as_view(), name='categories'),
    path('categories/create/', ProductCategoryCreateView.as_view(), name='category_create'),
    path('categories/<uuid:pk>/update/', ProductCategoryUpdateView.as_view(), name='category_update'),
    path('categories/<uuid:pk>/delete/', ProductCategoryDeleteView.as_view(), name='category_delete'),
    path('categories/ajax-create/', ProductCategoryAjaxCreateView.as_view(), name='category_ajax_create'),
    path('warehouses/', WarehouseListView.as_view(), name='warehouses'),
    path('warehouses/create/', WarehouseCreateView.as_view(), name='warehouse_create'),
    path('warehouses/<uuid:pk>/update/', WarehouseUpdateView.as_view(), name='warehouse_update'),
    path('warehouses/<uuid:pk>/delete/', WarehouseDeleteView.as_view(), name='warehouse_delete'),
    path('movements/', StockMovementListView.as_view(), name='movements'),
    path('movements/adjust/', StockAdjustmentView.as_view(), name='stock_adjust'),
    path('deliveries/', DeliveryOrderListView.as_view(), name='deliveries'),
    path('deliveries/<uuid:pk>/', DeliveryOrderDetailView.as_view(), name='delivery_detail'),
    path('deliveries/<uuid:pk>/ship/', ShipDeliveryView.as_view(), name='delivery_ship'),
    
    # WMS Phase 7
    path('wms/picklists/', PickListListView.as_view(), name='picklists'),
    path('wms/picklists/<uuid:pk>/', PickListDetailView.as_view(), name='picklist_detail'),
    path('wms/shipments/', ShipmentListView.as_view(), name='shipments'),
    path('wms/lots/', LotBatchListView.as_view(), name='lots'),
    path('wms/lots/<uuid:pk>/', LotBatchDetailView.as_view(), name='lot_detail'),
    path('wms/serials/', SerialNumberListView.as_view(), name='serials'),
    path('wms/serials/<uuid:pk>/', SerialNumberDetailView.as_view(), name='serial_detail'),
    path('wms/landed-costs/', LandedCostListView.as_view(), name='landed_costs'),
    
    path('reports/', InventoryReportsView.as_view(), name='reports'),
    
    # Transfers
    path('transfers/', TransferListView.as_view(), name='transfers'),
    path('transfers/create/', TransferCreateView.as_view(), name='transfer_create'),
    path('transfers/<uuid:pk>/', TransferDetailView.as_view(), name='transfer_detail'),
    path('transfers/<uuid:pk>/action/', TransferActionView.as_view(), name='transfer_action'),
    
    # Enterprise Inventory
    path('reorder-rules/', ReorderRuleListView.as_view(), name='reorder_rules'),
    path('reorder-rules/<uuid:pk>/', ReorderRuleDetailView.as_view(), name='reorder_rule_detail'),
]
