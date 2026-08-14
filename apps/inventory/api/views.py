import logging

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
from core.api.mixins import TenantScopedViewSetMixin
from core.pagination import StandardResultsSetPagination

logger = logging.getLogger(__name__)


class ProductViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "inventory.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission

    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    pagination_class = StandardResultsSetPagination

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


class WarehouseViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "inventory.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission

    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    pagination_class = StandardResultsSetPagination


class StockRecordViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "inventory.approve"
    queryset = StockRecord.objects.all()
    serializer_class = StockRecordSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get("product")
        warehouse_id = self.request.query_params.get("warehouse")

        if product_id:
            qs = qs.filter(product_id=product_id)
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)

        return qs


class StockMovementViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    required_permission = "inventory.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission

    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer
    pagination_class = StandardResultsSetPagination


class InventoryTransferViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    required_permission = "inventory.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission

    queryset = InventoryTransfer.objects.all()
    serializer_class = InventoryTransferSerializer
    pagination_class = StandardResultsSetPagination

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

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "inventory.create"
            elif request.method in ["PUT", "PATCH"]:
                return "inventory.update"
            elif request.method == "DELETE":
                return "inventory.delete"
        return self.required_permission

    @action(detail=False, methods=["post"], url_path="scan-receive")
    def scan_receive(self, request):
        barcode = request.data.get("barcode")
        warehouse_id = request.data.get("warehouse")
        qty = request.data.get("quantity", 1)

        if not barcode or not warehouse_id:
            return Response({"error": "barcode and warehouse are required"}, status=400)

        from decimal import Decimal

        qty = Decimal(str(qty))

        company = getattr(request.user, "primary_company", None)
        product = Product.objects.filter(
            barcode=barcode, company=company
        ).first()

        if not product:
            return Response({"error": f"Product with barcode {barcode} not found"}, status=44)

        try:
            warehouse = Warehouse.objects.get(pk=warehouse_id, company=company)
        except Warehouse.DoesNotExist:
            return Response({"error": "Warehouse not found"}, status=404)

        stock_record, _ = StockRecord.objects.get_or_create(
            company=company,
            product=product,
            warehouse=warehouse,
            defaults={"quantity_on_hand": 0},
        )

        stock_record.quantity_on_hand += qty
        stock_record.save(update_fields=["quantity_on_hand"])

        StockMovement.objects.create(
            company=company,
            product=product,
            warehouse=warehouse,
            movement_type=StockMovement.MovementType.RECEIPT,
            quantity=qty,
            reference="BARCODE_SCAN",
            performed_by=request.user,
        )

        return Response(
            {
                "status": "success",
                "product": product.name,
                "new_quantity": str(stock_record.quantity_on_hand),
            }
        )
