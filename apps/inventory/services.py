import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone

from .models import Product, StockMovement

logger = logging.getLogger(__name__)

class InventoryAnalyticsService:

    @staticmethod
    def compute_abc_analysis(company):
        """
        Compute ABC classification for all active stockable products in the company
        based on the consumption value over the past 12 months.
        A: Top 80%
        B: Next 15%
        C: Bottom 5%
        """
        one_year_ago = timezone.now().date() - timedelta(days=365)

        # Calculate total consumption value per product
        # Delivery, Production Out, etc. represent consumption
        consumption_types = [
            StockMovement.MovementType.DELIVERY,
            StockMovement.MovementType.PRODUCTION_OUT,
        ]

        # We need to aggregate the absolute value of quantity * unit_cost
        # Since Delivery quantity is usually negative, we multiply by -1
        products_usage = []
        total_usage_value = Decimal("0")

        for product in Product.objects.filter(
            company=company, is_active=True, product_type=Product.ProductType.STOCKABLE
        ):
            movements = StockMovement.objects.filter(
                product=product,
                movement_type__in=consumption_types,
                movement_date__gte=one_year_ago,
            )

            # Since outbound movements are negative quantity, we multiply by -1 to get positive consumption
            usage = movements.aggregate(
                val=Sum(
                    ExpressionWrapper(
                        F("quantity") * F("unit_cost") * -1, output_field=DecimalField()
                    )
                )
            )["val"] or Decimal("0")

            if usage > 0:
                products_usage.append({"product": product, "usage": usage})
                total_usage_value += usage
            else:
                # If no usage, automatically C
                product.abc_classification = "C"
                product.save(update_fields=["abc_classification"])

        if not total_usage_value:
            return

        # Sort products by usage descending
        products_usage.sort(key=lambda x: x["usage"], reverse=True)

        cumulative_value = Decimal("0")

        for item in products_usage:
            previous_percent = (cumulative_value / total_usage_value) * 100

            if previous_percent < 80:
                classification = "A"
            elif previous_percent < 95:
                classification = "B"
            else:
                classification = "C"

            cumulative_value += item["usage"]

            prod = item["product"]
            if prod.abc_classification != classification:
                prod.abc_classification = classification
                prod.save(update_fields=["abc_classification"])


from django.db import transaction  # noqa: E402

from apps.inventory.models import (  # noqa: E402
    InventoryTransfer,
    InventoryTransferLine,
    StockRecord,
)
from core.services import BaseService  # noqa: E402


class StockService(BaseService):
    @transaction.atomic
    def reserve_stock(
        self, product, warehouse, qty, reference_type="", reference_id=""
    ):
        qty = Decimal(str(qty))
        stock, _ = StockRecord.objects.select_for_update().get_or_create(
            product=product,
            warehouse=warehouse,
            defaults={
                "company": self.company,
                "average_cost": product.cost_price,
                "quantity_on_hand": 0,
                "quantity_reserved": 0,
            },
        )

        available = stock.quantity_on_hand - stock.quantity_reserved
        if available < qty:
            raise ValueError(
                f"Cannot reserve {qty} of {product.sku} at {warehouse.name}: only {available} available"
            )

        stock.quantity_reserved += qty
        stock.save(update_fields=["quantity_reserved"])

        # We also create a note on the stock movement log for this reservation? The spec just says return stock record.
        return stock

    @transaction.atomic
    def release_reservation(
        self, product, warehouse, qty, reference_type="", reference_id=""
    ):
        qty = Decimal(str(qty))
        # Use select_for_update to avoid race conditions
        stock = (
            StockRecord.objects.select_for_update()
            .filter(product=product, warehouse=warehouse)
            .first()
        )
        if not stock:
            return None

        # Decrement quantity_reserved by qty, clamped at 0
        stock.quantity_reserved = max(Decimal("0"), stock.quantity_reserved - qty)
        stock.save(update_fields=["quantity_reserved"])
        return stock

    def validate_tracking_requirements(
        self, product, batch_number=None, serial_numbers=None
    ):
        from django.core.exceptions import ValidationError

        if product.tracking_method == Product.TrackingMethod.LOT and not batch_number:
            raise ValidationError(f"{product.sku} requires a lot/batch number to ship.")

        if product.tracking_method == Product.TrackingMethod.SERIAL:
            if not serial_numbers or len(serial_numbers) == 0:
                raise ValidationError(
                    f"{product.sku} requires serial number(s) to ship."
                )

    @transaction.atomic
    def adjust_stock(self, product, warehouse, qty_input, adjustment_type, notes=""):
        qty = Decimal(str(qty_input))

        # Get or create stock record with lock
        stock, _ = StockRecord.objects.select_for_update().get_or_create(
            product=product,
            warehouse=warehouse,
            defaults={"company": self.company, "average_cost": product.cost_price},
        )

        if adjustment_type == "set":
            actual_qty = qty - stock.quantity_on_hand
        elif adjustment_type == "remove":
            actual_qty = -abs(qty)
        else:
            actual_qty = abs(qty)

        if actual_qty < 0 and stock.quantity_available < abs(actual_qty):
            raise ValueError(
                f"Insufficient stock for {product.sku} at {warehouse.name}: available {stock.quantity_available}, requested {abs(actual_qty)}"
            )
        stock.quantity_on_hand += actual_qty
        stock.save(update_fields=["quantity_on_hand"])

        unit_cost = stock.average_cost if actual_qty < 0 else product.cost_price

        # Record movement
        mov = StockMovement(
            company=self.company,
            product=product,
            warehouse=warehouse,
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            quantity=actual_qty,
            unit_cost=unit_cost,
            total_cost=Decimal(abs(actual_qty)) * unit_cost,
            movement_date=timezone.localdate(),
            notes=notes,
            stock_after=stock.quantity_on_hand,
        )
        mov.number = BaseService.generate_sequence_number(
            "ADJ", StockMovement, self.company.pk
        )
        mov.save()

        self.log_activity(
            action="adjusted",
            module="inventory",
            resource_type="StockRecord",
            resource_id=stock.pk,
            description=f"Adjusted stock for {product.name} at {warehouse.name} by {actual_qty}",
        )
        return mov

    @transaction.atomic
    def receive_stock(
        self,
        product,
        warehouse,
        qty,
        unit_cost,
        reference_type,
        reference_id,
        notes="",
        user=None,
    ):
        stock, _ = StockRecord.objects.select_for_update().get_or_create(
            product=product,
            warehouse=warehouse,
            defaults={"company": self.company, "average_cost": product.cost_price},
        )

        old_qty = stock.quantity_on_hand
        old_avg_cost = stock.average_cost

        new_qty = old_qty + qty
        if new_qty > 0:
            new_avg = ((old_qty * old_avg_cost) + (qty * unit_cost)) / new_qty
        else:
            new_avg = old_avg_cost

        stock.quantity_on_hand = new_qty
        stock.average_cost = new_avg
        stock.save(update_fields=["quantity_on_hand", "average_cost"])

        mov = StockMovement(
            company=self.company,
            product=product,
            warehouse=warehouse,
            movement_type=StockMovement.MovementType.RECEIPT,
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=qty * unit_cost,
            movement_date=timezone.localdate(),
            reference_type=reference_type,
            reference_id=str(reference_id),
            notes=notes,
            stock_after=stock.quantity_on_hand,
        )
        mov.number = BaseService.generate_sequence_number(
            "REC", StockMovement, self.company.pk
        )
        mov.save()
        return mov


class TransferService(BaseService):
    @transaction.atomic
    def create_transfer(self, data, user):
        from_wh_id = data.get("from_warehouse")
        to_wh_id = data.get("to_warehouse")

        if from_wh_id == to_wh_id:
            raise ValueError("Source and destination warehouses cannot be the same.")

        transfer = InventoryTransfer(
            company=self.company,
            from_warehouse_id=from_wh_id,
            to_warehouse_id=to_wh_id,
            transfer_date=data.get("transfer_date"),
            expected_arrival=data.get("expected_arrival") or None,
            notes=data.get("notes", ""),
            status=InventoryTransfer.Status.DRAFT,
        )
        transfer.number = BaseService.generate_sequence_number(
            "TR", InventoryTransfer, self.company.pk
        )
        transfer.save()

        # Process lines
        products = data.getlist("product[]")
        quantities = data.getlist("quantity[]")

        lines_created = 0
        for i, prod_id in enumerate(products):
            if not prod_id:
                continue
            qty = Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
            if qty > 0:
                InventoryTransferLine.objects.create(
                    transfer=transfer,
                    product_id=prod_id,
                    quantity_requested=qty,
                    quantity_sent=0,
                    quantity_received=0,
                )
                lines_created += 1

        if lines_created == 0:
            transfer.delete()
            raise ValueError("Transfer must have at least one valid product line.")

        self.log_activity(
            action="created",
            module="inventory",
            resource_type="InventoryTransfer",
            resource_id=transfer.pk,
            description=f"Created Inventory Transfer {transfer.number}",
        )
        return transfer

    @transaction.atomic
    def process_transfer(self, transfer, action, data, user):
        if action == "submit" and transfer.status == InventoryTransfer.Status.DRAFT:
            from apps.workflow.engine import WorkflowEngine

            workflow_instance = WorkflowEngine.trigger(transfer, "on_submit", user)
            if workflow_instance:
                transfer.status = InventoryTransfer.Status.PENDING_APPROVAL
            else:
                transfer.status = InventoryTransfer.Status.APPROVED
            transfer.save(update_fields=["status"])
            return transfer

        elif action == "ship" and transfer.status == InventoryTransfer.Status.APPROVED:
            lines = transfer.lines.all()
            stock_service = StockService(company=self.company, user=self.user)

            for line in lines:
                qty_sent = Decimal(
                    str(data.get(f"qty_sent_{line.id}", line.quantity_requested))
                )
                batch = data.get(f"batch_number_{line.id}", "")

                # Try getting it as a list first (from API), otherwise try single string and split (from form)
                serial_nums = data.getlist(f"serial_numbers_{line.id}")
                if not serial_nums:
                    serial_str = data.get(f"serial_numbers_{line.id}", "")
                    if serial_str:
                        serial_nums = [
                            s.strip() for s in serial_str.split(",") if s.strip()
                        ]

                line.quantity_sent = qty_sent
                line.batch_number = batch
                line.serial_numbers = serial_nums
                line.save(
                    update_fields=["quantity_sent", "batch_number", "serial_numbers"]
                )

                # STEP B.2: Validate tracking requirements BEFORE stock deduction
                stock_service.validate_tracking_requirements(
                    product=line.product,
                    batch_number=line.batch_number,
                    serial_numbers=line.serial_numbers,
                )

                # STEP B.3: For serial-tracked products, validate serial count matches quantity
                if line.product.tracking_method == line.product.TrackingMethod.SERIAL:
                    if len(line.serial_numbers) != int(qty_sent):
                        from django.core.exceptions import ValidationError

                        raise ValidationError(
                            f"{line.product.sku} requires exactly {int(qty_sent)} serial numbers, but {len(line.serial_numbers)} were provided."
                        )

                # Deduct from from_warehouse
                stock, _ = StockRecord.objects.select_for_update().get_or_create(
                    product=line.product,
                    warehouse=transfer.from_warehouse,
                    defaults={
                        "company": self.company,
                        "average_cost": line.product.cost_price,
                        "quantity_on_hand": 0,
                        "quantity_reserved": 0,
                    },
                )

                # Transfers do not reserve stock. The availability is just (on_hand - reserved).
                if stock.quantity_available < qty_sent:
                    raise ValueError(
                        f"Insufficient stock for {line.product.sku} at {transfer.from_warehouse.name}: available {stock.quantity_available}, requested {qty_sent}"
                    )

                stock.quantity_on_hand -= qty_sent
                stock.save(update_fields=["quantity_on_hand"])

                unit_cost = stock.average_cost

                # Create outgoing StockMovement
                mov = StockMovement(
                    company=self.company,
                    product=line.product,
                    warehouse=transfer.from_warehouse,
                    movement_type=StockMovement.MovementType.TRANSFER,
                    quantity=-qty_sent,
                    unit_cost=unit_cost,
                    total_cost=-(qty_sent * unit_cost),
                    movement_date=timezone.now().date(),
                    reference_type="InventoryTransfer",
                    reference_id=str(transfer.id),
                    notes=f"Transfer out to {transfer.to_warehouse.name}",
                    batch_number=line.batch_number,
                    serial_numbers=line.serial_numbers,
                    stock_after=stock.quantity_on_hand,
                )
                mov.number = BaseService.generate_sequence_number(
                    "TR-OUT", StockMovement, self.company.pk
                )
                mov.save()

            transfer.status = InventoryTransfer.Status.IN_TRANSIT
            transfer.save(update_fields=["status"])

            self.log_activity(
                action="shipped",
                module="inventory",
                resource_type="InventoryTransfer",
                resource_id=transfer.pk,
                description=f"Shipped Inventory Transfer {transfer.number}",
            )
            return transfer

        elif (
            action == "receive"
            and transfer.status == InventoryTransfer.Status.IN_TRANSIT
        ):
            lines = transfer.lines.all()
            for line in lines:
                qty_recv = Decimal(
                    str(data.get(f"qty_recv_{line.id}", line.quantity_sent))
                )
                line.quantity_received = qty_recv
                line.save(update_fields=["quantity_received"])

                # Add to to_warehouse
                stock, _ = StockRecord.objects.select_for_update().get_or_create(
                    product=line.product,
                    warehouse=transfer.to_warehouse,
                    defaults={
                        "company": self.company,
                        "average_cost": line.product.cost_price,
                    },
                )
                stock.quantity_on_hand += qty_recv
                stock.save(update_fields=["quantity_on_hand"])

                # Create incoming StockMovement
                mov = StockMovement(
                    company=self.company,
                    product=line.product,
                    warehouse=transfer.to_warehouse,
                    movement_type=StockMovement.MovementType.TRANSFER,
                    quantity=qty_recv,
                    unit_cost=line.product.cost_price,
                    total_cost=qty_recv * line.product.cost_price,
                    movement_date=timezone.now().date(),
                    reference_type="InventoryTransfer",
                    reference_id=str(transfer.id),
                    notes=f"Transfer in from {transfer.from_warehouse.name}",
                    stock_after=stock.quantity_on_hand,
                )
                mov.number = BaseService.generate_sequence_number(
                    "TR-IN", StockMovement, self.company.pk
                )
                mov.save()

            transfer.status = InventoryTransfer.Status.RECEIVED
            transfer.save(update_fields=["status"])

            self.log_activity(
                action="received",
                module="inventory",
                resource_type="InventoryTransfer",
                resource_id=transfer.pk,
                description=f"Received Inventory Transfer {transfer.number}",
            )
            return transfer

        elif action == "cancel" and transfer.status in (
            InventoryTransfer.Status.DRAFT,
            InventoryTransfer.Status.PENDING_APPROVAL,
            InventoryTransfer.Status.APPROVED,
        ):
            transfer.status = InventoryTransfer.Status.CANCELLED
            transfer.save(update_fields=["status"])

            self.log_activity(
                action="cancelled",
                module="inventory",
                resource_type="InventoryTransfer",
                resource_id=transfer.pk,
                description=f"Cancelled Inventory Transfer {transfer.number}",
            )
            return transfer

        else:
            raise ValueError(
                f"Invalid action {action} for transfer in status {transfer.status}"
            )


class DeliveryService(BaseService):
    @transaction.atomic
    def ship_delivery(self, delivery, user):
        from .models import DeliveryOrder

        # Lock the delivery order for idempotency protection
        delivery = DeliveryOrder.objects.select_for_update().get(pk=delivery.pk)

        if delivery.status != DeliveryOrder.Status.READY:
            raise ValueError("Delivery Order must be in READY status to ship.")

        stock_service = StockService(company=self.company, user=self.user)

        for line in delivery.lines.all():
            if line.quantity_shipped <= 0:
                continue

            # STEP B.2: Validate tracking requirements BEFORE stock deduction
            stock_service.validate_tracking_requirements(
                product=line.product,
                batch_number=line.batch_number,
                serial_numbers=line.serial_numbers,
            )

            # STEP B.3: For serial-tracked products, validate serial count matches quantity
            if line.product.tracking_method == line.product.TrackingMethod.SERIAL:
                if len(line.serial_numbers) != int(line.quantity_shipped):
                    from django.core.exceptions import ValidationError

                    raise ValidationError(
                        f"{line.product.sku} requires exactly {int(line.quantity_shipped)} serial numbers, but {len(line.serial_numbers)} were provided."
                    )

            stock_record, _ = StockRecord.objects.select_for_update().get_or_create(
                company=self.company,
                product=line.product,
                warehouse=delivery.warehouse,
                defaults={
                    "quantity_on_hand": 0,
                    "average_cost": line.product.cost_price,
                    "quantity_reserved": 0,
                },
            )

            # STEP A.5: Update the oversell guard to check availability, not just on-hand
            # Since this order previously reserved stock (during confirmation), its reservation is included in the total `quantity_reserved`.
            # To avoid failing the guard against its own reserved stock, we add its reserved amount (quantity_ordered) back to the available calculation.
            # We assume `line.quantity_ordered` is the amount that was reserved.
            this_order_reservation = line.quantity_ordered
            effective_available = (
                stock_record.quantity_on_hand - stock_record.quantity_reserved
            ) + this_order_reservation

            if effective_available < line.quantity_shipped:
                raise ValueError(
                    f"Insufficient stock for {line.product.sku} at {delivery.warehouse.name}: available {effective_available} (including this order's reservation), requested {line.quantity_shipped}"
                )

            stock_record.quantity_on_hand -= line.quantity_shipped
            stock_record.save(update_fields=["quantity_on_hand"])

            StockMovement.objects.create(
                company=self.company,
                product=line.product,
                warehouse=delivery.warehouse,
                movement_type=StockMovement.MovementType.DELIVERY,
                quantity=-line.quantity_shipped,
                unit_cost=stock_record.average_cost,
                total_cost=-(line.quantity_shipped * stock_record.average_cost),
                movement_date=timezone.now().date(),
                reference_type="DeliveryOrder",
                reference_id=str(delivery.id),
                batch_number=line.batch_number,
                serial_numbers=line.serial_numbers,
                notes=f"Shipped via {delivery.number} for {delivery.sales_order.number}",
                stock_after=stock_record.quantity_on_hand,
            )

            # STEP A.3: Release reservation on shipment
            stock_service.release_reservation(
                product=line.product,
                warehouse=delivery.warehouse,
                qty=line.quantity_shipped,
                reference_type="DeliveryOrder",
                reference_id=str(delivery.id),
            )

            so_line = delivery.sales_order.lines.filter(product=line.product).first()
            if so_line:
                so_line.qty_delivered += line.quantity_shipped
                so_line.save(update_fields=["qty_delivered"])

        delivery.status = DeliveryOrder.Status.SHIPPED
        delivery.shipped_date = timezone.now()
        delivery.shipped_by = user

        # Mock Shiprocket Integration
        try:
            from apps.administration.services.integrations import ShiprocketService

            shiprocket = ShiprocketService(credentials={"token": "mock"})  # nosec B105
            shipment = shiprocket.create_shipment(
                order_id=delivery.number,
                pickup_pincode="110001",
                delivery_pincode="400001",
                weight=1.5,
                dimensions="10x10x10",
            )
            delivery.tracking_number = shipment["awb_code"]
            delivery.notes = (
                (delivery.notes or "")
                + f"\n\nShipped via {shipment['courier_name']}. Est Delivery: {shipment['estimated_delivery']}"
            )
        except Exception as e:
            logger.warning("Shiprocket integration failed: %s", e)  # Non-critical failure

        delivery.save()

        all_delivered = True
        for so_line in delivery.sales_order.lines.all():
            if so_line.qty_delivered < so_line.quantity:
                all_delivered = False
                break

        if all_delivered:
            delivery.sales_order.status = delivery.sales_order.Status.DELIVERED
            delivery.sales_order.save(update_fields=["status"])
        elif delivery.sales_order.status == delivery.sales_order.Status.CONFIRMED:
            delivery.sales_order.status = delivery.sales_order.Status.PROCESSING
            delivery.sales_order.save(update_fields=["status"])

        self.log_activity(
            action="shipped",
            module="inventory",
            resource_type="DeliveryOrder",
            resource_id=delivery.pk,
            description=f"Shipped Delivery Order {delivery.number}",
        )
        return delivery
