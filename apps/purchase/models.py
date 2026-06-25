"""
Purchase Management Models
Vendors, Requisitions, Purchase Orders
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import CompanyScoped, AddressMixin, ContactMixin, NotesMixin, SequenceMixin, CurrencyMixin


class Vendor(CompanyScoped, AddressMixin, ContactMixin, NotesMixin):

    class VendorType(models.TextChoices):
        SUPPLIER = 'supplier', _('Supplier')
        CONTRACTOR = 'contractor', _('Contractor')
        SERVICE = 'service', _('Service Provider')

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        INACTIVE = 'inactive', _('Inactive')
        BLOCKED = 'blocked', _('Blocked')
        PENDING = 'pending', _('Pending Approval')

    name = models.CharField(max_length=255, db_index=True)
    vendor_code = models.CharField(max_length=50, blank=True, db_index=True)
    vendor_type = models.CharField(max_length=20, choices=VendorType.choices, default=VendorType.SUPPLIER)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    tax_id = models.CharField(max_length=100, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    payment_terms = models.PositiveSmallIntegerField(default=30)
    currency = models.ForeignKey('company.Currency', null=True, blank=True, on_delete=models.SET_NULL)
    credit_limit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    rating = models.PositiveSmallIntegerField(
        default=3, validators=[__import__('django.core.validators', fromlist=['MinValueValidator']).MinValueValidator(1),
                               __import__('django.core.validators', fromlist=['MaxValueValidator']).MaxValueValidator(5)]
    )
    bank_name = models.CharField(max_length=200, blank=True)
    bank_account_number = models.CharField(max_length=100, blank=True)
    is_approved = models.BooleanField(default=False)
    on_time_delivery_pct = models.DecimalField(max_digits=5, decimal_places=2, default=100.00)
    defect_rate_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    portal_user = models.OneToOneField('authentication.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_profile')

    class Meta:
        db_table = 'purchase_vendors'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.vendor_code or 'N/A'})"

    @property
    def outstanding_balance(self):
        from django.db.models import Sum
        return PurchaseOrder.objects.filter(
            vendor=self, status__in=['approved', 'partial']
        ).aggregate(total=Sum('balance_due'))['total'] or 0


class PurchaseRequest(CompanyScoped, SequenceMixin, NotesMixin):

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        SUBMITTED = 'submitted', _('Submitted')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        ORDERED = 'ordered', _('Purchase Order Created')
        CANCELLED = 'cancelled', _('Cancelled')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')
        URGENT = 'urgent', _('Urgent')

    title = models.CharField(max_length=255)
    department = models.ForeignKey('company.Department', null=True, blank=True, on_delete=models.SET_NULL)
    requested_by = models.ForeignKey(
        'authentication.User', on_delete=models.PROTECT, related_name='purchase_requests',
    )
    required_by = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True)
    approved_by = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='approved_purchase_requests',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    estimated_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'purchase_requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.number} | {self.title}"


class PurchaseRequestLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.ForeignKey('inventory.UnitOfMeasure', null=True, blank=True, on_delete=models.SET_NULL)
    estimated_unit_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    estimated_total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    specifications = models.TextField(blank=True)

    class Meta:
        db_table = 'purchase_request_lines'


class PurchaseOrder(CompanyScoped, SequenceMixin, CurrencyMixin, NotesMixin):

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        SENT = 'sent', _('Sent to Vendor')
        CONFIRMED = 'confirmed', _('Confirmed')
        PARTIAL = 'partial', _('Partially Received')
        RECEIVED = 'received', _('Fully Received')
        INVOICED = 'invoiced', _('Invoiced')
        CANCELLED = 'cancelled', _('Cancelled')

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='purchase_orders')
    purchase_request = models.ForeignKey(PurchaseRequest, null=True, blank=True, on_delete=models.SET_NULL)
    branch = models.ForeignKey('company.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    warehouse = models.ForeignKey('inventory.Warehouse', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True)
    order_date = models.DateField()
    expected_delivery = models.DateField(null=True, blank=True)
    actual_delivery = models.DateField(null=True, blank=True)
    payment_terms = models.PositiveSmallIntegerField(default=30)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    terms_conditions = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='approved_pos',
    )

    class Meta:
        db_table = 'purchase_orders'
        ordering = ['-order_date']

    def __str__(self):
        return f"{self.number} | {self.vendor.name}"


class PurchaseOrderLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit = models.ForeignKey('inventory.UnitOfMeasure', null=True, blank=True, on_delete=models.SET_NULL)
    unit_price = models.DecimalField(max_digits=15, decimal_places=4)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax = models.ForeignKey('company.Tax', null=True, blank=True, on_delete=models.SET_NULL)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    qty_received = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    qty_invoiced = models.DecimalField(max_digits=15, decimal_places=4, default=0)

    class Meta:
        db_table = 'purchase_order_lines'


class GoodsReceipt(CompanyScoped, SequenceMixin, NotesMixin):
    """Goods Receipt Note (GRN) when items arrive from vendor."""

    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        COMPLETED = 'completed', _('Completed')
        CANCELLED = 'cancelled', _('Cancelled')

    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name='receipts')
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT)
    receipt_date = models.DateField()
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    received_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT)
    quality_check = models.BooleanField(default=False)
    qc_notes = models.TextField(blank=True)

    class Meta:
        db_table = 'purchase_goods_receipts'

    def __str__(self):
        return f"{self.number} | {self.purchase_order.number}"


class GoodsReceiptLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    goods_receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name='lines')
    po_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT)
    quantity_received = models.DecimalField(max_digits=15, decimal_places=4)
    quantity_accepted = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    quantity_rejected = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    rejection_reason = models.TextField(blank=True)
    batch_number = models.CharField(max_length=100, blank=True)
    serial_numbers = models.JSONField(default=list)

    class Meta:
        db_table = 'purchase_goods_receipt_lines'



class Bill(CompanyScoped, SequenceMixin, CurrencyMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        OPEN = 'open', _('Open')
        PARTIAL = 'partial', _('Partially Paid')
        PAID = 'paid', _('Paid')
        OVERDUE = 'overdue', _('Overdue')
        CANCELLED = 'cancelled', _('Cancelled')

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='bills')
    purchase_order = models.ForeignKey(PurchaseOrder, null=True, blank=True, on_delete=models.SET_NULL, related_name='bills')
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True)
    bill_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    
    terms_conditions = models.TextField(blank=True)

    class Meta:
        db_table = 'purchase_bills'

    def __str__(self):
        return f'{self.number} | {self.vendor.name} | {self.total}'

    def calculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(l.subtotal for l in lines)
        self.tax_amount = sum(l.tax_amount for l in lines)
        self.total = self.subtotal + self.tax_amount - self.discount_amount
        self.save(update_fields=['subtotal', 'tax_amount', 'total'])
        self.update_balance()

    def update_balance(self):
        from django.db.models import Sum
        paid = self.payments.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0
        self.amount_paid = paid
        self.balance_due = self.total - paid
        if self.balance_due <= 0:
            self.status = self.Status.PAID
            # Automate closing the Purchase Order
            if self.purchase_order and self.purchase_order.status != self.purchase_order.Status.RECEIVED:
                self.purchase_order.status = self.purchase_order.Status.RECEIVED
                self.purchase_order.save(update_fields=['status'])
        elif paid > 0:
            self.status = self.Status.PARTIAL
        self.save(update_fields=['amount_paid', 'balance_due', 'status'])

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if self.status in [self.Status.OPEN]:
            from apps.accounting.models import JournalEntry
            if not JournalEntry.objects.filter(reference=f'BILL: {self.number}').exists():
                from apps.accounting.services import AutoJournalService
                AutoJournalService.post_purchase_bill(self)


class BillLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=15, decimal_places=4)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax = models.ForeignKey('company.Tax', null=True, blank=True, on_delete=models.SET_NULL)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = 'purchase_bill_lines'
        ordering = ['sort_order']

    def save(self, *args, **kwargs):
        from decimal import Decimal
        self.subtotal = self.quantity * self.unit_price
        self.discount_amount = self.subtotal * (self.discount_percent / Decimal('100'))
        taxable = self.subtotal - self.discount_amount
        self.tax_amount = self.tax.compute(taxable) if self.tax else Decimal('0')
        self.total = taxable + self.tax_amount
        super().save(*args, **kwargs)


class Payment(CompanyScoped, SequenceMixin, CurrencyMixin):
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        COMPLETED = 'completed', _('Completed')
        FAILED = 'failed', _('Failed')

    class Method(models.TextChoices):
        CASH = 'cash', _('Cash')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')
        CHEQUE = 'cheque', _('Cheque')
        CREDIT_CARD = 'credit_card', _('Credit Card')

    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name='payments')
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name='payments')
    currency = models.ForeignKey('company.Currency', null=True, blank=True, on_delete=models.SET_NULL, related_name='purchase_payments')
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    payment_date = models.DateField()
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.BANK_TRANSFER)
    reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'purchase_payments'

    def __str__(self):
        return f'{self.number} | {self.bill.number} | {self.amount}'

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        self.bill.update_balance()
        if self.status == self.Status.COMPLETED:
            from apps.accounting.models import JournalEntry
            if not JournalEntry.objects.filter(reference=f'VPAY: {self.number}').exists():
                from apps.accounting.services import AutoJournalService
                AutoJournalService.post_purchase_payment(self)

# ════════════════════════ ENTERPRISE PURCHASE ═════════════════════════════════

class RequestForQuotation(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        PUBLISHED = 'published', _('Published')
        CLOSED = 'closed', _('Closed')
        CANCELLED = 'cancelled', _('Cancelled')

    title = models.CharField(max_length=255)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    deadline = models.DateField()
    delivery_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT)
    purchase_request = models.ForeignKey('PurchaseRequest', null=True, blank=True, on_delete=models.SET_NULL, related_name='rfqs')

    class Meta:
        db_table = 'purchase_rfqs'

    def __str__(self):
        return f"{self.number} | {self.title}"

class RFQLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    rfq = models.ForeignKey(RequestForQuotation, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = 'purchase_rfq_lines'

class VendorBid(CompanyScoped):
    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        ACCEPTED = 'accepted', _('Accepted')
        REJECTED = 'rejected', _('Rejected')

    rfq = models.ForeignKey(RequestForQuotation, on_delete=models.CASCADE, related_name='bids')
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='bids')
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    total_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    bid_date = models.DateField(auto_now_add=True)
    valid_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'purchase_vendor_bids'
        unique_together = ('rfq', 'vendor')

    def __str__(self):
        return f"Bid from {self.vendor.name} for {self.rfq.number}"

class VendorBidLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    bid = models.ForeignKey(VendorBid, on_delete=models.CASCADE, related_name='lines')
    rfq_line = models.ForeignKey(RFQLine, on_delete=models.CASCADE)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        db_table = 'purchase_vendor_bid_lines'

    def save(self, *args, **kwargs):
        self.subtotal = self.unit_price * self.rfq_line.quantity
        super().save(*args, **kwargs)
