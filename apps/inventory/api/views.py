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

        # Delegate to StockService to perform the adjustment with proper
        # concurrency guards (select_for_update + transaction.atomic).
        from decimal import Decimal, InvalidOperation

        from apps.inventory.services import StockService

        try:
            quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError):
            return Response(
                {"error": "quantity must be a valid number"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        notes = request.data.get("notes", "")
        stock_service = StockService(company=product.company, user=request.user)
        try:
            if adjustment_type == "add":
                record = stock_service.receive_stock(
                    product=product, warehouse=warehouse, qty=quantity, reference="MANUAL_ADJUST", notes=notes
                )
            elif adjustment_type == "remove":
                record = stock_service.issue_stock(
                    product=product, warehouse=warehouse, qty=quantity, reference="MANUAL_ADJUST", notes=notes
                )
            else:  # set
                record = stock_service.set_stock(
                    product=product, warehouse=warehouse, qty=quantity, reference="MANUAL_ADJUST", notes=notes
                )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": "stock_adjusted",
                "product": product.name,
                "warehouse": warehouse.name,
                "new_quantity": str(record.quantity_on_hand),
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

        # Trigger actual stock movements for the transfer lines
        from django.db import transaction as db_transaction

        from apps.inventory.services import StockService

        with db_transaction.atomic():
            stock_service = StockService(company=transfer.company, user=request.user)
            for line in transfer.lines.select_related("product").all():
                if line.product:
                    stock_service.issue_stock(
                        product=line.product,
                        warehouse=transfer.source_warehouse,
                        qty=line.quantity,
                        reference=f"TRANSFER:{transfer.number}",
                        notes=f"Transfer to {transfer.destination_warehouse.name}",
                    )
                    stock_service.receive_stock(
                        product=line.product,
                        warehouse=transfer.destination_warehouse,
                        qty=line.quantity,
                        reference=f"TRANSFER:{transfer.number}",
                        notes=f"Transfer from {transfer.source_warehouse.name}",
                    )

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
            return Response(
                {"error": "barcode and warehouse are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from decimal import Decimal, InvalidOperation

        try:
            qty = Decimal(str(qty))
        except (InvalidOperation, TypeError):
            return Response(
                {"error": "quantity must be a valid number"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if qty <= 0:
            return Response(
                {"error": "quantity must be greater than zero"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Always use request.company (set by TenantMiddleware) for correct scoping
        company = getattr(request, "company", None) or getattr(request.user, "primary_company", None)
        if not company:
            return Response(
                {"error": "No active company context."},
                status=status.HTTP_403_FORBIDDEN,
            )

        product = Product.objects.filter(barcode=barcode, company=company).first()
        if not product:
            return Response(
                {"error": f"Product with barcode '{barcode}' not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            warehouse = Warehouse.objects.get(pk=warehouse_id, company=company)
        except Warehouse.DoesNotExist:
            return Response(
                {"error": "Warehouse not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Delegate to StockService so all concurrency guards (select_for_update,
        # transaction.atomic, StockMovement creation) happen in one place.
        from apps.inventory.services import StockService

        stock_service = StockService(company=company, user=request.user)
        try:
            record = stock_service.receive_stock(
                product=product,
                warehouse=warehouse,
                qty=qty,
                reference="BARCODE_SCAN",
                notes=f"Barcode scan receipt by {request.user.email}",
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "status": "success",
                "product": product.name,
                "new_quantity": str(record.quantity_on_hand),
            },
            status=status.HTTP_200_OK,
        )
