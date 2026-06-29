import pytest
from decimal import Decimal
from django.utils import timezone
from apps.sales.models import Quotation, QuotationLine, SalesOrder, SalesOrderLine, Invoice, Payment
from core.factories import CustomerFactory, ProductFactory

pytestmark = pytest.mark.django_db

def test_sales_happy_path(company, user, currency):
    """Test full happy path: Quotation -> SalesOrder -> Invoice -> Payment"""
    customer = CustomerFactory(company=company)
    product = ProductFactory(company=company, sale_price=Decimal('100.00'))

    # 1. Quotation
    quotation = Quotation.objects.create(
        company=company,
        customer=customer,
        status=Quotation.Status.DRAFT,
        validity_date=timezone.now().date(),
    )
    QuotationLine.objects.create(
        quotation=quotation,
        product=product,
        description=product.name,
        quantity=Decimal('2.00'),
        unit_price=Decimal('100.00')
    )
    quotation.recalculate_totals()
    
    assert quotation.subtotal == Decimal('200.00')
    assert quotation.total == Decimal('200.00')

    quotation.status = Quotation.Status.APPROVED
    quotation.save()

    # 2. Convert to SalesOrder
    so = SalesOrder.objects.create(
        company=company,
        quotation=quotation,
        customer=customer,
        order_date=timezone.now().date(),
        status=SalesOrder.Status.DRAFT
    )
    SalesOrderLine.objects.create(
        sales_order=so,
        product=product,
        description=product.name,
        quantity=Decimal('2.00'),
        unit_price=Decimal('100.00')
    )
    so.recalculate_totals()
    so.status = SalesOrder.Status.CONFIRMED
    so.save()

    assert so.total == Decimal('200.00')

    # 3. Create Invoice
    invoice = Invoice.objects.create(
        company=company,
        sales_order=so,
        customer=customer,
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        status=Invoice.Status.DRAFT
    )
    # The models handle the lines recalculation usually, but here we just manually create to simplify
    invoice.total = Decimal('200.00')
    invoice.balance_due = Decimal('200.00')
    invoice.status = Invoice.Status.SENT
    invoice.save()

    assert invoice.balance_due == Decimal('200.00')

    # 4. Create Payment
    payment = Payment.objects.create(
        company=company,
        invoice=invoice,
        customer=customer,
        amount=Decimal('200.00'),
        currency=currency,
        payment_date=timezone.now().date(),
        method=Payment.Method.BANK_TRANSFER,
        status=Payment.Status.COMPLETED
    )
    
    invoice.refresh_from_db()
    
    assert invoice.amount_paid == Decimal('200.00')
    assert invoice.balance_due == Decimal('0.00')

def test_sales_payment_fails_if_negative_amount(company, user, currency):
    """Test failure case where payment amount is invalid (negative)."""
    from django.core.exceptions import ValidationError
    customer = CustomerFactory(company=company)
    
    invoice = Invoice.objects.create(
        company=company,
        customer=customer,
        number='INV-TEST-001',
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        status=Invoice.Status.SENT,
        total=Decimal('100.00'),
        balance_due=Decimal('100.00')
    )
    
    payment = Payment(
        company=company,
        invoice=invoice,
        customer=customer,
        amount=Decimal('-50.00'),
        currency=currency,
        payment_date=timezone.now().date(),
        method=Payment.Method.CASH,
        status=Payment.Status.PENDING
    )
    
    with pytest.raises(ValidationError):
        payment.full_clean()

    invoice = Invoice.objects.create(
        company=company,
        customer=customer,
        number='INV-TEST-002',
        invoice_date=timezone.now().date(),
        due_date=timezone.now().date(),
        status=Invoice.Status.DRAFT,
        total=Decimal('100.00'),
        balance_due=Decimal('100.00'),
    )

    from apps.sales.services import PaymentService
    service = PaymentService(user=user, company=company)
    with pytest.raises(ValueError):
        service.record_payment(invoice, {'amount': '-50.00', 'payment_date': timezone.now().date(), 'method': 'bank_transfer'})

def test_quotation_service_create(company, user):
    customer = CustomerFactory(company=company)
    product = ProductFactory(company=company)
    
    from apps.sales.services import QuotationService
    from django.http import QueryDict
    
    data = QueryDict(mutable=True)
    data.update({
        'customer': customer.id,
        'payment_terms': '15',
    })
    data.setlist('product[]', [product.id])
    data.setlist('description[]', [product.name])
    data.setlist('quantity[]', ['2'])
    data.setlist('unit_price[]', ['100.00'])
    data.setlist('discount_percent[]', ['0'])
    data.setlist('tax[]', [''])
    
    service = QuotationService(user=user, company=company)
    quot = service.create_quotation(data, user)
    
    assert quot.customer == customer
    assert quot.payment_terms == 15
    assert quot.lines.count() == 1
    assert quot.total == Decimal('200.00')

def test_sales_order_service_create_and_invoice(company, user):
    customer = CustomerFactory(company=company)
    product = ProductFactory(company=company)
    
    from apps.sales.services import SalesOrderService
    from django.http import QueryDict
    
    data = QueryDict(mutable=True)
    data.update({
        'customer': customer.id,
        'payment_terms': '30',
    })
    data.setlist('product[]', [product.id])
    data.setlist('description[]', [product.name])
    data.setlist('quantity[]', ['5'])
    data.setlist('unit_price[]', ['10.00'])
    data.setlist('discount_percent[]', ['0'])
    data.setlist('tax[]', [''])
    
    service = SalesOrderService(user=user, company=company)
    so = service.create_order(data, user)
    
    assert so.customer == customer
    assert so.lines.count() == 1
    assert so.total == Decimal('50.00')
    
    inv = service.create_invoice(so)
    assert inv.customer == customer
    assert inv.sales_order == so
    assert inv.total == Decimal('50.00')
    assert inv.lines.count() == 1
    assert so.status == so.Status.INVOICED
