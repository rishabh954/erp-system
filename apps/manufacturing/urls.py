from django.urls import path
from . import views

app_name = 'manufacturing'

urlpatterns = [
    path('work-centers/', views.WorkCenterListView.as_view(), name='work_centers'),
    path('routings/', views.RoutingListView.as_view(), name='routings'),
    
    path('boms/', views.BOMListView.as_view(), name='boms'),
    path('boms/create/', views.BOMCreateView.as_view(), name='bom_create'),
    path('boms/<uuid:pk>/', views.BOMDetailView.as_view(), name='bom_detail'),
    
    path('work-orders/', views.WorkOrderListView.as_view(), name='work_orders'),
    path('work-orders/<uuid:pk>/', views.WorkOrderDetailView.as_view(), name='work_order_detail'),
    path('work-orders/<uuid:pk>/start/', views.WorkOrderStartView.as_view(), name='work_order_start'),
    path('work-orders/<uuid:pk>/complete/', views.WorkOrderCompleteView.as_view(), name='work_order_complete'),
    
    # Scrap & Downtime
    path('scrap/', __import__('apps.manufacturing.views', fromlist=['ScrapOrderListView']).ScrapOrderListView.as_view(), name='scrap_orders'),
    path('scrap/<uuid:pk>/', __import__('apps.manufacturing.views', fromlist=['ScrapOrderDetailView']).ScrapOrderDetailView.as_view(), name='scrap_order_detail'),
    path('downtime/', __import__('apps.manufacturing.views', fromlist=['DowntimeLogListView']).DowntimeLogListView.as_view(), name='downtime_logs'),
    path('downtime/<uuid:pk>/', __import__('apps.manufacturing.views', fromlist=['DowntimeLogDetailView']).DowntimeLogDetailView.as_view(), name='downtime_log_detail'),
    
    # Quality Control & Costing
    path('quality/', __import__('apps.manufacturing.views', fromlist=['QualityCheckListView']).QualityCheckListView.as_view(), name='quality_checks'),
    path('quality/<uuid:pk>/', __import__('apps.manufacturing.views', fromlist=['QualityCheckDetailView']).QualityCheckDetailView.as_view(), name='quality_check_detail'),
    path('costing/', __import__('apps.manufacturing.views', fromlist=['ProductionCostingListView']).ProductionCostingListView.as_view(), name='production_costings'),
    path('costing/<uuid:pk>/', __import__('apps.manufacturing.views', fromlist=['ProductionCostingDetailView']).ProductionCostingDetailView.as_view(), name='production_costing_detail'),
    
    path('orders/', views.MOListView.as_view(), name='orders'),
    path('orders/create/', views.MOCreateView.as_view(), name='mo_create'),
    path('orders/<uuid:pk>/', views.MODetailView.as_view(), name='mo_detail'),
    path('orders/<uuid:pk>/action/', views.MOActionView.as_view(), name='mo_action'),
]
