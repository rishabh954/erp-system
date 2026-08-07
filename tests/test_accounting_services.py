"""
Tests for Accounting Services in ERP system.
"""
import pytest
from datetime import date, timedelta
from decimal import Decimal

from apps.accounting.models import Account, Journal, JournalEntry, JournalItem
from apps.accounting.services import FinancialReportingService

@pytest.fixture
def accounting_data(company):
    ar_account = Account.objects.create(
        company=company, code="1200", name="Accounts Receivable", account_type="asset"
    )
    revenue_account = Account.objects.create(
        company=company, code="4000", name="Sales Revenue", account_type="revenue"
    )
    expense_account = Account.objects.create(
        company=company, code="5000", name="General Expenses", account_type="expense"
    )
    bank_account = Account.objects.create(
        company=company, code="1000", name="Bank", account_type="bank"
    )
    journal = Journal.objects.create(company=company, code="GEN", name="General Journal", journal_type="general")
    return {
        "ar": ar_account,
        "revenue": revenue_account,
        "expense": expense_account,
        "bank": bank_account,
        "journal": journal
    }

@pytest.mark.django_db
class TestAccountingServices:
    def test_double_entry_journal_posting(self, company, accounting_data):
        """Test: double-entry journal posting (debits == credits)"""
        entry = JournalEntry.objects.create(
            company=company,
            journal=accounting_data["journal"],
            date=date.today(),
            total_debit=Decimal("100.00"),
            total_credit=Decimal("100.00"),
        )
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["bank"], debit=Decimal("100.00"), credit=0)
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["revenue"], debit=0, credit=Decimal("100.00"))
        
        assert entry.is_balanced()
        entry.post()
        assert entry.status == JournalEntry.Status.POSTED

    def test_account_balance_calculation(self, company, accounting_data):
        """Test: Account balance calculation"""
        entry = JournalEntry.objects.create(
            company=company,
            journal=accounting_data["journal"],
            date=date.today(),
            total_debit=Decimal("200.00"),
            total_credit=Decimal("200.00"),
        )
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["bank"], debit=Decimal("200.00"), credit=0)
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["revenue"], debit=0, credit=Decimal("200.00"))
        entry.post()
        
        assert accounting_data["bank"].get_balance() == Decimal("200.00")
        assert accounting_data["revenue"].get_balance() == Decimal("200.00")

    def test_profit_and_loss_report(self, company, accounting_data):
        """Test: P&L report generation returns revenue/expense data"""
        entry = JournalEntry.objects.create(
            company=company,
            journal=accounting_data["journal"],
            date=date.today(),
            total_debit=Decimal("150.00"),
            total_credit=Decimal("150.00"),
        )
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["expense"], debit=Decimal("50.00"), credit=0)
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["bank"], debit=Decimal("150.00"), credit=0)
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["revenue"], debit=0, credit=Decimal("200.00"))
        entry.post()

        pl = FinancialReportingService.get_profit_and_loss(company)
        assert pl["total_revenue"] == Decimal("200.00")
        assert pl["total_expense"] == Decimal("50.00")
        assert pl["net_profit"] == Decimal("150.00")

    def test_trial_balance_sums_to_zero(self, company, accounting_data):
        """Test: trial balance sums to zero (total_debit == total_credit)"""
        entry = JournalEntry.objects.create(
            company=company,
            journal=accounting_data["journal"],
            date=date.today(),
            total_debit=Decimal("300.00"),
            total_credit=Decimal("300.00"),
        )
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["bank"], debit=Decimal("300.00"), credit=0)
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["revenue"], debit=0, credit=Decimal("300.00"))
        entry.post()

        tb = FinancialReportingService.get_trial_balance(company)
        assert tb["total_debit"] == Decimal("300.00")
        assert tb["total_credit"] == Decimal("300.00")
        assert tb["is_balanced"] is True

    def test_posting_to_locked_period_raises_error(self, company, accounting_data):
        """Test: posting to locked period raises error"""
        company.accounting_lock_date = date.today() + timedelta(days=1)
        company.save()

        entry = JournalEntry.objects.create(
            company=company,
            journal=accounting_data["journal"],
            date=date.today(),
            total_debit=Decimal("100.00"),
            total_credit=Decimal("100.00"),
        )
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["bank"], debit=Decimal("100.00"), credit=0)
        JournalItem.objects.create(journal_entry=entry, account=accounting_data["revenue"], debit=0, credit=Decimal("100.00"))
        
        with pytest.raises(ValueError, match="Cannot post entry before lock date"):
            entry.post()
