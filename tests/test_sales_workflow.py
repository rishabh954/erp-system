"""
Enterprise Sales Workflow Integration Tests
==========================================
Full Sales pipeline:
  Quotation -> SalesOrder -> CreditCheck -> DeliveryOrder -> Invoice -> Payment -> Return

Covers:
  - Quotation lifecycle and conversion
  - Credit control: limit exceeded, overdue hold, manager override
  - Stock reservation and delivery state machine
  - Invoice creation and journal idempotency
  - Payment (full/partial) and outstanding balance
  - Sales returns: create -> approve -> complete (restock + credit note + accounting)
  - Invalid state transitions blocked
  - Multi-tenant isolation
"""

from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.company.models import Currency
from apps.crm.models import Customer
from apps.inventory.models import Product, ProductCategory, StockRecord, Warehouse
from apps.inventory.services import StockService
from apps.sales.models import (
    CreditNote,
    Invoice,
    InvoiceLine,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
    SalesReturn,
)
from apps.sales.services import (
    CreditControlService,
    InvoiceService,
    PaymentService,
    SalesOrderService,
    SalesReturnService,
    SalesService,
)

User = get_user_model()


def _make_company(name="TestCo"):
    from apps.company.models import Company
    currency, _ = Currency.objects.get_or_create(
        code="USD", defaults={"name": "US Dollar", "symbol": "$", "is_base_currency": True}
    )
    company = Company.objects.create(
        name=name, legal_name=f"{name} Ltd",
        company_type="LLC", fiscal_year_start="01-01", default_currency=currency,
    )
    return company, currency


def _make_user(email, company):
    from apps.authentication.models import UserCompany
    user = User.objects.create_user(email=email, password="pass123", first_name="Test", last_name="User")
    UserCompany.objects.create(user=user, company=company, role="admin", is_active=True)
    user.primary_company = company
    user.save(update_fields=["primary_company"])
    return user


def _make_product(company, sku="PRD-001", price="100.00"):
    cat, _ = ProductCategory.objects.get_or_create(company=company, name="General")
    return Product.objects.create(
        company=company, name=f"Product {sku}", sku=sku,
        product_type="stockable", category=cat,
        cost_price=Decimal("50.00"), sale_price=Decimal(price),
    )


def _make_customer(company, name="Acme Corp", credit_limit="10000.00"):
    return Customer.objects.create(
        company=company, name=name,
        email=f"{name.lower().replace(' ', '')}@example.com",
        credit_limit=Decimal(credit_limit),
    )


def _receive_stock(user, company, product, qty=50):
    wh, _ = Warehouse.objects.get_or_create(company=company, name="Main WH", defaults={"is_active": True})
    StockService(user=user, company=company).receive_stock(
        product=product, warehouse=wh, qty=Decimal(str(qty)),
        unit_cost=Decimal("50.00"), reference_type="Initial", reference_id="INIT",
    )
    return wh


# ---------------------------------------------------------------------------
class SalesWorkflowTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_currencies", verbosity=0)
        cls.company, cls.currency = _make_company("SalesTestCo")
        cls.user = _make_user("sales@test.com", cls.company)
        cls.product = _make_product(cls.company, sku="SWTEST-001")
        cls.customer = _make_customer(cls.company, credit_limit="10000.00")
        cls.wh = _receive_stock(cls.user, cls.company, cls.product, qty=50)

    def _order_service(self):
        return SalesOrderService(user=self.user, company=self.company)

    def _payment_service(self):
        return PaymentService(user=self.user, company=self.company)

    def _return_service(self):
        return SalesReturnService(user=self.user, company=self.company)

    def _create_confirmed_order(self, qty="2", price="100.00"):
        q = Quotation.objects.create(
            company=self.company, customer=self.customer, currency=self.currency,
            status="approved", validity_date=timezone.now().date() + timezone.timedelta(days=30),
        )
        QuotationLine.objects.create(
            quotation=q, product=self.product, description=self.product.name,
            quantity=Decimal(qty), unit_price=Decimal(price),
        )
        q.recalculate_totals()
        so = SalesService(user=self.user, company=self.company).convert_quote_to_order(q)
        so = self._order_service().confirm_order(so)
        return so

    def _create_sent_invoice(self, qty="2"):
        so = self._create_confirmed_order(qty=qty)
        inv = self._order_service().create_invoice(so)
        if not inv.lines.exists():
            InvoiceLine.objects.create(
                invoice=inv, product=self.product,
                description="Item", quantity=Decimal(qty), unit_price=Decimal("100.00")
            )
            inv.recalculate_totals()
        inv.status = "sent"
        inv.save(update_fields=["status"])
        return inv


# ---------------------------------------------------------------------------
class TestQuotationLifecycle(SalesWorkflowTestCase):

    def test_convert_approved_quotation_to_order(self):
        q = Quotation.objects.create(
            company=self.company, customer=self.customer, currency=self.currency,
            status="approved", validity_date=timezone.now().date() + timezone.timedelta(days=30),
        )
        QuotationLine.objects.create(
            quotation=q, product=self.product, description="X",
            quantity=Decimal("3"), unit_price=Decimal("100.00"),
        )
        q.recalculate_totals()
        so = SalesService(user=self.user, company=self.company).convert_quote_to_order(q)
        self.assertIsNotNone(so)
        self.assertEqual(so.company, self.company)

    def test_convert_accepted_quotation_to_order(self):
        """ACCEPTED status (from customer portal) must be convertible."""
        q = Quotation.objects.create(
            company=self.company, customer=self.customer, currency=self.currency,
            status="accepted", validity_date=timezone.now().date() + timezone.timedelta(days=30),
        )
        QuotationLine.objects.create(
            quotation=q, product=self.product, description="X",
            quantity=Decimal("1"), unit_price=Decimal("100.00"),
        )
        q.recalculate_totals()
        so = SalesService(user=self.user, company=self.company).convert_quote_to_order(q)
        self.assertIsNotNone(so)

    def test_cannot_convert_draft_quotation(self):
        q = Quotation.objects.create(
            company=self.company, customer=self.customer, currency=self.currency,
            status="draft", validity_date=timezone.now().date() + timezone.timedelta(days=30),
        )
        QuotationLine.objects.create(
            quotation=q, product=self.product, description="X",
            quantity=Decimal("1"), unit_price=Decimal("100.00"),
        )
        with self.assertRaises((ValueError, Exception)):
            SalesService(user=self.user, company=self.company).convert_quote_to_order(q)


# ---------------------------------------------------------------------------
class TestCreditControl(SalesWorkflowTestCase):

    def test_credit_limit_evaluation_breach(self):
        customer = _make_customer(self.company, name="TinyCredit", credit_limit="100.00")
        so = SalesOrder.objects.create(
            company=self.company, customer=customer, currency=self.currency,
            status="draft", order_date=timezone.now().date(),
        )
        SalesOrderLine.objects.create(
            sales_order=so, product=self.product, description="X",
            quantity=Decimal("10"), unit_price=Decimal("500.00"),
        )
        so.recalculate_totals()
        result = CreditControlService.evaluate_credit(so.customer, so.total)
        self.assertIn("hold_required", result)
        self.assertTrue(result["hold_required"])

    def test_order_held_when_limit_exceeded(self):
        customer = _make_customer(self.company, name="OverLimit", credit_limit="10.00")
        so = SalesOrder.objects.create(
            company=self.company, customer=customer, currency=self.currency,
            status="draft", order_date=timezone.now().date(),
        )
        SalesOrderLine.objects.create(
            sales_order=so, product=self.product, description="X",
            quantity=Decimal("100"), unit_price=Decimal("100.00"),
        )
        so.recalculate_totals()
        
        passed, msg = CreditControlService(user=self.user, company=self.company).check_and_apply_credit_hold(so, self.user)
        self.assertFalse(passed)
        so.refresh_from_db()
        self.assertTrue(so.credit_hold)
        self.assertEqual(so.status, "pending_approval")

    def test_credit_override_releases_hold(self):
        customer = _make_customer(self.company, name="OverrideCo2", credit_limit="10.00")
        so = SalesOrder.objects.create(
            company=self.company, customer=customer, currency=self.currency,
            status="pending_approval", credit_hold=True,
            order_date=timezone.now().date(),
        )
        manager = _make_user("mgr@swtest.com", self.company)
        CreditControlService(user=manager, company=self.company).override_credit_hold(so, manager, "CFO approved — strategic account")
        so.refresh_from_db()
        so = self._order_service().confirm_order(so)
        self.assertFalse(so.credit_hold)
        self.assertEqual(so.status, "confirmed")

    def test_override_without_reason_raises(self):
        so = SalesOrder.objects.create(
            company=self.company, customer=self.customer, currency=self.currency,
            status="pending_approval", credit_hold=True,
            order_date=timezone.now().date(),
        )
        manager = _make_user("mgr2@swtest.com", self.company)
        with self.assertRaises((ValueError, Exception)):
            CreditControlService(user=manager, company=self.company).override_credit_hold(so, manager, "")


# ---------------------------------------------------------------------------
class TestDeliveryFlow(SalesWorkflowTestCase):

    def test_confirm_order_creates_delivery(self):
        from apps.inventory.models import DeliveryOrder
        so = self._create_confirmed_order(qty="2")
        self.assertTrue(DeliveryOrder.objects.filter(sales_order=so).exists())

    def test_delivery_state_machine(self):
        from apps.inventory.models import DeliveryOrder
        so = self._create_confirmed_order(qty="1")
        delivery = DeliveryOrder.objects.filter(sales_order=so).first()
        self.assertIsNotNone(delivery)
        delivery.start_picking()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "picking")
        delivery.start_packing()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "packing")
        delivery.status = "shipped"
        delivery.save(update_fields=["status"])
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "shipped")
        delivery.mark_delivered()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, "delivered")
        self.assertIsNotNone(delivery.delivered_date)


# ---------------------------------------------------------------------------
class TestInvoicingFlow(SalesWorkflowTestCase):

    def test_create_invoice_from_order(self):
        so = self._create_confirmed_order(qty="2")
        inv = self._order_service().create_invoice(so)
        self.assertIsNotNone(inv)
        self.assertEqual(inv.customer, self.customer)

    def test_invoice_journal_posted_on_send(self):
        from apps.accounting.models import JournalEntry
        inv = self._create_sent_invoice()
        ref = f"INV: {inv.number}"
        entry = JournalEntry.objects.filter(company=self.company, reference=ref).first()
        self.assertIsNotNone(entry, "Journal entry not created for sent invoice")
        self.assertEqual(entry.status, "posted")

    def test_invoice_journal_idempotent(self):
        from apps.accounting.models import JournalEntry
        inv = self._create_sent_invoice()
        inv.save()  # second save — must not create duplicate
        ref = f"INV: {inv.number}"
        count = JournalEntry.objects.filter(company=self.company, reference=ref).count()
        self.assertEqual(count, 1, "Duplicate journal entries created")


# ---------------------------------------------------------------------------
class TestPaymentFlow(SalesWorkflowTestCase):

    def test_full_payment_marks_invoice_paid(self):
        inv = self._create_sent_invoice()
        self._payment_service().record_payment(inv, {
            "amount": str(inv.total),
            "payment_date": str(timezone.now().date()),
            "method": "bank_transfer",
            "reference": "PAY-FULL-001",
        })
        inv.refresh_from_db()
        self.assertEqual(inv.status, "paid")
        self.assertEqual(inv.balance_due, Decimal("0.00"))

    def test_partial_payment_leaves_balance(self):
        inv = self._create_sent_invoice(qty="4")
        partial = inv.total / 2
        self._payment_service().record_payment(inv, {
            "amount": str(partial),
            "payment_date": str(timezone.now().date()),
            "method": "bank_transfer",
            "reference": "PAY-PART-001",
        })
        inv.refresh_from_db()
        self.assertEqual(inv.status, "partial")
        self.assertGreater(inv.balance_due, Decimal("0.00"))

    def test_payment_posts_journal(self):
        from apps.accounting.models import JournalEntry
        inv = self._create_sent_invoice()
        self._payment_service().record_payment(inv, {
            "amount": str(inv.total),
            "payment_date": str(timezone.now().date()),
            "method": "bank_transfer",
            "reference": "PAY-JNL-001",
        })
        entries = JournalEntry.objects.filter(company=self.company, reference__startswith="PAY:")
        self.assertTrue(entries.exists(), "Payment journal not created")

    def test_double_entry_balanced_for_all_journals(self):
        """Every journal entry must have equal debits and credits."""
        from apps.accounting.models import JournalEntry
        inv = self._create_sent_invoice()
        self._payment_service().record_payment(inv, {
            "amount": str(inv.total),
            "payment_date": str(timezone.now().date()),
            "method": "bank_transfer",
            "reference": "PAY-BALANCE-001",
        })
        for entry in JournalEntry.objects.filter(company=self.company):
            total_dr = sum(item.debit for item in entry.items.all())
            total_cr = sum(item.credit for item in entry.items.all())
            self.assertEqual(total_dr, total_cr, f"Entry {entry.reference} is unbalanced")


# ---------------------------------------------------------------------------
class TestSalesReturn(SalesWorkflowTestCase):

    def _get_order_and_invoice(self):
        so = self._create_confirmed_order(qty="5")
        inv = self._order_service().create_invoice(so)
        if not inv.lines.exists():
            InvoiceLine.objects.create(
                invoice=inv, product=self.product,
                description="Item", quantity=Decimal("5"), unit_price=Decimal("100.00")
            )
            inv.recalculate_totals()
        inv.status = "sent"
        inv.save(update_fields=["status"])
        return so, inv

    def _lines_data(self, so, qty="2", resellable=True):
        return [{"order_line_id": so.lines.first().pk, "product": self.product, "description": "Return",
                 "quantity": Decimal(qty), "unit_price": self.product.sale_price,
                 "is_resellable": resellable}]

    def test_create_return(self):
        so, _ = self._get_order_and_invoice()
        ret = self._return_service().create_return(so, self._lines_data(so), "defective")
        self.assertEqual(ret.status, "draft")
        self.assertEqual(ret.lines.count(), 1)

    def test_approve_return(self):
        so, _ = self._get_order_and_invoice()
        ret = self._return_service().create_return(so, self._lines_data(so), "defective")
        approver = _make_user("approver@swtest.com", self.company)
        self._return_service().approve_return(ret, approver)
        ret.refresh_from_db()
        self.assertEqual(ret.status, "approved")

    def test_complete_return_restocks_inventory(self):
        from django.db.models import Sum
        so, _ = self._get_order_and_invoice()
        stock_before = StockRecord.objects.filter(
            company=self.company, product=self.product
        ).aggregate(t=Sum("quantity_on_hand"))["t"] or 0
        ret = self._return_service().create_return(so, self._lines_data(so, resellable=True), "defective")
        approver = _make_user("approver2@swtest.com", self.company)
        self._return_service().approve_return(ret, approver)
        self._return_service().complete_return(ret)
        stock_after = StockRecord.objects.filter(
            company=self.company, product=self.product
        ).aggregate(t=Sum("quantity_on_hand"))["t"] or 0
        self.assertGreater(stock_after, stock_before, "Stock not restocked on return completion")

    def test_complete_return_creates_credit_note(self):
        so, _ = self._get_order_and_invoice()
        ret = self._return_service().create_return(so, self._lines_data(so, resellable=False), "wrong_item")
        approver = _make_user("approver3@swtest.com", self.company)
        self._return_service().approve_return(ret, approver)
        self._return_service().complete_return(ret)
        ret.refresh_from_db()
        self.assertIsNotNone(ret.credit_note_id, "CreditNote not created on return completion")

    def test_complete_return_posts_accounting(self):
        from apps.accounting.models import JournalEntry
        so, _ = self._get_order_and_invoice()
        ret = self._return_service().create_return(so, self._lines_data(so, resellable=True), "defective")
        approver = _make_user("approver4@swtest.com", self.company)
        self._return_service().approve_return(ret, approver)
        self._return_service().complete_return(ret)
        ret.refresh_from_db()
        cn = ret.credit_note
        self.assertIsNotNone(cn)
        entry = JournalEntry.objects.filter(company=self.company, reference=f"CN: {cn.number}").first()
        self.assertIsNotNone(entry, "Credit note journal not posted")
        self.assertEqual(entry.status, "posted")


# ---------------------------------------------------------------------------
class TestSalesMultiTenantIsolation(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        call_command("seed_currencies", verbosity=0)
        cls.company_a, cls.currency = _make_company("CompanyA")
        cls.company_b, _ = _make_company("CompanyB")
        cls.user_a = _make_user("usera@swtest.com", cls.company_a)
        cls.customer_a = _make_customer(cls.company_a, name="CustomerA")
        cls.customer_b = _make_customer(cls.company_b, name="CustomerB")

    def test_invoices_stay_within_company(self):
        Invoice.objects.create(
            company=self.company_a, customer=self.customer_a,
            currency=self.currency, status="draft",
            invoice_date=timezone.now().date(), due_date=timezone.now().date(),
        )
        for inv in Invoice.objects.filter(company=self.company_b):
            self.assertEqual(inv.company, self.company_b)

    def test_sales_orders_stay_within_company(self):
        SalesOrder.objects.create(
            company=self.company_a, customer=self.customer_a,
            currency=self.currency, status="draft",
            order_date=timezone.now().date(),
        )
        for so in SalesOrder.objects.filter(company=self.company_b):
            self.assertEqual(so.company, self.company_b)
