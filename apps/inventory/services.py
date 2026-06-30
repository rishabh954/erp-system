from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from .models import Product, StockMovement

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
            StockMovement.MovementType.PRODUCTION_OUT
        ]
        
        # We need to aggregate the absolute value of quantity * unit_cost
        # Since Delivery quantity is usually negative, we multiply by -1
        products_usage = []
        total_usage_value = Decimal('0')
        
        for product in Product.objects.filter(company=company, is_active=True, product_type=Product.ProductType.STOCKABLE):
            movements = StockMovement.objects.filter(
                product=product,
                movement_type__in=consumption_types,
                movement_date__gte=one_year_ago
            )
            
            # Since outbound movements are negative quantity, we multiply by -1 to get positive consumption
            usage = movements.aggregate(
                val=Sum(ExpressionWrapper(F('quantity') * F('unit_cost') * -1, output_field=DecimalField()))
            )['val'] or Decimal('0')
            
            if usage > 0:
                products_usage.append({'product': product, 'usage': usage})
                total_usage_value += usage
            else:
                # If no usage, automatically C
                product.abc_classification = 'C'
                product.save(update_fields=['abc_classification'])
                
        if not total_usage_value:
            return
            
        # Sort products by usage descending
        products_usage.sort(key=lambda x: x['usage'], reverse=True)
        
        cumulative_value = Decimal('0')
        
        for item in products_usage:
            cumulative_value += item['usage']
            percent = (cumulative_value / total_usage_value) * 100
            
            if percent <= 80:
                classification = 'A'
            elif percent <= 95:
                classification = 'B'
            else:
                classification = 'C'
                
            prod = item['product']
            if prod.abc_classification != classification:
                prod.abc_classification = classification
                prod.save(update_fields=['abc_classification'])

from datetime import date
from core.services import BaseService
from apps.inventory.models import (
    StockRecord, InventoryTransfer, InventoryTransferLine,
    DeliveryOrder, DeliveryOrderLine
)
from django.db import transaction

class StockService(BaseService):
    @transaction.atomic
    def adjust_stock(self, product, warehouse, qty_input, adjustment_type, notes=''):
        qty = Decimal(str(qty_input))
        
        # Get or create stock record with lock
        stock, _ = StockRecord.objects.select_for_update().get_or_create(
            product=product, warehouse=warehouse,
            defaults={'company': self.company, 'average_cost': product.cost_price}
        )

        if adjustment_type == 'set':
            actual_qty = qty - stock.quantity_on_hand
        elif adjustment_type == 'remove':
            actual_qty = -abs(qty)
        else:
            actual_qty = abs(qty)

        if actual_qty < 0 and stock.quantity_available < abs(actual_qty):
            raise ValueError(f"Insufficient stock for {product.sku} at {warehouse.name}: available {stock.quantity_available}, requested {abs(actual_qty)}")
        stock.quantity_on_hand += actual_qty
        stock.save(update_fields=['quantity_on_hand'])
        
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
            movement_date=date.today(),
            notes=notes,
            stock_after=stock.quantity_on_hand,
        )
        mov.number = BaseService.generate_sequence_number('ADJ', StockMovement, self.company.pk)
        mov.save()
        
        self.log_activity(
            action='adjusted',
            module='inventory',
            resource_type='StockRecord',
            resource_id=stock.pk,
            description=f"Adjusted stock for {product.name} at {warehouse.name} by {actual_qty}"
        )
        return mov

    @transaction.atomic
    def receive_stock(self, product, warehouse, qty, unit_cost, reference_type, reference_id, notes='', user=None):
        stock, _ = StockRecord.objects.select_for_update().get_or_create(
            product=product, warehouse=warehouse,
            defaults={'company': self.company, 'average_cost': product.cost_price}
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
        stock.save(update_fields=['quantity_on_hand', 'average_cost'])
        
        mov = StockMovement(
            company=self.company,
            product=product,
            warehouse=warehouse,
            movement_type=StockMovement.MovementType.RECEIPT,
            quantity=qty,
            unit_cost=unit_cost,
            total_cost=qty * unit_cost,
            movement_date=date.today(),
            reference_type=reference_type,
            reference_id=str(reference_id),
            notes=notes,
            stock_after=stock.quantity_on_hand
        )
        mov.number = BaseService.generate_sequence_number('REC', StockMovement, self.company.pk)
        mov.save()
        return mov


class TransferService(BaseService):
    @transaction.atomic
    def create_transfer(self, data, user):
        from_wh_id = data.get('from_warehouse')
        to_wh_id = data.get('to_warehouse')
        
        if from_wh_id == to_wh_id:
            raise ValueError("Source and destination warehouses cannot be the same.")

        transfer = InventoryTransfer(
            company=self.company,
            from_warehouse_id=from_wh_id,
            to_warehouse_id=to_wh_id,
            transfer_date=data.get('transfer_date'),
            expected_arrival=data.get('expected_arrival') or None,
            notes=data.get('notes', ''),
            status=InventoryTransfer.Status.DRAFT,
        )
        transfer.number = BaseService.generate_sequence_number('TR', InventoryTransfer, self.company.pk)
        transfer.save()

        # Process lines
        products = data.getlist('product[]')
        quantities = data.getlist('quantity[]')

        lines_created = 0
        for i, prod_id in enumerate(products):
            if not prod_id:
                continue
            qty = Decimal(str(quantities[i])) if quantities[i] else Decimal('1')
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
            action='created',
            module='inventory',
            resource_type='InventoryTransfer',
            resource_id=transfer.pk,
            description=f"Created Inventory Transfer {transfer.number}"
        )
        return transfer

    @transaction.atomic
    def process_transfer(self, transfer, action, data, user):
        if action == 'submit' and transfer.status == InventoryTransfer.Status.DRAFT:
            from apps.workflow.engine import WorkflowEngine
            workflow_instance = WorkflowEngine.trigger(transfer, 'on_submit', user)
            if workflow_instance:
                transfer.status = InventoryTransfer.Status.PENDING_APPROVAL
            else:
                transfer.status = InventoryTransfer.Status.APPROVED
            transfer.save(update_fields=['status'])
            return transfer

        elif action == 'ship' and transfer.status == InventoryTransfer.Status.APPROVED:
            lines = transfer.lines.all()
            for line in lines:
                qty_sent = Decimal(str(data.get(f'qty_sent_{line.id}', line.quantity_requested)))
                batch = data.get(f'batch_number_{line.id}', '')
                serial = data.get(f'serial_number_{line.id}', '')
                line.quantity_sent = qty_sent
                line.batch_number = batch
                line.serial_number = serial
                line.save(update_fields=['quantity_sent', 'batch_number', 'serial_number'])

                from .models import Product
                if line.product.tracking_method in (Product.TrackingMethod.LOT, Product.TrackingMethod.SERIAL):
                    if not line.batch_number and not line.serial_number:
                        from django.core.exceptions import ValidationError
                        raise ValidationError(f"Lot/Serial number is required for tracked product: {line.product.sku}")

                # Deduct from from_warehouse
                stock, _ = StockRecord.objects.select_for_update().get_or_create(
                    product=line.product, warehouse=transfer.from_warehouse,
                    defaults={'company': self.company, 'average_cost': line.product.cost_price}
                )
                if stock.quantity_available < qty_sent:
                    raise ValueError(f"Insufficient stock for {line.product.sku} at {transfer.from_warehouse.name}: available {stock.quantity_available}, requested {qty_sent}")
                stock.quantity_on_hand -= qty_sent
                stock.save(update_fields=['quantity_on_hand'])
                
                unit_cost = stock.average_cost

                # Create outgoing StockMovement
                mov = StockMovement(
                    company=self.company,
                    product=line.product,
                    warehouse=transfer.from_warehouse,
                    movement_type=StockMovement.MovementType.TRANSFER,
                    quantity=-qty_sent,
                    unit_cost=unit_cost,
                    total_cost=qty_sent * unit_cost,
                    movement_date=timezone.now().date(),
                    reference_type='InventoryTransfer',
                    reference_id=str(transfer.id),
                    notes=f'Transfer out to {transfer.to_warehouse.name}',
                    stock_after=stock.quantity_on_hand,
                )
                mov.number = BaseService.generate_sequence_number('TR-OUT', StockMovement, self.company.pk)
                mov.save()

            transfer.status = InventoryTransfer.Status.IN_TRANSIT
            transfer.save(update_fields=['status'])
            
            self.log_activity(
                action='shipped',
                module='inventory',
                resource_type='InventoryTransfer',
                resource_id=transfer.pk,
                description=f"Shipped Inventory Transfer {transfer.number}"
            )
            return transfer

        elif action == 'receive' and transfer.status == InventoryTransfer.Status.IN_TRANSIT:
            lines = transfer.lines.all()
            for line in lines:
                qty_recv = Decimal(str(data.get(f'qty_recv_{line.id}', line.quantity_sent)))
                line.quantity_received = qty_recv
                line.save(update_fields=['quantity_received'])

                # Add to to_warehouse
                stock, _ = StockRecord.objects.select_for_update().get_or_create(
                    product=line.product, warehouse=transfer.to_warehouse,
                    defaults={'company': self.company, 'average_cost': line.product.cost_price}
                )
                stock.quantity_on_hand += qty_recv
                stock.save(update_fields=['quantity_on_hand'])

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
                    reference_type='InventoryTransfer',
                    reference_id=str(transfer.id),
                    notes=f'Transfer in from {transfer.from_warehouse.name}',
                    stock_after=stock.quantity_on_hand,
                )
                mov.number = BaseService.generate_sequence_number('TR-IN', StockMovement, self.company.pk)
                mov.save()

            transfer.status = InventoryTransfer.Status.RECEIVED
            transfer.save(update_fields=['status'])
            
            self.log_activity(
                action='received',
                module='inventory',
                resource_type='InventoryTransfer',
                resource_id=transfer.pk,
                description=f"Received Inventory Transfer {transfer.number}"
            )
            return transfer

        elif action == 'cancel' and transfer.status in (InventoryTransfer.Status.DRAFT, InventoryTransfer.Status.PENDING_APPROVAL, InventoryTransfer.Status.APPROVED):
            transfer.status = InventoryTransfer.Status.CANCELLED
            transfer.save(update_fields=['status'])
            
            self.log_activity(
                action='cancelled',
                module='inventory',
                resource_type='InventoryTransfer',
                resource_id=transfer.pk,
                description=f"Cancelled Inventory Transfer {transfer.number}"
            )
            return transfer
            
        else:
            raise ValueError(f"Invalid action {action} for transfer in status {transfer.status}")


class DeliveryService(BaseService):
    @transaction.atomic
    def ship_delivery(self, delivery, user):
        from .models import DeliveryOrder
        # Lock the delivery order for idempotency protection
        delivery = DeliveryOrder.objects.select_for_update().get(pk=delivery.pk)
        
        if delivery.status != DeliveryOrder.Status.READY:
            raise ValueError("Delivery Order must be in READY status to ship.")
            
        for line in delivery.lines.all():
            if line.quantity_shipped <= 0:
                continue
                
            from .models import Product
            if line.product.tracking_method in (Product.TrackingMethod.LOT, Product.TrackingMethod.SERIAL):
                if not line.batch_number and not line.serial_number:
                    from django.core.exceptions import ValidationError
                    raise ValidationError(f"Lot/Serial number is required for tracked product: {line.product.sku}")
                
            stock_record, _ = StockRecord.objects.select_for_update().get_or_create(
                company=self.company,
                product=line.product,
                warehouse=delivery.warehouse,
                defaults={'quantity_on_hand': 0, 'average_cost': line.product.cost_price, 'quantity_reserved': 0}
            )
            
            # Since this is a shipment for a confirmed order, the stock is already reserved.
            # We check if there is enough total physical stock, or if we were somehow oversold.
            # The available stock check is technically on `quantity_available` but since we are
            # now *consuming* the reserved stock, we should be careful. 
            # If we reserved 5, on_hand=5, available=0. If we ship 5, we shouldn't fail the guard.
            # So the guard against available stock should only be for NON-reserved operations,
            # or we release the reservation FIRST.
            
            # Release the reservation (cap at 0 just in case)
            stock_record.quantity_reserved = max(Decimal('0'), stock_record.quantity_reserved - line.quantity_shipped)
            
            # Now we check if we have enough available stock (which includes the freshly released stock)
            if stock_record.quantity_available < line.quantity_shipped:
                raise ValueError(f"Insufficient stock for {line.product.sku} at {delivery.warehouse.name}: available {stock_record.quantity_available}, requested {line.quantity_shipped}")
                
            stock_record.quantity_on_hand -= line.quantity_shipped
            stock_record.save(update_fields=['quantity_on_hand', 'quantity_reserved'])
                
            StockMovement.objects.create(
                company=self.company,
                product=line.product,
                warehouse=delivery.warehouse,
                movement_type=StockMovement.MovementType.DELIVERY,
                quantity=-line.quantity_shipped,
                unit_cost=stock_record.average_cost,
                total_cost=line.quantity_shipped * stock_record.average_cost,
                movement_date=timezone.now().date(),
                reference_type='DeliveryOrder',
                reference_id=str(delivery.pk),
                notes=f"Shipped via {delivery.number} for {delivery.sales_order.number}",
                stock_after=stock_record.quantity_on_hand,
            )
            
            so_line = delivery.sales_order.lines.filter(product=line.product).first()
            if so_line:
                so_line.qty_delivered += line.quantity_shipped
                so_line.save(update_fields=['qty_delivered'])

        delivery.status = DeliveryOrder.Status.SHIPPED
        delivery.shipped_date = timezone.now()
        delivery.shipped_by = user
        delivery.save()

        all_delivered = True
        for so_line in delivery.sales_order.lines.all():
            if so_line.qty_delivered < so_line.quantity:
                all_delivered = False
                break
        
        if all_delivered:
            delivery.sales_order.status = delivery.sales_order.Status.DELIVERED
            delivery.sales_order.save(update_fields=['status'])
        elif delivery.sales_order.status == delivery.sales_order.Status.CONFIRMED:
            delivery.sales_order.status = delivery.sales_order.Status.PROCESSING
            delivery.sales_order.save(update_fields=['status'])

        self.log_activity(
            action='shipped',
            module='inventory',
            resource_type='DeliveryOrder',
            resource_id=delivery.pk,
            description=f"Shipped Delivery Order {delivery.number}"
        )
        return delivery
