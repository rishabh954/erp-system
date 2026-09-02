"""
Sales Models
Quotations → Sales Orders → Invoices → Payments
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped, CurrencyMixin, NotesMixin, SequenceMixin
from core.services import BaseService


class Quotation(CompanyScoped, SequenceMixin, CurrencyMixin, NotesMixin):

    from core.constants.sales import QuotationStatus
    Status = QuotationStatus

    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="quotations"
    )
    branch = models.ForeignKey(
        "company.Branch", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    validity_date = models.DateField(null=True, blank=True)
    delivery_date = models.DateField(null=True, blank=True)
    payment_terms = models.PositiveSmallIntegerField(default=30)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    terms_conditions = models.TextField(blank=True)
    sales_rep = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotations",
    )
    approved_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_quotations",
    )
    reject_reason = models.TextField(blank=True, help_text=_("Reason for rejection"))

    workflows = GenericRelation(
        "workflow.WorkflowInstance",
        object_id_field="object_id",
        content_type_field="content_type",
    )

    class Meta:
        db_table = "sales_quotations"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="uniq_sales_quotation_number"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0) & models.Q(tax_amount__gte=0) & models.Q(discount_amount__gte=0) & models.Q(total__gte=0), name="chk_quotation_amounts_non_neg"),
        ]
        indexes = [
            models.Index(fields=["company", "status"]),
        ]

    def __str__(self):
        return f"{self.number} | {self.customer.name}"

    def recalculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(item.subtotal for item in lines)
        self.tax_amount = sum(item.tax_amount for item in lines)
        self.discount_amount = sum(item.discount_amount for item in lines)
        self.total = self.subtotal + self.tax_amount - self.discount_amount
        self.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total"])


class QuotationLine(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    quotation = models.ForeignKey(
        Quotation, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        "inventory.Product", null=True, blank=True, on_delete=models.SET_NULL
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)
    unit_price = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax = models.ForeignKey(
        "company.Tax", null=True, blank=True, on_delete=models.SET_NULL
    )
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "sales_quotation_lines"
        ordering = ["sort_order"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0) & models.Q(discount_percent__gte=0) & models.Q(discount_percent__lte=100),
                name="chk_quotation_line_valid"
            ),
        ]

    def save(self, *args, **kwargs):
        from decimal import Decimal

        self.subtotal = self.quantity * self.unit_price
        self.discount_amount = self.subtotal * (self.discount_percent / Decimal("100"))
        taxable = self.subtotal - self.discount_amount
        self.tax_amount = self.tax.compute(taxable) if self.tax else Decimal("0")
        self.total = taxable + self.tax_amount
        super().save(*args, **kwargs)


class SalesOrder(CompanyScoped, SequenceMixin, CurrencyMixin, NotesMixin):

    from core.constants.sales import SalesOrderStatus
    Status = SalesOrderStatus

    quotation = models.ForeignKey(
        Quotation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )
    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="sales_orders"
    )
    branch = models.ForeignKey(
        "company.Branch", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    order_date = models.DateField(db_index=True)
    delivery_date = models.DateField(null=True, blank=True, db_index=True)
    payment_terms = models.PositiveSmallIntegerField(default=30)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    shipping_address = models.TextField(blank=True)
    terms_conditions = models.TextField(blank=True)
    sales_rep = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_orders",
    )
    cancel_reason = models.TextField(blank=True, help_text=_("Reason for cancellation"))
    price_list = models.ForeignKey(
        "PriceList", null=True, blank=True, on_delete=models.SET_NULL
    )
    discount_rule = models.ForeignKey(
        "DiscountRule", null=True, blank=True, on_delete=models.SET_NULL
    )
    coupon = models.ForeignKey(
        "Coupon", null=True, blank=True, on_delete=models.SET_NULL
    )

    workflows = GenericRelation(
        "workflow.WorkflowInstance",
        object_id_field="object_id",
        content_type_field="content_type",
    )

    class Meta:
        db_table = "sales_orders"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="uniq_sales_order_number"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0) & models.Q(tax_amount__gte=0) & models.Q(discount_amount__gte=0) & models.Q(total__gte=0), name="chk_so_amounts_non_neg"),
        ]
        indexes = [
            models.Index(fields=["company", "status", "order_date"]),
        ]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = BaseService.generate_sequence_number("SO", self.__class__, self.company_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.customer.name}"

    def recalculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(item.subtotal for item in lines)
        self.tax_amount = sum(item.tax_amount for item in lines)
        self.discount_amount = sum(item.discount_amount for item in lines)
        self.total = self.subtotal + self.tax_amount - self.discount_amount
        self.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total"])


class SalesOrderLine(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        "inventory.Product", null=True, blank=True, on_delete=models.SET_NULL
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=15, decimal_places=4)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax = models.ForeignKey(
        "company.Tax", null=True, blank=True, on_delete=models.SET_NULL
    )
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    qty_delivered = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    qty_invoiced = models.DecimalField(max_digits=15, decimal_places=4, default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "sales_order_lines"
        ordering = ["sort_order"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0) & models.Q(qty_delivered__gte=0) & models.Q(qty_invoiced__gte=0) & models.Q(qty_delivered__lte=models.F('quantity')) & models.Q(qty_invoiced__lte=models.F('quantity')),
                name="chk_soline_quantities_valid"
            ),
        ]

    def save(self, *args, **kwargs):
        from decimal import Decimal

        self.subtotal = self.quantity * self.unit_price
        self.discount_amount = self.subtotal * (self.discount_percent / Decimal("100"))
        taxable = self.subtotal - self.discount_amount
        self.tax_amount = self.tax.compute(taxable) if self.tax else Decimal("0")
        self.total = taxable + self.tax_amount
        super().save(*args, **kwargs)


class Invoice(CompanyScoped, SequenceMixin, CurrencyMixin, NotesMixin):

    from core.constants.sales import InvoiceDocumentType, InvoiceStatus
    Status = InvoiceStatus
    DocumentType = InvoiceDocumentType

    sales_order = models.ForeignKey(
        SalesOrder,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="invoices"
    )
    branch = models.ForeignKey(
        "company.Branch", null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    document_type = models.CharField(
        max_length=20,
        choices=DocumentType.choices,
        default=DocumentType.STANDARD,
        db_index=True,
    )
    invoice_date = models.DateField(db_index=True)
    due_date = models.DateField()
    payment_terms = models.PositiveSmallIntegerField(default=30)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    terms_conditions = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    coupon = models.ForeignKey(
        "Coupon", null=True, blank=True, on_delete=models.SET_NULL
    )

    # E-Invoicing & India TDS
    irn = models.CharField(
        max_length=64, blank=True, help_text="Invoice Reference Number"
    )
    ack_no = models.CharField(max_length=20, blank=True)
    ack_date = models.DateTimeField(null=True, blank=True)
    signed_qr_code = models.TextField(blank=True)
    tds_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    workflows = GenericRelation(
        "workflow.WorkflowInstance",
        object_id_field="object_id",
        content_type_field="content_type",
    )

    class Meta:
        db_table = "sales_invoices"
        ordering = ["-invoice_date"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="uniq_sales_invoice_number"),
            models.CheckConstraint(condition=models.Q(subtotal__gte=0) & models.Q(total__gte=0) & models.Q(amount_paid__gte=0) & models.Q(balance_due__gte=0), name="chk_invoice_amounts_valid"),
            models.CheckConstraint(condition=models.Q(due_date__gte=models.F('invoice_date')), name="chk_invoice_due_after_invoice_date"),
        ]
        indexes = [
            models.Index(fields=["company", "status", "due_date"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["company", "invoice_date"]),
            models.Index(fields=["sales_order", "status"]),
        ]

    def __str__(self):
        return f"{self.number} | {self.customer.name} | {self.total}"

    def recalculate_totals(self):
        lines = self.lines.all()
        self.subtotal = sum(item.subtotal for item in lines)
        self.tax_amount = sum(item.tax_amount for item in lines)
        self.discount_amount = sum(item.discount_amount for item in lines)
        self.total = self.subtotal + self.tax_amount - self.discount_amount
        self.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total"])
        self.update_balance()

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = BaseService.generate_sequence_number(
                "INV", self.__class__, self.company_id
            )

        is_new = self._state.adding
        super().save(*args, **kwargs)
        # Only auto-post journal when a new Invoice first reaches SENT status.
        # Running on every update would create duplicate journal entries.
        if is_new and self.status in [self.Status.SENT]:
            from django.db import transaction

            from apps.accounting.models import JournalEntry

            if not JournalEntry.objects.filter(
                reference=f"INV: {self.number}"
            ).exists():
                from apps.accounting.services import AutoJournalService

                with transaction.atomic():
                    AutoJournalService.post_sales_invoice(self)

    def update_balance(self):
        from django.db.models import Sum

        paid = (
            self.payments.filter(status="completed").aggregate(total=Sum("amount"))[
                "total"
            ]
            or 0
        )
        self.amount_paid = paid
        self.balance_due = self.total - paid
        if self.balance_due <= 0:
            self.status = self.Status.PAID
            # Automate closing the Sales Order
            if (
                self.sales_order
                and self.sales_order.status != self.sales_order.Status.COMPLETED
            ):
                self.sales_order.status = self.sales_order.Status.COMPLETED
                self.sales_order.save(update_fields=["status"])
        elif paid > 0:
            self.status = self.Status.PARTIAL
        self.save(update_fields=["amount_paid", "balance_due", "status"])


class InvoiceLine(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "inventory.Product", null=True, blank=True, on_delete=models.SET_NULL
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=15, decimal_places=4)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax = models.ForeignKey(
        "company.Tax", null=True, blank=True, on_delete=models.SET_NULL
    )
    subtotal = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "sales_invoice_lines"
        ordering = ["sort_order"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) & models.Q(unit_price__gte=0) & models.Q(discount_percent__gte=0) & models.Q(discount_percent__lte=100),
                name="chk_invoice_line_valid"
            ),
        ]
        indexes = [
            models.Index(fields=["invoice", "sort_order"]),
        ]

    def save(self, *args, **kwargs):
        from decimal import Decimal

        self.subtotal = self.quantity * self.unit_price
        self.discount_amount = self.subtotal * (self.discount_percent / Decimal("100"))
        taxable = self.subtotal - self.discount_amount
        self.tax_amount = self.tax.compute(taxable) if self.tax else Decimal("0")
        self.total = taxable + self.tax_amount
        super().save(*args, **kwargs)


class Payment(CompanyScoped, SequenceMixin):

    from core.constants.sales import PaymentMethod, PaymentStatus
    Status = PaymentStatus
    Method = PaymentMethod

    invoice = models.ForeignKey(
        Invoice, on_delete=models.PROTECT, related_name="payments"
    )
    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.DecimalField(
        max_digits=18, decimal_places=2, validators=[MinValueValidator(0)]
    )
    currency = models.ForeignKey("company.Currency", on_delete=models.PROTECT)
    payment_date = models.DateField(db_index=True)
    method = models.CharField(max_length=20, choices=Method.choices)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    reference = models.CharField(max_length=200, blank=True)
    bank_account = models.ForeignKey(
        "accounting.BankAccount", null=True, blank=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sales_payments"
        ordering = ["-payment_date"]
        constraints = [
            models.UniqueConstraint(fields=["company", "number"], name="uniq_sales_payment_number"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="chk_payment_amount_gt_zero"),
        ]
        indexes = [
            models.Index(fields=["company", "payment_date"]),
            models.Index(fields=["invoice", "status"]),
            models.Index(fields=["customer", "payment_date"]),
        ]

    def __str__(self):
        return f"{self.number} | {self.invoice.number} | {self.amount}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        self.invoice.update_balance()
        # Only post journal entry on creation of a COMPLETED payment, not on every update.
        if is_new and self.status == self.Status.COMPLETED:
            from django.db import transaction

            from apps.accounting.models import JournalEntry

            if not JournalEntry.objects.filter(
                reference=f"PAY: {self.number}"
            ).exists():
                from apps.accounting.services import AutoJournalService

                with transaction.atomic():
                    AutoJournalService.post_sales_payment(self)


# ════════════════════════ ENTERPRISE SALES ═══════════════════════════════════


class PriceList(CompanyScoped):
    name = models.CharField(max_length=255)
    currency = models.ForeignKey("company.Currency", on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sales_price_lists"

    def __str__(self):
        return self.name


class PriceListItem(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    price_list = models.ForeignKey(
        PriceList, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    min_quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)

    class Meta:
        db_table = "sales_price_list_items"


class DiscountRule(CompanyScoped):
    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", _("Percentage")
        FIXED = "fixed", _("Fixed Amount")

    name = models.CharField(max_length=255)
    discount_type = models.CharField(max_length=15, choices=DiscountType.choices)
    value = models.DecimalField(max_digits=18, decimal_places=4)
    min_order_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "sales_discount_rules"

    def __str__(self):
        return self.name


class Coupon(CompanyScoped):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_rule = models.ForeignKey(
        DiscountRule, on_delete=models.CASCADE, related_name="coupons"
    )
    usage_limit = models.PositiveIntegerField(
        default=1, help_text="Total times this coupon can be used"
    )
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sales_coupons"

    def __str__(self):
        return self.code

    def is_valid(self):
        return self.is_active and self.used_count < self.usage_limit


class Shipment(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PICKED = "picked", _("Picked")
        SHIPPED = "shipped", _("Shipped")
        DELIVERED = "delivered", _("Delivered")
        CANCELLED = "cancelled", _("Cancelled")

    sales_order = models.ForeignKey(
        SalesOrder, on_delete=models.CASCADE, related_name="shipments"
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    scheduled_date = models.DateField(null=True, blank=True)
    shipped_date = models.DateField(null=True, blank=True)
    tracking_number = models.CharField(max_length=100, blank=True)
    carrier = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "sales_shipments"

    def __str__(self):
        return f"{self.number} ({self.sales_order.number})"


class ShipmentLine(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    shipment = models.ForeignKey(
        Shipment, on_delete=models.CASCADE, related_name="lines"
    )
    order_line = models.ForeignKey(SalesOrderLine, on_delete=models.CASCADE)
    product = models.ForeignKey(
        "inventory.Product", null=True, blank=True, on_delete=models.SET_NULL
    )
    quantity = models.DecimalField(max_digits=15, decimal_places=4)

    class Meta:
        db_table = "sales_shipment_lines"


class ProductBundle(CompanyScoped):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "sales_product_bundles"

    def __str__(self):
        return self.name


class ProductBundleItem(models.Model):
    bundle = models.ForeignKey(
        ProductBundle, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=15, decimal_places=4, default=1)

    class Meta:
        db_table = "sales_product_bundle_items"


class Subscription(CompanyScoped, SequenceMixin):
    class BillingCycle(models.TextChoices):
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")
        YEARLY = "yearly", _("Yearly")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        PAUSED = "paused", _("Paused")
        CANCELLED = "cancelled", _("Cancelled")

    customer = models.ForeignKey(
        "crm.Customer", on_delete=models.PROTECT, related_name="subscriptions"
    )
    product = models.ForeignKey("inventory.Product", on_delete=models.PROTECT)
    billing_cycle = models.CharField(
        max_length=15, choices=BillingCycle.choices, default=BillingCycle.MONTHLY
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ACTIVE
    )
    start_date = models.DateField()
    next_billing_date = models.DateField()
    recurring_amount = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        db_table = "sales_subscriptions"


class CreditNote(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ISSUED = "issued", _("Issued")
        APPLIED = "applied", _("Applied")

    customer = models.ForeignKey("crm.Customer", on_delete=models.PROTECT)
    invoice = models.ForeignKey(
        "Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="credit_notes",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    date = models.DateField()
    amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    reason = models.TextField()

    class Meta:
        db_table = "sales_credit_notes"


class CreditNoteLine(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    credit_note = models.ForeignKey(
        CreditNote, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        "inventory.Product", null=True, blank=True, on_delete=models.SET_NULL
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=15, decimal_places=4)
    subtotal = models.DecimalField(max_digits=18, decimal_places=2)

    class Meta:
        db_table = "sales_credit_note_lines"

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class SalesCommission(CompanyScoped):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PAID = "paid", _("Paid")

    sales_rep = models.ForeignKey(
        "authentication.User", on_delete=models.CASCADE, related_name="commissions"
    )
    invoice = models.ForeignKey("Invoice", on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales_commissions"
