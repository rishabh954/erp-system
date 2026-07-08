import logging

from django.db import transaction
from django.utils import timezone

from apps.sales.models import (
    Invoice,
    InvoiceLine,
    Payment,
    Quotation,
    SalesOrder,
    SalesOrderLine,
)
from core.services import BaseService

logger = logging.getLogger(__name__)


class SalesService(BaseService):

    @transaction.atomic
    def convert_quote_to_order(self, quotation: Quotation) -> SalesOrder:
        """Convert an approved Quotation into a Sales Order."""
        if quotation.status == Quotation.Status.CONVERTED:
            raise ValueError("Quotation is already converted.")
        if quotation.status not in [Quotation.Status.APPROVED, Quotation.Status.SENT]:
            raise ValueError("Only approved or sent quotations can be converted.")

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
            shipping_address=quotation.customer.address_line1 or "",
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
        order.save(update_fields=["subtotal", "tax_amount", "discount_amount", "total"])

        quotation.status = Quotation.Status.CONVERTED
        quotation.save(update_fields=["status"])

        self.log_activity(
            action="converted",
            module="sales",
            resource_type="Quotation",
            resource_id=quotation.pk,
            description=f"Converted quotation {quotation.number} to sales order {order.number}",
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
            due_date=timezone.now().date()
            + timezone.timedelta(days=order.payment_terms),
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
        invoice.save(
            update_fields=[
                "subtotal",
                "tax_amount",
                "discount_amount",
                "total",
                "balance_due",
            ]
        )

        order.status = SalesOrder.Status.INVOICED
        order.save(update_fields=["status"])

        self.log_activity(
            action="invoiced",
            module="sales",
            resource_type="SalesOrder",
            resource_id=order.pk,
            description=f"Created invoice {invoice.number} from sales order {order.number}",
        )
        return invoice

    def send_invoice_email(self, invoice: Invoice) -> None:
        """Send invoice email to customer."""
        if not invoice.customer.email:
            raise ValueError("Customer has no email address.")

        context = {
            "invoice_number": invoice.number,
            "customer_name": invoice.customer.name,
            "total": invoice.total,
            "due_date": invoice.due_date,
            "payment_url": f"/portal/invoices/{invoice.pk}/pay/",  # Example URL
        }

        self.send_email(
            to_email=invoice.customer.email,
            to_name=invoice.customer.name,
            subject=f"Invoice {invoice.number} from {invoice.company.name}",
            template="emails/invoice.html",
            context=context,
        )

        if invoice.status == Invoice.Status.DRAFT:
            invoice.status = Invoice.Status.SENT
            invoice.sent_at = timezone.now()
            invoice.save(update_fields=["status", "sent_at"])

        self.log_activity(
            action="email_sent",
            module="sales",
            resource_type="Invoice",
            resource_id=invoice.pk,
            description=f"Sent invoice {invoice.number} to {invoice.customer.email}",
        )

    def calculate_invoice_totals(self, invoice: Invoice) -> dict:
        """Recalculate invoice totals from lines."""
        from decimal import Decimal

        lines = invoice.lines.all()
        subtotal = sum((l.subtotal for l in lines), Decimal("0"))
        tax_amount = sum((l.tax_amount for l in lines), Decimal("0"))
        discount_amount = sum((l.discount_amount for l in lines), Decimal("0"))

        # We don't save the invoice here, just return the computed dictionary.
        # This can be used in APIs before saving.
        return {
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "discount_amount": discount_amount,
            "total": subtotal + tax_amount - discount_amount,
        }

    @transaction.atomic
    def process_payment(
        self, invoice: Invoice, amount, method: str, reference: str = ""
    ) -> Payment:
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
            action="payment_received",
            module="sales",
            resource_type="Invoice",
            resource_id=invoice.pk,
            description=f"Processed {payment.currency.code} {amount} payment for invoice {invoice.number}",
        )
        return payment

    @transaction.atomic
    def create_shipment_from_order(
        self, order: SalesOrder, lines_data: list = None
    ) -> "Shipment":
        """Generate a Shipment from a Sales Order."""
        from apps.sales.models import Shipment, ShipmentLine

        if order.status in [
            SalesOrder.Status.SHIPPED,
            SalesOrder.Status.DELIVERED,
            SalesOrder.Status.CANCELLED,
        ]:
            raise ValueError("Order is already fully shipped or cancelled.")

        shipment = Shipment.objects.create(
            company=order.company,
            sales_order=order,
            status=Shipment.Status.PENDING,
            scheduled_date=order.delivery_date,
        )

        # Create Shipment Lines
        for line in order.lines.all():
            qty_to_ship = line.quantity - line.qty_delivered
            if qty_to_ship > 0:
                # If specific lines_data passed (for partial split), respect it
                if lines_data:
                    line_data = next(
                        (
                            item
                            for item in lines_data
                            if str(item["order_line_id"]) == str(line.id)
                        ),
                        None,
                    )
                    if line_data:
                        qty_to_ship = min(qty_to_ship, line_data["quantity"])
                    else:
                        continue

                ShipmentLine.objects.create(
                    shipment=shipment,
                    order_line=line,
                    product=line.product,
                    quantity=qty_to_ship,
                )

        self.log_activity(
            action="shipment_created",
            module="sales",
            resource_type="SalesOrder",
            resource_id=order.pk,
            description=f"Created shipment {shipment.number} for sales order {order.number}",
        )
        return shipment

    def verify_credit_limit(self, customer, amount) -> bool:
        """Check if customer has enough credit limit for this amount."""
        if customer.credit_limit <= 0:
            return True  # Unlimited or not enforced

        return customer.outstanding_balance + amount <= customer.credit_limit


class QuotationService(BaseService):
    @transaction.atomic
    def create_quotation(self, data, user):
        from decimal import Decimal

        from apps.sales.models import Quotation, QuotationLine

        quot = Quotation(
            company=self.company,
            customer_id=data["customer"],
            validity_date=data.get("validity_date") or None,
            delivery_date=data.get("delivery_date") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
            sales_rep=user,
        )
        quot.number = BaseService.generate_sequence_number(
            "QUO", Quotation, self.company.pk
        )
        quot.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = QuotationLine(
                quotation=quot,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if discounts[i] else Decimal("0")
                ),
                tax_id=taxes[i] if taxes[i] else None,
                sort_order=i,
            )
            line.save()

        quot.recalculate_totals()
        return quot


class SalesOrderService(BaseService):
    @transaction.atomic
    def create_order(self, data, user):
        from decimal import Decimal

        from apps.sales.models import SalesOrder, SalesOrderLine

        order = SalesOrder(
            company=self.company,
            customer_id=data["customer"],
            order_date=data.get("order_date") or timezone.now().date(),
            delivery_date=data.get("delivery_date") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
            sales_rep=user,
        )
        order.number = BaseService.generate_sequence_number(
            "SO", SalesOrder, self.company.pk
        )
        order.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = SalesOrderLine(
                sales_order=order,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if discounts[i] else Decimal("0")
                ),
                tax_id=taxes[i] if taxes[i] else None,
                sort_order=i,
            )
            line.save()

        order.recalculate_totals()
        return order


class InvoiceService(BaseService):
    @transaction.atomic
    def create_invoice(self, data):
        from decimal import Decimal

        from apps.sales.models import Invoice, InvoiceLine

        invoice = Invoice(
            company=self.company,
            customer_id=data["customer"],
            invoice_date=data.get("invoice_date") or timezone.now().date(),
            due_date=data.get("due_date") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
        )
        invoice.number = BaseService.generate_sequence_number(
            "INV", Invoice, self.company.pk
        )
        invoice.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        data.getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = InvoiceLine(
                invoice=invoice,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if discounts[i] else Decimal("0")
                ),
                payment_date=timezone.now().date(),
                method=method,
                status=Payment.Status.COMPLETED,
                reference=reference,
            )

        # Payment save() automatically calls invoice.update_balance()

        self.log_activity(
            action="payment_received",
            module="sales",
            resource_type="Invoice",
            resource_id=invoice.pk,
            description=f"Processed {payment.currency.code} {amount} payment for invoice {invoice.number}",
        )
        return payment

    @transaction.atomic
    def create_shipment_from_order(
        self, order: SalesOrder, lines_data: list = None
    ) -> "Shipment":
        """Generate a Shipment from a Sales Order."""
        from apps.sales.models import Shipment, ShipmentLine

        if order.status in [
            SalesOrder.Status.SHIPPED,
            SalesOrder.Status.DELIVERED,
            SalesOrder.Status.CANCELLED,
        ]:
            raise ValueError("Order is already fully shipped or cancelled.")

        shipment = Shipment.objects.create(
            company=order.company,
            sales_order=order,
            status=Shipment.Status.PENDING,
            scheduled_date=order.delivery_date,
        )

        # Create Shipment Lines
        for line in order.lines.all():
            qty_to_ship = line.quantity - line.qty_delivered
            if qty_to_ship > 0:
                # If specific lines_data passed (for partial split), respect it
                if lines_data:
                    line_data = next(
                        (
                            item
                            for item in lines_data
                            if str(item["order_line_id"]) == str(line.id)
                        ),
                        None,
                    )
                    if line_data:
                        qty_to_ship = min(qty_to_ship, line_data["quantity"])
                    else:
                        continue

                ShipmentLine.objects.create(
                    shipment=shipment,
                    order_line=line,
                    product=line.product,
                    quantity=qty_to_ship,
                )

        self.log_activity(
            action="shipment_created",
            module="sales",
            resource_type="SalesOrder",
            resource_id=order.pk,
            description=f"Created shipment {shipment.number} for sales order {order.number}",
        )
        return shipment

    def verify_credit_limit(self, customer, amount) -> bool:
        """Check if customer has enough credit limit for this amount."""
        if customer.credit_limit <= 0:
            return True  # Unlimited or not enforced

        return customer.outstanding_balance + amount <= customer.credit_limit


class QuotationService(BaseService):
    @transaction.atomic
    def create_quotation(self, data, user):
        from decimal import Decimal

        from apps.sales.models import Quotation, QuotationLine

        quot = Quotation(
            company=self.company,
            customer_id=data["customer"],
            validity_date=data.get("validity_date") or None,
            delivery_date=data.get("delivery_date") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
            sales_rep=user,
        )
        quot.number = BaseService.generate_sequence_number(
            "QUO", Quotation, self.company.pk
        )
        quot.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = QuotationLine(
                quotation=quot,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if discounts[i] else Decimal("0")
                ),
                tax_id=taxes[i] if taxes[i] else None,
                sort_order=i,
            )
            line.save()

        quot.recalculate_totals()
        return quot


class SalesOrderService(BaseService):
    @transaction.atomic
    def create_order(self, data, user):
        from decimal import Decimal

        from apps.sales.models import SalesOrder, SalesOrderLine

        order = SalesOrder(
            company=self.company,
            customer_id=data["customer"],
            order_date=data.get("order_date") or timezone.now().date(),
            delivery_date=data.get("delivery_date") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
            sales_rep=user,
        )
        order.number = BaseService.generate_sequence_number(
            "SO", SalesOrder, self.company.pk
        )
        order.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = SalesOrderLine(
                sales_order=order,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if discounts[i] else Decimal("0")
                ),
                tax_id=taxes[i] if taxes[i] else None,
                sort_order=i,
            )
            line.save()

        order.recalculate_totals()
        return order

    @transaction.atomic
    def create_delivery(self, order):
        from apps.inventory.models import DeliveryOrder, DeliveryOrderLine, Warehouse

        if not order.lines.exists():
            raise ValueError("Cannot create delivery for empty order.")

        warehouse = Warehouse.objects.filter(
            company=self.company, is_active=True
        ).first()
        if not warehouse:
            raise ValueError(
                "No active warehouse found. Please create a warehouse first."
            )

        delivery = DeliveryOrder.objects.create(
            company=self.company,
            number=BaseService.generate_sequence_number(
                "DEL", DeliveryOrder, self.company.pk
            ),
            sales_order=order,
            warehouse=warehouse,
            status=DeliveryOrder.Status.READY,
        )

        for line in order.lines.all():
            qty_remaining = line.quantity - line.qty_delivered
            if qty_remaining > 0:
                DeliveryOrderLine.objects.create(
                    delivery_order=delivery,
                    product=line.product,
                    description=line.description,
                    quantity_ordered=qty_remaining,
                    quantity_shipped=qty_remaining,
                )

        if not delivery.lines.exists():
            delivery.delete()
            raise ValueError("This Sales Order is already fully delivered.")

        return delivery

    @transaction.atomic
    def create_invoice(self, order):
        from datetime import timedelta

        from apps.sales.models import Invoice, InvoiceLine

        inv = Invoice(
            company=order.company,
            sales_order=order,
            customer=order.customer,
            invoice_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=order.payment_terms),
            payment_terms=order.payment_terms,
            currency=order.currency,
            subtotal=order.subtotal,
            tax_amount=order.tax_amount,
            discount_amount=order.discount_amount,
            total=order.total,
            balance_due=order.total,
        )
        inv.number = BaseService.generate_sequence_number(
            "INV", Invoice, order.company_id
        )
        inv.save()

        for line in order.lines.all():
            InvoiceLine.objects.create(
                invoice=inv,
                product=line.product,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax=line.tax,
                subtotal=line.subtotal,
                tax_amount=line.tax_amount,
                total=line.total,
                sort_order=line.sort_order,
            )

        order.status = order.Status.INVOICED
        order.save(update_fields=["status"])
        return inv

    @transaction.atomic
    def confirm_order(self, order):
        if order.status != order.Status.DRAFT:
            raise ValueError("Only draft orders can be confirmed.")

        from apps.inventory.models import Warehouse
        from apps.inventory.services import StockService

        # Assumption: If SalesOrder doesn't have a warehouse, use the first active one.
        warehouse = Warehouse.objects.filter(
            company=self.company, is_active=True
        ).first()

        if not warehouse:
            raise ValueError("No active warehouse found to reserve stock against.")

        stock_service = StockService(company=self.company, user=self.user)
        short_products = []

        for line in order.lines.all():
            if (
                line.product
                and line.product.product_type == line.product.ProductType.STOCKABLE
            ):
                try:
                    stock_service.reserve_stock(
                        product=line.product,
                        warehouse=warehouse,
                        qty=line.quantity,
                        reference_type="SalesOrder",
                        reference_id=str(order.id),
                    )
                except ValueError:
                    short_products.append(line.product.sku)

        if short_products:
            raise ValueError(
                f"Insufficient stock to confirm order. Short on: {', '.join(short_products)}"
            )

        order.status = order.Status.CONFIRMED
        order.save(update_fields=["status"])

        # Mock SMS Notification
        try:
            from apps.administration.services.integrations import TwilioService

            sms_service = TwilioService(
                credentials={"account_sid": "mock", "auth_token": "mock"}
            )
            if order.customer and order.customer.phone:
                result = sms_service.send_sms(
                    to_number=order.customer.phone,
                    message_body=f"Hi {order.customer.name}, your order {order.number} has been confirmed!",
                )
                order.notes = (
                    order.notes or ""
                ) + f"\n\nSMS Sent: {result['sid']} at {result['date_created']}"
                order.save(update_fields=["notes"])
        except Exception:
            pass  # Non-critical failure

        return order

    @transaction.atomic
    def cancel_order(self, order, reason=""):
        if order.status in [
            order.Status.SHIPPED,
            order.Status.DELIVERED,
            order.Status.INVOICED,
            order.Status.COMPLETED,
        ]:
            raise ValueError(
                "Cannot cancel an order that has already been shipped, invoiced, or completed."
            )

        # Release reservations if it was confirmed
        if order.status in [order.Status.CONFIRMED, order.Status.PROCESSING]:
            from apps.inventory.models import Warehouse
            from apps.inventory.services import StockService

            warehouse = Warehouse.objects.filter(
                company=self.company, is_active=True
            ).first()
            if warehouse:
                stock_service = StockService(company=self.company, user=self.user)
                for line in order.lines.all():
                    if (
                        line.product
                        and line.product.product_type
                        == line.product.ProductType.STOCKABLE
                    ):
                        # In a real cancellation, we would calculate (reserved - already_shipped)
                        # For simple implementation, assuming all line quantity was reserved
                        qty_to_release = line.quantity
                        stock_service.release_reservation(
                            product=line.product,
                            warehouse=warehouse,
                            qty=qty_to_release,
                            reference_type="SalesOrder",
                            reference_id=str(order.id),
                        )

        order.status = order.Status.CANCELLED
        order.cancel_reason = reason
        order.save(update_fields=["status", "cancel_reason"])
        return order


class InvoiceService(BaseService):
    @transaction.atomic
    def create_invoice(self, data):
        from decimal import Decimal

        from apps.sales.models import Invoice, InvoiceLine

        invoice = Invoice(
            company=self.company,
            customer_id=data["customer"],
            invoice_date=data.get("invoice_date") or timezone.now().date(),
            due_date=data.get("due_date") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
        )
        invoice.number = BaseService.generate_sequence_number(
            "INV", Invoice, self.company.pk
        )
        invoice.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = InvoiceLine(
                invoice=invoice,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if discounts[i] else Decimal("0")
                ),
                tax_id=taxes[i] if taxes[i] else None,
                sort_order=i,
            )
            line.save()

        invoice.recalculate_totals()
        return invoice


class PaymentService(BaseService):
    @transaction.atomic
    def record_payment(self, invoice, data):
        from decimal import Decimal

        from apps.sales.models import Payment

        amount = Decimal(data.get("amount", "0"))
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        payment = Payment(
            company=invoice.company,
            invoice=invoice,
            customer=invoice.customer,
            amount=amount,
            currency=invoice.currency,
            payment_date=data.get("payment_date") or timezone.now().date(),
            method=data.get("method", "bank_transfer"),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            status="completed",
        )
        payment.number = BaseService.generate_sequence_number(
            "PAY", Payment, invoice.company_id
        )
        payment.save()  # triggers invoice.update_balance()

        self.log_activity(
            action="payment_received",
            module="sales",
            resource_type="Invoice",
            resource_id=invoice.pk,
            description=f"Processed {payment.currency.code} {amount} payment for invoice {invoice.number}",
        )
        return payment
