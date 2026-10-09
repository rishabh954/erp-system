from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import Account, Journal, JournalEntry, JournalItem
from apps.company.models import FiscalYear

pytestmark = pytest.mark.django_db


def _balanced_entry(company, posting_date, code):
    debit_account = Account.objects.create(
        company=company,
        name=f"Cash {code}",
        code=f"{code}D",
        account_type=Account.AccountType.ASSET,
    )
    credit_account = Account.objects.create(
        company=company,
        name=f"Revenue {code}",
        code=f"{code}C",
        account_type=Account.AccountType.REVENUE,
    )
    journal = Journal.objects.create(
        company=company,
        name=f"Journal {code}",
        code=code,
        journal_type=Journal.JournalType.GENERAL,
    )
    entry = JournalEntry.objects.create(
        company=company,
        journal=journal,
        date=posting_date,
        total_debit=Decimal("25.00"),
        total_credit=Decimal("25.00"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("25.00"),
        credit=Decimal("0"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        debit=Decimal("0"),
        credit=Decimal("25.00"),
    )
    return entry, debit_account


@pytest.mark.parametrize(
    "status", [FiscalYear.Status.CLOSED, FiscalYear.Status.LOCKED]
)
def test_posting_is_refused_for_closed_or_locked_year(company, user, status):
    posting_date = timezone.localdate()
    fiscal_year = FiscalYear.objects.create(
        company=company,
        name=f"FY-{status}",
        start_date=posting_date.replace(month=1, day=1),
        end_date=posting_date.replace(month=12, day=31),
        status=status,
    )
    entry, debit_account = _balanced_entry(company, posting_date, "FY1")

    with pytest.raises(ValueError, match="Cannot post into"):
        entry.post(user=user)

    entry.refresh_from_db()
    debit_account.refresh_from_db()
    assert entry.status == JournalEntry.Status.DRAFT
    assert entry.fiscal_year_id is None
    assert fiscal_year.status == status
    assert debit_account.current_balance == Decimal("0")


def test_posting_assigns_matching_open_fiscal_year(company, user):
    posting_date = timezone.localdate()
    fiscal_year = FiscalYear.objects.create(
        company=company,
        name="Open fiscal year",
        start_date=posting_date.replace(month=1, day=1),
        end_date=posting_date.replace(month=12, day=31),
    )
    entry, _ = _balanced_entry(company, posting_date, "FY2")

    entry.post(user=user)

    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED
    assert entry.fiscal_year_id == fiscal_year.pk
