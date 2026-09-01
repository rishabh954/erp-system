"""
Company Management Models
Multi-company, multi-branch, departments, fiscal years, currency, tax
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import (
    AddressMixin,
    ContactMixin,
    SoftDeleteModel,
    TimeStampedModel,
    UUIDModel,
)


class Company(SoftDeleteModel, AddressMixin, ContactMixin):
    """Top-level tenant. All business data belongs to a company."""

    class CompanyType(models.TextChoices):
        LLC = "llc", _("LLC")
        CORPORATION = "corporation", _("Corporation")
        PARTNERSHIP = "partnership", _("Partnership")
        SOLE_PROPRIETOR = "sole_proprietor", _("Sole Proprietorship")
        NGO = "ngo", _("NGO / Non-Profit")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        INACTIVE = "inactive", _("Inactive")
        TRIAL = "trial", _("Trial")
        SUSPENDED = "suspended", _("Suspended")

    name = models.CharField(max_length=255, db_index=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="subsidiaries",
        help_text=_("Parent company for hierarchical structures and financial consolidation.")
    )
    legal_name = models.CharField(max_length=255, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    tax_id = models.CharField(max_length=100, blank=True)
    vat_number = models.CharField(max_length=100, blank=True)
    company_type = models.CharField(
        max_length=30, choices=CompanyType.choices, default=CompanyType.LLC
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    industry = models.CharField(max_length=100, blank=True)
    size = models.CharField(
        max_length=20,
        choices=[
            ("1-10", "1-10"),
            ("11-50", "11-50"),
            ("51-200", "51-200"),
            ("200+", "200+"),
        ],
        blank=True,
    )

    # Branding
    logo = models.ImageField(upload_to="company/logos/", null=True, blank=True)
    favicon = models.ImageField(upload_to="company/favicons/", null=True, blank=True)
    primary_color = models.CharField(max_length=7, default="#4361ee")
    secondary_color = models.CharField(max_length=7, default="#3f37c9")

    # Financial defaults
    default_currency = models.ForeignKey(
        "Currency",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="default_for_companies",
    )
    fiscal_year_start = models.CharField(
        max_length=5, default="01-01", help_text="MM-DD"
    )

    default_receivable_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receivable_for_companies",
    )
    default_payable_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payable_for_companies",
    )
    default_bank_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_for_companies",
    )

    # Settings
    language = models.CharField(max_length=10, default="en")
    timezone = models.CharField(max_length=50, default="UTC")
    date_format = models.CharField(max_length=20, default="YYYY-MM-DD")
    number_format = models.CharField(max_length=10, default="1,234.56")
    inventory_valuation_method = models.CharField(
        max_length=20,
        choices=[("FIFO", "FIFO"), ("LIFO", "LIFO"), ("AVERAGE", "Weighted Average")],
        default="FIFO",
    )
    accounting_lock_date = models.DateField(
        null=True,
        blank=True,
        help_text="Journal Entries before this date cannot be modified or posted.",
    )

    # Trial / subscription
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    subscription_plan = models.CharField(max_length=50, default="trial")

    class Meta:
        db_table = "company_companies"
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")

    def __str__(self):
        return self.name

    def get_all_subsidiary_ids(self):
        """Recursively fetch ordered IDs of all child subsidiaries (including self)."""
        ids = []
        seen = set()

        def walk(company):
            if company.id not in seen:
                ids.append(company.id)
                seen.add(company.id)
            for child in company.subsidiaries.filter(status="active", is_deleted=False).order_by("name"):
                walk(child)

        walk(self)
        return ids

    def get_consolidated_account_totals(self):
        """Aggregate current balances across this company and all subsidiaries."""
        from decimal import Decimal

        from apps.accounting.models import Account

        totals = {}
        for account in Account.objects.filter(
            company_id__in=self.get_all_subsidiary_ids(),
            is_deleted=False,
        ).only("code", "current_balance"):
            totals[account.code] = totals.get(account.code, Decimal("0.00")) + account.current_balance
        return totals

    def get_group_consolidated_report(self):
        """Return a grouped financial summary for the company and all subsidiaries."""
        from decimal import Decimal

        from apps.accounting.models import Account

        company_ids = self.get_all_subsidiary_ids()
        assets = {}
        liabilities = {}

        for account in Account.objects.filter(company_id__in=company_ids, is_deleted=False):
            if account.account_type == "asset":
                assets[account.code] = assets.get(account.code, Decimal("0.00")) + account.current_balance
            elif account.account_type == "liability":
                liabilities[account.code] = liabilities.get(account.code, Decimal("0.00")) + account.current_balance

        return {
            "assets": assets,
            "liabilities": liabilities,
            "company_count": len(company_ids),
        }

    @property
    def active_branches(self):
        return self.branches.filter(is_active=True, is_deleted=False)

    @property
    def active_departments(self):
        return self.departments.filter(is_active=True, is_deleted=False)


class Branch(SoftDeleteModel, AddressMixin, ContactMixin):
    """A physical or operational branch within a company."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="branches"
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20)
    is_headquarters = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    manager = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_branches",
    )

    class Meta:
        db_table = "company_branches"
        unique_together = ("company", "code")
        verbose_name = _("Branch")
        verbose_name_plural = _("Branches")

    def __str__(self):
        return f"{self.company.name} — {self.name}"


class Department(SoftDeleteModel):
    """Organizational department within a company."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="departments"
    )
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    head = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="headed_departments",
    )
    cost_center = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "company_departments"
        unique_together = ("company", "code")
        verbose_name = _("Department")
        verbose_name_plural = _("Departments")

    def __str__(self):
        return f"{self.name} ({self.company.name})"

    def get_all_children(self):
        """Recursive: return all sub-departments."""
        children = list(self.children.filter(is_deleted=False))
        for child in list(children):
            children.extend(child.get_all_children())
        return children


class Currency(UUIDModel):
    """Currency master list."""

    code = models.CharField(max_length=3, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=5)
    decimal_places = models.PositiveSmallIntegerField(default=2)
    is_active = models.BooleanField(default=True)
    is_base = models.BooleanField(default=False)

    class Meta:
        db_table = "company_currencies"
        verbose_name = _("Currency")
        verbose_name_plural = _("Currencies")

    def __str__(self):
        return f"{self.code} ({self.symbol})"


class ExchangeRate(TimeStampedModel):
    """Daily exchange rate records."""

    from_currency = models.ForeignKey(
        Currency, on_delete=models.CASCADE, related_name="rates_from"
    )
    to_currency = models.ForeignKey(
        Currency, on_delete=models.CASCADE, related_name="rates_to"
    )
    rate = models.DecimalField(max_digits=20, decimal_places=6)
    effective_date = models.DateField(db_index=True)
    source = models.CharField(max_length=50, default="manual")

    class Meta:
        db_table = "company_exchange_rates"
        unique_together = ("from_currency", "to_currency", "effective_date")
        ordering = ["-effective_date"]

    def __str__(self):
        return f"{self.from_currency.code}/{self.to_currency.code} = {self.rate} on {self.effective_date}"


class FiscalYear(TimeStampedModel):
    """Accounting fiscal year per company."""

    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        CLOSED = "closed", _("Closed")
        LOCKED = "locked", _("Locked")

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="fiscal_years"
    )
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    is_current = models.BooleanField(default=False)

    class Meta:
        db_table = "company_fiscal_years"
        unique_together = ("company", "name")
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.company.name} — {self.name} ({self.status})"

    def save(self, *args, **kwargs):
        # Atomically ensure only one fiscal year is current per company.
        # Without the lock, two concurrent saves of different years as
        # is_current=True could both read zero current rows after each
        # other's UPDATE, leaving two rows with is_current=True.
        if self.is_current:
            from django.db import transaction
            with transaction.atomic():
                # Lock all existing current fiscal years for this company
                # before clearing them, preventing concurrent writers from
                # racing past the UPDATE.
                FiscalYear.objects.select_for_update().filter(
                    company=self.company, is_current=True
                ).exclude(pk=self.pk).update(is_current=False)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)


class TaxGroup(TimeStampedModel):
    """Tax group (e.g., 'Standard VAT', 'Zero Rate')."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="tax_groups"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "company_tax_groups"

    def __str__(self):
        return self.name


class Tax(TimeStampedModel):
    """Individual tax rate definition."""

    class TaxType(models.TextChoices):
        PERCENTAGE = "percentage", _("Percentage")
        FIXED = "fixed", _("Fixed Amount")

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="taxes")
    tax_group = models.ForeignKey(
        TaxGroup, null=True, blank=True, on_delete=models.SET_NULL
    )
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=7, decimal_places=4)
    tax_type = models.CharField(
        max_length=15, choices=TaxType.choices, default=TaxType.PERCENTAGE
    )
    tax_account = models.ForeignKey(
        "accounting.Account",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="taxes",
    )
    is_active = models.BooleanField(default=True)
    is_compound = models.BooleanField(
        default=False, help_text="Applied on top of other taxes"
    )

    class Meta:
        db_table = "company_taxes"

    def __str__(self):
        return f"{self.name} ({self.rate}%)"

    def compute(self, amount):
        if self.tax_type == self.TaxType.PERCENTAGE:
            from decimal import Decimal
            return (amount * Decimal(str(self.rate)) / Decimal("100")).quantize(Decimal("0.01"))
        return self.rate


class CompanySettings(TimeStampedModel):
    """Key-value settings store per company (for extensibility)."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="settings"
    )
    key = models.CharField(max_length=100)
    value = models.TextField(blank=True)
    value_type = models.CharField(
        max_length=10,
        choices=[
            ("string", "String"),
            ("integer", "Integer"),
            ("boolean", "Boolean"),
            ("json", "JSON"),
        ],
        default="string",
    )

    class Meta:
        db_table = "company_settings"
        unique_together = ("company", "key")

    def __str__(self):
        return f"{self.company.name} | {self.key} = {self.value}"


class IntercompanySettlement(TimeStampedModel):
    """Netted settlement for matched intercompany transactions."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SETTLED = "settled", _("Settled")
        CANCELLED = "cancelled", _("Cancelled")

    source_company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="outgoing_intercompany_settlements",
    )
    target_company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="incoming_intercompany_settlements",
    )
    net_amount = models.DecimalField(max_digits=18, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "company_intercompany_settlements"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.source_company.name} -> {self.target_company.name}: {self.net_amount}"


class IntercompanyTransaction(TimeStampedModel):
    """Group-level intercompany posting between legal entities."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        POSTED = "posted", _("Posted")
        SETTLED = "settled", _("Settled")
        CANCELLED = "cancelled", _("Cancelled")

    source_company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="outgoing_intercompany_transactions",
    )
    target_company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="incoming_intercompany_transactions",
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.ForeignKey(
        "Currency",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="intercompany_transactions",
    )
    reference = models.CharField(max_length=100, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "company_intercompany_transactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_company", "target_company", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} ({self.source_company.name} -> {self.target_company.name})"


class LegalEntity(TimeStampedModel):
    """Legal entity configuration for a company, including tax and registration info."""

    class EntityType(models.TextChoices):
        HEADQUARTERS = "headquarters", _("Headquarters")
        SUBSIDIARY = "subsidiary", _("Subsidiary")
        BRANCH = "branch", _("Branch")
        PARTNER = "partner", _("Partner")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="legal_entity"
    )
    legal_name = models.CharField(max_length=255)
    entity_type = models.CharField(
        max_length=30,
        choices=EntityType.choices,
        default=EntityType.SUBSIDIARY,
        db_index=True,
    )
    country = models.CharField(max_length=2, default="US")
    tax_id = models.CharField(max_length=100, blank=True)
    registration_number = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "company_legal_entities"
        verbose_name = _("Legal Entity")
        verbose_name_plural = _("Legal Entities")

    @property
    def display_name(self):
        return self.legal_name or self.company.name

    def __str__(self):
        return f"{self.display_name} ({self.country})"


class CompanyAccountingConfig(TimeStampedModel):
    """Accounting configuration and policy for a company."""

    class AccountingPolicy(models.TextChoices):
        ACCRUAL = "accrual", _("Accrual")
        CASH = "cash", _("Cash")

    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="accounting_config"
    )
    tax_country = models.CharField(max_length=2, default="US")
    accounting_policy = models.CharField(
        max_length=20,
        choices=AccountingPolicy.choices,
        default=AccountingPolicy.ACCRUAL,
    )
    lock_date = models.DateField(null=True, blank=True)
    intercompany_posting_enabled = models.BooleanField(default=False)
    is_consolidation_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "company_accounting_configs"
        verbose_name = _("Accounting Configuration")
        verbose_name_plural = _("Accounting Configurations")

    def can_post_on_date(self, posting_date):
        if self.lock_date is None:
            return True
        if isinstance(posting_date, str):
            from datetime import date

            posting_date = date.fromisoformat(posting_date)
        return posting_date >= self.lock_date

    def __str__(self):
        return f"{self.company.name} accounting config"


class IntercompanyRule(TimeStampedModel):
    """Defines intercompany transfer or settlement rules between companies."""

    class SettlementMethod(models.TextChoices):
        NETTING = "netting", _("Netting")
        TRANSFER = "transfer", _("Transfer")
        MANUAL = "manual", _("Manual")

    source_company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="outgoing_intercompany_rules",
    )
    target_company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="incoming_intercompany_rules",
    )
    settlement_method = models.CharField(
        max_length=20,
        choices=SettlementMethod.choices,
        default=SettlementMethod.NETTING,
    )
    auto_posting_enabled = models.BooleanField(default=True)
    allow_cross_currency = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "company_intercompany_rules"
        unique_together = ("source_company", "target_company", "settlement_method")
        verbose_name = _("Intercompany Rule")
        verbose_name_plural = _("Intercompany Rules")

    def __str__(self):
        return f"{self.source_company.name} -> {self.target_company.name}"
