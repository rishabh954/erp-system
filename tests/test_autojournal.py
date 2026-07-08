from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounting.models import JournalEntry
from apps.accounting.services import AutoJournalService
from apps.crm.models import Customer
from apps.sales.models import Invoice, SalesOrder


@pytest.fixture
def sales_invoice(company):
    customer = Customer.objects.create(company=company, name="Test Customer")
    order = SalesOrder.objects.create(
        company=company,
        customer=customer,
        number="SO-100",
        order_date=timezone.now().date(),
        total=Decimal("105.00"),
    )
    invoice = Invoice.objects.create(
        company=company,
        customer=customer,
        sales_order=order,
        number="INV-100",
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date() + timedelta(days=30),
        subtotal=Decimal("100.00"),
        tax_amount=Decimal("5.00"),
        total=Decimal("105.00"),
    )
    return invoice


@pytest.mark.django_db
def test_post_sales_invoice_balances_and_updates(company, sales_invoice):
    """Test that AutoJournalService correctly posts an invoice, balances it, and updates A/R and Revenue."""  # noqa: E501
    entry = AutoJournalService.post_sales_invoice(sales_invoice)

    # Assert entry is balanced and posted
    assert entry.is_balanced()
    assert entry.status == JournalEntry.Status.POSTED

    # Assert accounts updated correctly
    ar_account = AutoJournalService.get_or_create_ar(company)
    ar_account.refresh_from_db()
    # A/R is an asset account, debit increases balance
    assert ar_account.current_balance == Decimal("105.00")

    # Check total debits and credits
    assert entry.total_debit == Decimal("105.00")
    assert entry.total_credit == Decimal("105.00")


@pytest.mark.django_db
def test_financial_close_date_lockout(company, sales_invoice):
    """Test that posting an entry before the financial close date raises an error."""
    # Set accounting lock date to tomorrow
    company.accounting_lock_date = timezone.now().date() + timedelta(days=1)
    company.save()

    with pytest.raises(ValueError, match="Cannot post entry before lock date"):
        AutoJournalService.post_sales_invoice(sales_invoice)
