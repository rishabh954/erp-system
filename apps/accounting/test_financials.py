from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from apps.accounting.models import Account, JournalEntry
from apps.accounting.services import AutoJournalService, FinancialReportingService

pytestmark = pytest.mark.django_db

def test_autojournal_post_sales_invoice(company, user):
    """Test that post_sales_invoice creates correct balanced journal entry."""
    invoice = MagicMock()
    invoice.company = company
    invoice.invoice_date = timezone.now().date()
    invoice.number = "INV-001"
    invoice.currency_id = 1
    invoice.currency = None
    invoice.total = Decimal("110.00")
    invoice.subtotal = Decimal("100.00")
    invoice.tax_amount = Decimal("10.00")
    invoice.customer.id = 1

    # Mock lines
    mock_line = MagicMock()
    mock_line.product.revenue_account = None
    invoice.lines.exists.return_value = True
    invoice.lines.first.return_value = mock_line

    entry = AutoJournalService.post_sales_invoice(invoice)

    assert entry.total_debit == Decimal("110.00")
    assert entry.total_credit == Decimal("110.00")
    assert entry.is_balanced() is True
    assert entry.status == JournalEntry.Status.POSTED
    assert entry.items.count() == 3  # AR, Revenue, Tax

def test_autojournal_post_purchase_bill(company, user):
    """Test that post_purchase_bill creates correct balanced journal entry."""
    bill = MagicMock()
    bill.company = company
    bill.bill_date = timezone.now().date()
    bill.number = "BILL-001"
    bill.currency_id = 1
    bill.currency = None
    bill.total = Decimal("220.00")
    bill.subtotal = Decimal("200.00")
    bill.tax_amount = Decimal("20.00")
    bill.vendor.id = 1

    mock_line = MagicMock()
    mock_line.product.cogs_account = None
    bill.lines.exists.return_value = True
    bill.lines.first.return_value = mock_line

    entry = AutoJournalService.post_purchase_bill(bill)

    assert entry.total_debit == Decimal("220.00")
    assert entry.total_credit == Decimal("220.00")
    assert entry.is_balanced() is True
    assert entry.status == JournalEntry.Status.POSTED
    assert entry.items.count() == 3  # AP, Expense, Tax

def test_financial_reporting_trial_balance(company, user):
    """Test trial balance correctly aggregates debits and credits."""
    # Create an Asset account (debit 100)
    asset_account = Account.objects.create(
        company=company, name="Cash", code="1000", account_type=Account.AccountType.ASSET, current_balance=Decimal("0")
    )
    # Create a Liability account (credit 100)
    liability_account = Account.objects.create(
        company=company, name="Loan", code="2000", account_type=Account.AccountType.LIABILITY, current_balance=Decimal("0")
    )

    from apps.accounting.models import Journal, JournalItem
    journal = Journal.objects.create(company=company, name="GEN", code="GEN", journal_type=Journal.JournalType.GENERAL)

    je = JournalEntry.objects.create(
        company=company, journal=journal, date=timezone.now().date(),
        total_debit=Decimal("100.00"), total_credit=Decimal("100.00"), status=JournalEntry.Status.POSTED
    )
    JournalItem.objects.create(journal_entry=je, account=asset_account, debit=Decimal("100.00"), credit=Decimal("0"))
    JournalItem.objects.create(journal_entry=je, account=liability_account, debit=Decimal("0"), credit=Decimal("100.00"))

    tb = FinancialReportingService.get_trial_balance(company)
    assert tb["total_debit"] == Decimal("100.00")
    assert tb["total_credit"] == Decimal("100.00")
    assert tb["is_balanced"] is True
