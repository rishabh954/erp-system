from core.permissions import PermissionRequiredMixin
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.inventory.api.serializers import (
    InventoryTransferSerializer,
    ProductSerializer,
    StockMovementSerializer,
    StockRecordSerializer,
    WarehouseSerializer,
)
from apps.inventory.models import (
    InventoryTransfer,
    Product,
    StockMovement,
    StockRecord,
    Warehouse,
)
from core.pagination import StandardResultsSetPagination


class ProductViewSet(viewsets.ModelViewSet):
    required_permission = "inventory.read"
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, "company") and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs

    @action(detail=True, methods=["get"])
    def stock_summary(self, request, pk=None):
        product = self.get_object()
        records = StockRecord.objects.filter(product=product)
        summary = []
        for record in records:
            summary.append(
                {
                    "warehouse": record.warehouse.name,
                    "quantity_on_hand": record.quantity_on_hand,
                    "quantity_reserved": record.quantity_reserved,
                    "quantity_available": record.quantity_available,
                }
            )
        return Response({"total_stock": product.total_stock, "warehouses": summary})

    @action(detail=True, methods=["post"])
    def adjust_stock(self, request, pk=None):
        product = self.get_object()
        warehouse_id = request.data.get("warehouse_id")
        quantity = request.data.get("quantity")
        adjustment_type = request.data.get("type")  # 'add', 'remove', 'set'
        request.data.get("notes", "")

        if (
            not warehouse_id
            or quantity is None
            or adjustment_type not in ["add", "remove", "set"]
        ):
            return Response(
                {"error": "Invalid parameters"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            warehouse = Warehouse.objects.get(pk=warehouse_id, company=product.company)
        except Warehouse.DoesNotExist:
            return Response(
                {"error": "Warehouse not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # In a real app, this would use a service to perform the adjustment, update StockRecord, and create StockMovement
        return Response(
            {
                "status": "stock_adjusted",
                "product": product.name,
                "warehouse": warehouse.name,
            }
        )


class WarehouseViewSet(viewsets.ModelViewSet):
    required_permission = "inventory.read"
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, "company") and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs


class StockRecordViewSet(viewsets.ReadOnlyModelViewSet):
    required_permission = "inventory.approve"
    queryset = StockRecord.objects.all()
    serializer_class = StockRecordSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, "company") and self.request.company:
            qs = qs.filter(company=self.request.company)

        product_id = self.request.query_params.get("product")
        warehouse_id = self.request.query_params.get("warehouse")

        if product_id:
            qs = qs.filter(product_id=product_id)
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        return qs


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    required_permission = "inventory.read"
    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, "company") and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs


class InventoryTransferViewSet(viewsets.ModelViewSet):
    required_permission = "inventory.read"
    queryset = InventoryTransfer.objects.all()
    serializer_class = InventoryTransferSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request, "company") and self.request.company:
            qs = qs.filter(company=self.request.company)
        return qs

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status != InventoryTransfer.Status.DRAFT:
            return Response(
                {"error": "Can only approve draft transfers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfer.status = InventoryTransfer.Status.APPROVED
        transfer.approved_by = request.user
        transfer.save(update_fields=["status", "approved_by"])
        return Response({"status": "approved"})

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status not in [
            InventoryTransfer.Status.APPROVED,
            InventoryTransfer.Status.IN_TRANSIT,
        ]:
            return Response(
                {"error": "Can only receive approved/in-transit transfers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transfer.status = InventoryTransfer.Status.COMPLETED
        transfer.received_by = request.user
        transfer.received_at = timezone.now()
        transfer.save(update_fields=["status", "received_by", "received_at"])

        # In a real app, this would also trigger the stock movements here
        return Response({"status": "received"})


class BarcodeScanViewSet(viewsets.ViewSet):
    required_permission = "inventory.read"
    @action(detail=False, methods=["post"], url_path="scan-receive")
    def scan_receive(self, request):
        barcode = request.data.get("barcode")
        warehouse_id = request.data.get("warehouse")
        qty = request.data.get("quantity", 1)

        if not barcode or not warehouse_id:
            return Response({"error": "barcode and warehouse are required"}, status=400)

        from decimal import Decimal

        qty = Decimal(str(qty))

        product = Product.objects.filter(
            barcode=barcode, company=request.user.primary_company
        ).first()
        if not product:
            return Response({"error": "Product not found"}, status=404)

        try:
            warehouse = Warehouse.objects.get(
                pk=warehouse_id, company=request.user.primary_company
            )
        except Warehouse.DoesNotExist:
            return Response({"error": "Warehouse not found"}, status=404)

        from apps.inventory.services import StockService

        try:
            StockService(
                user=request.user, company=request.user.primary_company
            ).receive_stock(
                product=product,
                warehouse=warehouse,
                qty=qty,
                unit_cost=product.cost_price,
                reference_type="Barcode Scan",
                reference_id="0",
                notes="Received via barcode scan",
            )
            return Response(
                {"status": "success", "product": product.name, "quantity": qty}
            )
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    @action(detail=False, methods=["post"], url_path="scan-pick")
    def scan_pick(self, request):
        barcode = request.data.get("barcode")
        pick_list_id = request.data.get("pick_list")

        if not barcode or not pick_list_id:
            return Response({"error": "barcode and pick_list are required"}, status=400)

        from apps.inventory.models import PickListLine

        line = PickListLine.objects.filter(
            pick_list_id=pick_list_id,
            product__barcode=barcode,
            pick_list__company=request.user.primary_company,
        ).first()

        if not line:
            return Response({"error": "Product not in pick list"}, status=404)

        if line.quantity_picked >= line.quantity_to_pick:
            return Response({"error": "Product already fully picked"}, status=400)

        line.quantity_picked += 1
        line.save(update_fields=["quantity_picked"])

        return Response(
            {
                "status": "success",
                "product": line.product.name,
                "picked": line.quantity_picked,
                "remaining": line.quantity_to_pick - line.quantity_picked,
            }
        )
