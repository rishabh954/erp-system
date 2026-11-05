from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from core.services import BaseService

from .models import Account, Journal, JournalEntry, JournalItem


def get_open_fiscal_year(company, posting_date, fiscal_year_id=None):
    from apps.company.models import FiscalYear

    fiscal_years = FiscalYear.objects.select_for_update().filter(company=company)
    matching_years = fiscal_years.filter(
        start_date__lte=posting_date, end_date__gte=posting_date
    )
    closed_year = matching_years.filter(
        status__in=(FiscalYear.Status.CLOSED, FiscalYear.Status.LOCKED)
    ).first()
    if closed_year:
        raise ValueError(
            f"Cannot post into {closed_year.get_status_display()} fiscal year "
            f"{closed_year.name}."
        )

    if fiscal_year_id:
        fiscal_year = fiscal_years.filter(pk=fiscal_year_id).first()
        if not fiscal_year:
            raise ValueError("The fiscal year does not belong to this company.")
        if not (
            fiscal_year.start_date <= posting_date <= fiscal_year.end_date
        ):
            raise ValueError("The journal entry date is outside its fiscal year.")
        if fiscal_year.status != FiscalYear.Status.OPEN:
            raise ValueError(
                f"Cannot post into {fiscal_year.get_status_display()} fiscal year "
                f"{fiscal_year.name}."
            )
        return fiscal_year

    fiscal_year = matching_years.filter(status=FiscalYear.Status.OPEN).order_by(
        "-start_date"
    ).first()
    if fiscal_year is None and fiscal_years.exists():
        raise ValueError("No open fiscal year covers the journal entry date.")
    return fiscal_year


class AccountingPostingService:
    """Validate and atomically post a journal entry to the general ledger."""

    @staticmethod
    @transaction.atomic
    def reverse(entry, *, user=None, reversal_date=None, reason=""):
        from .models import AuditLog, JournalItem

        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("A reason is required to reverse a posted journal entry.")
        if len(reason) > 2000:
            raise ValueError("Reversal reason must be 2000 characters or fewer.")

        original = (
            JournalEntry.objects.select_for_update()
            .select_related("company", "journal", "currency")
            .get(pk=entry.pk)
        )
        if original.status != JournalEntry.Status.POSTED:
            raise ValueError("Only posted journal entries can be reversed.")
        if original.is_deleted:
            raise ValueError("A deleted journal entry cannot be reversed.")

        existing = (
            JournalEntry.objects.select_for_update()
            .filter(
                company=original.company,
                reversal_of=original,
                is_reversal=True,
            )
            .first()
        )
        if existing:
            if existing.status == JournalEntry.Status.POSTED:
                return existing
            raise ValueError("A reversal already exists but is not posted.")

        reversal_date = reversal_date or timezone.localdate()
        reversal = JournalEntry.objects.create(
            company=original.company,
            journal=original.journal,
            date=reversal_date,
            reference=f"REV: {original.number}",
            status=JournalEntry.Status.DRAFT,
            currency=original.currency,
            exchange_rate=original.exchange_rate,
            total_debit=original.total_credit,
            total_credit=original.total_debit,
            is_reversal=True,
            reversal_of=original,
            source_type="journal_reversal",
            source_id=str(original.pk),
            notes=f"Reversal of {original.number}: {reason}",
        )

        for item in original.items.select_related("account", "cost_center", "tax"):
            JournalItem.objects.create(
                journal_entry=reversal,
                account=item.account,
                description=f"Reversal: {item.description}"[:500],
                debit=item.credit,
                credit=item.debit,
                currency=item.currency,
                amount_currency=item.amount_currency,
                partner_type=item.partner_type,
                partner_id=item.partner_id,
                tax=item.tax,
                cost_center=item.cost_center,
            )

        reversal.post(user=user)
        AuditLog.objects.create(
            company=original.company,
            journal_entry=original,
            action=AuditLog.Action.REVERSED,
            user=user,
            notes=reason,
        )
        return reversal

    @staticmethod
    @transaction.atomic
    def post(entry, user=None):
        from django.utils import timezone

        from .models import AuditLog, JournalItem

        locked_entry = (
            JournalEntry.objects.select_for_update()
            .select_related("company", "journal")
            .get(pk=entry.pk)
        )
        if locked_entry.status == JournalEntry.Status.POSTED:
            return locked_entry
        if locked_entry.status != JournalEntry.Status.DRAFT:
            raise ValueError("Only draft journal entries can be posted.")
        if locked_entry.is_deleted:
            raise ValueError("A deleted journal entry cannot be posted.")
        if (
            locked_entry.journal.company_id != locked_entry.company_id
            or not locked_entry.journal.is_active
        ):
            raise ValueError("Journal must be active and belong to the entry company.")
        if (
            locked_entry.company.accounting_lock_date
            and locked_entry.date <= locked_entry.company.accounting_lock_date
        ):
            raise ValueError(
                f"Cannot post entry before lock date: "
                f"{locked_entry.company.accounting_lock_date}"
            )

        locked_entry.fiscal_year = get_open_fiscal_year(
            locked_entry.company,
            locked_entry.date,
            locked_entry.fiscal_year_id,
        )

        items = list(
            JournalItem.objects.select_for_update()
            .filter(journal_entry=locked_entry)
            .select_related("account", "cost_center")
            .order_by("account_id", "pk")
        )
        if len(items) < 2:
            raise ValueError("A journal entry must contain at least two lines.")

        account_ids = sorted({item.account_id for item in items})
        accounts = {
            account.pk: account
            for account in Account.objects.select_for_update().filter(
                pk__in=account_ids
            )
        }
        if len(accounts) != len(account_ids):
            raise ValueError("Every journal account must exist.")

        debit_total = Decimal("0")
        credit_total = Decimal("0")
        for item in items:
            account = accounts[item.account_id]
            if account.company_id != locked_entry.company_id:
                raise ValueError("Journal accounts must belong to the entry company.")
            if not account.is_active or not account.allow_journal_entries:
                raise ValueError("Journal accounts must be active and allow entries.")
            if account.is_deleted:
                raise ValueError("Deleted accounts cannot be posted to.")
            if (item.debit < 0 or item.credit < 0) or (
                (item.debit > 0) == (item.credit > 0)
            ):
                raise ValueError(
                    "Each journal line must have one positive debit or credit."
                )
            if item.cost_center_id and (
                item.cost_center.company_id != locked_entry.company_id
                or not item.cost_center.is_active
                or item.cost_center.is_deleted
            ):
                raise ValueError(
                    "Cost centers must be active and belong to the entry company."
                )
            debit_total += item.debit
            credit_total += item.credit

        if debit_total <= 0 or debit_total != credit_total:
            raise ValueError(
                f"Journal entry {locked_entry.number} is not balanced "
                "with positive debit and credit totals."
            )

        locked_entry.total_debit = debit_total
        locked_entry.total_credit = credit_total
        locked_entry.status = JournalEntry.Status.POSTED
        locked_entry.posted_at = timezone.now()
        if user:
            locked_entry.posted_by = user
        locked_entry._posting_authorized = True
        try:
            locked_entry.save(
                update_fields=[
                    "status",
                    "posted_at",
                    "posted_by",
                    "fiscal_year",
                    "total_debit",
                    "total_credit",
                ]
            )
        finally:
            del locked_entry._posting_authorized

        for item in items:
            account = accounts[item.account_id]
            if account.account_type in ("asset", "expense", "cogs", "bank"):
                account.current_balance += item.debit - item.credit
            else:
                account.current_balance += item.credit - item.debit
            account.save(update_fields=["current_balance"])

        AuditLog.objects.create(
            company=locked_entry.company,
            journal_entry=locked_entry,
            action=AuditLog.Action.POSTED,
            user=user,
        )
        entry.status = locked_entry.status
        entry.posted_at = locked_entry.posted_at
        entry.posted_by = locked_entry.posted_by
        entry.fiscal_year = locked_entry.fiscal_year
        entry.total_debit = debit_total
        entry.total_credit = credit_total
        return locked_entry


class AutoJournalService:
    @staticmethod
    def _lock_source_and_get_existing(source, company, reference):
        from django.db.models import Model

        if isinstance(source, Model) and source.pk:
            source = source.__class__.objects.select_for_update().get(pk=source.pk)
            if source.company_id != company.pk:
                raise ValueError("Source transaction belongs to another company.")

        existing = (
            JournalEntry.objects.select_for_update()
            .filter(company=company, reference=reference)
            .first()
        )
        if existing and existing.status != JournalEntry.Status.POSTED:
            raise ValueError(
                f"Journal entry {reference} already exists and is not posted."
            )
        return source, existing

    @staticmethod
    def get_or_create_journal(company, journal_type):
        name_map = {
            "sales": "Sales Journal",
            "purchase": "Purchase Journal",
            "cash": "Cash & Bank Journal",
            "general": "General Journal",
        }
        journal, created = Journal.objects.get_or_create(
            company=company,
            journal_type=journal_type,
            defaults={
                "name": name_map.get(journal_type, "Journal"),
                "code": journal_type[:3].upper(),
            },
        )
        return journal

    @staticmethod
    def get_or_create_ar(company):
        if company.default_receivable_account:
            return company.default_receivable_account
        ar, _ = Account.objects.get_or_create(
            company=company,
            code="1200",
            defaults={
                "name": "Accounts Receivable",
                "account_type": "asset",
                "account_subtype": "accounts_receivable",
            },
        )
        company.default_receivable_account = ar
        company.save(update_fields=["default_receivable_account"])
        return ar

    @staticmethod
    def get_or_create_ap(company):
        if company.default_payable_account:
            return company.default_payable_account
        ap, _ = Account.objects.get_or_create(
            company=company,
            code="2000",
            defaults={
                "name": "Accounts Payable",
                "account_type": "liability",
                "account_subtype": "accounts_payable",
            },
        )
        company.default_payable_account = ap
        company.save(update_fields=["default_payable_account"])
        return ap

    @staticmethod
    def get_or_create_bank(company):
        if company.default_bank_account:
            return company.default_bank_account
        bank, _ = Account.objects.get_or_create(
            company=company,
            code="1000",
            defaults={
                "name": "Main Bank Account",
                "account_type": "asset",
                "account_subtype": "bank",
            },
        )
        company.default_bank_account = bank
        company.save(update_fields=["default_bank_account"])
        return bank

    @staticmethod
    def get_or_create_cogs(company):
        account, _ = Account.objects.get_or_create(
            company=company,
            code="5000",
            defaults={
                "name": "Cost of Goods Sold",
                "account_type": Account.AccountType.COGS,
            },
        )
        return account

    @staticmethod
    def get_or_create_inventory(company):
        account, _ = Account.objects.get_or_create(
            company=company,
            code="1400",
            defaults={
                "name": "Inventory Asset",
                "account_type": Account.AccountType.ASSET,
                "account_subtype": Account.AccountSubtype.CURRENT_ASSET,
            },
        )
        return account

    @staticmethod
    def get_or_create_grni(company):
        account, _ = Account.objects.get_or_create(
            company=company,
            code="2105",
            defaults={
                "name": "Goods Received Not Invoiced",
                "account_type": Account.AccountType.LIABILITY,
                "account_subtype": Account.AccountSubtype.CURRENT_LIABILITY,
            },
        )
        return account

    @staticmethod
    def _company_account(account, company, fallback):
        if account is None:
            return fallback
        if account.company_id != company.pk:
            raise ValueError("Product accounting account belongs to another company.")
        return account

    @staticmethod
    @transaction.atomic
    def post_sales_invoice(invoice):
        company = invoice.company
        reference = f"INV: {invoice.number}"
        invoice, existing = AutoJournalService._lock_source_and_get_existing(
            invoice, company, reference
        )
        if existing:
            return existing

        ar_account = AutoJournalService.get_or_create_ar(company)

        revenue_account = None
        # We can just use the first line's revenue account, or a company default
        if (
            invoice.lines.exists()
            and invoice.lines.first().product
            and invoice.lines.first().product.revenue_account
        ):
            revenue_account = invoice.lines.first().product.revenue_account
        else:
            # Fallback to a newly created/fetched Revenue account
            revenue_account, _ = Account.objects.get_or_create(
                company=company,
                code="4000",
                defaults={"name": "Sales Revenue", "account_type": "revenue"},
            )

        journal = AutoJournalService.get_or_create_journal(company, "sales")

        invoice_total = invoice.total or Decimal("0")
        # The persisted invoice total is authoritative (some legacy/imported
        # invoices have totals but no subtotal); tax remains a separate credit.
        revenue_credit = invoice_total - (invoice.tax_amount or Decimal("0"))

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=invoice.invoice_date or timezone.now().date(),
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=invoice.currency,
            total_debit=invoice_total,
            total_credit=invoice_total,
            source_type="sales_invoice",
            source_id=str(invoice.pk) if getattr(invoice, "pk", None) else "",
        )


        # Debit A/R (Total)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ar_account,
            description=f"Receivable for {invoice.number}",
            debit=invoice_total,
            credit=0,
            partner_type="customer",
            partner_id=str(invoice.customer.id),
        )

        # Discounts reduce recognized revenue, while tax remains a separate liability.
        JournalItem.objects.create(
            journal_entry=entry,
            account=revenue_account,
            description=f"Revenue for {invoice.number}",
            debit=0,
            credit=revenue_credit,
            partner_type="customer",
            partner_id=str(invoice.customer.id),
        )

        # Credit Tax (if any)
        if invoice.tax_amount > 0:
            tax_account, _ = Account.objects.get_or_create(
                company=company,
                code="2100",
                defaults={
                    "name": "Sales Tax Payable",
                    "account_type": "liability",
                    "account_subtype": "current_liability",
                },
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=tax_account,
                description=f"Tax for {invoice.number}",
                debit=0,
                credit=invoice.tax_amount,
            )

        entry.post()

        return entry

    @staticmethod
    @transaction.atomic
    def post_credit_note(credit_note):
        """
        Post journal entry for a Credit Note (Customer Return / Allowance).
        Debit: Sales Returns & Allowances  (amount)
        Credit: Accounts Receivable         (amount)
        SUM(Debit) == SUM(Credit).
        CreditNote model has: amount, customer, invoice(FK), date, number, company.
        No tax_amount / subtotal / currency fields — amount is the net total.
        """
        from decimal import Decimal

        company = credit_note.company
        reference = f"CN: {credit_note.number}"
        credit_note, existing = AutoJournalService._lock_source_and_get_existing(
            credit_note, company, reference
        )
        if existing:
            return existing

        ar_account = AutoJournalService.get_or_create_ar(company)

        return_account, _ = Account.objects.get_or_create(
            company=company,
            code="4100",
            defaults={"name": "Sales Returns & Allowances", "account_type": "revenue"},
        )

        journal = AutoJournalService.get_or_create_journal(company, "sales")
        total_amount = credit_note.amount or Decimal("0")

        # Derive currency from linked invoice or fall back to company default
        currency = None
        if credit_note.invoice_id:
            currency = getattr(credit_note.invoice, "currency", None)
        if not currency:
            currency = getattr(company, "default_currency", None)

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=credit_note.date or timezone.now().date(),
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=currency,
            total_debit=total_amount,
            total_credit=total_amount,
            source_type="credit_note",
            source_id=str(credit_note.pk) if getattr(credit_note, "pk", None) else "",
        )

        # Debit Sales Returns & Allowances
        JournalItem.objects.create(
            journal_entry=entry,
            account=return_account,
            description=f"Sales Return for {credit_note.number}",
            debit=total_amount,
            credit=0,
            partner_type="customer",
            partner_id=str(credit_note.customer.id),
        )

        # Credit Accounts Receivable
        JournalItem.objects.create(
            journal_entry=entry,
            account=ar_account,
            description=f"Credit Note for {credit_note.number}",
            debit=0,
            credit=total_amount,
            partner_type="customer",
            partner_id=str(credit_note.customer.id),
        )

        entry.post()
        return entry

    @staticmethod
    @transaction.atomic
    def post_delivery(delivery, movements=None):
        from apps.inventory.models import DeliveryOrder, StockMovement

        delivery = DeliveryOrder.objects.select_for_update().get(pk=delivery.pk)

        company = delivery.company
        reference = f"DEL: {delivery.number}"
        existing = (
            JournalEntry.objects.select_for_update()
            .filter(company=company, reference=reference)
            .first()
        )
        if existing:
            if existing.status == JournalEntry.Status.POSTED:
                return existing
            raise ValueError(f"Delivery journal {reference} already exists but is not posted.")

        movements = list(
            movements
            if movements is not None
            else StockMovement.objects.filter(
                company=company,
                reference_type="DeliveryOrder",
                reference_id=str(delivery.pk),
            ).select_related("product")
        )
        if not movements:
            return None

        journal = AutoJournalService.get_or_create_journal(company, "general")
        currency = getattr(delivery.sales_order, "currency", None)
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=timezone.localdate(),
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=currency,
            total_debit=Decimal("0"),
            total_credit=Decimal("0"),
            source_type="delivery",
            source_id=str(delivery.pk),
        )

        total_cost = Decimal("0")
        for movement in movements:
            amount = abs(Decimal(movement.total_cost or 0))
            if amount == 0:
                continue
            product = movement.product
            cogs_account = product.cogs_account if product else None
            inventory_account = product.inventory_account if product else None
            cogs = AutoJournalService._company_account(
                cogs_account,
                company,
                AutoJournalService.get_or_create_cogs(company)
                if cogs_account is None
                else None,
            )
            inventory = AutoJournalService._company_account(
                inventory_account,
                company,
                AutoJournalService.get_or_create_inventory(company)
                if inventory_account is None
                else None,
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=cogs,
                description=f"COGS for {delivery.number}",
                debit=amount,
                credit=0,
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=inventory,
                description=f"Inventory shipped via {delivery.number}",
                debit=0,
                credit=amount,
            )
            total_cost += amount

        if total_cost == 0:
            entry.delete()
            return None

        entry.total_debit = total_cost
        entry.total_credit = total_cost
        entry.save(update_fields=["total_debit", "total_credit"])
        entry.post()
        return entry

    @staticmethod
    @transaction.atomic
    def post_goods_receipt(receipt):
        from decimal import ROUND_HALF_UP

        from apps.purchase.models import GoodsReceipt

        receipt = (
            GoodsReceipt.objects.select_for_update()
            .select_related("company", "purchase_order")
            .get(pk=receipt.pk)
        )
        company = receipt.company
        reference = f"GRN: {receipt.number}"
        existing = (
            JournalEntry.objects.select_for_update()
            .filter(company=company, reference=reference)
            .first()
        )
        if existing:
            if existing.status == JournalEntry.Status.POSTED:
                return existing
            raise ValueError(f"Goods receipt journal {reference} already exists but is not posted.")

        grni = AutoJournalService.get_or_create_grni(company)
        journal = AutoJournalService.get_or_create_journal(company, "purchase")
        currency = getattr(receipt.purchase_order, "currency", None)
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=receipt.receipt_date,
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=currency,
            total_debit=Decimal("0"),
            total_credit=Decimal("0"),
            source_type="goods_receipt",
            source_id=str(receipt.purchase_order_id),
        )

        total_value = Decimal("0")
        for line in receipt.lines.select_related("po_line__product"):
            product = line.po_line.product
            if not product:
                continue
            unit_cost = line.po_line.unit_price * (
                Decimal("1") - line.po_line.discount_percent / Decimal("100")
            )
            amount = (line.quantity_received * unit_cost).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if amount <= 0:
                continue
            inventory = AutoJournalService._company_account(
                product.inventory_account,
                company,
                AutoJournalService.get_or_create_inventory(company)
                if product.inventory_account is None
                else None,
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=inventory,
                description=f"Inventory received via {receipt.number}",
                debit=amount,
                credit=0,
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=grni,
                description=f"Goods received not invoiced: {receipt.number}",
                debit=0,
                credit=amount,
            )
            total_value += amount

        if total_value == 0:
            entry.delete()
            return None

        entry.total_debit = total_value
        entry.total_credit = total_value
        entry.save(update_fields=["total_debit", "total_credit"])
        entry.post(user=receipt.received_by)
        return entry

    @staticmethod
    @transaction.atomic
    def post_sales_payment(payment):
        company = payment.company
        reference = f"PAY: {payment.number}"
        payment, existing = AutoJournalService._lock_source_and_get_existing(
            payment, company, reference
        )
        if existing:
            return existing

        ar_account = AutoJournalService.get_or_create_ar(company)
        bank_account = AutoJournalService.get_or_create_bank(company)

        journal = AutoJournalService.get_or_create_journal(company, "cash")

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=payment.payment_date,
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=payment.currency,
            total_debit=payment.amount,
            total_credit=payment.amount,
            source_type="sales_payment",
            source_id=str(payment.pk) if getattr(payment, "pk", None) else "",
        )


        # Debit Bank (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=bank_account,
            description=f"Payment Received {payment.number}",
            debit=payment.amount,
            credit=0,
            partner_type="customer",
            partner_id=str(payment.invoice.customer.id) if payment.invoice else "",
        )

        # Credit A/R (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ar_account,
            description=f"Payment for {payment.invoice.number if payment.invoice else ''}",
            debit=0,
            credit=payment.amount,
            partner_type="customer",
            partner_id=str(payment.invoice.customer.id) if payment.invoice else "",
        )
        entry.post()
        return entry

    @staticmethod
    @transaction.atomic
    def post_purchase_bill(bill):
        company = bill.company
        reference = f"BILL: {bill.number}"
        bill, existing = AutoJournalService._lock_source_and_get_existing(
            bill, company, reference
        )
        if existing:
            return existing

        ap_account = AutoJournalService.get_or_create_ap(company)

        expense_account = None
        if (
            bill.lines.exists()
            and bill.lines.first().product
            and bill.lines.first().product.cogs_account
        ):
            expense_account = bill.lines.first().product.cogs_account
        else:
            expense_account, _ = Account.objects.get_or_create(
                company=company,
                code="5000",
                defaults={"name": "General Expenses", "account_type": "expense"},
            )

        journal = AutoJournalService.get_or_create_journal(company, "purchase")

        # Use the persisted total so imported bills with incomplete subtotal
        # fields still post a balanced entry; tax is debited separately below.
        purchase_cost = (bill.total or Decimal("0")) - (
            bill.tax_amount or Decimal("0")
        )
        grni_account = Account.objects.filter(company=company, code="2105").first()
        grni_to_clear = Decimal("0")
        if bill.purchase_order_id and grni_account:
            from django.db.models import Sum

            grni_balance = JournalItem.objects.filter(
                account=grni_account,
                journal_entry__company=company,
                journal_entry__source_id=str(bill.purchase_order_id),
                journal_entry__source_type__in=("goods_receipt", "purchase_bill"),
                journal_entry__status=JournalEntry.Status.POSTED,
            ).aggregate(
                debit=Sum("debit"),
                credit=Sum("credit"),
            )
            available_grni = (grni_balance["credit"] or Decimal("0")) - (
                grni_balance["debit"] or Decimal("0")
            )
            grni_to_clear = min(purchase_cost, max(available_grni, Decimal("0")))
        expense_amount = purchase_cost - grni_to_clear

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=bill.bill_date or timezone.now().date(),
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=bill.currency,
            total_debit=bill.total,
            total_credit=bill.total,
            source_type="purchase_bill",
            source_id=str(bill.purchase_order_id or bill.pk),
        )


        # Credit A/P (Total)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ap_account,
            description=f"Payable for {bill.number}",
            debit=0,
            credit=bill.total,
            partner_type="vendor",
            partner_id=str(bill.vendor.id),
        )

        if grni_to_clear > 0:
            JournalItem.objects.create(
                journal_entry=entry,
                account=grni_account,
                description=f"Clear goods received for {bill.number}",
                debit=grni_to_clear,
                credit=0,
                partner_type="vendor",
                partner_id=str(bill.vendor.id),
            )

        if expense_amount > 0:
            JournalItem.objects.create(
                journal_entry=entry,
                account=expense_account,
                description=f"Expense for {bill.number}",
                debit=expense_amount,
                credit=0,
                partner_type="vendor",
                partner_id=str(bill.vendor.id),
            )

        # Debit Tax (if any)
        if bill.tax_amount > 0:
            tax_account, _ = Account.objects.get_or_create(
                company=company,
                code="1300",
                defaults={
                    "name": "Purchase Tax Receivable",
                    "account_type": "asset",
                    "account_subtype": "current_asset",
                },
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=tax_account,
                description=f"Tax for {bill.number}",
                debit=bill.tax_amount,
                credit=0,
            )

        entry.post()

        return entry

    @staticmethod
    @transaction.atomic
    def post_purchase_payment(payment):
        company = payment.company
        reference = f"VPAY: {payment.number}"
        payment, existing = AutoJournalService._lock_source_and_get_existing(
            payment, company, reference
        )
        if existing:
            return existing

        ap_account = AutoJournalService.get_or_create_ap(company)
        bank_account = AutoJournalService.get_or_create_bank(company)

        journal = AutoJournalService.get_or_create_journal(company, "cash")

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=payment.payment_date,
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            currency=payment.currency,
            total_debit=payment.amount,
            total_credit=payment.amount,
            source_type="purchase_payment",
            source_id=str(payment.pk) if getattr(payment, "pk", None) else "",
        )


        # Debit A/P (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ap_account,
            description=f"Payment for {payment.bill.number if payment.bill else ''}",
            debit=payment.amount,
            credit=0,
            partner_type="vendor",
            partner_id=str(payment.vendor.id) if payment.vendor else "",
        )

        # Credit Bank (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=bank_account,
            description=f"Vendor Payment {payment.number}",
            debit=0,
            credit=payment.amount,
            partner_type="vendor",
            partner_id=str(payment.vendor.id) if payment.vendor else "",
        )
        entry.post()
        return entry


class FinancialReportingService:
    @staticmethod
    def get_opening_balance_as_of(account, as_of_date=None):
        if (
            account.opening_balance_date
            and as_of_date
            and account.opening_balance_date > as_of_date
        ):
            return Decimal("0")
        if JournalEntry.objects.filter(
            company_id=account.company_id,
            status=JournalEntry.Status.POSTED,
            source_type="account_opening_balance",
            source_id=str(account.pk),
        ).exists():
            return Decimal("0")
        return account.opening_balance

    @staticmethod
    def get_account_balance_including_opening(account, as_of_date=None):
        balance = account.get_balance(to_date=as_of_date)
        return balance + FinancialReportingService.get_opening_balance_as_of(
            account, as_of_date
        )

    @staticmethod
    def get_trial_balance(company, as_of_date=None):
        from django.db.models import Sum

        accounts = Account.objects.filter(company=company)
        tb = []
        total_debit = 0
        total_credit = 0

        for account in accounts:
            qs = account.journal_items.filter(journal_entry__status="posted")
            if as_of_date:
                qs = qs.filter(journal_entry__date__lte=as_of_date)

            res = qs.aggregate(dr=Sum("debit"), cr=Sum("credit"))
            dr = res["dr"] or 0
            cr = res["cr"] or 0
            opening_balance = FinancialReportingService.get_opening_balance_as_of(
                account, as_of_date
            )
            if account.account_type in ("asset", "expense", "cogs", "bank"):
                dr += opening_balance
            else:
                cr += opening_balance

            if dr > 0 or cr > 0:
                tb.append(
                    {
                        "code": account.code,
                        "name": account.name,
                        "type": account.get_account_type_display(),
                        "debit": dr,
                        "credit": cr,
                    }
                )
                total_debit += dr
                total_credit += cr

        return {
            "accounts": tb,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "is_balanced": total_debit == total_credit,
        }

    @staticmethod
    def get_profit_and_loss(company, start_date=None, end_date=None):
        revenue_accounts = Account.objects.filter(
            company=company, account_type="revenue"
        )
        expense_accounts = Account.objects.filter(
            company=company, account_type__in=["expense", "cogs"]
        )

        revenues = []
        total_revenue = 0
        for acc in revenue_accounts:
            bal = acc.get_balance(from_date=start_date, to_date=end_date)
            if bal != 0:
                revenues.append({"code": acc.code, "name": acc.name, "balance": bal})
                total_revenue += bal

        expenses = []
        total_expense = 0
        for acc in expense_accounts:
            bal = acc.get_balance(from_date=start_date, to_date=end_date)
            if bal != 0:
                expenses.append({"code": acc.code, "name": acc.name, "balance": bal})
                total_expense += bal

        return {
            "revenues": revenues,
            "expenses": expenses,
            "total_revenue": total_revenue,
            "total_expense": total_expense,
            "net_profit": total_revenue - total_expense,
        }

    @staticmethod
    def get_balance_sheet(company, as_of_date=None):
        assets = []
        total_assets = 0
        liabilities = []
        total_liabilities = 0
        equities = []
        total_equity = 0

        for acc in Account.objects.filter(company=company):
            bal = FinancialReportingService.get_account_balance_including_opening(
                acc, as_of_date=as_of_date
            )
            if bal == 0:
                continue

            item = {"code": acc.code, "name": acc.name, "balance": bal}
            if acc.account_type in ["asset", "bank"]:
                assets.append(item)
                total_assets += bal
            elif acc.account_type == "liability":
                liabilities.append(item)
                total_liabilities += bal
            elif acc.account_type == "equity":
                equities.append(item)
                total_equity += bal

        # Calculate Retained Earnings (Net Profit)
        pl = FinancialReportingService.get_profit_and_loss(company, end_date=as_of_date)
        retained_earnings = pl["net_profit"]
        total_equity += retained_earnings

        return {
            "assets": assets,
            "liabilities": liabilities,
            "equities": equities,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "equity_accounts_total": total_equity - retained_earnings,
            "retained_earnings": retained_earnings,
            "total_liabilities_and_equity": total_liabilities + total_equity,
        }


class AccountService(BaseService):
    @staticmethod
    def _decimal(value, field, *, allow_negative=False):
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError(f"{field} must be a valid amount.") from None
        if not result.is_finite() or (not allow_negative and result < 0):
            raise ValueError(f"{field} must be a finite non-negative amount.")
        if result.as_tuple().exponent < -2 or result.adjusted() > 17:
            raise ValueError(f"{field} supports at most 18 digits and 2 decimals.")
        return result

    @transaction.atomic
    def create_account(self, data):
        """Validate and create an account scoped to the current company."""
        code = str(data.get("code", "")).strip()
        name = str(data.get("name", "")).strip()
        account_type = data.get("account_type")
        subtype = data.get("account_subtype", "")
        if not code or len(code) > 20:
            raise ValueError("Account code is required and must be 20 characters or fewer.")
        if not name or len(name) > 255:
            raise ValueError("Account name is required and must be 255 characters or fewer.")
        if account_type not in Account.AccountType.values:
            raise ValueError("Choose a valid account type.")
        if subtype and subtype not in Account.AccountSubtype.values:
            raise ValueError("Choose a valid account subtype.")

        parent_id = data.get("parent") or None
        if parent_id and not Account.objects.filter(
            pk=parent_id, company=self.company, is_deleted=False
        ).exists():
            raise ValueError("Parent account must belong to the active company.")
        currency_id = data.get("currency") or None
        if currency_id:
            from apps.company.models import Currency

            if not Currency.objects.filter(pk=currency_id, is_active=True).exists():
                raise ValueError("Choose a valid active currency.")
        opening_balance = self._decimal(
            data.get("opening_balance") or "0", "Opening balance"
        )
        opening_date = data.get("opening_balance_date") or None
        if opening_date:
            try:
                opening_date_string = str(opening_date)
                opening_date = date.fromisoformat(opening_date_string)
            except ValueError:
                raise ValueError("Opening balance date must be a valid date.") from None
            if opening_date.isoformat() != opening_date_string:
                raise ValueError("Opening balance date must use YYYY-MM-DD format.")
        opening_offset_id = data.get("opening_offset_account") or None
        opening_offset = None
        if opening_balance:
            if account_type not in (
                Account.AccountType.ASSET,
                Account.AccountType.BANK,
                Account.AccountType.LIABILITY,
                Account.AccountType.EQUITY,
            ):
                raise ValueError(
                    "Opening balances are only supported for balance-sheet accounts."
                )
            if not opening_date:
                raise ValueError("Opening balance date is required for a nonzero balance.")
            if not opening_offset_id:
                raise ValueError(
                    "Choose an equity account to offset the opening balance."
                )
            opening_offset = Account.objects.filter(
                pk=opening_offset_id,
                company=self.company,
                account_type=Account.AccountType.EQUITY,
                is_active=True,
                is_deleted=False,
                allow_journal_entries=True,
            ).first()
            if not opening_offset:
                raise ValueError(
                    "Opening balance offset must be an active, journal-enabled equity "
                    "account in the active company."
                )

        acc = Account(
            company=self.company,
            code=code,
            name=name,
            account_type=account_type,
            account_subtype=subtype,
            description=data.get("description", ""),
            parent_id=parent_id,
            currency_id=currency_id,
            is_reconcilable=data.get("is_reconcilable") == "on",
            opening_balance=opening_balance,
            opening_balance_date=opening_date,
        )
        acc.save()
        if opening_balance:
            self._post_opening_balance(acc, opening_offset, opening_balance, opening_date)
        return acc

    def _post_opening_balance(self, account, offset_account, amount, opening_date):
        journal = AutoJournalService.get_or_create_journal(
            self.company, Journal.JournalType.GENERAL
        )
        reference = f"OPENING: {account.code}"
        if JournalEntry.objects.filter(
            company=self.company,
            source_type="account_opening_balance",
            source_id=str(account.pk),
        ).exists():
            raise ValueError("An opening-balance journal already exists for this account.")

        entry = JournalEntry.objects.create(
            company=self.company,
            journal=journal,
            date=opening_date,
            reference=reference,
            total_debit=amount,
            total_credit=amount,
            source_type="account_opening_balance",
            source_id=str(account.pk),
            notes=f"Opening balance for account {account.code}.",
        )
        debit_normal = account.account_type in (
            Account.AccountType.ASSET,
            Account.AccountType.BANK,
        )
        opening_description = f"Opening balance for {account.code} - {account.name}"
        JournalItem.objects.create(
            journal_entry=entry,
            account=account if debit_normal else offset_account,
            description=opening_description[:500],
            debit=amount,
        )
        JournalItem.objects.create(
            journal_entry=entry,
            account=offset_account if debit_normal else account,
            description=opening_description[:500],
            credit=amount,
        )
        entry.post(user=self.user)


class JournalEntryService(BaseService):
    @transaction.atomic
    def create_entry(self, data):
        """Validate all header/line input before atomically creating the entry."""
        from datetime import date

        journal_id = data.get("journal")
        journal = Journal.objects.filter(
            pk=journal_id, company=self.company, is_active=True
        ).first()
        if not journal:
            raise ValueError("Choose an active journal in the active company.")
        try:
            posting_date = date.fromisoformat(str(data.get("date", "")))
        except ValueError:
            raise ValueError("Journal date must be a valid date.") from None

        accounts = data.getlist("account[]")
        descs = data.getlist("item_description[]")
        debits = data.getlist("debit[]")
        credits = data.getlist("credit[]")
        if not accounts or not (len(accounts) == len(debits) == len(credits)):
            raise ValueError("Provide at least one complete journal line.")
        account_ids = [value for value in accounts if value]
        if len(account_ids) < 2:
            raise ValueError("A journal entry must contain at least two account lines.")
        valid_accounts = {
            str(account.pk): account
            for account in Account.objects.filter(
                pk__in=account_ids,
                company=self.company,
                is_active=True,
                is_deleted=False,
                allow_journal_entries=True,
            )
        }
        if len(valid_accounts) != len(set(account_ids)):
            raise ValueError("Every journal account must be active and belong to the active company.")

        parsed_lines = []
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for index, account_id in enumerate(accounts):
            if not account_id:
                raise ValueError("Every journal line must have an account.")
            debit = AccountService._decimal(debits[index] or "0", f"Line {index + 1} debit")
            credit = AccountService._decimal(credits[index] or "0", f"Line {index + 1} credit")
            if (debit == 0) == (credit == 0):
                raise ValueError(f"Line {index + 1} must have exactly one positive debit or credit.")
            parsed_lines.append((valid_accounts[str(account_id)], debit, credit))
            total_debit += debit
            total_credit += credit
        if total_debit == 0 or total_debit != total_credit:
            raise ValueError("Journal entry debits and credits must be equal and greater than zero.")

        entry = JournalEntry(
            company=self.company,
            journal=journal,
            date=posting_date,
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            currency_id=data.get("currency") or None,
        )
        from core.services import BaseService as CoreBaseService

        entry.number = CoreBaseService.generate_sequence_number(
            "JE", JournalEntry, self.company.pk
        )
        entry.save()
        for i, (account, dr, cr) in enumerate(parsed_lines):
            JournalItem.objects.create(
                journal_entry=entry,
                account=account,
                description=descs[i] if i < len(descs) else "",
                debit=dr,
                credit=cr,
            )

        entry.total_debit = total_debit
        entry.total_credit = total_credit
        entry.save(update_fields=["total_debit", "total_credit"])

        entry.post()

        return entry


class BankingService(BaseService):
    @transaction.atomic
    def reconcile_transaction(self, line_id, journal_item_id):
        """Reconciles a Bank Statement Line with a Journal Item"""
        from .models import BankStatementLine

        line = BankStatementLine.objects.get(
            pk=line_id, statement__bank_account__company=self.company
        )
        item = JournalItem.objects.get(
            pk=journal_item_id, account__company=self.company
        )
        if line.is_reconciled or item.reconciled:
            raise ValueError("The statement line or journal item is already reconciled.")
        if item.account_id != line.statement.bank_account.gl_account_id:
            raise ValueError("Journal item must use the statement bank account's GL account.")
        if line.amount != item.debit - item.credit:
            raise ValueError("Statement amount does not match the journal item.")

        line.is_reconciled = True
        line.journal_item = item
        line.save(update_fields=["is_reconciled", "journal_item"])

        item.reconciled = True
        item.save(update_fields=["reconciled"])

        return line, item
