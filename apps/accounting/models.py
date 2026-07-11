"""
Accounting Module Models
Chart of Accounts, Journal Entries, Bank Reconciliation
"""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped, CurrencyMixin, NotesMixin, SequenceMixin
from core.services import BaseService


class Account(CompanyScoped):
    """Chart of Accounts."""

    class AccountType(models.TextChoices):
        ASSET = "asset", _("Asset")
        LIABILITY = "liability", _("Liability")
        EQUITY = "equity", _("Equity")
        REVENUE = "revenue", _("Revenue")
        EXPENSE = "expense", _("Expense")
        COGS = "cogs", _("Cost of Goods Sold")
        BANK = "bank", _("Bank & Cash")

    class AccountSubtype(models.TextChoices):
        CURRENT_ASSET = "current_asset", _("Current Asset")
        FIXED_ASSET = "fixed_asset", _("Fixed Asset")
        CURRENT_LIABILITY = "current_liability", _("Current Liability")
        LONG_TERM_LIABILITY = "long_term_liability", _("Long-Term Liability")
        ACCOUNTS_RECEIVABLE = "accounts_receivable", _("Accounts Receivable")
        ACCOUNTS_PAYABLE = "accounts_payable", _("Accounts Payable")
        RETAINED_EARNINGS = "retained_earnings", _("Retained Earnings")
        CAPITAL = "capital", _("Capital")
        OTHER = "other", _("Other")

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    code = models.CharField(max_length=20, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    account_type = models.CharField(
        max_length=20, choices=AccountType.choices, db_index=True
    )
    account_subtype = models.CharField(
        max_length=30, choices=AccountSubtype.choices, blank=True
    )
    description = models.TextField(blank=True)
    currency = models.ForeignKey(
        "company.Currency", null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)
    is_reconcilable = models.BooleanField(default=False)
    allow_journal_entries = models.BooleanField(default=True)
    current_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    opening_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    opening_balance_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "accounting_accounts"
        unique_together = ("company", "code")
        ordering = ["code"]
        indexes = [
            models.Index(fields=["company", "account_type", "is_active"]),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"

    @property
    def full_path(self):
        if self.parent:
            return f"{self.parent.full_path} / {self.name}"
        return self.name

    def get_balance(self, from_date=None, to_date=None):
        qs = self.journal_items.filter(journal_entry__status="posted")
        if from_date:
            qs = qs.filter(journal_entry__date__gte=from_date)
        if to_date:
            qs = qs.filter(journal_entry__date__lte=to_date)
        result = qs.aggregate(debit=models.Sum("debit"), credit=models.Sum("credit"))
        debit = result["debit"] or 0
        credit = result["credit"] or 0
        if self.account_type in ("asset", "expense", "cogs", "bank"):
            return debit - credit  # Normal debit balance
        return credit - debit  # Normal credit balance


class Journal(CompanyScoped):
    """Journal type (Sales, Purchases, Cash, Bank, etc.)."""

    class JournalType(models.TextChoices):
        SALES = "sales", _("Sales")
        PURCHASE = "purchase", _("Purchase")
        CASH = "cash", _("Cash")
        BANK = "bank", _("Bank")
        GENERAL = "general", _("General")
        PAYROLL = "payroll", _("Payroll")

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=10)
    journal_type = models.CharField(max_length=15, choices=JournalType.choices)
    default_account = models.ForeignKey(
        Account, null=True, blank=True, on_delete=models.SET_NULL
    )
    sequence_prefix = models.CharField(max_length=10, default="JE")
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_journals"
        unique_together = ("company", "code")

    def __str__(self):
        return f"{self.name} ({self.code})"


class JournalEntry(CompanyScoped, SequenceMixin, NotesMixin, CurrencyMixin):
    """Double-entry accounting journal entry."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        POSTED = "posted", _("Posted")
        REVERSED = "reversed", _("Reversed")
        CANCELLED = "cancelled", _("Cancelled")

    journal = models.ForeignKey(
        Journal, on_delete=models.PROTECT, related_name="entries"
    )
    date = models.DateField(db_index=True)
    reference = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    fiscal_year = models.ForeignKey(
        "company.FiscalYear", null=True, blank=True, on_delete=models.SET_NULL
    )
    total_debit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_credit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    is_reversal = models.BooleanField(default=False)
    reversal_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reversals",
    )
    source_type = models.CharField(
        max_length=50, blank=True
    )  # 'invoice', 'payment', 'payroll' etc.
    source_id = models.CharField(max_length=100, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="posted_entries",
    )

    class Meta:
        db_table = "accounting_journal_entries"
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["company", "date", "status"]),
            models.Index(fields=["journal", "date"]),
        ]

    def save(self, *args, **kwargs):
        if not self.number:
            prefix = self.journal.sequence_prefix if self.journal else "JE"
            self.number = BaseService.generate_sequence_number(prefix, self.__class__, self.company_id)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} | {self.date} | {self.total_debit}"

    def is_balanced(self):
        return self.total_debit == self.total_credit

    def post(self, user=None):
        from django.utils import timezone

        # Check financial close lock date
        if (
            self.company.accounting_lock_date
            and self.date <= self.company.accounting_lock_date
        ):
            raise ValueError(
                f"Cannot post entry before lock date: {self.company.accounting_lock_date}"
            )

        if not self.is_balanced():
            raise ValueError(f"Journal entry {self.number} is not balanced")
        self.status = self.Status.POSTED
        self.posted_at = timezone.now()
        if user:
            self.posted_by = user
        self.save()
        # Update account balances
        for item in self.items.all():
            account = item.account
            if account.account_type in ("asset", "expense", "cogs", "bank"):
                account.current_balance += item.debit - item.credit
            else:
                account.current_balance += item.credit - item.debit
            account.save(update_fields=["current_balance"])


class JournalItem(models.Model):
    """One line in a journal entry (debit or credit)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="items"
    )
    account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="journal_items"
    )
    description = models.CharField(max_length=500, blank=True)
    debit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    currency = models.ForeignKey(
        "company.Currency", null=True, blank=True, on_delete=models.SET_NULL
    )
    amount_currency = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    partner_type = models.CharField(max_length=20, blank=True)  # 'customer' or 'vendor'
    partner_id = models.CharField(max_length=100, blank=True)
    tax = models.ForeignKey(
        "company.Tax", null=True, blank=True, on_delete=models.SET_NULL
    )
    cost_center = models.ForeignKey(
        "CostCenter",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="journal_items",
    )
    reconciled = models.BooleanField(default=False)

    class Meta:
        db_table = "accounting_journal_items"

    def __str__(self):
        return f"{self.account.code} | Dr:{self.debit} Cr:{self.credit}"


class BankAccount(CompanyScoped):
    name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=100)
    bank_name = models.CharField(max_length=255)
    bank_code = models.CharField(max_length=50, blank=True)
    routing_number = models.CharField(max_length=50, blank=True)
    swift_code = models.CharField(max_length=20, blank=True)
    iban = models.CharField(max_length=50, blank=True)
    currency = models.ForeignKey("company.Currency", on_delete=models.PROTECT)
    gl_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="bank_accounts"
    )
    opening_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    current_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_bank_accounts"

    def __str__(self):
        return f"{self.name} ({self.account_number})"


class BankTransaction(CompanyScoped, SequenceMixin):
    class TransactionType(models.TextChoices):
        DEBIT = "debit", _("Debit")
        CREDIT = "credit", _("Credit")

    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="transactions"
    )
    transaction_date = models.DateField(db_index=True)
    value_date = models.DateField(null=True, blank=True)
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    description = models.CharField(max_length=500)
    reference = models.CharField(max_length=200, blank=True)
    is_reconciled = models.BooleanField(default=False, db_index=True)
    journal_item = models.ForeignKey(
        JournalItem, null=True, blank=True, on_delete=models.SET_NULL
    )
    balance_after = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    source = models.CharField(max_length=50, default="manual")

    class Meta:
        db_table = "accounting_bank_transactions"
        ordering = ["-transaction_date"]


class BankStatement(CompanyScoped, SequenceMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PROCESSING = "processing", _("Processing")
        RECONCILED = "reconciled", _("Reconciled")

    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, related_name="statements"
    )
    date_start = models.DateField()
    date_end = models.DateField()
    starting_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    ending_balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    file_upload = models.FileField(upload_to="bank_statements/", null=True, blank=True)

    class Meta:
        db_table = "accounting_bank_statements"
        ordering = ["-date_end"]


class BankStatementLine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    statement = models.ForeignKey(
        BankStatement, on_delete=models.CASCADE, related_name="lines"
    )
    date = models.DateField(db_index=True)
    description = models.CharField(max_length=500)
    amount = models.DecimalField(
        max_digits=20, decimal_places=2
    )  # + for deposit, - for withdrawal
    reference = models.CharField(max_length=200, blank=True)
    is_reconciled = models.BooleanField(default=False, db_index=True)
    journal_item = models.OneToOneField(
        JournalItem,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="bank_statement_line",
    )

    class Meta:
        db_table = "accounting_bank_statement_lines"
        ordering = ["date"]


class TaxReturn(CompanyScoped, SequenceMixin):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Submitted")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")

    period_start = models.DateField()
    period_end = models.DateField()
    tax_type = models.CharField(max_length=50)
    total_sales = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_purchases = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    output_tax = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    input_tax = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    net_tax = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submission_reference = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "accounting_tax_returns"


# ════════════════════════ COSTING & BUDGETING ═════════════════════════════════


class CostCenter(CompanyScoped):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    manager = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="managed_cost_centers",
    )
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "accounting_cost_centers"
        unique_together = ("company", "code")

    def __str__(self):
        return f"{self.code} - {self.name}"


class Budget(CompanyScoped):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        CLOSED = "closed", _("Closed")
        CANCELLED = "cancelled", _("Cancelled")

    name = models.CharField(max_length=200)
    cost_center = models.ForeignKey(
        CostCenter,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="budgets",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )

    class Meta:
        db_table = "accounting_budgets"

    def __str__(self):
        return f"{self.name} ({self.period_start} to {self.period_end})"


class BudgetLine(models.Model):
    import uuid as _uuid

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="budget_lines"
    )
    planned_amount = models.DecimalField(max_digits=20, decimal_places=2, default=0)

    class Meta:
        db_table = "accounting_budget_lines"
        unique_together = ("budget", "account")

    @property
    def actual_amount(self):
        # Calculate actual amount from journal items in this account and cost center within the budget period
        qs = JournalItem.objects.filter(
            account=self.account,
            journal_entry__status="posted",
            journal_entry__date__gte=self.budget.period_start,
            journal_entry__date__lte=self.budget.period_end,
        )
        if self.budget.cost_center:
            qs = qs.filter(cost_center=self.budget.cost_center)

        res = qs.aggregate(dr=models.Sum("debit"), cr=models.Sum("credit"))
        dr = res["dr"] or 0
        cr = res["cr"] or 0

        if self.account.account_type in ("expense", "cogs"):
            return dr - cr
        elif self.account.account_type in ("revenue",):
            return cr - dr
        else:
            return dr - cr

    @property
    def variance(self):
        return self.planned_amount - self.actual_amount


# ════════════════════════ ENTERPRISE ACCOUNTING ═════════════════════════════


class FixedAsset(CompanyScoped, SequenceMixin, NotesMixin):
    class DepreciationMethod(models.TextChoices):
        STRAIGHT_LINE = "straight_line", _("Straight Line")
        DECLINING_BALANCE = "declining_balance", _("Declining Balance")

    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)
    purchase_date = models.DateField()
    purchase_price = models.DecimalField(max_digits=20, decimal_places=2)
    salvage_value = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    useful_life_years = models.PositiveIntegerField(default=1)
    depreciation_method = models.CharField(
        max_length=20,
        choices=DepreciationMethod.choices,
        default=DepreciationMethod.STRAIGHT_LINE,
    )

    asset_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="asset_records"
    )
    depreciation_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="depreciation_records"
    )
    expense_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="expense_records"
    )

    class Meta:
        db_table = "accounting_fixed_asset"

    def __str__(self):
        return f"{self.number} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = BaseService.generate_sequence_number("FA", self.__class__, self.company_id)
        super().save(*args, **kwargs)


class DepreciationSchedule(CompanyScoped):
    asset = models.ForeignKey(
        FixedAsset, on_delete=models.CASCADE, related_name="schedules"
    )
    date = models.DateField()
    depreciation_amount = models.DecimalField(max_digits=20, decimal_places=2)
    cumulative_depreciation = models.DecimalField(max_digits=20, decimal_places=2)
    book_value = models.DecimalField(max_digits=20, decimal_places=2)
    journal_entry = models.ForeignKey(
        JournalEntry, null=True, blank=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "accounting_depreciation_schedule"
        ordering = ["date"]


class RecurringJournalEntry(CompanyScoped):
    class Frequency(models.TextChoices):
        DAILY = "daily", _("Daily")
        WEEKLY = "weekly", _("Weekly")
        MONTHLY = "monthly", _("Monthly")
        YEARLY = "yearly", _("Yearly")

    name = models.CharField(max_length=200)
    journal = models.ForeignKey(Journal, on_delete=models.PROTECT)
    frequency = models.CharField(
        max_length=15, choices=Frequency.choices, default=Frequency.MONTHLY
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    last_run_date = models.DateField(null=True, blank=True)
    next_run_date = models.DateField()
    is_active = models.BooleanField(default=True)

    # Template Data
    template_data = models.JSONField(default=dict)

    class Meta:
        db_table = "accounting_recurring_journal"

    def __str__(self):
        return self.name


class AuditLog(CompanyScoped):
    class Action(models.TextChoices):
        CREATED = "created", _("Created")
        POSTED = "posted", _("Posted")
        REVERSED = "reversed", _("Reversed")
        CANCELLED = "cancelled", _("Cancelled")

    journal_entry = models.ForeignKey(
        JournalEntry, on_delete=models.CASCADE, related_name="audit_logs"
    )
    action = models.CharField(max_length=15, choices=Action.choices)
    user = models.ForeignKey(
        "authentication.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "accounting_audit_log"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.journal_entry.number} - {self.action} by {self.user}"
