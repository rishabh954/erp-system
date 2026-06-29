"""
Accounting Views
Chart of Accounts, Journal Entries, Bank Accounts, Financial Reports
"""

from django.views.generic import ListView, DetailView, View, TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Sum, F
from datetime import date, timedelta
from decimal import Decimal

from .models import Account, Journal, JournalEntry, JournalItem, BankAccount, BankTransaction
from core.services import BaseService


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


# ═══════════════════════ CHART OF ACCOUNTS ════════════════════════════════════

class ChartOfAccountsView(CompanyMixin, ListView):
    template_name = 'accounting/chart_of_accounts.html'
    context_object_name = 'accounts'

    def get_queryset(self):
        qs = Account.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('parent').order_by('code')

        account_type = self.request.GET.get('type', '')
        q = self.request.GET.get('q', '')
        if account_type:
            qs = qs.filter(account_type=account_type)
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['account_type_choices'] = Account.AccountType.choices
        ctx['totals'] = {
            at[0]: Account.objects.filter(
                company=self.company(), account_type=at[0], is_deleted=False
            ).aggregate(bal=Sum('current_balance'))['bal'] or 0
            for at in Account.AccountType.choices
        }
        return ctx


class AccountDetailView(CompanyMixin, DetailView):
    template_name = 'accounting/account_detail.html'
    context_object_name = 'account'

    def get_object(self):
        return get_object_or_404(Account, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        acc = self.object
        from_date = self.request.GET.get('from_date', (date.today().replace(day=1)).isoformat())
        to_date = self.request.GET.get('to_date', date.today().isoformat())
        ctx['journal_items'] = JournalItem.objects.filter(
            account=acc,
            journal_entry__status='posted',
            journal_entry__date__range=(from_date, to_date),
        ).select_related('journal_entry').order_by('journal_entry__date')
        ctx['balance'] = acc.get_balance(from_date, to_date)
        ctx['from_date'] = from_date
        ctx['to_date'] = to_date
        return ctx


class AccountCreateView(CompanyMixin, View):
    template_name = 'accounting/account_form.html'

    def get(self, request):
        company = self.company()
        return render(request, self.template_name, {
            'account_type_choices': Account.AccountType.choices,
            'account_subtype_choices': Account.AccountSubtype.choices,
            'parent_accounts': Account.objects.filter(company=company, is_deleted=False).order_by('code'),
            'currencies': __import__('apps.company.models', fromlist=['Currency']).Currency.objects.filter(is_active=True),
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from .services import AccountService
            service = AccountService(user=request.user, company=company)
            acc = service.create_account(data)
            messages.success(request, f'Account {acc.code} — {acc.name} created.')
            return redirect('accounting:chart_of_accounts')
        except Exception as e:
            messages.error(request, f'Error: {e}')
            return redirect('accounting:chart_of_accounts')


# ═══════════════════════ JOURNAL ENTRIES ══════════════════════════════════════

class JournalListView(CompanyMixin, ListView):
    template_name = 'accounting/journals/list.html'
    context_object_name = 'entries'
    paginate_by = 30

    def get_queryset(self):
        qs = JournalEntry.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('journal', 'fiscal_year', 'posted_by').order_by('-date', '-created_at')

        status = self.request.GET.get('status', '')
        journal = self.request.GET.get('journal', '')
        from_date = self.request.GET.get('from_date', '')
        to_date = self.request.GET.get('to_date', '')

        if status:
            qs = qs.filter(status=status)
        if journal:
            qs = qs.filter(journal_id=journal)
        if from_date:
            qs = qs.filter(date__gte=from_date)
        if to_date:
            qs = qs.filter(date__lte=to_date)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['journals'] = Journal.objects.filter(company=self.company(), is_active=True)
        ctx['status_choices'] = JournalEntry.Status.choices
        return ctx


class JournalEntryCreateView(CompanyMixin, View):
    template_name = 'accounting/journals/form.html'

    def get(self, request):
        company = self.company()
        return render(request, self.template_name, {
            'journals': Journal.objects.filter(company=company, is_active=True),
            'accounts': Account.objects.filter(
                company=company, is_active=True, allow_journal_entries=True, is_deleted=False
            ).order_by('code'),
            'currencies': __import__('apps.company.models', fromlist=['Currency']).Currency.objects.filter(is_active=True),
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from .services import JournalEntryService
            service = JournalEntryService(user=request.user, company=company)
            entry = service.create_entry(data)
            
            if not entry.is_balanced():
                messages.warning(request, f'Journal entry {entry.number} saved but is NOT balanced (Dr={entry.total_debit}, Cr={entry.total_credit}).')
            else:
                messages.success(request, f'Journal entry {entry.number} created.')

            return redirect('accounting:journal_detail', pk=entry.pk)
        except Exception as e:
            messages.error(request, f'Error creating journal entry: {e}')
            return redirect('accounting:journals')


class JournalEntryDetailView(CompanyMixin, DetailView):
    template_name = 'accounting/journals/detail.html'
    context_object_name = 'entry'

    def get_object(self):
        return get_object_or_404(JournalEntry, pk=self.kwargs['pk'],
                                  company=self.company(), is_deleted=False)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['items'] = self.object.items.all().select_related('account', 'tax')
        return ctx


class PostJournalEntryView(CompanyMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(JournalEntry, pk=pk, company=self.company())
        if entry.status != JournalEntry.Status.DRAFT:
            messages.error(request, 'Only draft entries can be posted.')
            return redirect('accounting:journal_detail', pk=pk)
        try:
            entry.post(user=request.user)
            messages.success(request, f'Journal entry {entry.number} posted successfully.')
        except ValueError as e:
            messages.error(request, str(e))
        return redirect('accounting:journal_detail', pk=pk)


# ═══════════════════════ BANK ACCOUNTS ════════════════════════════════════════

class BankAccountListView(CompanyMixin, ListView):
    template_name = 'accounting/bank_accounts.html'
    context_object_name = 'bank_accounts'

    def get_queryset(self):
        return BankAccount.objects.filter(
            company=self.company(), is_deleted=False, is_active=True
        ).select_related('currency', 'gl_account')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_balance'] = self.get_queryset().aggregate(
            t=Sum('current_balance')
        )['t'] or 0
        return ctx


# ═══════════════════════ FINANCIAL REPORTS ════════════════════════════════════

class FinancialReportsView(CompanyMixin, TemplateView):
    template_name = 'accounting/reports/index.html'


class BalanceSheetView(CompanyMixin, View):
    template_name = 'accounting/reports/balance_sheet.html'

    def get(self, request):
        company = self.company()
        as_of = request.GET.get('as_of', date.today().isoformat())

        def get_accounts(account_type):
            return Account.objects.filter(
                company=company, account_type=account_type, is_active=True, is_deleted=False
            ).order_by('code')

        assets = get_accounts('asset')
        liabilities = get_accounts('liability')
        equity = get_accounts('equity')
        bank = get_accounts('bank')

        # Compute balances as of date
        def balance(acc):
            items = JournalItem.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=as_of,
            ).aggregate(dr=Sum('debit'), cr=Sum('credit'))
            dr = items['dr'] or Decimal('0')
            cr = items['cr'] or Decimal('0')
            if acc.account_type in ('asset', 'expense', 'bank'):
                return dr - cr
            return cr - dr

        asset_list = [(a, balance(a)) for a in list(assets) + list(bank)]
        liability_list = [(a, balance(a)) for a in liabilities]
        equity_list = [(a, balance(a)) for a in equity]

        total_assets = sum(b for _, b in asset_list)
        total_liabilities = sum(b for _, b in liability_list)
        total_equity = sum(b for _, b in equity_list)

        return render(request, self.template_name, {
            'as_of': as_of,
            'asset_list': asset_list,
            'liability_list': liability_list,
            'equity_list': equity_list,
            'total_assets': total_assets,
            'total_liabilities': total_liabilities,
            'total_equity': total_equity,
            'total_liabilities_equity': total_liabilities + total_equity,
            'is_balanced': abs(total_assets - (total_liabilities + total_equity)) < Decimal('0.01'),
        })


class ProfitAndLossView(CompanyMixin, View):
    template_name = 'accounting/reports/profit_and_loss.html'

    def get(self, request):
        company = self.company()
        from_date = request.GET.get('from_date', date.today().replace(month=1, day=1).isoformat())
        to_date   = request.GET.get('to_date', date.today().isoformat())

        def get_type_total(account_type):
            return JournalItem.objects.filter(
                account__company=company,
                account__account_type=account_type,
                journal_entry__status='posted',
                journal_entry__date__range=(from_date, to_date),
            ).aggregate(dr=Sum('debit'), cr=Sum('credit'))

        rev  = get_type_total('revenue')
        cogs = get_type_total('cogs')
        exp  = get_type_total('expense')

        revenue  = (rev['cr']  or Decimal('0')) - (rev['dr']  or Decimal('0'))
        cogs_val = (cogs['dr'] or Decimal('0')) - (cogs['cr'] or Decimal('0'))
        expenses = (exp['dr']  or Decimal('0')) - (exp['cr']  or Decimal('0'))
        gross_profit = revenue - cogs_val
        net_profit   = gross_profit - expenses

        # Per-account breakdown
        def account_breakdown(account_type):
            accs = Account.objects.filter(
                company=company, account_type=account_type, is_active=True, is_deleted=False
            ).order_by('code')
            result = []
            for acc in accs:
                items = JournalItem.objects.filter(
                    account=acc,
                    journal_entry__status='posted',
                    journal_entry__date__range=(from_date, to_date),
                ).aggregate(dr=Sum('debit'), cr=Sum('credit'))
                dr = items['dr'] or Decimal('0')
                cr = items['cr'] or Decimal('0')
                if account_type in ('revenue',):
                    b = cr - dr
                else:
                    b = dr - cr
                if b != 0:
                    result.append((acc, b))
            return result

        return render(request, self.template_name, {
            'from_date': from_date,
            'to_date': to_date,
            'revenue': revenue,
            'cogs': cogs_val,
            'gross_profit': gross_profit,
            'expenses': expenses,
            'net_profit': net_profit,
            'gross_margin': round(gross_profit / revenue * 100, 1) if revenue else 0,
            'net_margin': round(net_profit / revenue * 100, 1) if revenue else 0,
            'revenue_breakdown': account_breakdown('revenue'),
            'cogs_breakdown': account_breakdown('cogs'),
            'expense_breakdown': account_breakdown('expense'),
        })


class TrialBalanceView(CompanyMixin, View):
    template_name = 'accounting/reports/trial_balance.html'

    def get(self, request):
        company = self.company()
        as_of = request.GET.get('as_of', date.today().isoformat())
        accounts = Account.objects.filter(
            company=company, is_active=True, is_deleted=False
        ).order_by('code')

        rows = []
        total_dr = Decimal('0')
        total_cr = Decimal('0')

        for acc in accounts:
            items = JournalItem.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__lte=as_of,
            ).aggregate(dr=Sum('debit'), cr=Sum('credit'))
            dr = items['dr'] or Decimal('0')
            cr = items['cr'] or Decimal('0')
            if dr != 0 or cr != 0:
                rows.append({'account': acc, 'debit': dr, 'credit': cr})
                total_dr += dr
                total_cr += cr

        return render(request, self.template_name, {
            'as_of': as_of,
            'rows': rows,
            'total_debit': total_dr,
            'total_credit': total_cr,
            'is_balanced': abs(total_dr - total_cr) < Decimal('0.01'),
        })



# ════════════════════════ ACCOUNTING DASHBOARD ══════════════════════════════

class AccountingDashboardView(CompanyMixin, TemplateView):
    template_name = 'accounting/dashboard.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        
        # Bank Balances
        bank_accounts = BankAccount.objects.filter(company=company, is_active=True, is_deleted=False)
        total_cash = sum(ba.current_balance for ba in bank_accounts)
        
        # Open AR/AP
        ar_accs = Account.objects.filter(company=company, account_subtype='accounts_receivable')
        ap_accs = Account.objects.filter(company=company, account_subtype='accounts_payable')
        
        def get_open_balance(accounts):
            items = JournalItem.objects.filter(
                account__in=accounts,
                journal_entry__status='posted',
                reconciled=False
            ).aggregate(dr=Sum('debit'), cr=Sum('credit'))
            dr = items['dr'] or Decimal('0')
            cr = items['cr'] or Decimal('0')
            # AR is Dr normal, AP is Cr normal
            return abs(dr - cr)
            
        ctx['open_ar'] = get_open_balance(ar_accs)
        ctx['open_ap'] = get_open_balance(ap_accs)
        
        # Net Profit YTD
        ytd_start = date.today().replace(month=1, day=1)
        ytd_end = date.today()
        
        from .services import FinancialReportingService
        pl = FinancialReportingService.get_profit_and_loss(company, start_date=ytd_start, end_date=ytd_end)
        ctx['net_profit_ytd'] = pl['net_profit']
        
        bs = FinancialReportingService.get_balance_sheet(company, as_of_date=ytd_end)
        ctx['total_assets'] = bs['total_assets']
        ctx['total_liabilities'] = bs['total_liabilities']
        ctx['total_equity'] = bs['total_equity']
        ctx['total_cash'] = total_cash
        ctx['bank_accounts'] = bank_accounts
        
        # Recent Entries
        ctx['recent_entries'] = JournalEntry.objects.filter(company=company, is_deleted=False).order_by('-created_at')[:5]
        
        return ctx

# ════════════════════════ BANK RECONCILIATION ═══════════════════════════════

from .models import BankStatementLine

class BankReconciliationView(CompanyMixin, View):
    template_name = 'accounting/reconciliation.html'
    
    def get(self, request):
        company = self.company()
        # Get bank accounts with unreconciled statement lines
        bank_accounts = BankAccount.objects.filter(company=company, is_active=True, is_deleted=False)
        
        selected_bank_id = request.GET.get('bank_account')
        selected_bank = bank_accounts.filter(pk=selected_bank_id).first() if selected_bank_id else bank_accounts.first()
        
        statement_lines = []
        journal_items = []
        
        if selected_bank:
            statement_lines = BankStatementLine.objects.filter(
                statement__bank_account=selected_bank,
                is_reconciled=False
            ).select_related('statement').order_by('date')
            
            journal_items = JournalItem.objects.filter(
                account=selected_bank.gl_account,
                reconciled=False,
                journal_entry__status='posted'
            ).select_related('journal_entry').order_by('journal_entry__date')
            
        return render(request, self.template_name, {
            'bank_accounts': bank_accounts,
            'selected_bank': selected_bank,
            'statement_lines': statement_lines,
            'journal_items': journal_items
        })
        
    def post(self, request):
        company = self.company()
        action = request.POST.get('action')
        
        if action == 'reconcile':
            line_id = request.POST.get('statement_line_id')
            journal_item_id = request.POST.get('journal_item_id')
            
            try:
                from .services import BankingService
                service = BankingService(user=request.user, company=company)
                service.reconcile_transaction(line_id, journal_item_id)
                messages.success(request, 'Successfully reconciled transaction.')
            except Exception as e:
                messages.error(request, f'Reconciliation failed: {str(e)}')
                
                
        elif action == 'create_transaction':
            # Manual creation of a bank transaction for demo purposes
            bank_id = request.POST.get('bank_account')
            date_str = request.POST.get('date')
            tx_type = request.POST.get('type')
            amount = request.POST.get('amount')
            desc = request.POST.get('description')
            
            try:
                bank = BankAccount.objects.get(pk=bank_id, company=company)
                BankTransaction.objects.create(
                    company=company,
                    bank_account=bank,
                    transaction_date=date_str,
                    transaction_type=tx_type,
                    amount=amount,
                    description=desc
                )
                messages.success(request, 'Bank transaction created manually.')
            except Exception as e:
                messages.error(request, f'Failed to create transaction: {str(e)}')
                
        return redirect(f"{request.path}?bank_account={request.POST.get('bank_account', '')}")

# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = 'accounting'

urlpatterns = [
    path('accounts/', ChartOfAccountsView.as_view(), name='chart_of_accounts'),
    path('accounts/create/', AccountCreateView.as_view(), name='account_create'),
    path('accounts/<uuid:pk>/', AccountDetailView.as_view(), name='account_detail'),
    path('journals/', JournalListView.as_view(), name='journals'),
    path('journals/create/', JournalEntryCreateView.as_view(), name='journal_create'),
    path('journals/<uuid:pk>/', JournalEntryDetailView.as_view(), name='journal_detail'),
    path('journals/<uuid:pk>/post/', PostJournalEntryView.as_view(), name='journal_post'),
    path('bank/', BankAccountListView.as_view(), name='bank_accounts'),
    path('reports/', FinancialReportsView.as_view(), name='reports'),
    path('reports/balance-sheet/', BalanceSheetView.as_view(), name='balance_sheet'),
    path('reports/profit-loss/', ProfitAndLossView.as_view(), name='profit_loss'),
    path('reports/trial-balance/', TrialBalanceView.as_view(), name='trial_balance'),
]
from django.views.generic import View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from apps.sales.models import Invoice, InvoiceLine
from apps.crm.models import Customer
from core.services import BaseService

class IssueCreditNoteView(CompanyMixin, View):
    def get(self, request):
        company = self.company()
        customers = Customer.objects.filter(company=company, is_deleted=False)
        invoices = Invoice.objects.filter(company=company, is_deleted=False, document_type='standard')
        return render(request, 'accounting/issue_credit_note.html', {
            'customers': customers,
            'invoices': invoices,
        })
        
    def post(self, request):
        company = self.company()
        customer_id = request.POST.get('customer')
        invoice_id = request.POST.get('invoice')
        amount = request.POST.get('amount')
        reason = request.POST.get('reason')
        
        customer = get_object_or_404(Customer, pk=customer_id, company=company)
        
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                raise ValueError("Amount must be positive.")
                
            number = BaseService.generate_sequence_number('CN', Invoice, company.pk)
            
            cn = Invoice.objects.create(
                company=company,
                number=number,
                customer=customer,
                document_type=Invoice.DocumentType.CREDIT_NOTE,
                status=Invoice.Status.DRAFT,
                invoice_date=date.today(),
                due_date=date.today(),
                subtotal=-amount_val,
                total=-amount_val,
                notes=reason
            )
            
            # Create a single line item for the credit note
            InvoiceLine.objects.create(
                invoice=cn,
                description=reason or 'Credit Note applied',
                quantity=1,
                unit_price=-amount_val,
                subtotal=-amount_val,
                total=-amount_val
            )
            
            messages.success(request, f'Credit Note {number} created successfully.')
            # Redirecting to sales invoice detail since CN is just an invoice with negative amount
            return redirect('sales:invoice_detail', pk=cn.pk)
            
        except Exception as e:
            messages.error(request, f"Error creating Credit Note: {str(e)}")
            return redirect('accounting:issue_credit_note')

# ════════════════════════ COST CENTERS & BUDGETS ═════════════════════════════

from .models import CostCenter, Budget, BudgetLine

class CostCenterListView(CompanyMixin, ListView):
    template_name = 'accounting/cost_centers/list.html'
    context_object_name = 'cost_centers'
    
    def get_queryset(self):
        return CostCenter.objects.filter(company=self.company()).select_related('parent', 'manager')

class CostCenterDetailView(CompanyMixin, DetailView):
    template_name = 'accounting/cost_centers/detail.html'
    context_object_name = 'cost_center'
    
    def get_queryset(self):
        return CostCenter.objects.filter(company=self.company()).select_related('parent', 'manager')
        
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Add budget data
        ctx['budgets'] = self.object.budgets.all().order_by('-period_start')
        # Add recent expenses
        ctx['recent_expenses'] = JournalItem.objects.filter(
            cost_center=self.object,
            journal_entry__status='posted',
            account__account_type__in=['expense', 'cogs']
        ).select_related('journal_entry', 'account').order_by('-journal_entry__date')[:50]
        return ctx

class BudgetListView(CompanyMixin, ListView):
    template_name = 'accounting/budgets/list.html'
    context_object_name = 'budgets'
    
    def get_queryset(self):
        return Budget.objects.filter(company=self.company()).select_related('cost_center')

class BudgetDetailView(CompanyMixin, DetailView):
    template_name = 'accounting/budgets/detail.html'
    context_object_name = 'budget'
    
    def get_queryset(self):
        return Budget.objects.filter(company=self.company()).select_related('cost_center').prefetch_related('lines__account')



from django.views.generic import CreateView
from django.urls import reverse_lazy

class CostCenterCreateView(CompanyMixin, CreateView):
    model = CostCenter
    template_name = 'accounting/cost_centers/form.html'
    fields = ['code', 'name', 'parent', 'manager', 'description', 'is_active']
    
    def form_valid(self, form):
        form.instance.company = self.company()
        return super().form_valid(form)
        
    def get_success_url(self):
        return reverse_lazy('accounting:cost_center_detail', kwargs={'pk': self.object.pk})

class BudgetCreateView(CompanyMixin, CreateView):
    model = Budget
    template_name = 'accounting/budgets/form.html'
    fields = ['name', 'cost_center', 'period_start', 'period_end', 'status']
    
    def form_valid(self, form):
        form.instance.company = self.company()
        return super().form_valid(form)
        
    def get_success_url(self):
        return reverse_lazy('accounting:budget_detail', kwargs={'pk': self.object.pk})

# ════════════════════════ ENTERPRISE FINANCIAL REPORTS ═══════════════════════

class GeneralLedgerView(CompanyMixin, TemplateView):
    template_name = 'accounting/reports/general_ledger.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        from_date = self.request.GET.get('from_date', (date.today().replace(day=1)).isoformat())
        to_date = self.request.GET.get('to_date', date.today().isoformat())
        
        # Group by account
        accounts = Account.objects.filter(company=company, is_deleted=False).order_by('code')
        ledger_data = []
        
        for acc in accounts:
            items = JournalItem.objects.filter(
                account=acc,
                journal_entry__status='posted',
                journal_entry__date__range=(from_date, to_date)
            ).select_related('journal_entry').order_by('journal_entry__date')
            
            if items.exists():
                totals = items.aggregate(dr=Sum('debit'), cr=Sum('credit'))
                dr = totals['dr'] or Decimal('0')
                cr = totals['cr'] or Decimal('0')
                ledger_data.append({
                    'account': acc,
                    'items': items,
                    'total_debit': dr,
                    'total_credit': cr,
                    'net_change': dr - cr if acc.account_type in ('asset', 'expense', 'cogs', 'bank') else cr - dr
                })
                
        ctx['ledger_data'] = ledger_data
        ctx['from_date'] = from_date
        ctx['to_date'] = to_date
        return ctx

class ARAgingReportView(CompanyMixin, TemplateView):
    template_name = 'accounting/reports/ar_aging.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        as_of = self.request.GET.get('as_of', date.today().isoformat())
        as_of_date = date.fromisoformat(as_of)
        
        from apps.sales.models import Invoice
        
        # Get all posted, unpaid sales invoices
        invoices = Invoice.objects.filter(
            company=company,
            status=Invoice.Status.POSTED,
            document_type='standard',
            amount_due__gt=0,
            invoice_date__lte=as_of_date
        ).select_related('customer')
        
        aging_data = {}
        for inv in invoices:
            cust = inv.customer
            if cust not in aging_data:
                aging_data[cust] = {'current': 0, '30': 0, '60': 0, '90': 0, 'total': 0}
            
            days_past = (as_of_date - inv.due_date).days
            amount = inv.amount_due
            
            if days_past <= 0:
                aging_data[cust]['current'] += amount
            elif days_past <= 30:
                aging_data[cust]['30'] += amount
            elif days_past <= 60:
                aging_data[cust]['60'] += amount
            else:
                aging_data[cust]['90'] += amount
                
            aging_data[cust]['total'] += amount
            
        ctx['aging_data'] = aging_data
        ctx['as_of'] = as_of
        return ctx

class APAgingReportView(CompanyMixin, TemplateView):
    template_name = 'accounting/reports/ap_aging.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        as_of = self.request.GET.get('as_of', date.today().isoformat())
        as_of_date = date.fromisoformat(as_of)
        
        from apps.purchase.models import PurchaseOrder
        # Wait, AP aging is usually tracked via Bills, not Purchase Orders.
        # But we added `apps.purchase.views.BillListView` earlier, let's assume `Bill` model exists in `purchase.models` or `accounting.models`.
        # Actually in Phase 2/3, we had "Bills" as an alias to PurchaseOrder or a separate model? Let's check where Bill comes from.
        # It's likely PurchaseOrder has `amount_due` and `status` or we just track it via Accounts Payable journal items.
        
        # A reliable way: group by Vendor on JournalItems for Accounts Payable!
        ap_accounts = Account.objects.filter(company=company, account_subtype='accounts_payable')
        
        items = JournalItem.objects.filter(
            account__in=ap_accounts,
            journal_entry__status='posted',
            journal_entry__date__lte=as_of_date,
            reconciled=False # Assuming unreconciled items are open AP
        ).select_related('journal_entry')
        
        aging_data = {}
        # Simple AP tracking by journal items (partner_id)
        from apps.purchase.models import Vendor
        vendors = {str(v.pk): v for v in Vendor.objects.filter(company=company)}
        
        for item in items:
            vid = item.partner_id
            if not vid: continue
            vendor = vendors.get(vid)
            if not vendor: continue
            
            if vendor not in aging_data:
                aging_data[vendor] = {'current': 0, '30': 0, '60': 0, '90': 0, 'total': 0}
                
            days_past = (as_of_date - item.journal_entry.date).days
            amount = item.credit - item.debit # AP is credit normal
            if amount <= 0: continue
            
            if days_past <= 30:
                aging_data[vendor]['current'] += amount
            elif days_past <= 60:
                aging_data[vendor]['30'] += amount
            elif days_past <= 90:
                aging_data[vendor]['60'] += amount
            else:
                aging_data[vendor]['90'] += amount
                
            aging_data[vendor]['total'] += amount
            
        ctx['aging_data'] = aging_data
        ctx['as_of'] = as_of
        return ctx

