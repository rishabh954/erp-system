import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.purchase.models import (
    Bill,
    BillLine,
    GoodsReceipt,
    GoodsReceiptLine,
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    RequestForQuotation,
    RFQLine,
    VendorBid,
    VendorBidLine,
)
from core.services import BaseService

logger = logging.getLogger(__name__)


class PurchaseRequestService(BaseService):
    @transaction.atomic
    def create_request(self, data, user):
        pr = PurchaseRequest(
            company=self.company,
            title=data["title"],
            department_id=data.get("department") or None,
            requested_by=user,
            required_by=data.get("required_by") or None,
            priority=data.get("priority", "medium"),
            notes=data.get("notes", ""),
            status="draft",
        )
        pr.number = BaseService.generate_sequence_number(
            "PR", PurchaseRequest, self.company.pk
        )
        pr.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        est_prices = data.getlist("estimated_unit_price[]")

        total = Decimal("0")
        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            qty = Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
            price = (
                Decimal(str(est_prices[i]))
                if (i < len(est_prices) and est_prices[i])
                else Decimal("0")
            )
            line_total = qty * price
            PurchaseRequestLine.objects.create(
                request=pr,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=qty,
                estimated_unit_price=price,
                estimated_total=line_total,
            )
            total += line_total

        pr.estimated_cost = total
        pr.save(update_fields=["estimated_cost"])

        self.log_activity(
            action="created",
            module="purchase",
            resource_type="PurchaseRequest",
            resource_id=pr.pk,
            description=f"Created Purchase Request {pr.number}",
        )
        return pr

    @transaction.atomic
    def update_request(self, pr, data):
        if pr.status != "draft":
            raise ValueError("Only draft purchase requests can be edited.")

        pr.title = data["title"]
        pr.department_id = data.get("department") or None
        pr.required_by = data.get("required_by") or None
        pr.priority = data.get("priority", "medium")
        pr.notes = data.get("notes", "")
        pr.save()

        pr.lines.all().delete()
        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        est_prices = data.getlist("estimated_unit_price[]")

        total = Decimal("0")
        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            qty = Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
            price = (
                Decimal(str(est_prices[i]))
                if (i < len(est_prices) and est_prices[i])
                else Decimal("0")
            )
            line_total = qty * price
            PurchaseRequestLine.objects.create(
                request=pr,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=qty,
                estimated_unit_price=price,
                estimated_total=line_total,
            )
            total += line_total

        pr.estimated_cost = total
        pr.save(update_fields=["estimated_cost"])

        self.log_activity(
            action="updated",
            module="purchase",
            resource_type="PurchaseRequest",
            resource_id=pr.pk,
            description=f"Updated Purchase Request {pr.number}",
        )
        return pr


class PurchaseOrderService(BaseService):
    @transaction.atomic
    def create_order(self, data, user):
        po = PurchaseOrder(
            company=self.company,
            vendor_id=data["vendor"],
            purchase_request_id=data.get("purchase_request") or None,
            purchase_contract_id=data.get("purchase_contract") or None,
            warehouse_id=data.get("warehouse") or None,
            order_date=data.get("order_date") or timezone.now().date(),
            expected_delivery=data.get("expected_delivery") or None,
            payment_terms=int(data.get("payment_terms", 30)),
            currency_id=data.get("currency") or None,
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
            status="draft",
        )
        po.number = BaseService.generate_sequence_number(
            "PO", PurchaseOrder, self.company.pk
        )
        po.save()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            qty = Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
            price = Decimal(str(prices[i])) if prices[i] else Decimal("0")
            disc = (
                Decimal(str(discounts[i]))
                if (i < len(discounts) and discounts[i])
                else Decimal("0")
            )
            sub = qty * price
            disc_amt = sub * disc / 100
            taxable = sub - disc_amt
            tax_amt = Decimal("0")

            tax_id = taxes[i] if (i < len(taxes) and taxes[i]) else None
            if tax_id:
                from apps.company.models import Tax

                try:
                    t = Tax.objects.get(pk=tax_id)
                    tax_amt = t.compute(taxable)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to compute tax: %s", e)
            total = taxable + tax_amt
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=qty,
                unit_price=price,
                discount_percent=disc,
                tax_id=tax_id,
                subtotal=sub,
                tax_amount=tax_amt,
                total=total,
            )

            # Drawdown from contract if applicable
            if po.purchase_contract_id and products[i]:
                try:
                    contract_line = po.purchase_contract.lines.get(
                        product_id=products[i]
                    )
                    contract_line.quantity_ordered += qty
                    contract_line.save(update_fields=["quantity_ordered"])
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to update contract: %s", e)

            subtotal += taxable
            tax_total += tax_amt

        po.subtotal = subtotal
        po.tax_amount = tax_total
        po.total = subtotal + tax_total
        po.balance_due = po.total
        po.save(update_fields=["subtotal", "tax_amount", "total", "balance_due"])

        self.log_activity(
            action="created",
            module="purchase",
            resource_type="PurchaseOrder",
            resource_id=po.pk,
            description=f"Created Purchase Order {po.number}",
        )
        return po

    @transaction.atomic
    def update_order(self, po, data):
        if po.status != "draft":
            raise ValueError("Only draft purchase orders can be edited.")

        po.vendor_id = data["vendor"]
        po.purchase_request_id = data.get("purchase_request") or None
        po.purchase_contract_id = data.get("purchase_contract") or None
        po.warehouse_id = data.get("warehouse") or None
        po.order_date = data["order_date"]
        po.expected_delivery = data.get("expected_delivery") or None
        po.payment_terms = int(data.get("payment_terms", 30))
        po.currency_id = data.get("currency") or None
        po.notes = data.get("notes", "")
        po.terms_conditions = data.get("terms_conditions", "")
        po.save()

        po.lines.all().delete()

        products = data.getlist("product[]")
        descs = data.getlist("description[]")
        quantities = data.getlist("quantity[]")
        prices = data.getlist("unit_price[]")
        discounts = data.getlist("discount_percent[]")
        taxes = data.getlist("tax[]")

        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for i, desc in enumerate(descs):
            if not desc.strip():
                continue
            qty = Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
            price = Decimal(str(prices[i])) if prices[i] else Decimal("0")
            disc = (
                Decimal(str(discounts[i]))
                if (i < len(discounts) and discounts[i])
                else Decimal("0")
            )
            sub = qty * price
            disc_amt = sub * disc / 100
            taxable = sub - disc_amt
            tax_amt = Decimal("0")

            tax_id = taxes[i] if (i < len(taxes) and taxes[i]) else None
            if tax_id:
                from apps.company.models import Tax

                try:
                    t = Tax.objects.get(pk=tax_id)
                    tax_amt = t.compute(taxable)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to compute tax: %s", e)
            total = taxable + tax_amt
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                product_id=products[i] if products[i] else None,
                description=desc,
                quantity=qty,
                unit_price=price,
                discount_percent=disc,
                tax_id=tax_id,
                subtotal=sub,
                tax_amount=tax_amt,
                total=total,
            )

            subtotal += sub
            tax_total += tax_amt

        po.subtotal = subtotal
        po.tax_amount = tax_total
        po.total = subtotal + tax_total
        po.balance_due = po.total
        po.save(update_fields=["subtotal", "tax_amount", "total", "balance_due"])

        self.log_activity(
            action="updated",
            module="purchase",
            resource_type="PurchaseOrder",
            resource_id=po.pk,
            description=f"Updated Purchase Order {po.number}",
        )
        return po

    @transaction.atomic
    def create_bill(self, order):
        from datetime import timedelta

        if order.status not in [
            PurchaseOrder.Status.CONFIRMED,
            PurchaseOrder.Status.PARTIAL,
            PurchaseOrder.Status.RECEIVED,
        ]:
            raise ValueError("Cannot create bill for this Purchase Order status.")

        bill = Bill(
            company=self.company,
            purchase_order=order,
            vendor=order.vendor,
            bill_date=timezone.now().date(),
            due_date=timezone.now().date() + timedelta(days=order.payment_terms),
            status=Bill.Status.DRAFT,
            currency=order.currency,
        )
        bill.number = BaseService.generate_sequence_number(
            "BILL", Bill, self.company.pk
        )
        bill.save()

        lines_created = 0
        for line in order.lines.all():
            qty_to_bill = float(line.qty_received) - float(line.qty_invoiced)
            if qty_to_bill <= 0:
                continue
            BillLine.objects.create(
                bill=bill,
                product=line.product,
                description=line.description,
                quantity=Decimal(str(qty_to_bill)),
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax=line.tax,
            )
            line.qty_invoiced += Decimal(str(qty_to_bill))
            line.save(update_fields=["qty_invoiced"])
            lines_created += 1

        if lines_created == 0:
            bill.delete()
            raise ValueError("Nothing to bill for this Purchase Order.")

        bill.calculate_totals()

        self.log_activity(
            action="billed",
            module="purchase",
            resource_type="PurchaseOrder",
            resource_id=order.pk,
            description=f"Created Bill {bill.number} for PO {order.number}",
        )
        return bill

    @transaction.atomic
    def create_goods_receipt(self, order, data, user):
        from apps.inventory.models import Warehouse

        warehouse_id = data.get("warehouse")
        if not warehouse_id:
            raise ValueError("Active warehouse required for receiving goods.")

        warehouse = Warehouse.objects.get(pk=warehouse_id)

        receipt = GoodsReceipt.objects.create(
            company=self.company,
            purchase_order=order,
            warehouse=warehouse,
            receipt_date=timezone.now().date(),
            received_by=user,
            status=GoodsReceipt.Status.COMPLETED,
            notes=data.get("notes", ""),
        )
        receipt.number = BaseService.generate_sequence_number(
            "GRN", GoodsReceipt, self.company.pk
        )
        receipt.save(update_fields=["number"])

        all_received = True
        lines_created = 0

        for line in order.lines.all():
            qty_input = data.get(f"qty_{line.pk}")
            if not qty_input:
                if line.qty_received < line.quantity:
                    all_received = False
                continue

            qty = Decimal(str(qty_input))
            if qty > 0:
                GoodsReceiptLine.objects.create(
                    goods_receipt=receipt,
                    po_line=line,
                    quantity_received=qty,
                    quantity_accepted=qty,
                    batch_number=data.get(f"batch_{line.pk}", ""),
                )
                line.qty_received += qty
                line.save(update_fields=["qty_received"])
                lines_created += 1

                # Update stock level
                if line.product and receipt.warehouse:
                    from apps.inventory.services import StockService

                    StockService(company=self.company).receive_stock(
                        product=line.product,
                        warehouse=receipt.warehouse,
                        qty=qty,
                        unit_cost=line.unit_price,
                        reference_type="GoodsReceipt",
                        reference_id=str(receipt.pk),
                        notes=f"Received against PO {order.number}",
                        user=user,
                    )

            if line.qty_received < line.quantity:
                all_received = False

        if lines_created == 0:
            receipt.delete()
            raise ValueError("No quantities provided to receive.")

        # Update PO status
        order.status = (
            PurchaseOrder.Status.RECEIVED
            if all_received
            else PurchaseOrder.Status.PARTIAL
        )
        order.save(update_fields=["status"])

        self.log_activity(
            action="received",
            module="purchase",
            resource_type="PurchaseOrder",
            resource_id=order.pk,
            description=f"Created Goods Receipt {receipt.number} for PO {order.number}",
        )
        return receipt


class PaymentService(BaseService):
    @transaction.atomic
    def record_vendor_payment(self, bill, data):
        amount = Decimal(data.get("amount", "0"))
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        payment = Payment(
            company=self.company,
            bill=bill,
            vendor=bill.vendor,
            amount=amount,
            currency=bill.currency,
            payment_date=data.get("payment_date") or timezone.now().date(),
            method=data.get("method", "bank_transfer"),
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            status="completed",
        )
        payment.number = BaseService.generate_sequence_number(
            "VPAY", Payment, self.company.pk
        )
        payment.save()  # triggers bill.update_balance()

        self.log_activity(
            action="payment_sent",
            module="purchase",
            resource_type="Bill",
            resource_id=bill.pk,
            description=f"Processed {payment.currency.code if payment.currency else ''} {amount} payment for bill {bill.number}",
        )
        return payment


class RFQService(BaseService):
    @transaction.atomic
    def create_rfq(self, data, user):
        rfq = RequestForQuotation(
            company=self.company,
            title=data.get("title"),
            deadline=data.get("deadline"),
            delivery_date=data.get("delivery_date") or None,
            created_by=user,
            status=RequestForQuotation.Status.DRAFT,
        )
        rfq.number = BaseService.generate_sequence_number(
            "RFQ", RequestForQuotation, self.company.pk
        )
        rfq.save()

        products = data.getlist("product[]")
        quantities = data.getlist("quantity[]")
        descriptions = data.getlist("description[]")

        for i, prod_id in enumerate(products):
            if prod_id or descriptions[i]:
                RFQLine.objects.create(
                    rfq=rfq,
                    product_id=prod_id if prod_id else None,
                    quantity=(
                        Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
                    ),
                    description=descriptions[i],
                )

        self.log_activity(
            action="created",
            module="purchase",
            resource_type="RequestForQuotation",
            resource_id=rfq.pk,
            description=f"Created RFQ {rfq.number}",
        )
        return rfq

    @transaction.atomic
    def update_rfq(self, rfq, data):
        if rfq.status != "draft":
            raise ValueError("Only draft RFQs can be edited.")

        rfq.title = data.get("title")
        rfq.deadline = data.get("deadline")
        rfq.delivery_date = data.get("delivery_date") or None
        rfq.save()

        rfq.lines.all().delete()
        products = data.getlist("product[]")
        quantities = data.getlist("quantity[]")
        descriptions = data.getlist("description[]")

        for i, prod_id in enumerate(products):
            if prod_id or descriptions[i]:
                RFQLine.objects.create(
                    rfq=rfq,
                    product_id=prod_id if prod_id else None,
                    quantity=(
                        Decimal(str(quantities[i])) if quantities[i] else Decimal("1")
                    ),
                    description=descriptions[i],
                )

        self.log_activity(
            action="updated",
            module="purchase",
            resource_type="RequestForQuotation",
            resource_id=rfq.pk,
            description=f"Updated RFQ {rfq.number}",
        )
        return rfq


class VendorBidService(BaseService):
    @transaction.atomic
    def create_bid(self, rfq, data):
        bid, created = VendorBid.objects.get_or_create(
            company=self.company,
            rfq=rfq,
            vendor_id=data["vendor"],
            defaults={
                "bid_date": timezone.now().date(),
                "valid_until": data.get("valid_until") or None,
                "total_amount": 0,
                "status": VendorBid.Status.PENDING,
                "notes": data.get("notes", ""),
            },
        )
        if not created:
            bid.lines.all().delete()
            bid.valid_until = data.get("valid_until") or None
            bid.notes = data.get("notes", "")
            bid.status = VendorBid.Status.PENDING

        bid.save()

        total = Decimal("0")
        prices = data.getlist("price[]")

        for i, line in enumerate(rfq.lines.all()):
            price = (
                Decimal(str(prices[i]))
                if (i < len(prices) and prices[i])
                else Decimal("0")
            )
            line_total = price * line.quantity
            total += line_total

            VendorBidLine.objects.create(
                bid=bid, rfq_line=line, unit_price=price, subtotal=line_total
            )

        bid.total_amount = total
        bid.save(update_fields=["total_amount"])

        self.log_activity(
            action="created" if created else "updated",
            module="purchase",
            resource_type="VendorBid",
            resource_id=bid.pk,
            description="Received bid from vendor",
        )
        return bid

    @transaction.atomic
    def accept_bid(self, bid, user):
        if bid.status != VendorBid.Status.PENDING:
            raise ValueError("Only submitted bids can be accepted.")

        po = PurchaseOrder.objects.create(
            company=self.company,
            number=BaseService.generate_sequence_number(
                "PO", PurchaseOrder, self.company.pk
            ),
            vendor=bid.vendor,
            order_date=timezone.now().date(),
            payment_terms=bid.vendor.payment_terms or 30,
            currency=bid.vendor.currency,
            notes=f"Generated from Bid for RFQ {bid.rfq.number}",
        )

        subtotal = Decimal("0")
        for bline in bid.lines.all():
            qty = bline.rfq_line.quantity
            price = bline.unit_price
            line_total = qty * price
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                product=bline.rfq_line.product,
                description=bline.rfq_line.description,
                quantity=qty,
                unit_price=price,
                subtotal=line_total,
                total=line_total,
            )
            subtotal += line_total

        po.subtotal = subtotal
        po.total = subtotal
        po.balance_due = subtotal
        po.save(update_fields=["subtotal", "total", "balance_due"])

        # Update bid and RFQ status
        bid.status = VendorBid.Status.ACCEPTED
        bid.save(update_fields=["status"])

        VendorBid.objects.filter(rfq=bid.rfq, status=VendorBid.Status.PENDING).update(
            status=VendorBid.Status.REJECTED
        )

        rfq = bid.rfq
        if rfq:
            rfq.status = RequestForQuotation.Status.CLOSED
            rfq.save(update_fields=["status"])

        self.log_activity(
            action="accepted",
            module="purchase",
            resource_type="VendorBid",
            resource_id=bid.pk,
            description=f"Accepted bid and generated PO {po.number}",
        )
        return po
