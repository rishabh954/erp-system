import logging
from django.db import transaction
from django.utils import timezone
from core.services import BaseService
from apps.sales.models import Quotation, SalesOrder, SalesOrderLine, Invoice, InvoiceLine, Payment
from apps.company.models import Currency

logger = logging.getLogger(__name__)

class SalesService(BaseService):
    
    @transaction.atomic
    def convert_quote_to_order(self, quotation: Quotation) -> SalesOrder:
        """Convert an approved Quotation into a Sales Order."""
        if quotation.status == Quotation.Status.CONVERTED:
            raise ValueError("Quotation is already converted.")
        if quotation.status != Quotation.Status.APPROVED:
            raise ValueError("Only approved quotations can be converted.")

        # Create Sales Order
        order = SalesOrder.objects.create(
            company=quotation.company,
            branch=quotation.branch,
            quotation=quotation,
            customer=quotation.customer,
            order_date=timezone.now().date(),
            delivery_date=quotation.delivery_date,
            payment_terms=quotation.payment_terms,
            currency=quotation.currency,
            exchange_rate=quotation.exchange_rate,
            sales_rep=quotation.sales_rep,
            shipping_address=quotation.customer.address_line1 or '',
            notes=quotation.notes,
            terms_conditions=quotation.terms_conditions,
        )

        # Create Sales Order Lines
        for line in quotation.lines.all():
            SalesOrderLine.objects.create(
                sales_order=order,
                product=line.product,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax=line.tax,
                subtotal=line.subtotal,
                tax_amount=line.tax_amount,
                total=line.total,
            )

        # Update order totals and quotation status
        order.subtotal = quotation.subtotal
        order.tax_amount = quotation.tax_amount
        order.discount_amount = quotation.discount_amount
        order.total = quotation.total
        order.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total'])

        quotation.status = Quotation.Status.CONVERTED
        quotation.save(update_fields=['status'])

        self.log_activity(
            action='converted',
            module='sales',
            resource_type='Quotation',
            resource_id=quotation.pk,
            description=f"Converted quotation {quotation.number} to sales order {order.number}"
        )
        return order

    @transaction.atomic
    def create_invoice_from_order(self, order: SalesOrder) -> Invoice:
        """Generate an Invoice from a Sales Order."""
        if order.status in [SalesOrder.Status.INVOICED, SalesOrder.Status.CANCELLED]:
            raise ValueError("Order is already invoiced or cancelled.")

        # Create Invoice
        invoice = Invoice.objects.create(
            company=order.company,
            branch=order.branch,
            sales_order=order,
            customer=order.customer,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timezone.timedelta(days=order.payment_terms),
            payment_terms=order.payment_terms,
            currency=order.currency,
            exchange_rate=order.exchange_rate,
            notes=order.notes,
            terms_conditions=order.terms_conditions,
        )

        # Create Invoice Lines
        for line in order.lines.all():
            InvoiceLine.objects.create(
                invoice=invoice,
                product=line.product,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax=line.tax,
                subtotal=line.subtotal,
                tax_amount=line.tax_amount,
                total=line.total,
            )

        # Update invoice totals and order status
        invoice.subtotal = order.subtotal
        invoice.tax_amount = order.tax_amount
        invoice.discount_amount = order.discount_amount
        invoice.total = order.total
        invoice.balance_due = order.total
        invoice.save(update_fields=['subtotal', 'tax_amount', 'discount_amount', 'total', 'balance_due'])

        order.status = SalesOrder.Status.INVOICED
        order.save(update_fields=['status'])

        self.log_activity(
            action='invoiced',
            module='sales',
            resource_type='SalesOrder',
            resource_id=order.pk,
            description=f"Created invoice {invoice.number} from sales order {order.number}"
        )
        return invoice

    def send_invoice_email(self, invoice: Invoice) -> None:
        """Send invoice email to customer."""
        if not invoice.customer.email:
            raise ValueError("Customer has no email address.")
        
        context = {
            'invoice_number': invoice.number,
            'customer_name': invoice.customer.name,
            'total': invoice.total,
            'due_date': invoice.due_date,
            'payment_url': f"/portal/invoices/{invoice.pk}/pay/",  # Example URL
        }
        
        self.send_email(
            to_email=invoice.customer.email,
            to_name=invoice.customer.name,
            subject=f"Invoice {invoice.number} from {invoice.company.name}",
            template="emails/invoice.html",
            context=context
        )
        
        if invoice.status == Invoice.Status.DRAFT:
            invoice.status = Invoice.Status.SENT
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=['status', 'sent_at'])
            
        self.log_activity(
            action='email_sent',
            module='sales',
            resource_type='Invoice',
            resource_id=invoice.pk,
            description=f"Sent invoice {invoice.number} to {invoice.customer.email}"
        )

    def calculate_invoice_totals(self, invoice: Invoice) -> dict:
        """Recalculate invoice totals from lines."""
        from decimal import Decimal
        lines = invoice.lines.all()
        subtotal = sum((l.subtotal for l in lines), Decimal('0'))
        tax_amount = sum((l.tax_amount for l in lines), Decimal('0'))
        discount_amount = sum((l.discount_amount for l in lines), Decimal('0'))
        
        # We don't save the invoice here, just return the computed dictionary.
        # This can be used in APIs before saving.
        return {
            'subtotal': subtotal,
            'tax_amount': tax_amount,
            'discount_amount': discount_amount,
            'total': subtotal + tax_amount - discount_amount
        }

    @transaction.atomic
    def process_payment(self, invoice: Invoice, amount, method: str, reference: str = '') -> Payment:
        """Process a payment against an invoice."""
        if invoice.status == Invoice.Status.PAID:
            raise ValueError("Invoice is already fully paid.")

        payment = Payment.objects.create(
            company=invoice.company,
            invoice=invoice,
            customer=invoice.customer,
            amount=amount,
            currency=invoice.currency,
            payment_date=timezone.now().date(),
            method=method,
            status=Payment.Status.COMPLETED,
            reference=reference,
        )
        
        # Payment save() automatically calls invoice.update_balance()
        
        self.log_activity(
            action='payment_received',
            module='sales',
            resource_type='Invoice',
            resource_id=invoice.pk,
            description=f"Processed {payment.currency.code} {amount} payment for invoice {invoice.number}"
        )
        return payment
