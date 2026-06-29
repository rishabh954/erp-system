"""
Inventory Management Models
Products, Categories, Warehouses, Stock, Transfers, Serial/Batch Tracking
"""
import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator
from django.contrib.contenttypes.fields import GenericRelation
from core.models import CompanyScoped, SequenceMixin, NotesMixin


class UnitOfMeasure(CompanyScoped):
    name = models.CharField(max_length=100)
    abbreviation = models.CharField(max_length=20)
    uom_type = models.CharField(
        max_length=20,
        choices=[('unit', 'Unit'), ('weight', 'Weight'), ('volume', 'Volume'),
                 ('length', 'Length'), ('area', 'Area'), ('time', 'Time')],
        default='unit',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_uom'
        unique_together = ('company', 'abbreviation')

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class ProductCategory(CompanyScoped):
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children')
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_product_categories'
        unique_together = ('company', 'name')

    def __str__(self):
        return self.name


class Brand(CompanyScoped):
    name = models.CharField(max_length=200)
    logo = models.ImageField(upload_to='brands/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_brands'

    def __str__(self):
        return self.name


class Product(CompanyScoped, NotesMixin):

    class ProductType(models.TextChoices):
        STOCKABLE = 'stockable', _('Stockable Product')
        CONSUMABLE = 'consumable', _('Consumable')
        SERVICE = 'service', _('Service')
        DIGITAL = 'digital', _('Digital')

    class TrackingMethod(models.TextChoices):
        NONE = 'none', _('No Tracking')
        LOT = 'lot', _('By Lot/Batch')
        SERIAL = 'serial', _('By Serial Number')

    sku = models.CharField(max_length=100, db_index=True)
    barcode = models.CharField(max_length=100, blank=True, db_index=True)
    name = models.CharField(max_length=500, db_index=True)
    description = models.TextField(blank=True)
    short_description = models.CharField(max_length=500, blank=True)
    product_type = models.CharField(max_length=15, choices=ProductType.choices, default=ProductType.STOCKABLE)
    category = models.ForeignKey(ProductCategory, null=True, blank=True, on_delete=models.SET_NULL)
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.SET_NULL)
    uom = models.ForeignKey(UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name='products')
    purchase_uom = models.ForeignKey(UnitOfMeasure, null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_products')

    # Pricing
    cost_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    sale_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    min_sale_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    currency = models.ForeignKey('company.Currency', null=True, blank=True, on_delete=models.SET_NULL)

    # Inventory settings
    tracking_method = models.CharField(max_length=10, choices=TrackingMethod.choices, default=TrackingMethod.NONE)
    min_stock_level = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    max_stock_level = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reorder_point = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    reorder_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    # Physical attributes
    weight = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    weight_unit = models.CharField(max_length=10, default='kg')
    dimensions = models.JSONField(default=dict, blank=True)  # {length, width, height, unit}

    # Accounts
    inventory_account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.SET_NULL, related_name='inventory_products',
    )
    revenue_account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.SET_NULL, related_name='revenue_products',
    )
    cogs_account = models.ForeignKey(
        'accounting.Account', null=True, blank=True, on_delete=models.SET_NULL, related_name='cogs_products',
    )

    # Tax
    tax = models.ForeignKey('company.Tax', null=True, blank=True, on_delete=models.SET_NULL)

    image = models.ImageField(upload_to='products/', null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_purchasable = models.BooleanField(default=True)
    is_sellable = models.BooleanField(default=True)
    
    # QA and ABC
    abc_classification = models.CharField(
        max_length=1, choices=[('A', 'A-Class'), ('B', 'B-Class'), ('C', 'C-Class')], 
        null=True, blank=True, help_text="A: Top 80%, B: Next 15%, C: Bottom 5% value"
    )
    needs_qa = models.BooleanField(default=False, help_text="Requires Quality Inspection on receipt")

    class Meta:
        db_table = 'inventory_products'
        unique_together = ('company', 'sku')
        indexes = [
            models.Index(fields=['company', 'is_active']),
            models.Index(fields=['company', 'category']),
        ]

    def __str__(self):
        return f"{self.sku} — {self.name}"

    @property
    def total_stock(self):
        return self.stock_records.filter(is_deleted=False).aggregate(
            total=models.Sum('quantity_on_hand')
        )['total'] or 0

    @property
    def is_low_stock(self):
        return self.total_stock <= self.reorder_point


class ProductVariant(CompanyScoped):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=100)
    barcode = models.CharField(max_length=100, blank=True)
    attributes = models.JSONField(default=dict)  # {color: Red, size: L}
    cost_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    sale_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    image = models.ImageField(upload_to='variants/', null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_product_variants'
        unique_together = ('company', 'sku')


class Warehouse(CompanyScoped):
    branch = models.ForeignKey('company.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    manager = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='managed_warehouses',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_warehouses'
        unique_together = ('company', 'code')

    def __str__(self):
        return f"{self.name} ({self.code})"


class BinLocation(CompanyScoped):
    """Physical bin/shelf location within a warehouse."""
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='bins')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50)
    aisle = models.CharField(max_length=20, blank=True)
    rack = models.CharField(max_length=20, blank=True)
    shelf = models.CharField(max_length=20, blank=True)
    bin = models.CharField(max_length=20, blank=True)
    max_weight = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_bin_locations'
        unique_together = ('warehouse', 'code')

    def __str__(self):
        return f"{self.warehouse.name} / {self.code}"


class StockRecord(CompanyScoped):
    """Current stock quantity per product per warehouse (per bin, optionally)."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_records')
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    bin_location = models.ForeignKey(BinLocation, null=True, blank=True, on_delete=models.SET_NULL)
    quantity_on_hand = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_reserved = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_incoming = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    average_cost = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    last_counted_at = models.DateTimeField(null=True, blank=True)
    batch_number = models.CharField(max_length=100, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    barcode = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'inventory_stock_records'
        unique_together = ('product', 'variant', 'warehouse', 'bin_location', 'batch_number', 'serial_number')

    def __str__(self):
        return f"{self.product.sku} @ {self.warehouse.name}: {self.quantity_on_hand}"

    @property
    def quantity_available(self):
        return self.quantity_on_hand - self.quantity_reserved


class StockMovement(CompanyScoped, SequenceMixin, NotesMixin):
    """Every stock change is recorded as a movement."""

    class MovementType(models.TextChoices):
        RECEIPT = 'receipt', _('Receipt (Purchase)')
        DELIVERY = 'delivery', _('Delivery (Sale)')
        TRANSFER = 'transfer', _('Warehouse Transfer')
        ADJUSTMENT = 'adjustment', _('Stock Adjustment')
        RETURN_IN = 'return_in', _('Return In')
        RETURN_OUT = 'return_out', _('Return Out')
        PRODUCTION_IN = 'production_in', _('Production In')
        PRODUCTION_OUT = 'production_out', _('Production Out')
        OPENING = 'opening', _('Opening Stock')

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='movements')
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='movements')
    bin_location = models.ForeignKey(BinLocation, null=True, blank=True, on_delete=models.SET_NULL)
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)  # positive=in, negative=out
    unit_cost = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    total_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    movement_date = models.DateField(db_index=True)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    batch_number = models.CharField(max_length=100, blank=True)
    serial_numbers = models.JSONField(default=list)
    stock_after = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = 'inventory_stock_movements'
        ordering = ['-movement_date', '-created_at']
        indexes = [
            models.Index(fields=['product', 'warehouse', 'movement_date']),
            models.Index(fields=['company', 'movement_type', 'movement_date']),
        ]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('SM', self.__class__)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.product.sku} | {self.movement_type} | {self.quantity}"


class InventoryTransfer(CompanyScoped, SequenceMixin, NotesMixin):
    """Transfer stock between warehouses."""

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        PENDING_APPROVAL = 'pending_approval', _('Pending Approval')
        REQUESTED = 'requested', _('Requested')
        APPROVED = 'approved', _('Approved')
        IN_TRANSIT = 'in_transit', _('In Transit')
        RECEIVED = 'received', _('Received')
        CANCELLED = 'cancelled', _('Cancelled')

    from_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transfers_out')
    to_warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='transfers_in')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    transfer_date = models.DateField()
    expected_arrival = models.DateField(null=True, blank=True)
    approved_by = models.ForeignKey(
        'authentication.User', null=True, blank=True, 
        on_delete=models.SET_NULL, related_name='approved_transfers',
        help_text='User who approved the transfer'
    )
    workflows = GenericRelation('workflow.WorkflowInstance', object_id_field='object_id', content_type_field='content_type')

    class Meta:
        db_table = 'inventory_transfers'

    def __str__(self):
        return f"{self.number} | {self.from_warehouse} → {self.to_warehouse}"


class InventoryTransferLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transfer = models.ForeignKey(InventoryTransfer, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL)
    quantity_requested = models.DecimalField(max_digits=15, decimal_places=4)
    quantity_sent = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_received = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = 'inventory_transfer_lines'


class DeliveryOrder(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        READY = 'ready', _('Ready')
        SHIPPED = 'shipped', _('Shipped')
        CANCELLED = 'cancelled', _('Cancelled')

    sales_order = models.ForeignKey('sales.SalesOrder', on_delete=models.CASCADE, related_name='delivery_orders')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='delivery_orders')
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True)
    scheduled_date = models.DateField(null=True, blank=True)
    shipped_date = models.DateTimeField(null=True, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    shipped_by = models.ForeignKey(
        'authentication.User', null=True, blank=True, 
        on_delete=models.SET_NULL, related_name='shipped_deliveries'
    )

    class Meta:
        db_table = 'inventory_delivery_orders'
        ordering = ['-created_at']

    def __str__(self):
        return self.number

    def ship(self, user):
        if self.status != self.Status.READY:
            raise ValueError("Delivery Order must be in READY status to ship.")
        
        from django.utils import timezone
        from .models import StockMovement, StockRecord
        
        for line in self.lines.all():
            if line.quantity_shipped <= 0:
                continue
                
            StockMovement.objects.create(
                company=self.company,
                product=line.product,
                warehouse=self.warehouse,
                movement_type=StockMovement.MovementType.DELIVERY,
                quantity=-line.quantity_shipped,
                movement_date=timezone.now().date(),
                reference_type='DeliveryOrder',
                reference_id=str(self.pk),
                notes=f"Shipped via {self.number} for {self.sales_order.number}",
            )
            
            stock_record, _ = StockRecord.objects.get_or_create(
                company=self.company,
                product=line.product,
                warehouse=self.warehouse,
                defaults={'quantity_on_hand': 0}
            )
            stock_record.quantity_on_hand -= line.quantity_shipped
            stock_record.save()
            
            so_line = self.sales_order.lines.filter(product=line.product).first()
            if so_line:
                so_line.qty_delivered += line.quantity_shipped
                so_line.save(update_fields=['qty_delivered'])

        self.status = self.Status.SHIPPED
        self.shipped_date = timezone.now()
        self.shipped_by = user
        self.save()

        all_delivered = True
        for so_line in self.sales_order.lines.all():
            if so_line.qty_delivered < so_line.quantity:
                all_delivered = False
                break
        
        if all_delivered:
            self.sales_order.status = self.sales_order.Status.DELIVERED
            self.sales_order.save(update_fields=['status'])
        elif self.sales_order.status == self.sales_order.Status.CONFIRMED:
            self.sales_order.status = self.sales_order.Status.PROCESSING
            self.sales_order.save(update_fields=['status'])


class DeliveryOrderLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    delivery_order = models.ForeignKey(DeliveryOrder, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    description = models.CharField(max_length=500, blank=True)
    quantity_ordered = models.DecimalField(max_digits=15, decimal_places=4)
    quantity_shipped = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = 'inventory_delivery_order_lines'

# ════════════════════════ ENTERPRISE INVENTORY ════════════════════════════════

class ReorderRule(CompanyScoped):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reorder_rules')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='reorder_rules')
    min_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    max_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'inventory_reorder_rules'
        unique_together = ('product', 'warehouse')

    def __str__(self):
        return f"{self.product.name} @ {self.warehouse.name} (Min: {self.min_quantity})"

# ------------------------ ADVANCED WMS (PHASE 7) --------------------------------

class LotBatch(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        EXPIRED = 'expired', _('Expired')
        QUARANTINED = 'quarantined', _('Quarantined')
        DEPLETED = 'depleted', _('Depleted')

    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='lots')
    variant = models.ForeignKey('inventory.ProductVariant', null=True, blank=True, on_delete=models.CASCADE)
    number = models.CharField(max_length=100, db_index=True)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    vendor = models.ForeignKey('purchase.Vendor', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'inventory_lot_batch'
        unique_together = ('product', 'number')

    def __str__(self):
        return f"{self.product.name} - Lot {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('LOT', self.__class__)
        super().save(*args, **kwargs)

class SerialNumber(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        IN_STOCK = 'in_stock', _('In Stock')
        SOLD = 'sold', _('Sold')
        RETURNED = 'returned', _('Returned')
        DAMAGED = 'damaged', _('Damaged')

    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE, related_name='serial_numbers')
    variant = models.ForeignKey('inventory.ProductVariant', null=True, blank=True, on_delete=models.CASCADE)
    lot = models.ForeignKey(LotBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='serial_numbers')
    number = models.CharField(max_length=100, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_STOCK)
    warranty_expiration = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'inventory_serial_number'
        unique_together = ('product', 'number')

    def __str__(self):
        return f"{self.product.sku} - S/N: {self.number}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('SN', self.__class__)
        super().save(*args, **kwargs)

class PickList(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        READY = 'ready', _('Ready to Pick')
        IN_PROGRESS = 'in_progress', _('In Progress')
        PICKED = 'picked', _('Picked')
        CANCELLED = 'cancelled', _('Cancelled')

    delivery_order = models.ForeignKey('inventory.DeliveryOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='pick_lists')
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    assigned_to = models.ForeignKey('authentication.User', null=True, blank=True, on_delete=models.SET_NULL)
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'inventory_pick_list'

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('PICK', self.__class__)
        super().save(*args, **kwargs)


class PickListLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    pick_list = models.ForeignKey(PickList, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    bin_location = models.ForeignKey('inventory.BinLocation', null=True, blank=True, on_delete=models.SET_NULL)
    quantity_to_pick = models.DecimalField(max_digits=15, decimal_places=4)
    quantity_picked = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = 'inventory_pick_list_line'


class PackingSlip(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        PACKED = 'packed', _('Packed')

    pick_list = models.ForeignKey(PickList, null=True, blank=True, on_delete=models.SET_NULL, related_name='packing_slips')
    delivery_order = models.ForeignKey('inventory.DeliveryOrder', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    packed_by = models.ForeignKey('authentication.User', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'inventory_packing_slip'

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('PACK', self.__class__)
        super().save(*args, **kwargs)


class PackingSlipLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    packing_slip = models.ForeignKey(PackingSlip, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    box_number = models.CharField(max_length=50, blank=True)

    class Meta:
        db_table = 'inventory_packing_slip_line'


class Shipment(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        SHIPPED = 'shipped', _('Shipped')
        DELIVERED = 'delivered', _('Delivered')
        RETURNED = 'returned', _('Returned')

    delivery_order = models.ForeignKey('inventory.DeliveryOrder', null=True, blank=True, on_delete=models.SET_NULL, related_name='shipments')
    packing_slip = models.ForeignKey(PackingSlip, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    carrier = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    tracking_url = models.URLField(max_length=500, blank=True)
    shipping_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    shipped_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'inventory_shipment'

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('SHIP', self.__class__)
        super().save(*args, **kwargs)


class LandedCost(CompanyScoped, SequenceMixin, NotesMixin):
    class AllocationMethod(models.TextChoices):
        VALUE = 'value', _('By Value')
        QUANTITY = 'quantity', _('By Quantity')
        WEIGHT = 'weight', _('By Weight')
        VOLUME = 'volume', _('By Volume')
        EQUAL = 'equal', _('Equally')

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        POSTED = 'posted', _('Posted')

    receipt = models.ForeignKey('purchase.GoodsReceipt', on_delete=models.CASCADE, related_name='landed_costs')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    allocation_method = models.CharField(max_length=20, choices=AllocationMethod.choices, default=AllocationMethod.VALUE)
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    date = models.DateField()

    class Meta:
        db_table = 'inventory_landed_cost'

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('LC', self.__class__)
        super().save(*args, **kwargs)


class LandedCostAllocation(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    landed_cost = models.ForeignKey(LandedCost, on_delete=models.CASCADE, related_name='allocations')
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    cost_category = models.CharField(max_length=100, help_text="e.g. Freight, Customs, Insurance")
    allocated_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        db_table = 'inventory_landed_cost_allocation'

class CycleCount(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        IN_PROGRESS = 'in_progress', _('In Progress')
        COUNTED = 'counted', _('Counted / Pending Review')
        COMPLETED = 'completed', _('Completed / Adjusted')
        CANCELLED = 'cancelled', _('Cancelled')

    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.CASCADE, related_name='cycle_counts')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    scheduled_date = models.DateField()
    counted_by = models.ForeignKey('authentication.User', null=True, blank=True, on_delete=models.SET_NULL)
    
    workflows = __import__('django.contrib.contenttypes.fields', fromlist=['GenericRelation']).GenericRelation('workflow.WorkflowInstance', object_id_field='object_id', content_type_field='content_type')

    class Meta:
        db_table = 'inventory_cycle_count'

    def __str__(self):
        return f"{self.number} - {self.warehouse.name}"
        
    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('CC', self.__class__)
        super().save(*args, **kwargs)

class CycleCountLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    cycle_count = models.ForeignKey(CycleCount, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE)
    bin_location = models.ForeignKey('inventory.BinLocation', null=True, blank=True, on_delete=models.SET_NULL)
    system_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    counted_quantity = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)
    variance = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = 'inventory_cycle_count_line'
        
    def save(self, *args, **kwargs):
        if self.counted_quantity is not None:
            self.variance = self.counted_quantity - self.system_quantity
        super().save(*args, **kwargs)

class QualityInspection(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending Inspection')
        PASSED = 'passed', _('Passed')
        FAILED = 'failed', _('Failed')
        PARTIAL = 'partial', _('Partially Passed')

    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE)
    receipt = models.ForeignKey('purchase.GoodsReceipt', null=True, blank=True, on_delete=models.CASCADE, related_name='inspections')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    inspector = models.ForeignKey('authentication.User', null=True, blank=True, on_delete=models.SET_NULL)
    inspection_date = models.DateTimeField(null=True, blank=True)
    quantity_inspected = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_passed = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_failed = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = 'inventory_quality_inspection'

    def __str__(self):
        return f"{self.number} - {self.product.sku}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('QA', self.__class__)
        super().save(*args, **kwargs)
