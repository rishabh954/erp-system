import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import CompanyScoped, SequenceMixin, NotesMixin


# ═══════════════════════════════ ASSET MANAGEMENT ══════════════════════════════

class AssetCategory(CompanyScoped):
    name = models.CharField(max_length=200)
    depreciation_method = models.CharField(
        max_length=20,
        choices=[('straight_line', 'Straight Line'), ('declining_balance', 'Declining Balance'),
                 ('sum_of_years', 'Sum of Years'), ('units_of_production', 'Units of Production')],
        default='straight_line',
    )
    useful_life_years = models.PositiveSmallIntegerField(default=5)
    salvage_value_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    depreciation_account = models.ForeignKey('accounting.Account', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    accumulated_depreciation_account = models.ForeignKey('accounting.Account', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    asset_account = models.ForeignKey('accounting.Account', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        db_table = 'assets_categories'

    def __str__(self):
        return self.name


class Asset(CompanyScoped, SequenceMixin, NotesMixin):

    class Status(models.TextChoices):
        ACTIVE = 'active', _('Active')
        UNDER_MAINTENANCE = 'under_maintenance', _('Under Maintenance')
        DISPOSED = 'disposed', _('Disposed')
        SOLD = 'sold', _('Sold')
        LOST = 'lost', _('Lost/Stolen')

    name = models.CharField(max_length=500)
    asset_code = models.CharField(max_length=100, blank=True)
    category = models.ForeignKey(AssetCategory, on_delete=models.PROTECT)
    branch = models.ForeignKey('company.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    purchase_date = models.DateField()
    purchase_cost = models.DecimalField(max_digits=18, decimal_places=2)
    salvage_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    useful_life_years = models.PositiveSmallIntegerField(default=5)
    depreciation_method = models.CharField(max_length=20, default='straight_line')
    current_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    accumulated_depreciation = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    vendor = models.ForeignKey('purchase.Vendor', null=True, blank=True, on_delete=models.SET_NULL)
    serial_number = models.CharField(max_length=200, blank=True)
    model_number = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=255, blank=True)
    assigned_to = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assigned_assets',
    )
    warranty_expiry = models.DateField(null=True, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)
    image = models.ImageField(upload_to='assets/', null=True, blank=True)
    disposal_date = models.DateField(null=True, blank=True)
    disposal_amount = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    disposal_reason = models.TextField(blank=True)

    class Meta:
        db_table = 'assets_assets'
        ordering = ['-purchase_date']

    def __str__(self):
        return f"{self.number} | {self.name}"

    def calculate_annual_depreciation(self):
        if self.depreciation_method == 'straight_line':
            return (self.purchase_cost - self.salvage_value) / max(self.useful_life_years, 1)
        return 0


class AssetMaintenance(CompanyScoped, SequenceMixin):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', _('Scheduled')
        IN_PROGRESS = 'in_progress', _('In Progress')
        COMPLETED = 'completed', _('Completed')
        CANCELLED = 'cancelled', _('Cancelled')

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='maintenances')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    maintenance_type = models.CharField(
        max_length=20,
        choices=[('preventive', 'Preventive'), ('corrective', 'Corrective'), ('predictive', 'Predictive')],
    )
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.SCHEDULED)
    scheduled_date = models.DateField()
    completed_date = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    performed_by = models.CharField(max_length=255, blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'assets_maintenances'


class DepreciationEntry(CompanyScoped):
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='depreciation_entries')
    period_start = models.DateField()
    period_end = models.DateField()
    depreciation_amount = models.DecimalField(max_digits=18, decimal_places=2)
    book_value_before = models.DecimalField(max_digits=18, decimal_places=2)
    book_value_after = models.DecimalField(max_digits=18, decimal_places=2)
    journal_entry = models.ForeignKey('accounting.JournalEntry', null=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'assets_depreciation_entries'
