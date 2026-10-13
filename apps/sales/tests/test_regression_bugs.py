"""
Regression tests for sales module bug fixes.

Phase 3:
  - BUG-SALES-1: CreditNoteListView used select_related("branch") but
                  CreditNote has no branch field.
  - BUG-SALES-2: SalesOrderService.create_invoice must guard duplicate invoicing.
  - BUG-SALES-3: SalesOrderService.create_delivery must reject double deliveries.
  - BUG-SALES-4: Commission signal must be idempotent (no duplicates on re-save).
"""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.crm.models import Customer
from apps.sales.models import (
    CreditNote,
    Invoice,
    SalesCommission,
    SalesOrder,
    SalesOrderLine,
)

pytestmark = pytest.mark.django_db


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def admin_user(company):
    u = User.objects.create_user(
        email="sales_admin@test.com",
        password="password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company,
    )
    UserCompany.objects.create(user=u, company=company, is_active=True)
    return u


@pytest.fixture
def auth_client(company, admin_user):
    c = Client()
    c.force_login(admin_user)
    s = c.session
    s["active_company_id"] = str(company.pk)
    s.save()
    return c


@pytest.fixture
def customer(company):
    return Customer.objects.create(company=company, name="Test Customer")


@pytest.fixture
def sales_order(company, customer, currency):
    order = SalesOrder.objects.create(
        company=company,
        customer=customer,
        order_date=timezone.localdate(),
        payment_terms=30,
        status=SalesOrder.Status.CONFIRMED,
        subtotal=Decimal("90.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("9.00"),
        total=Decimal("89.00"),
        currency=currency,
    )
    SalesOrderLine.objects.create(
        sales_order=order,
        description="Widget A",
        quantity=Decimal("1"),
        unit_price=Decimal("100.00"),
        discount_percent=Decimal("10"),
        subtotal=Decimal("100.00"),
        discount_amount=Decimal("10.00"),
        tax_amount=Decimal("9.00"),
        total=Decimal("99.00"),
    )
    return order


# ─── BUG-SALES-1: CreditNoteListView branch select_related ─────────────────────

class TestCreditNoteView:
    def test_credit_note_list_view_no_branch_field_error(self, auth_client, company, customer):
        """GET /sales/credit-notes/ must not raise FieldError due to branch select_related."""
        CreditNote.objects.create(
            company=company,
            customer=customer,
            date=timezone.localdate(),
            amount=Decimal("50.00"),
            reason="Test return",
        )
        url = reverse("sales:credit_notes")
        response = auth_client.get(url)
        # Must not crash with FieldError or 500
        assert response.status_code in (200, 302), (
            f"Credit notes list returned {response.status_code}; "
            "branch select_related may still be present"
        )

    def test_credit_note_model_has_no_branch_field(self):
        """CreditNote model must not have a branch field."""
        field_names = [f.name for f in CreditNote._meta.get_fields()]
        assert "branch" not in field_names, (
            "CreditNote unexpectedly has a branch field"
        )


# ─── BUG-SALES-2: SalesOrderService.create_invoice guards ─────────────────────

class TestCreateInvoiceGuards:
    def test_cannot_double_invoice_order(self, company, admin_user, sales_order, currency):
        """create_invoice must raise ValueError if a non-cancelled invoice already exists."""
        from apps.sales.services import SalesOrderService

        service = SalesOrderService(user=admin_user, company=company)

        # First invoice creation should succeed
        inv1 = service.create_invoice(sales_order)
        assert inv1 is not None

        # Re-fetch order to get updated status
        sales_order.refresh_from_db()

        # Second attempt must raise
        with pytest.raises(ValueError, match="already (invoiced|exists)"):
            service.create_invoice(sales_order)

    def test_cannot_invoice_draft_order(self, company, admin_user, customer, currency):
        """create_invoice must reject DRAFT orders."""
        from apps.sales.services import SalesOrderService

        order = SalesOrder.objects.create(
            company=company,
            customer=customer,
            order_date=timezone.localdate(),
            payment_terms=30,
            status=SalesOrder.Status.DRAFT,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            currency=currency,
        )
        SalesOrderLine.objects.create(
            sales_order=order,
            description="Item",
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )

        service = SalesOrderService(user=admin_user, company=company)
        with pytest.raises(ValueError, match="[Dd]raft|[Cc]annot"):
            service.create_invoice(order)

    def test_cannot_invoice_cancelled_order(self, company, admin_user, customer, currency):
        """create_invoice must reject CANCELLED orders."""
        from apps.sales.services import SalesOrderService

        order = SalesOrder.objects.create(
            company=company,
            customer=customer,
            order_date=timezone.localdate(),
            payment_terms=30,
            status=SalesOrder.Status.CANCELLED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            currency=currency,
        )
        SalesOrderLine.objects.create(
            sales_order=order,
            description="Item",
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )

        service = SalesOrderService(user=admin_user, company=company)
        with pytest.raises(ValueError):
            service.create_invoice(order)


# ─── BUG-SALES-3: Double delivery guard ───────────────────────────────────────

class TestCreateDeliveryGuards:
    def test_cannot_create_duplicate_open_delivery(self, company, admin_user, sales_order, warehouse):
        """create_delivery must raise ValueError if an open delivery already exists."""
        from apps.inventory.models import DeliveryOrder
        from apps.sales.services import SalesOrderService

        service = SalesOrderService(user=admin_user, company=company)

        # Create first delivery manually
        DeliveryOrder.objects.create(
            company=company,
            number="DEL-TEST-001",
            sales_order=sales_order,
            warehouse=warehouse,
            status=DeliveryOrder.Status.READY,
        )

        with pytest.raises(ValueError, match="open delivery"):
            service.create_delivery(sales_order)


# ─── BUG-SALES-4: Commission signal idempotency ────────────────────────────────

class TestSalesCommissionIdempotency:
    def test_commission_created_once_per_paid_invoice(self, company, admin_user, customer, currency):
        """Saving a PAID invoice multiple times must produce exactly one commission."""
        sales_rep = User.objects.create_user(
            email="rep_idem@test.com",
            password="pw",
            role=User.Role.EMPLOYEE,
            primary_company=company,
        )
        UserCompany.objects.create(user=sales_rep, company=company, is_active=True)

        order = SalesOrder.objects.create(
            company=company,
            customer=customer,
            order_date=timezone.localdate(),
            payment_terms=30,
            status=SalesOrder.Status.INVOICED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            sales_rep=sales_rep,
            currency=currency,
        )

        invoice = Invoice.objects.create(
            company=company,
            customer=customer,
            sales_order=order,
            invoice_date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=Invoice.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("0.00"),
            currency=currency,
        )

        # Save again (simulating a subsequent update)
        invoice.notes = "Updated notes"
        invoice.save(update_fields=["notes"])

        # Save once more
        invoice.save(update_fields=["notes"])

        count = SalesCommission.objects.filter(
            company=company, invoice=invoice, sales_rep=sales_rep
        ).count()
        assert count == 1, f"Expected 1 commission, got {count} (idempotency broken)"

    def test_commission_rate_from_company_settings(self, company, admin_user, customer, currency):
        """Commission amount should use the company setting rate if present."""
        from apps.company.models import CompanySettings

        CompanySettings.objects.create(
            company=company, key="sales_commission_rate", value="0.10"
        )

        sales_rep = User.objects.create_user(
            email="rep_rate@test.com",
            password="pw",
            role=User.Role.EMPLOYEE,
            primary_company=company,
        )
        UserCompany.objects.create(user=sales_rep, company=company, is_active=True)

        order = SalesOrder.objects.create(
            company=company,
            customer=customer,
            order_date=timezone.localdate(),
            payment_terms=30,
            status=SalesOrder.Status.INVOICED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            sales_rep=sales_rep,
            currency=currency,
        )

        Invoice.objects.create(
            company=company,
            customer=customer,
            sales_order=order,
            invoice_date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=Invoice.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("0.00"),
            currency=currency,
        )

        commission = SalesCommission.objects.filter(
            company=company, sales_rep=sales_rep
        ).first()
        assert commission is not None
        assert commission.amount == Decimal("10.00"), (
            f"Commission should be 10% of 100 = 10.00, got {commission.amount}"
        )

    def test_commission_reduced_by_credit_note(self, company, admin_user, customer, currency):
        """When a credit note is issued, the commission must be recalculated downward."""
        sales_rep = User.objects.create_user(
            email="rep_cn@test.com",
            password="pw",
            role=User.Role.EMPLOYEE,
            primary_company=company,
        )
        UserCompany.objects.create(user=sales_rep, company=company, is_active=True)

        order = SalesOrder.objects.create(
            company=company,
            customer=customer,
            order_date=timezone.localdate(),
            payment_terms=30,
            status=SalesOrder.Status.INVOICED,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            sales_rep=sales_rep,
            currency=currency,
        )

        invoice = Invoice.objects.create(
            company=company,
            customer=customer,
            sales_order=order,
            invoice_date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=Invoice.Status.PAID,
            total=Decimal("100.00"),
            subtotal=Decimal("100.00"),
            amount_paid=Decimal("100.00"),
            balance_due=Decimal("0.00"),
            currency=currency,
        )

        # Commission at 5% of 100 = 5.00
        commission = SalesCommission.objects.filter(
            company=company, invoice=invoice, sales_rep=sales_rep
        ).first()
        assert commission is not None
        original_amount = commission.amount

        # Issue a credit note
        CreditNote.objects.create(
            company=company,
            customer=customer,
            invoice=invoice,
            date=timezone.localdate(),
            amount=Decimal("40.00"),
            status=CreditNote.Status.ISSUED,
            reason="Partial return",
        )

        commission.refresh_from_db()
        # Commissionable total is now 100 - 40 = 60, so 5% = 3.00
        assert commission.amount < original_amount, (
            f"Commission ({commission.amount}) should be less than original ({original_amount}) after credit note"
        )
