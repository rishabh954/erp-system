from django.db import models
from django.utils.translation import gettext_lazy as _


class QuotationStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SENT = "sent", _("Sent")
    VIEWED = "viewed", _("Viewed")
    ACCEPTED = "accepted", _("Accepted")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    EXPIRED = "expired", _("Expired")
    CONVERTED = "converted", _("Converted to SO")
    CANCELLED = "cancelled", _("Cancelled")

class SalesOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_APPROVAL = "pending_approval", _("Pending Approval")
    CONFIRMED = "confirmed", _("Confirmed")
    PROCESSING = "processing", _("Processing")
    PARTIALLY_DELIVERED = "partially_delivered", _("Partially Delivered")
    SHIPPED = "shipped", _("Shipped")
    DELIVERED = "delivered", _("Delivered")
    PARTIALLY_INVOICED = "partially_invoiced", _("Partially Invoiced")
    INVOICED = "invoiced", _("Fully Invoiced")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")

class DeliveryOrderStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    READY = "ready", _("Ready")
    PICKING = "picking", _("Picking")
    PACKING = "packing", _("Packing")
    SHIPPED = "shipped", _("Shipped")
    DELIVERED = "delivered", _("Delivered")
    CANCELLED = "cancelled", _("Cancelled")

class SalesReturnStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_APPROVAL = "pending_approval", _("Pending Approval")
    APPROVED = "approved", _("Approved")
    RECEIVED = "received", _("Items Received")
    INSPECTED = "inspected", _("Quality Inspected")
    COMPLETED = "completed", _("Completed")
    REJECTED = "rejected", _("Rejected")

class ReturnReason(models.TextChoices):
    DAMAGED = "damaged", _("Damaged Goods")
    DEFECTIVE = "defective", _("Defective Product")
    WRONG_ITEM = "wrong_item", _("Wrong Item Shipped")
    NOT_AS_DESCRIBED = "not_as_described", _("Not As Described")
    BUYER_REMORSE = "buyer_remorse", _("Customer Return")
    OTHER = "other", _("Other")

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
