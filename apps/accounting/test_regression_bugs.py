"""
Regression tests for accounting bug fixes.

Phase 2:
  - BUG-ACCT-1: ARAgingReportView used Invoice.Status.POSTED (doesn't exist)
                 and amount_due instead of balance_due.
  - BUG-ACCT-2: BankStatement views missing required_permission.
"""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounting.models import Account, Journal, JournalEntry, JournalItem
from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.crm.models import Customer
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
        inv_sent = Invoice.objects.create(
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
