from django.db import models
from core.models import CompanyScoped, SequenceMixin, NotesMixin
from django.utils.translation import gettext_lazy as _

class POSSession(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        OPEN = 'open', _('Open')
        CLOSED = 'closed', _('Closed')

    user = models.ForeignKey('authentication.User', on_delete=models.PROTECT)
    warehouse = models.ForeignKey('inventory.Warehouse', on_delete=models.PROTECT)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    starting_cash = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    ending_cash = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    class Meta:
        db_table = 'pos_session'

    def __str__(self):
        return f"{self.number} - {self.user.full_name}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('POS-S', self.__class__)
        super().save(*args, **kwargs)


class POSOrder(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        DRAFT = 'draft', _('Draft')
        PAID = 'paid', _('Paid')
        CANCELLED = 'cancelled', _('Cancelled')

    session = models.ForeignKey(POSSession, on_delete=models.PROTECT, related_name='orders')
    customer = models.ForeignKey('crm.Customer', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pos_order'

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number('POS', self.__class__)
        super().save(*args, **kwargs)


class POSOrderLine(models.Model):
    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name='lines')
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=15, decimal_places=4)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    subtotal = models.DecimalField(max_digits=15, decimal_places=2)

    class Meta:
        db_table = 'pos_order_line'


class POSPayment(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', _('Cash')
        CARD = 'card', _('Credit/Debit Card')
        MOBILE = 'mobile', _('Mobile Money')
        BANK_TRANSFER = 'bank_transfer', _('Bank Transfer')

    import uuid as _uuid
    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    order = models.ForeignKey(POSOrder, on_delete=models.CASCADE, related_name='payments')
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    tendered = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    change = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    reference = models.CharField(max_length=100, blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pos_payment'
