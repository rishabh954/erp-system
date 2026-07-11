from datetime import date
from decimal import Decimal

import pytest

from apps.crm.models import Customer
from apps.sales.models import (
    Invoice,
    InvoiceLine,
    Payment,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def customer(company):
    return Customer.objects.create(
        company=company, name="Flow Test Customer", email="flow@test.com"
    )


def test_sales_flow(client, user, company, customer, product, tax, currency):
    client.force_login(user)

    # 1. Create Quote
    quote = Quotation.objects.create(
        company=company,
        customer=customer,
        validity_date=date.today(),
        status=Quotation.Status.DRAFT,
    )
    QuotationLine.objects.create(
        quotation=quote,
        product=product,
        description=product.name,
        quantity=Decimal("2.0000"),
        unit_price=product.sale_price,
        tax=tax,
    )
    quote.recalculate_totals()
    assert quote.total == Decimal("220.00")

    # Convert to Order
    quote.status = Quotation.Status.APPROVED
    quote.save()

    order = SalesOrder.objects.create(
        company=company,
        quotation=quote,
        customer=customer,
        order_date=date.today(),
        status=SalesOrder.Status.CONFIRMED,
    )
    SalesOrderLine.objects.create(
        sales_order=order,
        product=product,
        description=product.name,
        quantity=Decimal("2.0000"),
        unit_price=product.sale_price,
        tax=tax,
    )
    order.recalculate_totals()
    quote.status = Quotation.Status.CONVERTED
    quote.save()

    assert order.total == Decimal("220.00")

    # Create Invoice from Order
    invoice = Invoice.objects.create(
        company=company,
        sales_order=order,
        customer=customer,
        invoice_date=date.today(),
        due_date=date.today(),
        status=Invoice.Status.DRAFT,
    )
    InvoiceLine.objects.create(
        invoice=invoice,
        product=product,
        description=product.name,
        quantity=Decimal("2.0000"),
        unit_price=product.sale_price,
        tax=tax,
    )
    invoice.recalculate_totals()
    invoice.status = Invoice.Status.SENT
    invoice.save()

    assert invoice.balance_due == Decimal("220.00")

    # Register Payment
    Payment.objects.create(
        company=company,
        invoice=invoice,
        customer=customer,
        amount=Decimal("220.00"),
        currency=currency,
        payment_date=date.today(),
        method=Payment.Method.BANK_TRANSFER,
        status=Payment.Status.COMPLETED,
    )

    invoice.refresh_from_db()
    assert invoice.balance_due == Decimal("0.00")
    assert invoice.status == Invoice.Status.PAID

    order.refresh_from_db()
    assert order.status == SalesOrder.Status.COMPLETED
