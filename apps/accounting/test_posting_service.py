from datetime import date
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import Account, AuditLog, Journal, JournalEntry, JournalItem
from apps.accounting.services import (
    AccountingPostingService,
    AccountService,
    AutoJournalService,
    FinancialReportingService,
)
from apps.company.models import Company
from apps.crm.models import Customer
from apps.sales.models import Invoice

pytestmark = pytest.mark.django_db


def _entry(company, *, debit_account=None, credit_account=None, totals=True):
    debit_account = debit_account or Account.objects.create(
        company=company,
        name="Cash",
        code=f"C{Account.objects.filter(company=company).count()}",
        account_type=Account.AccountType.ASSET,
    )
    credit_account = credit_account or Account.objects.create(
        company=company,
        name="Revenue",
        code=f"R{Account.objects.filter(company=company).count()}",
        account_type=Account.AccountType.REVENUE,
    )
    journal = Journal.objects.create(
        company=company,
        name="General",
        code=f"J{Journal.objects.filter(company=company).count()}",
        journal_type=Journal.JournalType.GENERAL,
    )
    entry = JournalEntry.objects.create(
        company=company,
        journal=journal,
        date=timezone.localdate(),
        total_debit=Decimal("10") if totals else Decimal("0"),
        total_credit=Decimal("10") if totals else Decimal("0"),
    )
    return entry, debit_account, credit_account


def test_posting_service_posts_and_audits_balanced_entry(company, user):
    entry, debit_account, credit_account = _entry(company)
    JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
    )

    posted = AccountingPostingService.post(entry, user=user)

    entry.refresh_from_db()
    debit_account.refresh_from_db()
    credit_account.refresh_from_db()
    assert posted.pk == entry.pk
    assert entry.status == JournalEntry.Status.POSTED
    assert debit_account.current_balance == Decimal("10")
    assert credit_account.current_balance == Decimal("10")
    assert AuditLog.objects.filter(
        journal_entry=entry, action=AuditLog.Action.POSTED, user=user
    ).exists()


def test_posting_rejects_empty_zero_entry(company):
    entry, _, _ = _entry(company, totals=False)

    with pytest.raises(ValueError, match="at least two lines"):
        entry.post()


def test_posting_rejects_cross_company_account(company):
    other_company = Company.objects.create(name="Other company")
    foreign_account = Account.objects.create(
        company=other_company,
        name="Foreign Cash",
        code="FC1",
        account_type=Account.AccountType.ASSET,
    )
    entry, _, credit_account = _entry(company, debit_account=foreign_account)
    JournalItem.objects.create(
        journal_entry=entry,
        account=foreign_account,
        debit=Decimal("10"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
    )

    with pytest.raises(ValueError, match="belong to the entry company"):
        entry.post()

    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.DRAFT


@pytest.mark.parametrize(
    "account_changes",
    [
        {"is_active": False},
        {"allow_journal_entries": False},
    ],
)
def test_posting_rejects_inactive_or_restricted_account(company, account_changes):
    entry, debit_account, credit_account = _entry(company)
    Account.objects.filter(pk=debit_account.pk).update(**account_changes)
    JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
    )

    with pytest.raises(ValueError, match="active and allow entries"):
        entry.post()

    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.DRAFT


def test_posting_is_idempotent_for_already_posted_entry(company, user):
    entry, debit_account, credit_account = _entry(company)
    JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
    )

    entry.post(user=user)
    posted_at = entry.posted_at
    entry.post(user=user)

    debit_account.refresh_from_db()
    assert debit_account.current_balance == Decimal("10")
    assert entry.posted_at == posted_at
    assert AuditLog.objects.filter(
        journal_entry=entry, action=AuditLog.Action.POSTED
    ).count() == 1


def test_invoice_source_retry_returns_existing_journal(company):
    customer = Customer.objects.create(company=company, name="Posting customer")
    invoice = Invoice.objects.create(
        company=company,
        customer=customer,
        invoice_date=timezone.localdate(),
        due_date=timezone.localdate(),
        subtotal=Decimal("10"),
        total=Decimal("10"),
    )
    invoice.status = Invoice.Status.SENT
    invoice.save()
    existing = JournalEntry.objects.get(
        company=company, reference=f"INV: {invoice.number}"
    )

    retried = AutoJournalService.post_sales_invoice(invoice)

    assert retried.pk == existing.pk
    assert JournalEntry.objects.filter(
        company=company, reference=f"INV: {invoice.number}"
    ).count() == 1


def test_reversal_posts_opposite_entry_without_changing_original(company, user):
    entry, debit_account, credit_account = _entry(company)
    JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
        description="Original debit",
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
        description="Original credit",
    )
    entry.post(user=user)

    reversal = AccountingPostingService.reverse(
        entry,
        user=user,
        reason="Correcting the source transaction",
    )

    entry.refresh_from_db()
    debit_account.refresh_from_db()
    credit_account.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED
    assert reversal.status == JournalEntry.Status.POSTED
    assert reversal.is_reversal
    assert reversal.reversal_of_id == entry.pk
    reversed_lines = {
        item.account_id: (item.debit, item.credit)
        for item in reversal.items.all()
    }
    assert reversed_lines[debit_account.pk] == (Decimal("0"), Decimal("10"))
    assert reversed_lines[credit_account.pk] == (Decimal("10"), Decimal("0"))
    assert debit_account.current_balance == Decimal("0")
    assert credit_account.current_balance == Decimal("0")
    assert AuditLog.objects.filter(
        journal_entry=entry, action=AuditLog.Action.REVERSED, user=user
    ).exists()

    retried = AccountingPostingService.reverse(
        entry,
        user=user,
        reason="Retry after timeout",
    )
    assert retried.pk == reversal.pk
    assert JournalEntry.objects.filter(reversal_of=entry).count() == 1


def test_posted_journal_entry_rejects_mutation_and_deletion(company, user):
    entry, debit_account, credit_account = _entry(company)
    JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
    )
    entry.post(user=user)

    entry.reference = "Changed reference"
    with pytest.raises(ValueError, match="immutable"):
        entry.save()
    with pytest.raises(ValueError, match="immutable"):
        JournalEntry.objects.filter(pk=entry.pk).update(reference="Changed")
    with pytest.raises(ValueError, match="immutable"):
        JournalEntry.all_objects.filter(pk=entry.pk).update(reference="Changed")
    with pytest.raises(ValueError, match="cannot be deleted"):
        entry.delete()
    with pytest.raises(ValueError, match="cannot be deleted"):
        JournalEntry.objects.filter(pk=entry.pk).delete()
    with pytest.raises(ValueError, match="cannot be deleted"):
        JournalEntry.all_objects.filter(pk=entry.pk).hard_delete()

    entry.refresh_from_db()
    assert entry.reference == ""
    assert entry.status == JournalEntry.Status.POSTED


def test_posted_journal_lines_reject_instance_and_queryset_writes(company, user):
    entry, debit_account, credit_account = _entry(company)
    debit_item = JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
    )
    JournalItem.objects.create(
        journal_entry=entry,
        account=credit_account,
        credit=Decimal("10"),
    )
    entry.post(user=user)

    debit_item.description = "Changed line"
    with pytest.raises(ValueError, match="immutable"):
        debit_item.save()
    with pytest.raises(ValueError, match="immutable"):
        JournalItem.objects.create(
            journal_entry=entry,
            account=debit_account,
            debit=Decimal("1"),
        )
    with pytest.raises(ValueError, match="immutable"):
        JournalItem.objects.filter(pk=debit_item.pk).update(
            description="Changed line"
        )
    with pytest.raises(ValueError, match="immutable"):
        JournalItem.all_objects.filter(pk=debit_item.pk).update(
            description="Changed line"
        )
    with pytest.raises(ValueError, match="cannot be deleted"):
        debit_item.delete()
    with pytest.raises(ValueError, match="cannot be deleted"):
        JournalItem.objects.filter(pk=debit_item.pk).delete()
    with pytest.raises(ValueError, match="immutable"):
        JournalItem.objects.bulk_create(
            [JournalItem(journal_entry=entry, account=debit_account, debit=1)]
        )
    with pytest.raises(ValueError, match="immutable"):
        JournalItem.objects.bulk_update([debit_item], ["description"])
    draft_entry, draft_account, _ = _entry(company)
    draft_item = JournalItem.objects.create(
        journal_entry=draft_entry,
        account=draft_account,
        debit=Decimal("1"),
    )
    with pytest.raises(ValueError, match="immutable"):
        JournalItem.objects.filter(pk=draft_item.pk).update(journal_entry=entry)

    debit_item.refresh_from_db()
    assert debit_item.description == ""


def test_draft_journal_entries_and_lines_remain_editable(company):
    entry, debit_account, _ = _entry(company)
    item = JournalItem.objects.create(
        journal_entry=entry,
        account=debit_account,
        debit=Decimal("10"),
    )

    entry.reference = "Draft edit"
    entry.save(update_fields=["reference"])
    item.description = "Draft line edit"
    item.save(update_fields=["description"])

    assert entry.reference == "Draft edit"
    assert item.description == "Draft line edit"
    item.delete()
    assert not JournalItem.objects.filter(pk=item.pk).exists()


def test_account_opening_balance_posts_auditable_balanced_journal(company, user):
    offset = Account.objects.create(
        company=company,
        code="OPEN-EQ",
        name="Opening equity",
        account_type=Account.AccountType.EQUITY,
    )
    service = AccountService(user=user, company=company)

    account = service.create_account(
        {
            "code": "OPEN-CASH",
            "name": "Opening cash",
            "account_type": Account.AccountType.ASSET,
            "opening_balance": "125.50",
            "opening_balance_date": "2026-01-01",
            "opening_offset_account": str(offset.pk),
        }
    )

    entry = JournalEntry.objects.get(
        company=company,
        source_type="account_opening_balance",
        source_id=str(account.pk),
    )
    account.refresh_from_db()
    offset.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED
    assert entry.date == date(2026, 1, 1)
    assert entry.reference == "OPENING: OPEN-CASH"
    assert entry.items.count() == 2
    assert all(
        line.description == "Opening balance for OPEN-CASH - Opening cash"
        for line in entry.items.all()
    )
    assert entry.is_balanced()
    assert AuditLog.objects.filter(
        journal_entry=entry,
        action=AuditLog.Action.POSTED,
        user=user,
    ).exists()
    assert account.current_balance == Decimal("125.50")
    assert offset.current_balance == Decimal("125.50")
    assert FinancialReportingService.get_account_balance_including_opening(
        account, date(2026, 1, 2)
    ) == Decimal("125.50")
    trial_balance = FinancialReportingService.get_trial_balance(company, date(2026, 1, 2))
    assert trial_balance["total_debit"] == Decimal("125.50")
    assert trial_balance["total_credit"] == Decimal("125.50")


@pytest.mark.parametrize(
    "account_type",
    [Account.AccountType.LIABILITY, Account.AccountType.EQUITY],
)
def test_credit_normal_opening_balance_posts_correct_entry_sides(
    company, user, account_type
):
    offset = Account.objects.create(
        company=company,
        code=f"OFFSET-{account_type}",
        name="Opening equity offset",
        account_type=Account.AccountType.EQUITY,
    )
    account = AccountService(user=user, company=company).create_account(
        {
            "code": f"OPEN-{account_type}",
            "name": "Opening credit-normal account",
            "account_type": account_type,
            "opening_balance": "80.00",
            "opening_balance_date": "2026-01-01",
            "opening_offset_account": str(offset.pk),
        }
    )
    entry = JournalEntry.objects.get(source_id=str(account.pk))
    lines = {line.account_id: line for line in entry.items.all()}
    assert lines[account.pk].credit == Decimal("80.00")
    assert lines[offset.pk].debit == Decimal("80.00")
    account.refresh_from_db()
    assert account.current_balance == Decimal("80.00")


@pytest.mark.parametrize(
    "missing_or_invalid",
    [
        {"opening_balance_date": ""},
        {"opening_offset_account": ""},
    ],
)
def test_opening_balance_rejects_missing_journal_requirements(
    company, user, missing_or_invalid
):
    offset = Account.objects.create(
        company=company,
        code="OPEN-REQUIREMENT-EQ",
        name="Opening equity",
        account_type=Account.AccountType.EQUITY,
    )
    payload = {
        "code": "OPEN-REQUIREMENT",
        "name": "Opening account",
        "account_type": Account.AccountType.ASSET,
        "opening_balance": "25.00",
        "opening_balance_date": "2026-01-01",
        "opening_offset_account": str(offset.pk),
    }
    payload.update(missing_or_invalid)

    with pytest.raises(ValueError):
        AccountService(user=user, company=company).create_account(payload)

    assert not Account.objects.filter(company=company, code="OPEN-REQUIREMENT").exists()
    assert not JournalEntry.objects.filter(
        company=company, source_type="account_opening_balance"
    ).exists()


def test_opening_balance_rejects_offset_from_another_company(company, user):
    other_company = Company.objects.create(name="Foreign opening company")
    foreign_offset = Account.objects.create(
        company=other_company,
        code="FOREIGN-EQUITY",
        name="Foreign equity",
        account_type=Account.AccountType.EQUITY,
    )

    with pytest.raises(ValueError, match="active company"):
        AccountService(user=user, company=company).create_account(
            {
                "code": "OPEN-FOREIGN",
                "name": "Opening account",
                "account_type": Account.AccountType.ASSET,
                "opening_balance": "25.00",
                "opening_balance_date": "2026-01-01",
                "opening_offset_account": str(foreign_offset.pk),
            }
        )

    assert not Account.objects.filter(company=company, code="OPEN-FOREIGN").exists()


def test_zero_opening_balance_does_not_require_offset_or_create_journal(company, user):
    account = AccountService(user=user, company=company).create_account(
        {
            "code": "OPEN-ZERO",
            "name": "No opening amount",
            "account_type": Account.AccountType.ASSET,
            "opening_balance": "",
        }
    )

    assert account.opening_balance == Decimal("0")
    assert account.current_balance == Decimal("0")
    assert not JournalEntry.objects.filter(
        company=company, source_type="account_opening_balance"
    ).exists()
