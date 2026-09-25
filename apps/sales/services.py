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
        if quotation.status not in [Quotation.Status.APPROVED, Quotation.Status.SENT, Quotation.Status.ACCEPTED]:
            raise ValueError("Only approved, accepted, or sent quotations can be converted.")

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
        subtotal = sum((item.subtotal for item in lines), Decimal("0"))
        tax_amount = sum((item.tax_amount for item in lines), Decimal("0"))
        discount_amount = sum((item.discount_amount for item in lines), Decimal("0"))

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
    ) -> "Shipment":  # noqa: F821
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
        res = CreditControlService.evaluate_credit(customer, amount)
        return res["allowed"]


class CreditControlService(BaseService):
    """
    Enterprise credit control and risk management service.
    Evaluates customer credit limits, outstanding balances, overdue invoices,
    and payment risk before order confirmation.
    """

    @staticmethod
    def evaluate_credit(customer, order_amount=0):
        from decimal import Decimal
        from django.utils import timezone
        from apps.sales.models import Invoice

        order_amount = Decimal(str(order_amount or "0"))
        credit_limit = Decimal(str(customer.credit_limit or "0"))
        outstanding = Decimal(str(customer.outstanding_balance or "0"))
        projected_balance = outstanding + order_amount
        available_credit = max(Decimal("0"), credit_limit - outstanding) if credit_limit > 0 else Decimal("999999999")

        # Overdue invoices check
        today = timezone.localdate()
        overdue_invoices = Invoice.objects.filter(
            customer=customer,
            status__in=[Invoice.Status.SENT, Invoice.Status.PARTIAL, Invoice.Status.OVERDUE],
            due_date__lt=today,
            balance_due__gt=0,
            is_deleted=False,
        )
        has_overdue = overdue_invoices.exists()
        overdue_count = overdue_invoices.count()
        overdue_amount = sum((inv.balance_due for inv in overdue_invoices), Decimal("0"))

        reasons = []
        warnings = []
        hold_required = False

        if credit_limit > 0 and projected_balance > credit_limit:
            hold_required = True
            excess = projected_balance - credit_limit
            reasons.append(
                f"Credit limit exceeded: Limit is {credit_limit}, current outstanding is {outstanding}, "
                f"new order is {order_amount}. Projected total {projected_balance} exceeds limit by {excess}."
            )

        if has_overdue:
            warnings.append(
                f"Customer has {overdue_count} overdue invoice(s) totaling {overdue_amount}."
            )
            if credit_limit > 0 and overdue_amount > (credit_limit * Decimal("0.2")):
                hold_required = True
                reasons.append(f"Significant overdue invoices: {overdue_amount} overdue.")

        return {
            "allowed": not hold_required,
            "hold_required": hold_required,
            "credit_limit": credit_limit,
            "outstanding_balance": outstanding,
            "order_amount": order_amount,
            "projected_balance": projected_balance,
            "available_credit": available_credit,
            "has_overdue": has_overdue,
            "overdue_count": overdue_count,
            "overdue_amount": overdue_amount,
            "reasons": reasons,
            "warnings": warnings,
        }

    @transaction.atomic
    def check_and_apply_credit_hold(self, order, user=None):
        """
        Evaluate order against customer credit limit.
        If credit is breached and not overridden, place order on credit hold.
        """
        if order.credit_override_by:
            return True, "Credit hold previously overridden."

        evaluation = self.evaluate_credit(order.customer, order.total)
        if evaluation["hold_required"]:
            order.status = order.Status.PENDING_APPROVAL
            order.credit_hold = True
            order.save(update_fields=["status", "credit_hold"])
            self.log_activity(
                action="credit_hold",
                module="sales",
                resource_type="SalesOrder",
                resource_id=order.pk,
                description="Order placed on credit hold: " + "; ".join(evaluation["reasons"]),
            )
            return False, "; ".join(evaluation["reasons"])

        return True, "Credit check passed."

    @transaction.atomic
    def override_credit_hold(self, order, user, reason: str):
        """Manager override for credit hold."""
        if not reason or not reason.strip():
            raise ValueError("A documented override reason is required to bypass credit hold.")

        order.credit_hold = False
        order.credit_override_by = user
        order.credit_override_reason = reason.strip()
        order.status = order.Status.DRAFT
        order.save(update_fields=["credit_hold", "credit_override_by", "credit_override_reason", "status"])

        self.log_activity(
            action="credit_override",
            module="sales",
            resource_type="SalesOrder",
            resource_id=order.pk,
            description=f"Credit hold overridden by {user}: {reason}",
        )
        return order




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
        if order.status not in [order.Status.DRAFT, order.Status.PENDING_APPROVAL]:
            raise ValueError(f"Only draft or pending approval orders can be confirmed, current: {order.status}.")

        # 1. Credit Control Evaluation
        credit_service = CreditControlService(company=self.company, user=self.user)
        passed, msg = credit_service.check_and_apply_credit_hold(order, self.user)
        if not passed:
            raise ValueError(f"Order cannot be confirmed due to credit hold: {msg}")

        from apps.inventory.models import DeliveryOrder, DeliveryOrderLine, Warehouse
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

        # Auto-create DeliveryOrder in READY status if not already existing
        if not order.delivery_orders.filter(status__in=[DeliveryOrder.Status.READY, DeliveryOrder.Status.DRAFT, DeliveryOrder.Status.PICKING, DeliveryOrder.Status.PACKING]).exists():
            delivery = DeliveryOrder.objects.create(
                company=self.company,
                number=BaseService.generate_sequence_number("DEL", DeliveryOrder, self.company.pk),
                sales_order=order,
                warehouse=warehouse,
                status=DeliveryOrder.Status.READY,
                scheduled_date=order.delivery_date,
            )
            for line in order.lines.all():
                qty_remaining = line.quantity - (line.qty_delivered or 0)
                if qty_remaining > 0:
                    DeliveryOrderLine.objects.create(
                        delivery_order=delivery,
                        product=line.product,
                        description=line.description,
                        quantity_ordered=qty_remaining,
                        quantity_shipped=qty_remaining,
                    )

        # Optional Twilio SMS notification — only runs when credentials are configured.
        # A failure here must never roll back the order confirmation.
        try:
            from apps.administration.services.integrations import (
                IntegrationNotConfiguredError,
                TwilioService,
            )

            sms_service = TwilioService()
            if sms_service.is_connected and order.customer and order.customer.phone:
                result = sms_service.send_sms(
                    to_number=order.customer.phone,
                    message_body=f"Hi {order.customer.name}, your order {order.number} has been confirmed!",
                )
                logger.info("SMS sent for order %s: SID=%s", order.number, result.get("sid"))
        except IntegrationNotConfiguredError:
            logger.info("Twilio not configured; skipping SMS for order %s", order.number)
        except Exception as e:
            logger.warning("SMS sending failed for order %s: %s", order.number, e)

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

        # Release only the quantity that is still reserved (not yet shipped).
        # For a fully confirmed order with no shipments, qty_to_release == line.quantity.
        # For a partially shipped order, qty_to_release == ordered - delivered.
        # This prevents releasing more than was ever reserved and avoids
        # quantity_reserved going negative on the StockRecord.
        if order.status in [order.Status.CONFIRMED, order.Status.PROCESSING]:
            from apps.inventory.models import StockRecord, Warehouse
            from apps.inventory.services import StockService

            warehouse = Warehouse.objects.filter(
                company=self.company, is_active=True
            ).first()
            if warehouse:
                stock_service = StockService(company=self.company, user=self.user)
                for line in order.lines.select_related("product").all():
                    if (
                        line.product
                        and line.product.product_type
                        == line.product.ProductType.STOCKABLE
                    ):
                        # qty_delivered tracks how much has already been physically shipped.
                        # The reservation covers only the unshipped remainder.
                        qty_delivered = getattr(line, "qty_delivered", 0) or 0
                        qty_to_release = max(line.quantity - qty_delivered, 0)
                        if qty_to_release <= 0:
                            continue
                        # Safety clamp: never release more than what is currently reserved
                        # on the StockRecord to avoid going negative.
                        try:
                            record = StockRecord.objects.get(
                                company=self.company,
                                product=line.product,
                                warehouse=warehouse,
                            )
                            qty_to_release = min(qty_to_release, record.quantity_reserved)
                        except StockRecord.DoesNotExist:
                            qty_to_release = 0
                        if qty_to_release > 0:
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

        # Support both Django QueryDict (has getlist) and plain dict (from tests/API).
        def _getlist(key):
            if hasattr(data, "getlist"):
                return data.getlist(key)
            val = data.get(key, [])
            return val if isinstance(val, list) else [val]

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

        products = _getlist("product[]")
        descs = _getlist("description[]")
        quantities = _getlist("quantity[]")
        prices = _getlist("unit_price[]")
        discounts = _getlist("discount_percent[]")
        taxes = _getlist("tax[]")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            line = InvoiceLine(
                invoice=invoice,
                product_id=products[i] if i < len(products) and products[i] else None,
                description=desc,
                quantity=Decimal(str(quantities[i])) if i < len(quantities) and quantities[i] else Decimal("1"),
                unit_price=Decimal(str(prices[i])) if i < len(prices) and prices[i] else Decimal("0"),
                discount_percent=(
                    Decimal(str(discounts[i])) if i < len(discounts) and discounts[i] else Decimal("0")
                ),
                tax_id=taxes[i] if i < len(taxes) and taxes[i] else None,
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


class SalesReturnService(BaseService):
    """
    Enterprise RMA / Sales Return Service.
    Handles customer returns, inspection, stock restocking, credit note generation,
    and accounting reversals.
    """

    @transaction.atomic
    def create_return(self, order, lines_data, reason, user=None):
        from decimal import Decimal
        from apps.sales.models import SalesReturn, SalesReturnLine
        from apps.inventory.models import Warehouse

        warehouse = Warehouse.objects.filter(company=self.company, is_active=True).first()
        if not warehouse:
            raise ValueError("No active warehouse found for receiving returned goods.")

        ret = SalesReturn.objects.create(
            company=self.company,
            sales_order=order,
            customer=order.customer,
            warehouse=warehouse,
            return_reason=reason,
            return_date=timezone.now().date(),
            status=SalesReturn.Status.DRAFT,
        )

        total = Decimal("0")
        for item in lines_data:
            order_line = order.lines.get(pk=item["order_line_id"])
            qty = Decimal(str(item["quantity"]))
            unit_price = Decimal(str(item.get("unit_price", order_line.unit_price)))
            line_sub = qty * unit_price
            condition = item.get("condition", "resellable")

            SalesReturnLine.objects.create(
                sales_return=ret,
                order_line=order_line,
                product=order_line.product,
                quantity=qty,
                unit_price=unit_price,
                subtotal=line_sub,
                condition=condition,
            )
            total += line_sub

        ret.total_amount = total
        ret.save(update_fields=["total_amount"])

        self.log_activity(
            action="return_created",
            module="sales",
            resource_type="SalesReturn",
            resource_id=ret.pk,
            description=f"Created Sales Return {ret.number} for Order {order.number}",
        )
        return ret

    @transaction.atomic
    def approve_return(self, sales_return, user):
        if sales_return.status != sales_return.Status.DRAFT:
            raise ValueError("Only draft returns can be approved.")
        sales_return.status = sales_return.Status.APPROVED
        sales_return.approved_by = user
        sales_return.approved_at = timezone.now()
        sales_return.save(update_fields=["status", "approved_by", "approved_at"])

        self.log_activity(
            action="return_approved",
            module="sales",
            resource_type="SalesReturn",
            resource_id=sales_return.pk,
            description=f"Approved Sales Return {sales_return.number}",
        )
        return sales_return

    @transaction.atomic
    def complete_return(self, sales_return, user=None):
        """
        Completes the return:
        1. Restocks resellable items in inventory via StockMovement (RETURN_IN)
        2. Generates Credit Note and triggers accounting reversal
        3. Sets status to COMPLETED
        """
        from decimal import Decimal
        from apps.inventory.models import StockMovement, StockRecord
        from apps.sales.models import CreditNote, CreditNoteLine
        from apps.accounting.services import AutoJournalService

        if sales_return.status not in [sales_return.Status.APPROVED, sales_return.Status.RECEIVED, sales_return.Status.INSPECTED]:
            raise ValueError(f"Cannot complete return in status {sales_return.status}.")

        # 1. Restock resellable products
        for line in sales_return.lines.all():
            if line.condition == "resellable" and line.product:
                stock_record, _ = StockRecord.objects.select_for_update().get_or_create(
                    company=self.company,
                    product=line.product,
                    warehouse=sales_return.warehouse,
                    defaults={"quantity_on_hand": 0, "average_cost": line.unit_price, "quantity_reserved": 0},
                )
                stock_record.quantity_on_hand += line.quantity
                stock_record.save(update_fields=["quantity_on_hand"])

                StockMovement.objects.create(
                    company=self.company,
                    product=line.product,
                    warehouse=sales_return.warehouse,
                    movement_type=StockMovement.MovementType.RETURN_IN,
                    quantity=line.quantity,
                    unit_cost=stock_record.average_cost,
                    total_cost=line.quantity * stock_record.average_cost,
                    movement_date=timezone.now().date(),
                    reference_type="SalesReturn",
                    reference_id=str(sales_return.id),
                    notes=f"Restocked from Return {sales_return.number}",
                    stock_after=stock_record.quantity_on_hand,
                )

        # 2. Generate Credit Note
        cn = CreditNote.objects.create(
            company=self.company,
            customer=sales_return.customer,
            status=CreditNote.Status.ISSUED,
            date=timezone.now().date(),
            amount=sales_return.total_amount,
            reason=f"Credit for Return {sales_return.number} (Reason: {sales_return.get_return_reason_display()})",
        )
        for line in sales_return.lines.all():
            CreditNoteLine.objects.create(
                credit_note=cn,
                product=line.product,
                description=f"Return: {line.product.name if line.product else ''}",
                quantity=line.quantity,
                unit_price=line.unit_price,
                subtotal=line.subtotal,
            )

        sales_return.credit_note = cn
        sales_return.status = sales_return.Status.COMPLETED
        sales_return.save(update_fields=["credit_note", "status"])

        # 3. Post to accounting
        AutoJournalService.post_credit_note(cn)

        self.log_activity(
            action="return_completed",
            module="sales",
            resource_type="SalesReturn",
            resource_id=sales_return.pk,
            description=f"Completed Return {sales_return.number}, issued Credit Note {cn.number}",
        )
        return sales_return

