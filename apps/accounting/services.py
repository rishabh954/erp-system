from decimal import Decimal

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

    return matching_years.filter(status=FiscalYear.Status.OPEN).order_by(
        "-start_date"
    ).first()


class AutoJournalService:
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
            reference=f"INV: {invoice.number}",
            status=JournalEntry.Status.DRAFT,
            currency=invoice.currency,
            total_debit=invoice_total,
            total_credit=invoice_total,
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
            reference=f"CN: {credit_note.number}",
            status=JournalEntry.Status.DRAFT,
            currency=currency,
            total_debit=total_amount,
            total_credit=total_amount,
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
        ar_account = AutoJournalService.get_or_create_ar(company)
        bank_account = AutoJournalService.get_or_create_bank(company)

        journal = AutoJournalService.get_or_create_journal(company, "cash")

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=payment.payment_date,
            reference=f"PAY: {payment.number}",
            status=JournalEntry.Status.DRAFT,
            currency=payment.currency,
            total_debit=payment.amount,
            total_credit=payment.amount,
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
            reference=f"BILL: {bill.number}",
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
        ap_account = AutoJournalService.get_or_create_ap(company)
        bank_account = AutoJournalService.get_or_create_bank(company)

        journal = AutoJournalService.get_or_create_journal(company, "cash")

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=payment.payment_date,
            reference=f"VPAY: {payment.number}",
            status=JournalEntry.Status.DRAFT,
            currency=payment.currency,
            total_debit=payment.amount,
            total_credit=payment.amount,
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
    def get_trial_balance(company, as_of_date=None):
        from django.db.models import Sum

        accounts = Account.objects.filter(company=company, is_active=True)
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
            company=company, account_type="revenue", is_active=True
        )
        expense_accounts = Account.objects.filter(
            company=company, account_type__in=["expense", "cogs"], is_active=True
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

        for acc in Account.objects.filter(company=company, is_active=True):
            bal = acc.get_balance(to_date=as_of_date)
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

        return {
            "assets": assets,
            "liabilities": liabilities,
            "equities": equities,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "total_equity": total_equity,
            "retained_earnings": retained_earnings,
            "total_liabilities_and_equity": total_liabilities
            + total_equity
            + retained_earnings,
        }


class AccountService(BaseService):
    @transaction.atomic
    def create_account(self, data):
        """Creates a new Account based on POST data"""
        acc = Account(
            company=self.company,
            code=data["code"],
            name=data["name"],
            account_type=data["account_type"],
            account_subtype=data.get("account_subtype", ""),
            description=data.get("description", ""),
            parent_id=data.get("parent") or None,
            currency_id=data.get("currency") or None,
            is_reconcilable=data.get("is_reconcilable") == "on",
            opening_balance=data.get("opening_balance", "0"),
            opening_balance_date=data.get("opening_balance_date") or None,
        )
        acc.current_balance = acc.opening_balance
        acc.save()
        return acc


class JournalEntryService(BaseService):
    @transaction.atomic
    def create_entry(self, data):
        """Creates a Journal Entry and its associated Journal Items"""
        entry = JournalEntry(
            company=self.company,
            journal_id=data["journal"],
            date=data["date"],
            reference=data.get("reference", ""),
            notes=data.get("notes", ""),
            currency_id=data.get("currency") or None,
        )
        from core.services import BaseService as CoreBaseService

        entry.number = CoreBaseService.generate_sequence_number(
            "JE", JournalEntry, self.company.pk
        )
        entry.save()

        accounts = data.getlist("account[]")
        descs = data.getlist("item_description[]")
        debits = data.getlist("debit[]")
        credits = data.getlist("credit[]")

        from decimal import Decimal

        total_debit = Decimal("0")
        total_credit = Decimal("0")

        for i, acc_id in enumerate(accounts):
            if not acc_id:
                continue
            dr = Decimal(debits[i] or "0")
            cr = Decimal(credits[i] or "0")
            JournalItem.objects.create(
                journal_entry=entry,
                account_id=acc_id,
                description=descs[i] if i < len(descs) else "",
                debit=dr,
                credit=cr,
            )
            total_debit += dr
            total_credit += cr

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

        # Simple check, we could check signs later
        if line.amount == 0 and item.debit == 0 and item.credit == 0:
            pass  # allow zero

        line.is_reconciled = True
        line.journal_item = item
        line.save(update_fields=["is_reconciled", "journal_item"])

        item.reconciled = True
        item.save(update_fields=["reconciled"])

        return line, item
