"""
Regression tests for accounting bug fixes.

Phase 2:
  - BUG-ACCT-1: ARAgingReportView used Invoice.Status.POSTED (doesn't exist)
                 and amount_due instead of balance_due.
  - BUG-ACCT-2: BankStatement views missing required_permission.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import Account, Journal, JournalEntry, JournalItem
from apps.crm.models import Customer
from apps.purchase.models import Bill
from apps.purchase.models import Payment as VendorPayment
from apps.sales.models import Invoice

pytestmark = pytest.mark.django_db


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def auth_client(company, user):
    c = Client()
    c.force_login(user)
    s = c.session
    s["active_company_id"] = str(company.pk)
    s.save()
    return c


# ─── BUG-ACCT-1: ARAgingReportView ────────────────────────────────────────────

class TestARAgingReportView:
    """The AR aging report must not reference Invoice.Status.POSTED (nonexistent)."""

    def test_invoice_status_has_no_posted_value(self):
        """Invoice.Status must NOT have a POSTED attribute."""
        assert not hasattr(Invoice.Status, "POSTED"), (
            "Invoice.Status.POSTED was added unexpectedly — check InvoiceStatus in core/constants/sales.py"
        )

    def test_ar_aging_view_returns_200(self, auth_client, company):
        """GET /accounting/reports/ar-aging/ must return 200, not 500."""
        url = reverse("accounting:ar_aging")
        response = auth_client.get(url)
        assert response.status_code == 200, (
            f"AR Aging report returned {response.status_code}; "
            "likely still using Invoice.Status.POSTED or amount_due"
        )

    def test_ar_aging_only_includes_open_invoices(self, auth_client, company, currency):
        """AR aging must include SENT/PARTIAL/OVERDUE invoices but not PAID/DRAFT."""
        customer = Customer.objects.create(company=company, name="Aging Customer")

        # SENT invoice — should appear in aging
        Invoice.objects.create(
            company=company,
            customer=customer,
            invoice_date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=Invoice.Status.SENT,
            document_type="standard",
            total=Decimal("100.00"),
            balance_due=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            currency=currency,
        )

        # PAID invoice — must NOT appear
        Invoice.objects.create(
            company=company,
            customer=customer,
            invoice_date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=Invoice.Status.PAID,
            document_type="standard",
            total=Decimal("200.00"),
            balance_due=Decimal("0.00"),
            amount_paid=Decimal("200.00"),
            subtotal=Decimal("200.00"),
            currency=currency,
        )

        url = reverse("accounting:ar_aging")
        response = auth_client.get(url)
        assert response.status_code == 200

        # The view uses balance_due__gt=0, so paid invoice should be excluded
        # (its balance_due is 0). The aging_data dict keys are customer objects.
        ctx = response.context
        aging_data = ctx.get("aging_data", {})
        if customer in aging_data:
            total_in_aging = aging_data[customer]["total"]
            # Only the SENT invoice (balance 100) should contribute
            assert total_in_aging <= Decimal("100.00"), (
                f"PAID invoice appears to be included in aging (total={total_in_aging})"
            )


# ─── BUG-ACCT-2: BankStatement views permission ───────────────────────────────

class TestBankStatementPermissions:
    def test_bank_statement_list_has_required_permission(self):
        from apps.accounting.statement_views import BankStatementListView
        assert hasattr(BankStatementListView, "required_permission"), (
            "BankStatementListView is missing required_permission"
        )
        assert BankStatementListView.required_permission == "accounting.read", (
            f"BankStatementListView.required_permission is '{BankStatementListView.required_permission}'"
        )

    def test_bank_statement_create_has_required_permission(self):
        from apps.accounting.statement_views import BankStatementCreateView
        assert hasattr(BankStatementCreateView, "required_permission"), (
            "BankStatementCreateView is missing required_permission"
        )
        assert BankStatementCreateView.required_permission == "accounting.create", (
            f"BankStatementCreateView.required_permission is '{BankStatementCreateView.required_permission}'"
        )


class TestBalanceSheetReport:
    def test_includes_opening_balances_and_retained_earnings(
        self, auth_client, company, user
    ):
        from apps.accounting.services import FinancialReportingService

        as_of = date(2026, 4, 30)
        cash = Account.objects.create(
            company=company,
            code="BS-CASH",
            name="Opening cash",
            account_type=Account.AccountType.ASSET,
            opening_balance=Decimal("100.00"),
            opening_balance_date=date(2026, 1, 1),
        )
        equity = Account.objects.create(
            company=company,
            code="BS-EQUITY",
            name="Opening equity",
            account_type=Account.AccountType.EQUITY,
            opening_balance=Decimal("100.00"),
            opening_balance_date=date(2026, 1, 1),
        )
        revenue = Account.objects.create(
            company=company,
            code="BS-REVENUE",
            name="Revenue",
            account_type=Account.AccountType.REVENUE,
        )
        journal = Journal.objects.create(
            company=company,
            name="Balance sheet test",
            code="BST",
            journal_type=Journal.JournalType.GENERAL,
        )
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=date(2026, 2, 1),
            total_debit=Decimal("50.00"),
            total_credit=Decimal("50.00"),
        )
        JournalItem.objects.create(
            journal_entry=entry, account=cash, debit=Decimal("50.00")
        )
        JournalItem.objects.create(
            journal_entry=entry, account=revenue, credit=Decimal("50.00")
        )
        entry.post(user=user)
        Account.objects.filter(
            pk__in=[cash.pk, equity.pk, revenue.pk]
        ).update(is_active=False)

        response = auth_client.get(
            reverse("accounting:balance_sheet"), {"as_of": as_of.isoformat()}
        )

        assert response.status_code == 200
        assert response.context["total_assets"] == Decimal("150.00")
        assert response.context["retained_earnings"] == Decimal("50.00")
        assert response.context["total_equity"] == Decimal("150.00")
        assert response.context["total_liabilities_equity"] == Decimal("150.00")
        assert response.context["is_balanced"] is True
        assert b"Retained Earnings" in response.content
        service_report = FinancialReportingService.get_balance_sheet(company, as_of)
        assert service_report["total_assets"] == Decimal("150.00")
        assert service_report["total_equity"] == Decimal("150.00")
        assert service_report["total_liabilities_and_equity"] == Decimal("150.00")
        trial_balance = FinancialReportingService.get_trial_balance(company, as_of)
        assert trial_balance["total_debit"] == Decimal("150.00")
        assert trial_balance["total_credit"] == Decimal("150.00")
        trial_balance_response = auth_client.get(
            reverse("accounting:trial_balance"), {"as_of": as_of.isoformat()}
        )
        assert trial_balance_response.context["total_debit"] == Decimal("150.00")
        assert trial_balance_response.context["total_credit"] == Decimal("150.00")

        before_opening = auth_client.get(
            reverse("accounting:balance_sheet"), {"as_of": "2025-12-31"}
        )
        assert before_opening.context["total_assets"] == Decimal("0")
        assert before_opening.context["total_equity"] == Decimal("0")


class TestAPAgingReport:
    def test_ages_bills_by_due_date_and_as_of_payments(self, auth_client, company, vendor):
        as_of = date(2026, 3, 31)

        def create_bill(number, due_date, amount, *, status=Bill.Status.OPEN):
            return Bill.objects.create(
                company=company,
                vendor=vendor,
                number=number,
                bill_date=date(2026, 1, 1),
                due_date=due_date,
                status=status,
                total=Decimal(amount),
                balance_due=Decimal(amount),
            )

        with patch("apps.accounting.services.AutoJournalService.post_purchase_bill"):
            current_bill = create_bill("AP-CURRENT", as_of, "100.00")
            overdue_30_bill = create_bill("AP-30", date(2026, 3, 15), "200.00")
            overdue_60_bill = create_bill("AP-60", date(2026, 2, 10), "300.00")
            create_bill("AP-90", date(2026, 1, 15), "400.00")
            overdue_bill = create_bill("AP-OLD", date(2025, 12, 1), "500.00")
            draft_bill = create_bill(
                "AP-DRAFT", date(2026, 3, 1), "700.00", status=Bill.Status.DRAFT
            )

        with patch("apps.accounting.services.AutoJournalService.post_purchase_payment"):
            VendorPayment.objects.create(
                company=company,
                bill=overdue_30_bill,
                vendor=vendor,
                amount=Decimal("50.00"),
                payment_date=date(2026, 3, 20),
                status=VendorPayment.Status.COMPLETED,
            )
            VendorPayment.objects.create(
                company=company,
                bill=overdue_60_bill,
                vendor=vendor,
                amount=Decimal("300.00"),
                payment_date=date(2026, 4, 1),
                status=VendorPayment.Status.COMPLETED,
            )

        response = auth_client.get(
            reverse("accounting:ap_aging"), {"as_of": as_of.isoformat()}
        )

        assert response.status_code == 200
        aging = response.context["aging_data"][vendor]
        assert aging == {
            "current": Decimal("100.00"),
            "30": Decimal("150.00"),
            "60": Decimal("300.00"),
            "61_90": Decimal("400.00"),
            "90": Decimal("500.00"),
            "total": Decimal("1450.00"),
        }
        assert b"400.00" in response.content
        assert draft_bill.status == Bill.Status.DRAFT
        assert current_bill.balance_due == Decimal("100.00")
        assert overdue_bill.balance_due == Decimal("500.00")


@pytest.mark.parametrize(
    ("route_name", "query"),
    [
        ("accounting:balance_sheet", {"as_of": "2026-02-30"}),
        ("accounting:profit_loss", {"from_date": "2026-02-30"}),
        ("accounting:trial_balance", {"as_of": "20260201"}),
        ("accounting:ar_aging", {"as_of": "not-a-date"}),
        ("accounting:ap_aging", {"as_of": ""}),
        ("accounting:general_ledger", {"to_date": "2026-02-30"}),
    ],
)
def test_accounting_reports_reject_invalid_dates(auth_client, route_name, query):
    response = auth_client.get(reverse(route_name), query)

    assert response.status_code == 400
    assert b"valid YYYY-MM-DD date" in response.content


@pytest.mark.parametrize(
    ("route_name", "query"),
    [
        (
            "accounting:profit_loss",
            {"from_date": "2026-02-02", "to_date": "2026-02-01"},
        ),
        (
            "accounting:general_ledger",
            {"from_date": "2026-02-02", "to_date": "2026-02-01"},
        ),
        ("accounting:profit_loss", {"from_date": "2099-01-01"}),
    ],
)
def test_accounting_reports_reject_reversed_date_ranges(
    auth_client, route_name, query
):
    response = auth_client.get(reverse(route_name), query)

    assert response.status_code == 400
    assert b"from_date must be on or before to_date" in response.content


def test_account_detail_rejects_invalid_date_filter(auth_client, company):
    account = Account.objects.create(
        company=company,
        code="DATE-TEST",
        name="Date filter account",
        account_type=Account.AccountType.ASSET,
    )

    response = auth_client.get(
        reverse("accounting:account_detail", kwargs={"pk": account.pk}),
        {"from_date": "2026-02-30"},
    )

    assert response.status_code == 400
    assert b"valid YYYY-MM-DD date" in response.content


@pytest.mark.parametrize(
    ("active_filter", "expected_code"),
    [("1", "COA-ACTIVE"), ("0", "COA-INACTIVE")],
)
def test_chart_of_accounts_filters_by_active_status(
    auth_client, company, active_filter, expected_code
):
    Account.objects.create(
        company=company,
        code="COA-ACTIVE",
        name="Active account",
        account_type=Account.AccountType.ASSET,
        is_active=True,
    )
    Account.objects.create(
        company=company,
        code="COA-INACTIVE",
        name="Inactive account",
        account_type=Account.AccountType.ASSET,
        is_active=False,
    )

    response = auth_client.get(
        reverse("accounting:chart_of_accounts"), {"active": active_filter}
    )

    assert response.status_code == 200
    assert {account.code for account in response.context["accounts"]} == {
        expected_code
    }


def test_account_create_view_posts_nonzero_opening_balance(
    auth_client, company
):
    offset = Account.objects.create(
        company=company,
        code="VIEW-OPEN-EQ",
        name="Opening equity",
        account_type=Account.AccountType.EQUITY,
    )

    response = auth_client.post(
        reverse("accounting:account_create"),
        {
            "code": "VIEW-OPEN-ASSET",
            "name": "Opening asset",
            "account_type": Account.AccountType.ASSET,
            "opening_balance": "42.00",
            "opening_balance_date": "2026-01-01",
            "opening_offset_account": str(offset.pk),
        },
    )

    account = Account.objects.get(company=company, code="VIEW-OPEN-ASSET")
    entry = JournalEntry.objects.get(
        company=company,
        source_type="account_opening_balance",
        source_id=str(account.pk),
    )
    assert response.status_code == 302
    assert entry.status == JournalEntry.Status.POSTED
    assert account.current_balance == Decimal("42.00")
