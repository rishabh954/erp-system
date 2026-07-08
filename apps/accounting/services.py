from django.db import transaction
from django.utils import timezone

from core.services import BaseService

from .models import Account, Journal, JournalEntry, JournalItem


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

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=invoice.invoice_date or timezone.now().date(),
            reference=f"INV: {invoice.number}",
            status=JournalEntry.Status.DRAFT,
            currency=invoice.currency,
            total_debit=invoice.total,
            total_credit=invoice.total,
        )


        # Debit A/R (Total)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ar_account,
            description=f"Receivable for {invoice.number}",
            debit=invoice.total,
            credit=0,
            partner_type="customer",
            partner_id=str(invoice.customer.id),
        )

        # Credit Revenue (Subtotal)
        JournalItem.objects.create(
            journal_entry=entry,
            account=revenue_account,
            description=f"Revenue for {invoice.number}",
            debit=0,
            credit=invoice.subtotal,
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

        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=bill.bill_date or timezone.now().date(),
            reference=f"BILL: {bill.number}",
            status=JournalEntry.Status.DRAFT,
            currency=bill.currency,
            total_debit=bill.total,
            total_credit=bill.total,
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

        # Debit Expense (Subtotal)
        JournalItem.objects.create(
            journal_entry=entry,
            account=expense_account,
            description=f"Expense for {bill.number}",
            debit=bill.subtotal,
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
