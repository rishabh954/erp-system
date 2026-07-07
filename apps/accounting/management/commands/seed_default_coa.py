from django.core.management.base import BaseCommand
from apps.accounting.models import Account
from apps.company.models import Company

class Command(BaseCommand):
    help = 'Seeds a default Chart of Accounts for a specific company'

    def add_arguments(self, parser):
        parser.add_argument('company_id', type=str, help='UUID of the company to seed COA for')

    def handle(self, *args, **options):
        company_id = options['company_id']
        try:
            company = Company.objects.get(pk=company_id)
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Company with ID {company_id} not found.'))
            return

        self.stdout.write(self.style.NOTICE(f'Seeding default Chart of Accounts for {company.name}...'))

        # Chart definition
        chart = [
            # Assets
            {'code': '1000', 'name': 'Current Assets', 'type': 'asset', 'subtype': 'current_asset', 'children': [
                {'code': '1010', 'name': 'Cash and Cash Equivalents', 'type': 'bank', 'subtype': 'current_asset'},
                {'code': '1020', 'name': 'Bank Accounts', 'type': 'bank', 'subtype': 'current_asset'},
                {'code': '1030', 'name': 'Accounts Receivable', 'type': 'asset', 'subtype': 'accounts_receivable'},
                {'code': '1040', 'name': 'Inventory', 'type': 'asset', 'subtype': 'current_asset'},
                {'code': '1050', 'name': 'Prepaid Expenses', 'type': 'asset', 'subtype': 'current_asset'},
            ]},
            {'code': '1500', 'name': 'Fixed Assets', 'type': 'asset', 'subtype': 'fixed_asset', 'children': [
                {'code': '1510', 'name': 'Property, Plant & Equipment', 'type': 'asset', 'subtype': 'fixed_asset'},
                {'code': '1520', 'name': 'Accumulated Depreciation', 'type': 'asset', 'subtype': 'fixed_asset'},
            ]},
            # Liabilities
            {'code': '2000', 'name': 'Current Liabilities', 'type': 'liability', 'subtype': 'current_liability', 'children': [
                {'code': '2010', 'name': 'Accounts Payable', 'type': 'liability', 'subtype': 'accounts_payable'},
                {'code': '2020', 'name': 'Accrued Expenses', 'type': 'liability', 'subtype': 'current_liability'},
                {'code': '2030', 'name': 'Taxes Payable', 'type': 'liability', 'subtype': 'current_liability'},
                {'code': '2040', 'name': 'Short-Term Loans', 'type': 'liability', 'subtype': 'current_liability'},
            ]},
            {'code': '2500', 'name': 'Long-Term Liabilities', 'type': 'liability', 'subtype': 'long_term_liability', 'children': [
                {'code': '2510', 'name': 'Long-Term Debt', 'type': 'liability', 'subtype': 'long_term_liability'},
            ]},
            # Equity
            {'code': '3010', 'name': "Owner's / Shareholder's Equity", 'type': 'equity', 'subtype': 'capital'},
            {'code': '3020', 'name': 'Retained Earnings', 'type': 'equity', 'subtype': 'retained_earnings'},
            {'code': '3030', 'name': 'Current Year Earnings', 'type': 'equity', 'subtype': 'capital'},
            # Income
            {'code': '4010', 'name': 'Sales Revenue', 'type': 'revenue', 'subtype': ''},
            {'code': '4020', 'name': 'Service Revenue', 'type': 'revenue', 'subtype': ''},
            {'code': '4030', 'name': 'Other Income', 'type': 'revenue', 'subtype': 'other'},
            {'code': '4900', 'name': 'Sales Returns & Allowances', 'type': 'revenue', 'subtype': ''},
            # Expenses
            {'code': '5010', 'name': 'Cost of Goods Sold', 'type': 'cogs', 'subtype': ''},
            {'code': '5100', 'name': 'Operating Expenses', 'type': 'expense', 'subtype': '', 'children': [
                {'code': '5110', 'name': 'Salaries & Wages', 'type': 'expense', 'subtype': ''},
                {'code': '5120', 'name': 'Rent', 'type': 'expense', 'subtype': ''},
                {'code': '5130', 'name': 'Utilities', 'type': 'expense', 'subtype': ''},
                {'code': '5140', 'name': 'Office Supplies', 'type': 'expense', 'subtype': ''},
                {'code': '5150', 'name': 'Depreciation Expense', 'type': 'expense', 'subtype': ''},
            ]},
            {'code': '5900', 'name': 'Other Expenses', 'type': 'expense', 'subtype': 'other'},
        ]

        created_count = 0

        def create_account(data, parent=None):
            nonlocal created_count
            acc, created = Account.objects.get_or_create(
                company=company,
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'account_type': data['type'],
                    'account_subtype': data.get('subtype', ''),
                    'parent': parent
                }
            )
            if created:
                created_count += 1
            for child_data in data.get('children', []):
                create_account(child_data, parent=acc)

        for account_data in chart:
            create_account(account_data)

        self.stdout.write(self.style.SUCCESS(f'Successfully created {created_count} default accounts for {company.name}.'))
