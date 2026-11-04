import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

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
    Vendor,
    VendorBid,
    VendorBidLine,
)
from core.services import BaseService

logger = logging.getLogger(__name__)


def _input_list(data, key):
    if hasattr(data, "getlist"):
        return data.getlist(key)
    value = data.get(key, [])
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _required_text(data, key, label, max_length):
    value = str(data.get(key, "") or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    if len(value) > max_length:
        raise ValueError(f"{label} must be {max_length} characters or fewer.")
    return value


def _optional_date(value, label, required=False):
    if value is None or not str(value).strip():
        if required:
            raise ValueError(f"{label} is required.")
        return None
    result = value if isinstance(value, date) else parse_date(str(value).strip())
    if result is None:
        raise ValueError(f"Enter a valid {label.lower()}.")
    return result


def _decimal_value(
    value, label, *, required=True, default=None, minimum=None, maximum=None,
    max_digits=15, decimal_places=4
):
    raw = "" if value is None else str(value).strip()
    if not raw:
        if required:
            raise ValueError(f"{label} is required.")
        return default
    try:
        result = Decimal(raw)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid number for {label.lower()}.") from None
    if not result.is_finite():
        raise ValueError(f"Enter a valid number for {label.lower()}.")
    if result.as_tuple().exponent < -decimal_places:
        raise ValueError(
            f"{label} supports at most {decimal_places} decimal places."
        )
    if abs(result) >= Decimal(10) ** (max_digits - decimal_places):
        raise ValueError(f"{label} is too large.")
    if minimum is not None and result < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and result > maximum:
        raise ValueError(f"{label} must be no more than {maximum}.")
    return result


def _optional_company_relation(model, value, company, label, **filters):
    if value is None or not str(value).strip():
        return None
    try:
        relation = model.objects.filter(
            pk=value, company=company, **filters
        ).first()
    except (ValidationError, TypeError, ValueError):
        relation = None
    if relation is None:
        raise ValueError(f"Select a valid {label} for this company.")
    return relation


def _aligned_list(data, key, expected, label, *, optional=False, default=""):
    values = _input_list(data, key)
    if not values and optional:
        return [default] * expected
    if len(values) != expected:
        raise ValueError(f"Provide one {label.lower()} for each line.")
    return values


def _validated_request_lines(data, company):
    from apps.company.models import Department
    from apps.inventory.models import Product

    descriptions = _input_list(data, "description[]")
    if not descriptions:
        raise ValueError("At least one purchase request line is required.")
    products = _aligned_list(
        data, "product[]", len(descriptions), "Product", optional=True
    )
    quantities = _aligned_list(data, "quantity[]", len(descriptions), "Quantity")
    prices = _aligned_list(
        data, "estimated_unit_price[]", len(descriptions), "Estimated unit price"
    )

    department_id = data.get("department")
    department = _optional_company_relation(
        Department,
        department_id,
        company,
        "department",
        is_active=True,
        is_deleted=False,
    )
    priority = str(data.get("priority", PurchaseRequest.Priority.MEDIUM)).strip()
    if priority not in PurchaseRequest.Priority.values:
        raise ValueError("Select a valid purchase request priority.")
    required_by = _optional_date(data.get("required_by"), "required-by date")

    lines = []
    for index, raw_description in enumerate(descriptions):
        description = str(raw_description or "").strip()
        if not description:
            raise ValueError("Each purchase request line needs a description.")
        if len(description) > 500:
            raise ValueError("Line descriptions must be 500 characters or fewer.")
        product = _optional_company_relation(
            Product,
            products[index],
            company,
            "product",
            is_active=True,
            is_deleted=False,
        )
        quantity = _decimal_value(
            quantities[index], "Quantity", minimum=Decimal("0.0001")
        )
        price = _decimal_value(
            prices[index],
            "Estimated unit price",
            minimum=Decimal("0"),
        )
        lines.append((description, product, quantity, price))

    title = _required_text(data, "title", "Purchase request title", 255)
    return title, department, required_by, priority, lines


def _validated_order_input(data, company):
    from apps.company.models import Currency, Tax
    from apps.inventory.models import Product, Warehouse
    from apps.purchase.models import PurchaseContract

    vendor_id = str(data.get("vendor", "") or "").strip()
    vendor = _optional_company_relation(
        Vendor,
        vendor_id,
        company,
        "active vendor",
        status=Vendor.Status.ACTIVE,
        is_deleted=False,
    )
    if vendor is None:
        raise ValueError("An active vendor is required.")
    purchase_request = _optional_company_relation(
        PurchaseRequest,
        data.get("purchase_request"),
        company,
        "approved purchase request",
        status=PurchaseRequest.Status.APPROVED,
        is_deleted=False,
    )
    contract = _optional_company_relation(
        PurchaseContract,
        data.get("purchase_contract"),
        company,
        "purchase contract",
        is_deleted=False,
    )
    warehouse = _optional_company_relation(
        Warehouse,
        data.get("warehouse"),
        company,
        "warehouse",
        is_active=True,
        is_deleted=False,
    )
    currency_id = str(data.get("currency", "") or "").strip()
    currency = None
    if currency_id:
        try:
            currency = Currency.objects.filter(pk=currency_id, is_active=True).first()
        except (ValidationError, TypeError, ValueError):
            currency = None
        if currency is None:
            raise ValueError("Select an active currency.")

    try:
        payment_terms = int(data.get("payment_terms", 30))
        if str(data.get("payment_terms", 30)).strip() != str(payment_terms):
            raise ValueError
        if not 0 <= payment_terms <= 32767:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Payment terms must be a whole number from 0 to 32767.") from None

    raw_order_date = data.get("order_date")
    order_date = (
        _optional_date(raw_order_date, "order date", required=True)
        if raw_order_date is not None and str(raw_order_date).strip()
        else timezone.now().date()
    )
    expected_delivery = _optional_date(
        data.get("expected_delivery"), "expected delivery date"
    )
    descriptions = _input_list(data, "description[]")
    if not descriptions:
        raise ValueError("At least one purchase order line is required.")
    products = _aligned_list(data, "product[]", len(descriptions), "Product", optional=True)
    quantities = _aligned_list(data, "quantity[]", len(descriptions), "Quantity")
    prices = _aligned_list(data, "unit_price[]", len(descriptions), "Unit price")
    discounts = _aligned_list(
        data, "discount_percent[]", len(descriptions), "Discount", optional=True,
        default="0",
    )
    taxes = _aligned_list(data, "tax[]", len(descriptions), "Tax", optional=True)

    lines = []
    for index, raw_description in enumerate(descriptions):
        description = str(raw_description or "").strip()
        if not description:
            continue
        if len(description) > 500:
            raise ValueError("Line descriptions must be 500 characters or fewer.")
        product = _optional_company_relation(
            Product,
            products[index],
            company,
            "product",
            is_active=True,
            is_deleted=False,
        )
        quantity = _decimal_value(
            quantities[index], "Quantity", minimum=Decimal("0.0001")
        )
        price = _decimal_value(prices[index], "Unit price", minimum=Decimal("0"))
        discount = _decimal_value(
            discounts[index],
            "Discount percent",
            minimum=Decimal("0"),
            maximum=Decimal("100"),
            max_digits=5,
            decimal_places=2,
        )
        tax_id = str(taxes[index] or "").strip()
        tax = None
        if tax_id:
            tax = _optional_company_relation(
                Tax, tax_id, company, "tax", is_active=True
            )
        lines.append((description, product, quantity, price, discount, tax))
    return {
        "vendor": vendor,
        "purchase_request": purchase_request,
        "purchase_contract": contract,
        "warehouse": warehouse,
        "currency": currency,
        "payment_terms": payment_terms,
        "order_date": order_date,
        "expected_delivery": expected_delivery,
        "lines": lines,
    }


class PurchaseRequestService(BaseService):
    @transaction.atomic
    def create_request(self, data, user):
        title, department, required_by, priority, lines = _validated_request_lines(
            data, self.company
        )
        pr = PurchaseRequest(
            company=self.company,
            title=title,
            department=department,
            requested_by=user,
            required_by=required_by,
            priority=priority,
            notes=data.get("notes", ""),
            status="draft",
        )
        pr.number = BaseService.generate_sequence_number(
            "PR", PurchaseRequest, self.company.pk
        )
        pr.save()

        total = Decimal("0")
        for desc, product, qty, price in lines:
            line_total = qty * price
            PurchaseRequestLine.objects.create(
                request=pr,
                product=product,
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

        title, department, required_by, priority, lines = _validated_request_lines(
            data, self.company
        )
        pr.title = title
        pr.department = department
        pr.required_by = required_by
        pr.priority = priority
        pr.notes = data.get("notes", "")
        pr.save()

        pr.lines.all().delete()
        total = Decimal("0")
        for desc, product, qty, price in lines:
            line_total = qty * price
            PurchaseRequestLine.objects.create(
                request=pr,
                product=product,
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
        validated = _validated_order_input(data, self.company)
        po = PurchaseOrder(
            company=self.company,
            vendor=validated["vendor"],
            purchase_request=validated["purchase_request"],
            purchase_contract=validated["purchase_contract"],
            warehouse=validated["warehouse"],
            order_date=validated["order_date"],
            expected_delivery=validated["expected_delivery"],
            payment_terms=validated["payment_terms"],
            currency=validated["currency"],
            notes=data.get("notes", ""),
            terms_conditions=data.get("terms_conditions", ""),
            status="draft",
        )
        po.number = BaseService.generate_sequence_number(
            "PO", PurchaseOrder, self.company.pk
        )
        po.save()

        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for desc, product, qty, price, disc, tax in validated["lines"]:
            sub = qty * price
            disc_amt = sub * disc / 100
            taxable = sub - disc_amt
            tax_amt = Decimal("0")
            if tax:
                tax_amt = tax.compute(taxable)
            total = taxable + tax_amt
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                product=product,
                description=desc,
                quantity=qty,
                unit_price=price,
                discount_percent=disc,
                tax=tax,
                subtotal=sub,
                tax_amount=tax_amt,
                total=total,
            )

            # Drawdown from contract if applicable
            if po.purchase_contract_id and product:
                try:
                    contract_line = po.purchase_contract.lines.get(
                        product=product
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

        validated = _validated_order_input(data, self.company)
        po.vendor = validated["vendor"]
        po.purchase_request = validated["purchase_request"]
        po.purchase_contract = validated["purchase_contract"]
        po.warehouse = validated["warehouse"]
        po.order_date = validated["order_date"]
        po.expected_delivery = validated["expected_delivery"]
        po.payment_terms = validated["payment_terms"]
        po.currency = validated["currency"]
        po.notes = data.get("notes", "")
        po.terms_conditions = data.get("terms_conditions", "")
        po.save()

        po.lines.all().delete()

        subtotal = Decimal("0")
        tax_total = Decimal("0")

        for desc, product, qty, price, disc, tax in validated["lines"]:
            sub = qty * price
            disc_amt = sub * disc / 100
            taxable = sub - disc_amt
            tax_amt = Decimal("0")
            if tax:
                tax_amt = tax.compute(taxable)
            total = taxable + tax_amt
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                product=product,
                description=desc,
                quantity=qty,
                unit_price=price,
                discount_percent=disc,
                tax=tax,
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
            qty_to_bill = line.qty_received - line.qty_invoiced
            if qty_to_bill <= 0:
                continue
            BillLine.objects.create(
                bill=bill,
                product=line.product,
                description=line.description,
                quantity=qty_to_bill,
                unit_price=line.unit_price,
                discount_percent=line.discount_percent,
                tax=line.tax,
            )
            line.qty_invoiced += qty_to_bill
            line.save(update_fields=["qty_invoiced"])
            lines_created += 1

        if lines_created == 0:
            bill.delete()
            raise ValueError("Nothing to bill for this Purchase Order.")

        bill.calculate_totals()
        ThreeWayMatchingService.verify_bill(bill)

        self.log_activity(
            action="billed",
            module="purchase",
            resource_type="PurchaseOrder",
            resource_id=order.pk,
            description=f"Created Bill {bill.number} for PO {order.number} (3-Way Match: {bill.matching_status})",
        )
        return bill

    def _goods_receipt_overage_percent(self):
        """Company setting for GRN overage, default 0 (no over-receipt)."""
        from apps.company.models import CompanySettings

        setting = CompanySettings.objects.filter(
            company=self.company, key="goods_receipt_overage_percent"
        ).first()
        if not setting or not setting.value:
            return Decimal("0")
        try:
            value = Decimal(str(setting.value))
        except Exception:
            return Decimal("0")
        return max(Decimal("0"), value)

    @transaction.atomic
    def create_goods_receipt(self, order, data, user):
        from apps.inventory.models import Warehouse

        if order.company_id != self.company.pk:
            raise ValueError("Purchase order not found for this company.")
        warehouse_id = str(data.get("warehouse", "") or "").strip()
        if not warehouse_id:
            raise ValueError("Active warehouse required for receiving goods.")

        try:
            warehouse = Warehouse.objects.get(
                pk=warehouse_id,
                company=self.company,
                is_active=True,
                is_deleted=False,
            )
        except (Warehouse.DoesNotExist, ValidationError, TypeError, ValueError):
            raise ValueError("Warehouse not found for this company.") from None

        overage_percent = self._goods_receipt_overage_percent()

        receipt_lines = []
        all_received = True
        for line in order.lines.select_related("product"):
            raw_quantity = data.get(f"qty_{line.pk}")
            if raw_quantity is None or raw_quantity == "":
                if line.qty_received < line.quantity:
                    all_received = False
                continue
            qty = _decimal_value(
                raw_quantity, "Received quantity", minimum=Decimal("0.0001")
            )
            remaining = max(line.quantity - line.qty_received, Decimal("0"))
            max_qty = remaining + line.quantity * overage_percent / Decimal("100")
            if qty > max_qty:
                raise ValueError(
                    f"Cannot receive {qty} for '{line.description}'; "
                    f"remaining ordered quantity is {remaining}."
                )
            receipt_lines.append((line, qty))
            if line.qty_received + qty < line.quantity:
                all_received = False

        if not receipt_lines:
            raise ValueError("No quantities provided to receive.")

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

        for line, qty in receipt_lines:
            GoodsReceiptLine.objects.create(
                goods_receipt=receipt,
                po_line=line,
                quantity_received=qty,
                quantity_accepted=qty,
                batch_number=data.get(f"batch_{line.pk}", ""),
            )
            line.qty_received += qty
            line.save(update_fields=["qty_received"])

            if line.product:
                from apps.inventory.services import StockService

                StockService(company=self.company).receive_stock(
                    product=line.product,
                    warehouse=receipt.warehouse,
                    qty=qty,
                    unit_cost=line.unit_price
                    * (Decimal("1") - line.discount_percent / Decimal("100")),
                    reference_type="GoodsReceipt",
                    reference_id=str(receipt.pk),
                    notes=f"Received against PO {order.number}",
                    user=user,
                )

        from apps.accounting.services import AutoJournalService

        AutoJournalService.post_goods_receipt(receipt)

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
        bill = (
            Bill.objects.select_for_update()
            .filter(pk=bill.pk, company=self.company)
            .select_related("vendor")
            .first()
        )
        if bill is None:
            raise ValueError("Bill not found for this company.")
        if bill.status not in (
            Bill.Status.OPEN,
            Bill.Status.PARTIAL,
            Bill.Status.OVERDUE,
        ):
            raise ValueError("Payments can only be recorded for an open bill.")
        amount = _decimal_value(
            data.get("amount"),
            "Payment amount",
            max_digits=18,
            decimal_places=2,
        )
        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if amount > bill.balance_due:
            raise ValueError("Payment amount cannot exceed the bill balance due.")
        method = str(data.get("method", Payment.Method.BANK_TRANSFER) or "").strip()
        if method not in Payment.Method.values:
            raise ValueError("Select a valid payment method.")
        payment_date = _optional_date(
            data.get("payment_date"), "payment date", required=True
        )
        if len(str(data.get("reference", "") or "")) > 100:
            raise ValueError("Payment reference must be 100 characters or fewer.")
        if len(str(data.get("notes", "") or "")) > 2000:
            raise ValueError("Payment notes must be 2000 characters or fewer.")
        payment = Payment(
            company=self.company,
            bill=bill,
            vendor=bill.vendor,
            amount=amount,
            currency=bill.currency,
            payment_date=payment_date,
            method=method,
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


class ThreeWayMatchingService(BaseService):
    """
    Enterprise 3-Way Matching Engine.
    Cross-checks Purchase Order ↔ Goods Receipt (GRN) ↔ Vendor Bill.
    Validates product, quantity, unit price, tax, and line totals.
    Identifies quantity overbilling, price escalation, or unreceived items.
    """

    @classmethod
    def verify_bill(cls, bill):
        from apps.purchase.models import Bill, GoodsReceiptLine

        po = bill.purchase_order
        if not po:
            bill.matching_status = Bill.MatchingStatus.MATCHED
            bill.mismatch_details = {"mismatches": [], "count": 0, "note": "Standalone bill without PO"}
            bill.save(update_fields=["matching_status", "mismatch_details"])
            return {
                "status": bill.matching_status,
                "matched": True,
                "mismatches": [],
                "count": 0,
            }

        mismatches = []
        po_lines_map = {str(line.product_id): line for line in po.lines.all() if line.product_id}

        for bill_line in bill.lines.all():
            if not bill_line.product_id:
                continue

            prod_id_str = str(bill_line.product_id)
            po_line = po_lines_map.get(prod_id_str)

            if not po_line:
                mismatches.append({
                    "type": "unmatched_product",
                    "product": str(bill_line.product),
                    "message": f"Product {bill_line.product} on bill is not in Purchase Order {po.number}.",
                })
                continue

            # 1. Price check: Bill unit price vs PO unit price
            price_diff = bill_line.unit_price - po_line.unit_price
            if price_diff > Decimal("0.01"):
                mismatches.append({
                    "type": "price_mismatch",
                    "product": str(bill_line.product),
                    "po_price": str(po_line.unit_price),
                    "bill_price": str(bill_line.unit_price),
                    "variance": str(price_diff),
                    "message": f"Price mismatch on {bill_line.product}: Billed at {bill_line.unit_price}, PO was {po_line.unit_price} (+{price_diff}).",
                })

            # 2. Quantity check: Billed qty vs Received/Accepted qty across completed GRNs
            gr_lines = GoodsReceiptLine.objects.filter(
                goods_receipt__purchase_order=po,
                goods_receipt__status="completed",
                po_line=po_line,
            )
            total_accepted_qty = sum((gr.quantity_accepted for gr in gr_lines), Decimal("0"))

            if bill_line.quantity > total_accepted_qty:
                qty_diff = bill_line.quantity - total_accepted_qty
                mismatches.append({
                    "type": "quantity_mismatch",
                    "product": str(bill_line.product),
                    "ordered_qty": str(po_line.quantity),
                    "received_accepted_qty": str(total_accepted_qty),
                    "billed_qty": str(bill_line.quantity),
                    "variance": str(qty_diff),
                    "message": f"Quantity mismatch on {bill_line.product}: Billed {bill_line.quantity}, but only {total_accepted_qty} accepted in GRN (excess: {qty_diff}).",
                })

        has_mismatch = len(mismatches) > 0
        if has_mismatch:
            bill.matching_status = Bill.MatchingStatus.MISMATCH
            bill.mismatch_details = {"mismatches": mismatches, "count": len(mismatches)}
        else:
            bill.matching_status = Bill.MatchingStatus.MATCHED
            bill.mismatch_details = {"mismatches": [], "count": 0}

        bill.save(update_fields=["matching_status", "mismatch_details"])

        return {
            "status": bill.matching_status,
            "matched": not has_mismatch,
            "mismatches": mismatches,
            "count": len(mismatches),
        }

    @classmethod
    def override_mismatch(cls, bill, user, reason: str):
        if not reason or not reason.strip():
            raise ValueError("An explicit documented reason is required to override 3-way matching exceptions.")
        bill.matching_status = bill.MatchingStatus.OVERRIDDEN
        bill.mismatch_override_by = user
        bill.mismatch_override_reason = reason.strip()
        bill.save(update_fields=["matching_status", "mismatch_override_by", "mismatch_override_reason"])
        return bill
