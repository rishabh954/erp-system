from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import Account, JournalEntry, JournalItem

pytestmark = pytest.mark.django_db


def test_journal_entry_posting_balances_debits_credits(company, user):
    """Test that posting a journal entry checks for balance and updates accounts correctly."""
    # Create an Asset account (debit increases balance)
    asset_account = Account.objects.create(
        company=company,
        name="Cash",
        code="1000",
        account_type=Account.AccountType.ASSET,
        current_balance=Decimal("0"),
    )

    # Create a Revenue account (credit increases balance)
    revenue_account = Account.objects.create(
        company=company,
        name="Sales Revenue",
        code="4000",
        account_type=Account.AccountType.REVENUE,
        current_balance=Decimal("0"),
    )

    from apps.accounting.models import Journal

    journal = Journal.objects.create(
        company=company,
        name="General Journal",
        code="GEN",
        journal_type=Journal.JournalType.GENERAL,
    )

    # Create unposted journal entry
    je = JournalEntry.objects.create(
        company=company,
        journal=journal,
        date=timezone.now().date(),
        reference="TEST-01",
        total_debit=Decimal("100.00"),
        total_credit=Decimal("100.00"),
        status=JournalEntry.Status.DRAFT,
    )

    # Add Journal Items
    JournalItem.objects.create(
        journal_entry=je,
        account=asset_account,
        debit=Decimal("100.00"),
        credit=Decimal("0"),
    )
    JournalItem.objects.create(
        journal_entry=je,
        account=revenue_account,
        debit=Decimal("0"),
        credit=Decimal("100.00"),
    )

    # Test balance validation
    assert je.is_balanced() == True

    # Post it
    je.post(user=user)

    # Refresh accounts from DB
    asset_account.refresh_from_db()
    revenue_account.refresh_from_db()

    # Assert balances were updated
    assert asset_account.current_balance == Decimal("100.00")
    assert revenue_account.current_balance == Decimal("100.00")


def test_journal_entry_post_unbalanced_fails(company, user):
    """Test that unbalanced journal entries raise an error."""
    asset_account = Account.objects.create(
        company=company,
        name="Cash 2",
        code="1001",
        account_type=Account.AccountType.ASSET,
    )

    revenue_account = Account.objects.create(
        company=company,
        name="Sales Revenue 2",
        code="4001",
        account_type=Account.AccountType.REVENUE,
    )

    from apps.accounting.models import Journal

    journal = Journal.objects.create(
        company=company,
        name="General Journal 2",
        code="GEN2",
        journal_type=Journal.JournalType.GENERAL,
    )

    je = JournalEntry.objects.create(
        company=company,
        journal=journal,
        date=timezone.now().date(),
        total_debit=Decimal("100.00"),
        total_credit=Decimal("50.00"),
        status=JournalEntry.Status.DRAFT,
    )

    JournalItem.objects.create(
        journal_entry=je,
        account=asset_account,
        debit=Decimal("100.00"),
        credit=Decimal("0"),
    )
    JournalItem.objects.create(
        journal_entry=je,
        account=revenue_account,
        debit=Decimal("0"),
        credit=Decimal("50.00"),
    )

    assert je.is_balanced() == False

    with pytest.raises(ValueError, match="is not balanced"):
        je.post(user=user)


def test_account_get_balance(company):
    """Test that get_balance calculates correctly for different account types."""
    asset_account = Account.objects.create(
        company=company,
        name="Asset Acc",
        code="1002",
        account_type=Account.AccountType.ASSET,
    )
    liability_account = Account.objects.create(
        company=company,
        name="Liability Acc",
        code="2000",
        account_type=Account.AccountType.LIABILITY,
    )

    from apps.accounting.models import Journal

    journal = Journal.objects.create(
        company=company,
        name="General Journal 3",
        code="GEN3",
        journal_type=Journal.JournalType.GENERAL,
    )

    je = JournalEntry.objects.create(
        company=company,
        journal=journal,
        date=timezone.now().date(),
        total_debit=Decimal("50.00"),
        total_credit=Decimal("50.00"),
        status=JournalEntry.Status.POSTED,
    )

    # Asset gets a debit of 50
    JournalItem.objects.create(
        journal_entry=je,
        account=asset_account,
        debit=Decimal("50.00"),
        credit=Decimal("0"),
    )
    # Liability gets a credit of 50
    JournalItem.objects.create(
        journal_entry=je,
        account=liability_account,
        debit=Decimal("0"),
        credit=Decimal("50.00"),
    )

    # asset_account is normal debit: debit - credit -> 50 - 0 = 50
    assert asset_account.get_balance() == Decimal("50.00")

    # liability_account is normal credit: credit - debit -> 50 - 0 = 50
    assert liability_account.get_balance() == Decimal("50.00")


def test_journal_entry_service_create(company, user):
    """Test JournalEntryService.create_entry handles logic correctly."""
    from django.http import QueryDict

    from apps.accounting.services import JournalEntryService

    asset_account = Account.objects.create(
        company=company,
        name="Asset",
        code="1005",
        account_type=Account.AccountType.ASSET,
    )
    revenue_account = Account.objects.create(
        company=company,
        name="Rev",
        code="4005",
        account_type=Account.AccountType.REVENUE,
    )
    from apps.accounting.models import Journal

    journal = Journal.objects.create(
        company=company,
        name="GEN4",
        code="GEN4",
        journal_type=Journal.JournalType.GENERAL,
    )

    # Mock data as QueryDict to simulate request.POST
    data = QueryDict(mutable=True)
    data["journal"] = journal.id
    data["date"] = timezone.now().date()
    data.setlist("account[]", [str(asset_account.id), str(revenue_account.id)])
    data.setlist("debit[]", ["200", "0"])
    data.setlist("credit[]", ["0", "200"])
    data.setlist("item_description[]", ["Debit Asset", "Credit Rev"])

    service = JournalEntryService(user=user, company=company)
    entry = service.create_entry(data)

    assert entry.total_debit == Decimal("200")
    assert entry.total_credit == Decimal("200")
    assert entry.items.count() == 2
    assert entry.is_balanced() == True


def test_banking_service_reconcile(company, user, currency):
    """Test BankingService.reconcile_transaction matches correctly."""
    from apps.accounting.models import BankAccount, BankStatement, BankStatementLine
    from apps.accounting.services import BankingService

    bank_account = BankAccount.objects.create(
        company=company,
        name="Bank",
        account_number="1234",
        currency=currency,
        gl_account=Account.objects.create(
            company=company,
            name="Bank GL",
            code="1006",
            account_type=Account.AccountType.BANK,
        ),
    )
    statement = BankStatement.objects.create(
        company=company,
        bank_account=bank_account,
        date_start=timezone.now().date(),
        date_end=timezone.now().date(),
    )
    line = BankStatementLine.objects.create(
        statement=statement,
        date=timezone.now().date(),
        amount=Decimal("500.00"),
        description="Deposit",
    )

    from apps.accounting.models import Journal

    journal = Journal.objects.create(
        company=company,
        name="Bank Journal",
        code="BNK",
        journal_type=Journal.JournalType.BANK,
    )
    je = JournalEntry.objects.create(
        company=company, journal=journal, date=timezone.now().date()
    )

    item = JournalItem.objects.create(
        journal_entry=je,
        account=bank_account.gl_account,
        debit=Decimal("500.00"),
        credit=Decimal("0.00"),
    )

    service = BankingService(user=user, company=company)
    res_line, res_item = service.reconcile_transaction(line.id, item.id)

    assert res_line.is_reconciled == True
    assert res_item.reconciled == True
    assert res_line.journal_item == res_item

def test_issue_credit_note_permissions(client, company):
    from django.urls import reverse

    from apps.authentication.models import ModulePermission, User

    # 1. Setup users
    user_read = User.objects.create_user(email="read@acc.com", password="password", primary_company=company, role=User.Role.CUSTOMER_PORTAL)
    ModulePermission.objects.filter(role=User.Role.CUSTOMER_PORTAL, module="accounting").delete()
    ModulePermission.objects.create(role=User.Role.CUSTOMER_PORTAL, module="accounting", can_read=True, can_create=False)

    user_create = User.objects.create_user(email="create@acc.com", password="password", primary_company=company, role=User.Role.EMPLOYEE)
    ModulePermission.objects.filter(role=User.Role.EMPLOYEE, module="accounting").delete()
    ModulePermission.objects.create(role=User.Role.EMPLOYEE, module="accounting", can_read=True, can_create=True)

    url = reverse('accounting:issue_credit_note')

    # 2. Test user_read (should be allowed on GET, forbidden on POST)
    client.force_login(user_read)
    response_get = client.get(url)
    assert response_get.status_code == 200, "Read user should be allowed to view the credit note page"

    response_post = client.post(url, data={})
    assert response_post.status_code == 403, "Read user must be forbidden on POST"

    # 3. Test user_create (should be allowed on both GET and POST)
    client.force_login(user_create)
    response_post2 = client.post(url, data={})
    assert response_post2.status_code != 403, "Create user must pass permission check"
