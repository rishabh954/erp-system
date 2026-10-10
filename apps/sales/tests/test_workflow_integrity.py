from datetime import date
from decimal import Decimal

import pytest

from apps.company.models import CompanySettings
from apps.crm.models import Customer
from apps.inventory.models import DeliveryOrder, DeliveryOrderLine
from apps.sales.models import (
    CreditNote,
    Invoice,
    Payment,
    SalesCommission,
    SalesOrder,
    SalesOrderLine,
    SalesReturn,
    SalesReturnLine,
)
from apps.sales.services import SalesOrderService, SalesReturnService, SalesService

pytestmark = pytest.mark.django_db


@pytest.fixture
def sales_order(company, user, product):
    customer = Customer.objects.create(company=company, name="Workflow customer")
    order = SalesOrder.objects.create(
        company=company,
        customer=customer,
        sales_rep=user,
        order_date=date.today(),
        status=SalesOrder.Status.CONFIRMED,
    )
    SalesOrderLine.objects.create(
        sales_order=order,
        product=product,
        description="Workflow item",
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
    )
    order.recalculate_totals()
    return order


def test_invoice_creation_is_single_path_and_rejects_duplicates(sales_order, user, company):
    service = SalesOrderService(user=user, company=company)
    invoice = service.create_invoice(sales_order)

    assert invoice.sales_order_id == sales_order.pk
    assert invoice.lines.count() == 1
    with pytest.raises(ValueError, match="already invoiced|already exists"):
        SalesService(user=user, company=company).create_invoice_from_order(
            sales_order
        )


@pytest.mark.parametrize(
    "status",
    [SalesOrder.Status.DRAFT, SalesOrder.Status.CANCELLED],
)
def test_invoice_creation_rejects_draft_and_cancelled_orders(
    sales_order, user, company, status
):
    sales_order.status = status
    sales_order.save(update_fields=["status"])

    with pytest.raises(ValueError, match="cannot be invoiced"):
        SalesOrderService(user=user, company=company).create_invoice(sales_order)


def test_create_delivery_rejects_existing_open_delivery(
    sales_order, company, warehouse, user
):
    existing = DeliveryOrder.objects.create(
        company=company,
        sales_order=sales_order,
        warehouse=warehouse,
        status=DeliveryOrder.Status.PICKING,
    )
    DeliveryOrderLine.objects.create(
        delivery_order=existing,
        product=sales_order.lines.first().product,
        quantity_ordered=Decimal("4"),
    )

    with pytest.raises(ValueError, match="open delivery already exists"):
        SalesOrderService(user=user, company=company).create_delivery(sales_order)
    assert sales_order.delivery_orders.count() == 1


def test_create_delivery_uses_remaining_quantity(
    sales_order, company, user, warehouse
):
    line = sales_order.lines.first()
    line.qty_delivered = Decimal("4")
    line.save(update_fields=["qty_delivered"])

    delivery = SalesOrderService(user=user, company=company).create_delivery(
        sales_order
    )

    assert delivery.lines.get(product=line.product).quantity_ordered == Decimal("6")


def test_confirm_and_delivery_use_company_default_warehouse(
    company, user, product, warehouse
):
    from apps.inventory.models import StockRecord, Warehouse

    preferred = Warehouse.objects.create(
        company=company, name="Preferred Warehouse", code="PREFERRED"
    )
    CompanySettings.objects.create(
        company=company,
        key="default_warehouse",
        value=str(preferred.pk),
    )
    StockRecord.objects.create(
        company=company,
        product=product,
        warehouse=preferred,
        quantity_on_hand=Decimal("10"),
        quantity_reserved=Decimal("0"),
        average_cost=Decimal("50"),
    )
    customer = Customer.objects.create(company=company, name="Warehouse customer")
    order = SalesOrder.objects.create(
        company=company,
        customer=customer,
        order_date=date.today(),
    )
    SalesOrderLine.objects.create(
        sales_order=order,
        product=product,
        description="Reserved item",
        quantity=Decimal("2"),
        unit_price=Decimal("100"),
    )

    SalesOrderService(user=user, company=company).confirm_order(order)
    delivery = order.delivery_orders.get()

    assert delivery.warehouse_id == preferred.pk
    assert StockRecord.objects.get(
        product=product, warehouse=preferred
    ).quantity_reserved == Decimal("2")


def test_paid_invoice_commission_is_idempotent_and_reduced_by_credit_note(
    sales_order, company, user, currency
):
    CompanySettings.objects.create(
        company=company,
        key="sales_commission_rate",
        value="0.10",
    )
    invoice = SalesService(user=user, company=company).create_invoice_from_order(
        sales_order
    )
    first = Payment.objects.create(
        company=company,
        number="PAY-SPLIT-1",
        invoice=invoice,
        customer=invoice.customer,
        amount=Decimal("400"),
        currency=currency,
        payment_date=date.today(),
        method=Payment.Method.BANK_TRANSFER,
        status=Payment.Status.COMPLETED,
    )
    assert not SalesCommission.objects.filter(invoice=invoice).exists()

    final_payment = Payment.objects.create(
        company=company,
        number="PAY-SPLIT-2",
        invoice=invoice,
        customer=invoice.customer,
        amount=Decimal("600"),
        currency=currency,
        payment_date=date.today(),
        method=Payment.Method.BANK_TRANSFER,
        status=Payment.Status.COMPLETED,
    )
    commission = SalesCommission.objects.get(invoice=invoice, sales_rep=user)
    assert commission.amount == Decimal("100.00")

    final_payment.save()
    first.save()
    assert SalesCommission.objects.filter(invoice=invoice).count() == 1
    assert SalesCommission.objects.get(invoice=invoice).amount == Decimal("100.00")

    CreditNote.objects.create(
        company=company,
        customer=invoice.customer,
        invoice=invoice,
        status=CreditNote.Status.ISSUED,
        date=date.today(),
        amount=Decimal("200"),
        reason="Partial credit",
    )
    commission.refresh_from_db()
    assert commission.amount == Decimal("80.00")


def test_completed_return_reduces_paid_invoice_commission(
    sales_order, company, user, currency, warehouse
):
    invoice = SalesService(user=user, company=company).create_invoice_from_order(
        sales_order
    )
    Payment.objects.create(
        company=company,
        number="PAY-RETURN-1",
        invoice=invoice,
        customer=invoice.customer,
        amount=invoice.total,
        currency=currency,
        payment_date=date.today(),
        method=Payment.Method.BANK_TRANSFER,
        status=Payment.Status.COMPLETED,
    )
    commission = SalesCommission.objects.get(invoice=invoice, sales_rep=user)
    assert commission.amount == Decimal("50.00")

    return_record = SalesReturn.objects.create(
        company=company,
        sales_order=sales_order,
        customer=invoice.customer,
        warehouse=warehouse,
        status=SalesReturn.Status.APPROVED,
        return_date=date.today(),
        total_amount=Decimal("200"),
    )
    SalesReturnLine.objects.create(
        sales_return=return_record,
        order_line=sales_order.lines.first(),
        product=sales_order.lines.first().product,
        quantity=Decimal("2"),
        unit_price=Decimal("100"),
    )

    completed = SalesReturnService(user=user, company=company).complete_return(
        return_record
    )

    assert completed.credit_note.invoice_id == invoice.pk
    commission.refresh_from_db()
    assert commission.amount == Decimal("40.00")
