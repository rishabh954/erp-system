from django.utils import timezone
from .models import Journal, JournalEntry, JournalItem, Account
from django.db import transaction

class AutoJournalService:
    @staticmethod
    def get_or_create_journal(company, journal_type):
        name_map = {
            'sales': 'Sales Journal',
            'purchase': 'Purchase Journal',
            'cash': 'Cash & Bank Journal',
            'general': 'General Journal'
        }
        journal, created = Journal.objects.get_or_create(
            company=company,
            journal_type=journal_type,
            defaults={'name': name_map.get(journal_type, 'Journal'), 'code': journal_type[:3].upper()}
        )
        return journal

    @staticmethod
    def get_or_create_ar(company):
        if company.default_receivable_account:
            return company.default_receivable_account
        ar, _ = Account.objects.get_or_create(company=company, code='1200', defaults={'name': 'Accounts Receivable', 'account_type': 'asset', 'account_subtype': 'accounts_receivable'})
        company.default_receivable_account = ar
        company.save(update_fields=['default_receivable_account'])
        return ar

    @staticmethod
    def get_or_create_ap(company):
        if company.default_payable_account:
            return company.default_payable_account
        ap, _ = Account.objects.get_or_create(company=company, code='2000', defaults={'name': 'Accounts Payable', 'account_type': 'liability', 'account_subtype': 'accounts_payable'})
        company.default_payable_account = ap
        company.save(update_fields=['default_payable_account'])
        return ap

    @staticmethod
    def get_or_create_bank(company):
        if company.default_bank_account:
            return company.default_bank_account
        bank, _ = Account.objects.get_or_create(company=company, code='1000', defaults={'name': 'Main Bank Account', 'account_type': 'asset', 'account_subtype': 'bank'})
        company.default_bank_account = bank
        company.save(update_fields=['default_bank_account'])
        return bank

    @staticmethod
    @transaction.atomic
    def post_sales_invoice(invoice):
        company = invoice.company
        ar_account = AutoJournalService.get_or_create_ar(company)
            
        revenue_account = None
        # We can just use the first line's revenue account, or a company default
        if invoice.lines.exists() and invoice.lines.first().product and invoice.lines.first().product.revenue_account:
            revenue_account = invoice.lines.first().product.revenue_account
        else:
            # Fallback to a newly created/fetched Revenue account
            revenue_account, _ = Account.objects.get_or_create(
                company=company, code='4000', defaults={'name': 'Sales Revenue', 'account_type': 'revenue'}
            )
            
        journal = AutoJournalService.get_or_create_journal(company, 'sales')
        
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=invoice.invoice_date or timezone.now().date(),
            reference=f"INV: {invoice.number}",
            status=JournalEntry.Status.POSTED,
            currency=invoice.currency,
            total_debit=invoice.total,
            total_credit=invoice.total
        )
        entry.number = entry.generate_number(journal.sequence_prefix, entry.__class__)
        entry.save(update_fields=['number'])
        
        # Debit A/R (Total)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ar_account,
            description=f"Receivable for {invoice.number}",
            debit=invoice.total,
            credit=0,
            partner_type='customer',
            partner_id=str(invoice.customer.id)
        )
        
        # Credit Revenue (Subtotal)
        JournalItem.objects.create(
            journal_entry=entry,
            account=revenue_account,
            description=f"Revenue for {invoice.number}",
            debit=0,
            credit=invoice.subtotal,
            partner_type='customer',
            partner_id=str(invoice.customer.id)
        )
        
        # Credit Tax (if any)
        if invoice.tax_amount > 0:
            tax_account, _ = Account.objects.get_or_create(
                company=company, code='2100', defaults={'name': 'Sales Tax Payable', 'account_type': 'liability', 'account_subtype': 'current_liability'}
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=tax_account,
                description=f"Tax for {invoice.number}",
                debit=0,
                credit=invoice.tax_amount
            )
            
        return entry

    @staticmethod
    @transaction.atomic
    def post_sales_payment(payment):
        company = payment.company
        ar_account = AutoJournalService.get_or_create_ar(company)
        bank_account = AutoJournalService.get_or_create_bank(company)
            
        journal = AutoJournalService.get_or_create_journal(company, 'cash')
        
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=payment.payment_date,
            reference=f"PAY: {payment.number}",
            status=JournalEntry.Status.POSTED,
            currency=payment.currency,
            total_debit=payment.amount,
            total_credit=payment.amount
        )
        entry.number = entry.generate_number(journal.sequence_prefix, entry.__class__)
        entry.save(update_fields=['number'])
        
        # Debit Bank (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=bank_account,
            description=f"Payment Received {payment.number}",
            debit=payment.amount,
            credit=0,
            partner_type='customer',
            partner_id=str(payment.invoice.customer.id) if payment.invoice else ''
        )
        
        # Credit A/R (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ar_account,
            description=f"Payment for {payment.invoice.number if payment.invoice else ''}",
            debit=0,
            credit=payment.amount,
            partner_type='customer',
            partner_id=str(payment.invoice.customer.id) if payment.invoice else ''
        )
        return entry

    @staticmethod
    @transaction.atomic
    def post_purchase_bill(bill):
        company = bill.company
        ap_account = AutoJournalService.get_or_create_ap(company)
            
        expense_account = None
        if bill.lines.exists() and bill.lines.first().product and bill.lines.first().product.cogs_account:
            expense_account = bill.lines.first().product.cogs_account
        else:
            expense_account, _ = Account.objects.get_or_create(
                company=company, code='5000', defaults={'name': 'General Expenses', 'account_type': 'expense'}
            )
            
        journal = AutoJournalService.get_or_create_journal(company, 'purchase')
        
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=bill.bill_date or timezone.now().date(),
            reference=f"BILL: {bill.number}",
            status=JournalEntry.Status.POSTED,
            currency=bill.currency,
            total_debit=bill.total,
            total_credit=bill.total
        )
        entry.number = entry.generate_number(journal.sequence_prefix, entry.__class__)
        entry.save(update_fields=['number'])
        
        # Credit A/P (Total)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ap_account,
            description=f"Payable for {bill.number}",
            debit=0,
            credit=bill.total,
            partner_type='vendor',
            partner_id=str(bill.vendor.id)
        )
        
        # Debit Expense (Subtotal)
        JournalItem.objects.create(
            journal_entry=entry,
            account=expense_account,
            description=f"Expense for {bill.number}",
            debit=bill.subtotal,
            credit=0,
            partner_type='vendor',
            partner_id=str(bill.vendor.id)
        )
        
        # Debit Tax (if any)
        if bill.tax_amount > 0:
            tax_account, _ = Account.objects.get_or_create(
                company=company, code='1300', defaults={'name': 'Purchase Tax Receivable', 'account_type': 'asset', 'account_subtype': 'current_asset'}
            )
            JournalItem.objects.create(
                journal_entry=entry,
                account=tax_account,
                description=f"Tax for {bill.number}",
                debit=bill.tax_amount,
                credit=0
            )
            
        return entry

    @staticmethod
    @transaction.atomic
    def post_purchase_payment(payment):
        company = payment.company
        ap_account = AutoJournalService.get_or_create_ap(company)
        bank_account = AutoJournalService.get_or_create_bank(company)
            
        journal = AutoJournalService.get_or_create_journal(company, 'cash')
        
        entry = JournalEntry.objects.create(
            company=company,
            journal=journal,
            date=payment.payment_date,
            reference=f"VPAY: {payment.number}",
            status=JournalEntry.Status.POSTED,
            currency=payment.currency,
            total_debit=payment.amount,
            total_credit=payment.amount
        )
        entry.number = entry.generate_number(journal.sequence_prefix, entry.__class__)
        entry.save(update_fields=['number'])
        
        # Debit A/P (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=ap_account,
            description=f"Payment for {payment.bill.number if payment.bill else ''}",
            debit=payment.amount,
            credit=0,
            partner_type='vendor',
            partner_id=str(payment.vendor.id) if payment.vendor else ''
        )
        
        # Credit Bank (Amount)
        JournalItem.objects.create(
            journal_entry=entry,
            account=bank_account,
            description=f"Vendor Payment {payment.number}",
            debit=0,
            credit=payment.amount,
            partner_type='vendor',
            partner_id=str(payment.vendor.id) if payment.vendor else ''
        )
        return entry
