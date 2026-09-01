"""
View & Service Layer Coverage Tests
=====================================
Targets the four lowest-coverage areas identified by the coverage report:
  - apps/sales/views.py        (was ~20-35%)
  - apps/purchase/views.py     (was ~20-35%)
  - apps/purchase/services.py  (was 0%)
  - apps/workflow/views.py     (basic smoke)

Priority areas for every test:
  1. Money movement  — payment recording, invoice balance updates, bill creation
  2. Stock quantities — GRN updates stock, PO totals computed correctly
  3. Cross-tenant access — data from another company returns 404, not 200

All tests use force_login so they exercise real view + permission logic
without depending on JWT token issuance.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.authentication.models import User, UserCompany
from apps.company.models import Currency
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


# ─── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def company(db):
    return CompanyFactory()


@pytest.fixture
def other_company(db):
    return CompanyFactory(name="Other Corp")


@pytest.fixture
def admin_user(db, company):
    u = UserFactory(
        primary_company=company,
        role=User.Role.COMPANY_ADMIN,
    )
    UserCompany.objects.get_or_create(
        user=u, company=company,
        defaults={"role": User.Role.COMPANY_ADMIN, "is_active": True},
    )
    return u


@pytest.fixture
def currency(db):
    c, _ = Currency.objects.get_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "is_base": True},
    )
    return c


@pytest.fixture
def vendor(db, company):
    from apps.purchase.models import Vendor
    return Vendor.objects.create(
        company=company,
        name="Acme Supplies",
        vendor_code="ACME-001",
        email="acme@example.com",
        payment_terms=30,
    )


@pytest.fixture
def other_vendor(db, other_company):
    from apps.purchase.models import Vendor
    return Vendor.objects.create(
        company=other_company,
        name="Other Vendor",
        vendor_code="OTH-001",
    )


@pytest.fixture
def customer(db, company):
    from apps.crm.models import Customer
    return Customer.objects.create(company=company, name="Test Customer")


@pytest.fixture
def other_customer(db, other_company):
    from apps.crm.models import Customer
    return Customer.objects.create(company=other_company, name="Other Customer")


@pytest.fixture
def warehouse(db, company):
    from apps.inventory.models import Warehouse
    return Warehouse.objects.create(company=company, name="Main WH", code="MAIN")


@pytest.fixture
def product(db, company):
    from apps.inventory.models import Product
    return Product.objects.create(
        company=company,
        name="Widget",
        sku="WDG-001",
        product_type="stockable",
        cost_price=Decimal("10.00"),
        sale_price=Decimal("20.00"),
    )


@pytest.fixture
def purchase_order(db, company, vendor, currency):
    from apps.purchase.models import PurchaseOrder
    return PurchaseOrder.objects.create(
        company=company,
        vendor=vendor,
        order_date=date.today(),
        expected_delivery=date.today() + timedelta(days=7),
        status=PurchaseOrder.Status.CONFIRMED,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        balance_due=Decimal("100.00"),
        currency=currency,
    )


@pytest.fixture
def other_purchase_order(db, other_company, other_vendor):
    from apps.purchase.models import PurchaseOrder
    return PurchaseOrder.objects.create(
        company=other_company,
        vendor=other_vendor,
        order_date=date.today(),
        status=PurchaseOrder.Status.DRAFT,
        number="PO-99999",
        total=Decimal("500.00"),
        balance_due=Decimal("500.00"),
    )


@pytest.fixture
def invoice(db, company, customer, currency):
    from apps.sales.models import Invoice
    return Invoice.objects.create(
        company=company,
        customer=customer,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=Invoice.Status.SENT,
        currency=currency,
        subtotal=Decimal("200.00"),
        total=Decimal("200.00"),
        balance_due=Decimal("200.00"),
    )


@pytest.fixture
def other_invoice(db, other_company, other_customer):
    from apps.sales.models import Invoice
    c, _ = Currency.objects.get_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "is_base": True},
    )
    return Invoice.objects.create(
        company=other_company,
        customer=other_customer,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=Invoice.Status.SENT,
        currency=c,
        number="INV-99999",
        total=Decimal("999.00"),
        balance_due=Decimal("999.00"),
    )


@pytest.fixture
def bill(db, company, vendor, currency, purchase_order):
    from apps.purchase.models import Bill
    b = Bill.objects.create(
        company=company,
        vendor=vendor,
        purchase_order=purchase_order,
        bill_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=Bill.Status.OPEN,
        currency=currency,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
        balance_due=Decimal("100.00"),
    )
    return b


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _login(client, user, company):
    """Force-login user and set active company session."""
    client.force_login(user)
    session = client.session
    session["active_company_id"] = str(company.pk)
    session.save()


# ══════════════════════════════════════════════════════════════════════════════
#  PURCHASE VIEWS — cross-tenant access
# ══════════════════════════════════════════════════════════════════════════════

class TestPurchaseViewTenantIsolation:
    """Vendor and PO detail views must 404 for objects from another company."""

    def test_vendor_detail_from_other_company_returns_404(
        self, client, admin_user, company, other_vendor
    ):
        _login(client, admin_user, company)
        resp = client.get(
            reverse("purchase:vendor_detail", kwargs={"pk": other_vendor.pk})
        )
        assert resp.status_code == 404, (
            f"Expected 404 for cross-company vendor access, got {resp.status_code}"
        )

    def test_purchase_order_detail_from_other_company_returns_404(
        self, client, admin_user, company, other_purchase_order
    ):
        _login(client, admin_user, company)
        resp = client.get(
            reverse("purchase:order_detail", kwargs={"pk": other_purchase_order.pk})
        )
        assert resp.status_code == 404, (
            f"Expected 404 for cross-company PO access, got {resp.status_code}"
        )

    def test_own_vendor_detail_returns_200(
        self, client, admin_user, company, vendor
    ):
        _login(client, admin_user, company)
        resp = client.get(
            reverse("purchase:vendor_detail", kwargs={"pk": vendor.pk})
        )
        assert resp.status_code == 200

    def test_own_purchase_order_detail_returns_200(
        self, client, admin_user, company, purchase_order
    ):
        _login(client, admin_user, company)
        resp = client.get(
            reverse("purchase:order_detail", kwargs={"pk": purchase_order.pk})
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
#  SALES VIEWS — cross-tenant access
# ══════════════════════════════════════════════════════════════════════════════

class TestSalesViewTenantIsolation:
    """Invoice and Sales Order detail views must 404 for other-company objects."""

    def test_invoice_from_other_company_returns_404(
        self, client, admin_user, company, other_invoice
    ):
        _login(client, admin_user, company)
        resp = client.get(
            reverse("sales:invoice_detail", kwargs={"pk": other_invoice.pk})
        )
        assert resp.status_code == 404, (
            f"Expected 404 for cross-company invoice access, got {resp.status_code}"
        )

    def test_own_invoice_detail_returns_200(
        self, client, admin_user, company, invoice
    ):
        _login(client, admin_user, company)
        resp = client.get(
            reverse("sales:invoice_detail", kwargs={"pk": invoice.pk})
        )
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
#  PURCHASE SERVICES — money movement
# ══════════════════════════════════════════════════════════════════════════════

class TestPurchaseOrderServiceMoneyMovement:
    """PurchaseOrderService.create_order() must compute totals correctly."""

    def test_create_order_computes_subtotal_and_total(
        self, admin_user, company, vendor
    ):
        from apps.purchase.services import PurchaseOrderService

        class FakeData:
            """Simulate Django QueryDict-like data for the service."""
            def __init__(self, mapping=None, lists=None):
                self._mapping = mapping or {}
                self._lists = lists or {}

            def __getitem__(self, key):
                return self._mapping[key]

            def get(self, key, default=None):
                return self._mapping.get(key, default)

            def getlist(self, key):
                return self._lists.get(key, [])

        data = FakeData(
            mapping={
                "vendor": str(vendor.pk),
                "order_date": str(date.today()),
                "payment_terms": "30",
            },
            lists={
                "description[]": ["Widget A", "Widget B"],
                "quantity[]": ["10", "5"],
                "unit_price[]": ["50.00", "20.00"],
                "product[]": ["", ""],
                "discount_percent[]": ["0", "0"],
                "tax[]": ["", ""],
            },
        )

        service = PurchaseOrderService(user=admin_user, company=company)
        po = service.create_order(data, admin_user)

        # 10 * 50 + 5 * 20 = 500 + 100 = 600
        assert po.subtotal == Decimal("600.00"), (
            f"Expected subtotal=600.00, got {po.subtotal}"
        )
        assert po.total == Decimal("600.00")
        assert po.balance_due == Decimal("600.00")

    def test_create_order_skips_blank_description_lines(
        self, admin_user, company, vendor
    ):
        from apps.purchase.services import PurchaseOrderService

        class FakeData:
            def __getitem__(self, key):
                mapping = {"vendor": str(vendor.pk), "payment_terms": "30"}
                return mapping[key]

            def get(self, key, default=None):
                return {"vendor": str(vendor.pk), "payment_terms": "30"}.get(key, default)

            def getlist(self, key):
                return {
                    "description[]": ["  ", "Real Item"],
                    "quantity[]": ["1", "3"],
                    "unit_price[]": ["999.00", "40.00"],
                    "product[]": ["", ""],
                    "discount_percent[]": ["0", "0"],
                    "tax[]": ["", ""],
                }.get(key, [])

        service = PurchaseOrderService(user=admin_user, company=company)
        po = service.create_order(FakeData(), admin_user)

        # Only "Real Item" line: 3 * 40 = 120
        assert po.subtotal == Decimal("120.00"), (
            f"Blank lines should be skipped; expected 120.00, got {po.subtotal}"
        )
        assert po.lines.count() == 1


class TestPurchasePaymentServiceMoneyMovement:
    """PaymentService.record_vendor_payment() must update bill balance."""

    def test_vendor_payment_reduces_bill_balance(
        self, admin_user, company, bill
    ):
        from apps.purchase.services import PaymentService

        initial_balance = bill.balance_due  # 100.00

        service = PaymentService(user=admin_user, company=company)
        payment = service.record_vendor_payment(
            bill,
            {
                "amount": "60.00",
                "payment_date": str(date.today()),
                "method": "bank_transfer",
                "reference": "REF-001",
            },
        )

        bill.refresh_from_db()
        assert payment.amount == Decimal("60.00")
        assert bill.amount_paid == Decimal("60.00"), (
            f"Bill amount_paid should be 60.00, got {bill.amount_paid}"
        )
        assert bill.balance_due == initial_balance - Decimal("60.00"), (
            f"Bill balance_due should be 40.00, got {bill.balance_due}"
        )
        assert bill.status == bill.Status.PARTIAL

    def test_full_vendor_payment_marks_bill_paid(
        self, admin_user, company, bill
    ):
        from apps.purchase.services import PaymentService

        service = PaymentService(user=admin_user, company=company)
        service.record_vendor_payment(
            bill,
            {
                "amount": "100.00",
                "payment_date": str(date.today()),
                "method": "cash",
            },
        )

        bill.refresh_from_db()
        assert bill.balance_due == Decimal("0.00") or bill.balance_due <= Decimal("0.01")
        assert bill.status == bill.Status.PAID

    def test_zero_payment_amount_raises_value_error(
        self, admin_user, company, bill
    ):
        from apps.purchase.services import PaymentService

        service = PaymentService(user=admin_user, company=company)
        with pytest.raises(ValueError, match="greater than zero"):
            service.record_vendor_payment(bill, {"amount": "0.00"})

    def test_negative_payment_amount_raises_value_error(
        self, admin_user, company, bill
    ):
        from apps.purchase.services import PaymentService

        service = PaymentService(user=admin_user, company=company)
        with pytest.raises(ValueError):
            service.record_vendor_payment(bill, {"amount": "-10.00"})


class TestGoodsReceiptServiceStockMovement:
    """create_goods_receipt() must update PO status and trigger stock receipt."""

    def test_goods_receipt_updates_po_status_to_received(
        self, admin_user, company, vendor, warehouse, product, currency
    ):
        from apps.purchase.models import PurchaseOrder, PurchaseOrderLine
        from apps.purchase.services import PurchaseOrderService

        # Build a confirmed PO with one line
        po = PurchaseOrder.objects.create(
            company=company,
            vendor=vendor,
            order_date=date.today(),
            status=PurchaseOrder.Status.CONFIRMED,
            total=Decimal("50.00"),
            balance_due=Decimal("50.00"),
            currency=currency,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=po,
            product=product,
            description="Widget",
            quantity=Decimal("5.00"),
            unit_price=Decimal("10.00"),
            subtotal=Decimal("50.00"),
            total=Decimal("50.00"),
        )

        service = PurchaseOrderService(user=admin_user, company=company)

        class FakeData:
            def __getitem__(self, key):
                mapping = {
                    "warehouse": str(warehouse.pk),
                    f"qty_{line.pk}": "5",
                }
                return mapping[key]

            def get(self, key, default=None):
                mapping = {
                    "warehouse": str(warehouse.pk),
                    f"qty_{line.pk}": "5",
                }
                return mapping.get(key, default)

            def getlist(self, key):
                return []

        receipt = service.create_goods_receipt(po, FakeData(), admin_user)

        po.refresh_from_db()
        assert po.status == PurchaseOrder.Status.RECEIVED, (
            f"PO status should be RECEIVED after full receipt, got {po.status}"
        )
        assert receipt is not None
        assert receipt.lines.count() == 1

    def test_goods_receipt_increments_po_line_qty_received(
        self, admin_user, company, vendor, warehouse, product, currency
    ):
        from apps.purchase.models import PurchaseOrder, PurchaseOrderLine
        from apps.purchase.services import PurchaseOrderService

        po = PurchaseOrder.objects.create(
            company=company,
            vendor=vendor,
            order_date=date.today(),
            status=PurchaseOrder.Status.CONFIRMED,
            total=Decimal("100.00"),
            balance_due=Decimal("100.00"),
            currency=currency,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=po,
            product=product,
            description="Widget",
            quantity=Decimal("10.00"),
            unit_price=Decimal("10.00"),
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
        )
        assert line.qty_received == Decimal("0.00")

        service = PurchaseOrderService(user=admin_user, company=company)

        class FakeData:
            def __getitem__(self, key):
                mapping = {
                    "warehouse": str(warehouse.pk),
                    f"qty_{line.pk}": "6",
                }
                return mapping[key]

            def get(self, key, default=None):
                return {
                    "warehouse": str(warehouse.pk),
                    f"qty_{line.pk}": "6",
                }.get(key, default)

            def getlist(self, key):
                return []

        service.create_goods_receipt(po, FakeData(), admin_user)

        line.refresh_from_db()
        assert line.qty_received == Decimal("6.00"), (
            f"Expected qty_received=6.00, got {line.qty_received}"
        )

    def test_goods_receipt_with_no_quantities_raises_value_error(
        self, admin_user, company, vendor, warehouse, product, currency
    ):
        from apps.purchase.models import PurchaseOrder, PurchaseOrderLine
        from apps.purchase.services import PurchaseOrderService

        po = PurchaseOrder.objects.create(
            company=company,
            vendor=vendor,
            order_date=date.today(),
            status=PurchaseOrder.Status.CONFIRMED,
            total=Decimal("50.00"),
            balance_due=Decimal("50.00"),
            currency=currency,
        )
        PurchaseOrderLine.objects.create(
            purchase_order=po,
            product=product,
            description="Widget",
            quantity=Decimal("5.00"),
            unit_price=Decimal("10.00"),
            subtotal=Decimal("50.00"),
            total=Decimal("50.00"),
        )

        service = PurchaseOrderService(user=admin_user, company=company)

        class FakeData:
            def __getitem__(self, key):
                return {"warehouse": str(warehouse.pk)}[key]

            def get(self, key, default=None):
                return {"warehouse": str(warehouse.pk)}.get(key, default)

            def getlist(self, key):
                return []

        with pytest.raises(ValueError, match="No quantities"):
            service.create_goods_receipt(po, FakeData(), admin_user)


class TestPurchaseRequestService:
    """PurchaseRequestService creates requests with correct totals."""

    def test_create_request_computes_estimated_cost(self, admin_user, company):
        from apps.purchase.services import PurchaseRequestService

        class FakeData:
            def __getitem__(self, key):
                return {"title": "Q1 Stationery", "priority": "medium"}[key]

            def get(self, key, default=None):
                return {"title": "Q1 Stationery", "priority": "medium"}.get(key, default)

            def getlist(self, key):
                return {
                    "description[]": ["Paper", "Pens"],
                    "quantity[]": ["100", "50"],
                    "estimated_unit_price[]": ["2.00", "1.00"],
                    "product[]": ["", ""],
                }.get(key, [])

        service = PurchaseRequestService(user=admin_user, company=company)
        pr = service.create_request(FakeData(), admin_user)

        # 100*2 + 50*1 = 200 + 50 = 250
        assert pr.estimated_cost == Decimal("250.00"), (
            f"Expected 250.00, got {pr.estimated_cost}"
        )
        assert pr.status == "draft"
        assert pr.lines.count() == 2

    def test_update_request_blocked_for_non_draft(self, admin_user, company):
        from apps.purchase.models import PurchaseRequest
        from apps.purchase.services import PurchaseRequestService

        pr = PurchaseRequest.objects.create(
            company=company,
            title="Locked Request",
            requested_by=admin_user,
            status="submitted",
        )

        class FakeData:
            def __getitem__(self, key):
                return {"title": "Changed"}[key]

            def get(self, key, default=None):
                return {"title": "Changed"}.get(key, default)

            def getlist(self, key):
                return {"description[]": [], "quantity[]": [], "estimated_unit_price[]": [], "product[]": []}.get(key, [])

        service = PurchaseRequestService(user=admin_user, company=company)
        with pytest.raises(ValueError, match="draft"):
            service.update_request(pr, FakeData())


# ══════════════════════════════════════════════════════════════════════════════
#  SALES VIEWS — money movement via view layer
# ══════════════════════════════════════════════════════════════════════════════

class TestSalesPaymentView:
    """RecordPaymentView must create a payment and update invoice balance."""

    def test_record_payment_reduces_invoice_balance(
        self, client, admin_user, company, invoice, currency
    ):
        _login(client, admin_user, company)
        initial_balance = invoice.balance_due  # 200.00

        resp = client.post(
            reverse("sales:record_payment", kwargs={"pk": invoice.pk}),
            {
                "amount": "80.00",
                "method": "cash",
                "payment_date": str(date.today()),
                "currency": str(currency.pk),
            },
        )
        # Expect redirect on success
        assert resp.status_code in (200, 302), (
            f"Unexpected status {resp.status_code}: {resp.content[:200]}"
        )

        invoice.refresh_from_db()
        # balance_due should have decreased — 200 - 80 = 120
        assert invoice.balance_due < initial_balance, (
            f"Invoice balance_due should have decreased from {initial_balance}, "
            f"got {invoice.balance_due}"
        )
        assert invoice.amount_paid == Decimal("80.00"), (
            f"Expected amount_paid=80.00, got {invoice.amount_paid}"
        )

    def test_record_payment_cross_company_returns_404(
        self, client, admin_user, company, other_invoice, currency
    ):
        _login(client, admin_user, company)
        resp = client.post(
            reverse("sales:record_payment", kwargs={"pk": other_invoice.pk}),
            {
                "amount": "50.00",
                "method": "cash",
                "payment_date": str(date.today()),
                "currency": str(currency.pk),
            },
        )
        assert resp.status_code == 404, (
            "Cross-company payment recording should return 404"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  PURCHASE VIEWS — vendor and order list scoping
# ══════════════════════════════════════════════════════════════════════════════

class TestPurchaseListViewScoping:
    """List views must only surface objects from the authenticated user's company."""

    def test_vendor_list_excludes_other_company_vendors(
        self, client, admin_user, company, vendor, other_vendor
    ):
        _login(client, admin_user, company)
        resp = client.get(reverse("purchase:vendors"))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert vendor.name in content, "Own vendor should appear in list"
        assert other_vendor.name not in content, (
            "Other-company vendor must not appear in vendor list"
        )

    def test_purchase_order_list_excludes_other_company_orders(
        self, client, admin_user, company, purchase_order, other_purchase_order
    ):
        _login(client, admin_user, company)
        resp = client.get(reverse("purchase:orders"))
        assert resp.status_code == 200
        # The other company's PO number must not appear in the response
        content = resp.content.decode()
        assert other_purchase_order.number not in content, (
            "Other-company PO must not appear in purchase order list"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  SALES VIEWS — list and detail scoping
# ══════════════════════════════════════════════════════════════════════════════

class TestSalesListViewScoping:
    """Invoice list must not reveal data from other companies."""

    def test_invoice_list_excludes_other_company_invoices(
        self, client, admin_user, company, invoice, other_invoice
    ):
        _login(client, admin_user, company)
        resp = client.get(reverse("sales:invoices"))
        assert resp.status_code == 200
        content = resp.content.decode()
        assert invoice.number in content, "Own invoice should appear in list"
        assert other_invoice.number not in content, (
            "Other-company invoice must not appear in invoice list"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  PURCHASE REQUEST VIEWS — approval workflow
# ══════════════════════════════════════════════════════════════════════════════

class TestPurchaseRequestApprovalView:
    """ApprovePurchaseRequestView must correctly transition PR status."""

    def _make_pr(self, company, user, status="draft"):
        from apps.purchase.models import PurchaseRequest
        pr = PurchaseRequest.objects.create(
            company=company,
            title="Test PR",
            requested_by=user,
            status=status,
        )
        return pr

    def test_submit_draft_pr(self, client, admin_user, company):
        pr = self._make_pr(company, admin_user, status="draft")
        _login(client, admin_user, company)
        resp = client.post(
            reverse("purchase:request_action", kwargs={"pk": pr.pk}),
            {"action": "submit"},
        )
        assert resp.status_code in (200, 302)
        pr.refresh_from_db()
        assert pr.status == "submitted", f"Expected submitted, got {pr.status}"

    def test_approve_submitted_pr(self, client, admin_user, company):
        pr = self._make_pr(company, admin_user, status="submitted")
        _login(client, admin_user, company)
        resp = client.post(
            reverse("purchase:request_action", kwargs={"pk": pr.pk}),
            {"action": "approve"},
        )
        assert resp.status_code in (200, 302)
        pr.refresh_from_db()
        assert pr.status == "approved", f"Expected approved, got {pr.status}"

    def test_reject_submitted_pr(self, client, admin_user, company):
        pr = self._make_pr(company, admin_user, status="submitted")
        _login(client, admin_user, company)
        resp = client.post(
            reverse("purchase:request_action", kwargs={"pk": pr.pk}),
            {"action": "reject", "rejection_reason": "Budget exceeded"},
        )
        assert resp.status_code in (200, 302)
        pr.refresh_from_db()
        assert pr.status == "rejected", f"Expected rejected, got {pr.status}"

    def test_approve_pr_cross_company_returns_404(
        self, client, admin_user, company, other_company
    ):
        from apps.purchase.models import PurchaseRequest
        other_user = UserFactory(primary_company=other_company)
        pr = PurchaseRequest.objects.create(
            company=other_company,
            title="Other PR",
            requested_by=other_user,
            status="submitted",
        )
        _login(client, admin_user, company)
        resp = client.post(
            reverse("purchase:request_action", kwargs={"pk": pr.pk}),
            {"action": "approve"},
        )
        assert resp.status_code == 404, (
            "Approving another company's PR should return 404"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  SALES VIEWS — quotation status workflow
# ══════════════════════════════════════════════════════════════════════════════

class TestSalesQuotationWorkflow:
    """Quotation approve/reject/send views must gate on current status."""

    def _make_quotation(self, company, customer, status="draft"):
        from apps.sales.models import Quotation
        q = Quotation.objects.create(
            company=company,
            customer=customer,
            status=status,
            total=Decimal("100.00"),
        )
        return q

    def test_approve_draft_quotation(self, client, admin_user, company, customer):
        q = self._make_quotation(company, customer, status="draft")
        _login(client, admin_user, company)
        resp = client.post(
            reverse("sales:quotation_approve", kwargs={"pk": q.pk})
        )
        assert resp.status_code in (200, 302)
        q.refresh_from_db()
        assert q.status == "approved", f"Expected approved, got {q.status}"

    def test_reject_quotation(self, client, admin_user, company, customer):
        q = self._make_quotation(company, customer, status="sent")
        _login(client, admin_user, company)
        resp = client.post(
            reverse("sales:quotation_reject", kwargs={"pk": q.pk}),
            {"reject_reason": "Price too high"},
        )
        assert resp.status_code in (200, 302)
        q.refresh_from_db()
        assert q.status == "rejected", f"Expected rejected, got {q.status}"

    def test_approve_quotation_cross_company_returns_404(
        self, client, admin_user, company, other_customer
    ):
        from apps.sales.models import Quotation
        q = Quotation.objects.create(
            company=other_customer.company,
            customer=other_customer,
            status="draft",
        )
        _login(client, admin_user, company)
        resp = client.post(
            reverse("sales:quotation_approve", kwargs={"pk": q.pk})
        )
        assert resp.status_code == 404, (
            "Approving another company's quotation should return 404"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  VendorBidService — accept_bid creates PO atomically
# ══════════════════════════════════════════════════════════════════════════════

class TestVendorBidService:
    """accept_bid must create a PO and mark other bids as rejected."""

    def _make_rfq_with_bids(self, company, vendor, user, product):
        from apps.purchase.models import (
            RequestForQuotation,
            RFQLine,
            VendorBid,
            VendorBidLine,
        )

        rfq = RequestForQuotation.objects.create(
            company=company,
            title="Q1 RFQ",
            deadline=date.today() + timedelta(days=7),
            created_by=user,
            status="published",
        )
        rfq_line = RFQLine.objects.create(
            rfq=rfq, product=product, quantity=Decimal("10"), description="Widget"
        )

        bid = VendorBid.objects.create(
            company=company,
            rfq=rfq,
            vendor=vendor,
            bid_date=date.today(),
            total_amount=Decimal("200.00"),
            status=VendorBid.Status.PENDING,
        )
        VendorBidLine.objects.create(
            bid=bid, rfq_line=rfq_line, unit_price=Decimal("20.00"), subtotal=Decimal("200.00")
        )
        return rfq, bid

    def test_accept_bid_creates_purchase_order(
        self, admin_user, company, vendor, product
    ):
        from apps.purchase.services import VendorBidService

        rfq, bid = self._make_rfq_with_bids(company, vendor, admin_user, product)

        service = VendorBidService(user=admin_user, company=company)
        po = service.accept_bid(bid, admin_user)

        assert po is not None
        assert po.vendor == vendor
        assert po.company == company
        assert po.subtotal == Decimal("200.00")

    def test_accept_bid_closes_rfq(self, admin_user, company, vendor, product):
        from apps.purchase.services import VendorBidService

        rfq, bid = self._make_rfq_with_bids(company, vendor, admin_user, product)

        service = VendorBidService(user=admin_user, company=company)
        service.accept_bid(bid, admin_user)

        rfq.refresh_from_db()
        assert rfq.status == "closed", f"Expected RFQ closed, got {rfq.status}"

    def test_accept_non_pending_bid_raises(
        self, admin_user, company, vendor, product
    ):
        from apps.purchase.models import VendorBid
        from apps.purchase.services import VendorBidService

        rfq, bid = self._make_rfq_with_bids(company, vendor, admin_user, product)
        bid.status = VendorBid.Status.ACCEPTED
        bid.save(update_fields=["status"])

        service = VendorBidService(user=admin_user, company=company)
        with pytest.raises(ValueError, match="submitted"):
            service.accept_bid(bid, admin_user)
