from django.db import models
from django.utils.translation import gettext_lazy as _

class QuotationStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    EXPIRED = "expired", _("Expired")
    CONVERTED = "converted", _("Converted to SO")

class SalesOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    CONFIRMED = "confirmed", _("Confirmed")
    PROCESSING = "processing", _("Processing")
    SHIPPED = "shipped", _("Shipped")
    DELIVERED = "delivered", _("Delivered")
    INVOICED = "invoiced", _("Invoiced")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")

class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    PARTIAL = "partial", _("Partially Paid")
    PAID = "paid", _("Paid")
    OVERDUE = "overdue", _("Overdue")
    CANCELLED = "cancelled", _("Cancelled")
    REFUNDED = "refunded", _("Refunded")

class InvoiceDocumentType(models.TextChoices):
    STANDARD = "standard", _("Standard Invoice")
    CREDIT_NOTE = "credit_note", _("Credit Note")
    DEBIT_NOTE = "debit_note", _("Debit Note")

class PaymentMethod(models.TextChoices):
    CASH = "cash", _("Cash")
    BANK_TRANSFER = "bank_transfer", _("Bank Transfer")
    CHEQUE = "cheque", _("Cheque")
    CREDIT_CARD = "credit_card", _("Credit Card")
    ONLINE = "online", _("Online Payment")

class PaymentStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    COMPLETED = "completed", _("Completed")
    FAILED = "failed", _("Failed")
    REFUNDED = "refunded", _("Refunded")
