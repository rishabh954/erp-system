"""
Core Abstract Models
All ERP models inherit from these base classes.
Implements: UUID PKs, soft delete, audit fields, multi-tenancy
"""

import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UUIDModel(models.Model):
    """Abstract base giving every model a UUID primary key."""

    id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False, db_index=True
    )

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    """Adds created_at / updated_at audit timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class SoftDeleteQuerySet(models.QuerySet):
    def delete(self):
        return super().update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

    def alive(self):
        return self.filter(is_deleted=False)

    def dead(self):
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    def get_queryset(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def all_with_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db)

    def only_deleted(self):
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=True)


class SoftDeleteModel(TimeStampedModel):
    """Soft delete: sets is_deleted=True instead of removing rows."""

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_deleted",
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False, deleted_by=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if deleted_by:
            self.deleted_by = deleted_by
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    def hard_delete(self):
        super().delete()


class AuditedModel(SoftDeleteModel):
    """Full audit trail: created_by, updated_by, plus soft delete."""

    created_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True


class CompanyScoped(AuditedModel):
    """
    Base for all company-scoped (multi-tenant) records.
    All business data inherits from this.
    """

    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Validate the record belongs to a valid company
        if not self.company_id:
            raise ValueError("company is required for all business records")
        super().save(*args, **kwargs)


class BranchScoped(CompanyScoped):
    """For records tied to a specific branch within a company."""

    branch = models.ForeignKey(
        "company.Branch",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_set",
    )

    class Meta:
        abstract = True


class StatusMixin(models.Model):
    """Generic status field with common choices."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        CANCELLED = "cancelled", _("Cancelled")
        COMPLETED = "completed", _("Completed")
        CLOSED = "closed", _("Closed")

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    class Meta:
        abstract = True


class CurrencyMixin(models.Model):
    """Add currency to financial records."""

    currency = models.ForeignKey(
        "company.Currency",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    exchange_rate = models.DecimalField(
        max_digits=15, decimal_places=6, default=1.000000
    )

    class Meta:
        abstract = True


class AddressMixin(models.Model):
    """Reusable address fields."""

    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    class Meta:
        abstract = True

    @property
    def full_address(self):
        parts = [
            self.address_line1,
            self.address_line2,
            self.city,
            self.state,
            self.postal_code,
            self.country,
        ]
        return ", ".join(p for p in parts if p)


class ContactMixin(models.Model):
    """Reusable contact fields."""

    phone = models.CharField(max_length=30, blank=True)
    mobile = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    class Meta:
        abstract = True


class NotesMixin(models.Model):
    """Adds a notes field."""

    notes = models.TextField(blank=True)

    class Meta:
        abstract = True


class AttachmentMixin(models.Model):
    """Adds file attachment support via GenericRelation."""

    # Use in concrete models with:
    # attachments = GenericRelation('documents.Attachment')
    class Meta:
        abstract = True


class SequenceMixin(models.Model):
    """Adds an auto-generated human-readable number (e.g. INV-00001).

    All number generation must use BaseService.generate_sequence_number()
    from core.services — it is company-scoped and uses consistent 5-digit padding.
    """

    number = models.CharField(max_length=50, blank=True, db_index=True)

    class Meta:
        abstract = True
