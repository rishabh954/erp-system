"""
Company Management Views
Settings, Branches, Departments, Users, Fiscal Years, Currencies
"""

from django.views.generic import ListView, DetailView, View, TemplateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib import messages
from django.utils.translation import gettext_lazy as _

from .models import Company, Branch, Department, Currency, ExchangeRate, FiscalYear, Tax, TaxGroup


class CompanyMixin(LoginRequiredMixin):
    def company(self):
        return self.request.user.primary_company


# ── Settings ──────────────────────────────────────────────────────────────────

class CompanySettingsView(CompanyMixin, View):
    template_name = 'company/settings.html'

    def get(self, request):
        company = self.company()
        return render(request, self.template_name, {
            'company': company,
            'currencies': Currency.objects.filter(is_active=True),
        })

    def post(self, request):
        company = self.company()
        data = request.POST
        company.name = data.get('name', company.name)
        company.legal_name = data.get('legal_name', '')
        company.tax_id = data.get('tax_id', '')
        company.vat_number = data.get('vat_number', '')
        company.phone = data.get('phone', '')
        company.email = data.get('email', '')
        company.website = data.get('website', '')
        company.address_line1 = data.get('address_line1', '')
        company.city = data.get('city', '')
        company.country = data.get('country', '')
        company.language = data.get('language', 'en')
        company.timezone = data.get('timezone', 'UTC')
        company.fiscal_year_start = data.get('fiscal_year_start', '01-01')
        company.primary_color = data.get('primary_color', '#4361ee')
        if 'inventory_valuation_method' in data:
            company.inventory_valuation_method = data['inventory_valuation_method']
        if data.get('default_currency'):
            company.default_currency_id = data['default_currency']
        if request.FILES.get('logo'):
            company.logo = request.FILES['logo']
        company.save()
        messages.success(request, 'Company settings updated.')
        return redirect('company:settings')


class SwitchCompanyView(CompanyMixin, View):
    def get(self, request, company_id):
        from apps.authentication.models import UserCompany
        try:
            uc = UserCompany.objects.get(user=request.user, company_id=company_id, is_active=True)
            request.user.primary_company = uc.company
            request.user.save(update_fields=['primary_company'])
            messages.success(request, f'Switched to {uc.company.name}.')
        except UserCompany.DoesNotExist:
            messages.error(request, 'You do not have access to that company.')
        return redirect('dashboard:index')


# ── Branches ──────────────────────────────────────────────────────────────────

class BranchListView(CompanyMixin, ListView):
    template_name = 'company/branches/list.html'
    context_object_name = 'branches'

    def get_queryset(self):
        return Branch.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('manager').order_by('name')


class BranchCreateView(CompanyMixin, View):
    template_name = 'company/branches/form.html'

    def get(self, request):
        from apps.authentication.models import User
        return render(request, self.template_name, {
            'managers': User.objects.filter(companies=self.company(), is_active=True),
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            Branch.objects.create(
                company=company,
                name=data['name'],
                code=data['code'],
                is_headquarters=data.get('is_headquarters') == 'on',
                phone=data.get('phone', ''),
                email=data.get('email', ''),
                address_line1=data.get('address_line1', ''),
                city=data.get('city', ''),
                country=data.get('country', ''),
                manager_id=data.get('manager') or None,
            )
            messages.success(request, 'Branch created.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('company:branches')


# ── Departments ───────────────────────────────────────────────────────────────

class DepartmentListView(CompanyMixin, ListView):
    template_name = 'company/departments/list.html'
    context_object_name = 'departments'

    def get_queryset(self):
        return Department.objects.filter(
            company=self.company(), is_deleted=False
        ).select_related('parent', 'head').order_by('name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.hrms.models import Employee
        for dept in ctx['departments']:
            dept.employee_count = Employee.objects.filter(
                department=dept, status='active', is_deleted=False
            ).count()
        return ctx


class DepartmentCreateView(CompanyMixin, View):
    template_name = 'company/departments/form.html'

    def get(self, request):
        from apps.authentication.models import User
        from apps.company.models import Branch, Department
        return render(request, self.template_name, {
            'branches': Branch.objects.filter(company=self.company(), is_active=True, is_deleted=False),
            'departments': Department.objects.filter(company=self.company(), is_deleted=False),
            'users': User.objects.filter(companies=self.company(), is_active=True).order_by('first_name'),
        })

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            from apps.authentication.models import User
            Department.objects.create(
                company=company,
                name=data['name'],
                code=data['code'],
                description=data.get('description', ''),
                parent_id=data.get('parent') or None,
                branch_id=data.get('branch') or None,
                head_id=data.get('head') or None,
                cost_center=data.get('cost_center', ''),
            )
            messages.success(request, 'Department created.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('company:departments')


# ── Users & Roles ─────────────────────────────────────────────────────────────

class UserManagementView(CompanyMixin, ListView):
    template_name = 'company/users/list.html'
    context_object_name = 'users'

    def get_queryset(self):
        from apps.authentication.models import User
        return User.objects.filter(
            companies=self.company(), is_active=True
        ).order_by('first_name')


class InviteUserView(CompanyMixin, View):
    def post(self, request):
        data = request.POST
        company = self.company()
        email = data.get('email', '').strip()
        role  = data.get('role', 'employee')

        from apps.authentication.models import User, UserCompany
        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                'first_name': data.get('first_name', ''),
                'last_name': data.get('last_name', ''),
                'role': role,
                'is_active': True,
            }
        )
        if created:
            temp_pass = User.objects.make_random_password()
            user.set_password(temp_pass)
            user.save()

        UserCompany.objects.get_or_create(
            user=user, company=company,
            defaults={'role_override': role}
        )

        if not user.primary_company:
            user.primary_company = company
            user.save(update_fields=['primary_company'])

        messages.success(request, f'User {email} added to {company.name}.')
        return redirect('company:users')


# ── Fiscal Years ──────────────────────────────────────────────────────────────

class FiscalYearListView(CompanyMixin, ListView):
    template_name = 'company/fiscal_years/list.html'
    context_object_name = 'fiscal_years'

    def get_queryset(self):
        return FiscalYear.objects.filter(
            company=self.company()
        ).order_by('-start_date')


class FiscalYearCreateView(CompanyMixin, View):
    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            FiscalYear.objects.create(
                company=company,
                name=data['name'],
                start_date=data['start_date'],
                end_date=data['end_date'],
                is_current=data.get('is_current') == 'on',
            )
            messages.success(request, 'Fiscal year created.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('company:fiscal_years')


# ── Currencies ────────────────────────────────────────────────────────────────

class CurrencyListView(CompanyMixin, TemplateView):
    template_name = 'company/currencies/list.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['currencies'] = Currency.objects.filter(is_active=True).order_by('code')
        ctx['exchange_rates'] = ExchangeRate.objects.select_related(
            'from_currency', 'to_currency'
        ).order_by('-effective_date')[:20]
        return ctx


class CurrencyCreateView(CompanyMixin, View):
    def post(self, request):
        try:
            Currency.objects.create(
                code=request.POST['code'].upper(),
                name=request.POST['name'],
                symbol=request.POST.get('symbol', ''),
                decimal_places=int(request.POST.get('decimal_places', 2)),
                is_base=request.POST.get('is_base') == 'on',
                is_active=True
            )
            messages.success(request, 'Currency added successfully.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('company:currencies')


class CurrencyUpdateView(CompanyMixin, UpdateView):
    model = Currency
    template_name = 'company/currencies/form.html'
    fields = ['code', 'name', 'symbol', 'decimal_places', 'is_base', 'is_active']
    
    def get_success_url(self):
        from django.urls import reverse_lazy
        return reverse_lazy('company:currencies')
        
    def form_valid(self, form):
        messages.success(self.request, 'Currency updated successfully.')
        return super().form_valid(form)


class CurrencyDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        try:
            currency = Currency.objects.get(pk=pk)
            # Instead of a hard delete, we set is_active=False
            # This prevents foreign key errors in old exchange rates/invoices
            currency.is_active = False
            currency.save(update_fields=['is_active'])
            messages.success(request, f'Currency {currency.code} has been successfully deleted.')
        except Currency.DoesNotExist:
            messages.error(request, 'Currency not found.')
        except Exception as e:
            messages.error(request, f'Error deleting currency: {e}')
        return redirect('company:currencies')


class ExchangeRateCreateView(CompanyMixin, View):
    def post(self, request):
        try:
            from decimal import Decimal
            from_currency_id = request.POST['from_currency']
            to_currency_id = request.POST['to_currency']
            rate = Decimal(request.POST['rate'])
            effective_date = request.POST['effective_date']
            
            ExchangeRate.objects.create(
                from_currency_id=from_currency_id,
                to_currency_id=to_currency_id,
                rate=rate,
                effective_date=effective_date,
                source='manual'
            )
            messages.success(request, 'Exchange rate added successfully.')
        except Exception as e:
            messages.error(request, f'Error: {e}')
        return redirect('company:currencies')


# ════════════════════════ UNIT OF MEASURE ═════════════════════════════════════

from apps.inventory.models import UnitOfMeasure

class UomListView(CompanyMixin, TemplateView):
    template_name = 'company/uoms/list.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Assuming CompanyScoped models support soft-delete via is_deleted, if not we just filter is_active
        ctx['uoms'] = UnitOfMeasure.objects.filter(company=self.company()).order_by('name')
        return ctx

class UomCreateView(CompanyMixin, View):
    def post(self, request):
        try:
            UnitOfMeasure.objects.create(
                company=self.company(),
                name=request.POST['name'],
                abbreviation=request.POST['abbreviation'],
                uom_type=request.POST.get('uom_type', 'unit'),
                is_active=request.POST.get('is_active') == 'on'
            )
            messages.success(request, 'Unit of Measure created successfully.')
        except Exception as e:
            messages.error(request, f'Error creating UOM: {e}')
        return redirect('company:uoms')

class UomUpdateView(CompanyMixin, View):
    def post(self, request, pk):
        try:
            uom = get_object_or_404(UnitOfMeasure, pk=pk, company=self.company())
            uom.name = request.POST['name']
            uom.abbreviation = request.POST['abbreviation']
            uom.uom_type = request.POST.get('uom_type', 'unit')
            uom.is_active = request.POST.get('is_active') == 'on'
            uom.save()
            messages.success(request, 'Unit of Measure updated successfully.')
        except Exception as e:
            messages.error(request, f'Error updating UOM: {e}')
        return redirect('company:uoms')

class UomDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        try:
            uom = get_object_or_404(UnitOfMeasure, pk=pk, company=self.company())
            if hasattr(uom, 'is_deleted'):
                uom.is_deleted = True
                uom.is_active = False
                uom.save()
                messages.success(request, 'Unit of Measure archived successfully.')
            else:
                uom.delete()
                messages.success(request, 'Unit of Measure deleted successfully.')
        except Exception as e:
            messages.error(request, f'Error deleting UOM: {e}')
        return redirect('company:uoms')


# ════════════════════════ TAXES ═══════════════════════════════════════════════

class TaxListView(CompanyMixin, TemplateView):
    template_name = 'company/taxes/list.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['taxes'] = Tax.objects.filter(company=self.company()).select_related('tax_group', 'tax_account').order_by('name')
        ctx['tax_groups'] = TaxGroup.objects.filter(company=self.company(), is_active=True)
        try:
            from apps.accounting.models import Account
            ctx['accounts'] = Account.objects.filter(company=self.company(), is_active=True)
        except ImportError:
            ctx['accounts'] = []
        return ctx

class TaxCreateView(CompanyMixin, View):
    def post(self, request):
        try:
            from decimal import Decimal
            tax_group_id = request.POST.get('tax_group')
            tax_account_id = request.POST.get('tax_account')
            
            Tax.objects.create(
                company=self.company(),
                name=request.POST['name'],
                rate=Decimal(request.POST['rate']),
                tax_type=request.POST.get('tax_type', 'percentage'),
                tax_group_id=tax_group_id if tax_group_id else None,
                tax_account_id=tax_account_id if tax_account_id else None,
                is_compound=request.POST.get('is_compound') == 'on',
                is_active=request.POST.get('is_active') == 'on'
            )
            messages.success(request, 'Tax created successfully.')
        except Exception as e:
            messages.error(request, f'Error creating tax: {e}')
        return redirect('company:taxes')

class TaxUpdateView(CompanyMixin, View):
    def post(self, request, pk):
        try:
            from decimal import Decimal
            tax = get_object_or_404(Tax, pk=pk, company=self.company())
            tax.name = request.POST['name']
            tax.rate = Decimal(request.POST['rate'])
            tax.tax_type = request.POST.get('tax_type', 'percentage')
            
            tax_group_id = request.POST.get('tax_group')
            tax_account_id = request.POST.get('tax_account')
            tax.tax_group_id = tax_group_id if tax_group_id else None
            tax.tax_account_id = tax_account_id if tax_account_id else None
            
            tax.is_compound = request.POST.get('is_compound') == 'on'
            tax.is_active = request.POST.get('is_active') == 'on'
            tax.save()
            messages.success(request, 'Tax updated successfully.')
        except Exception as e:
            messages.error(request, f'Error updating tax: {e}')
        return redirect('company:taxes')

class TaxDeleteView(CompanyMixin, View):
    def post(self, request, pk):
        try:
            tax = get_object_or_404(Tax, pk=pk, company=self.company())
            # Soft delete if applicable or just hard delete/deactivate
            if hasattr(tax, 'is_deleted'):
                tax.is_deleted = True
                tax.is_active = False
                tax.save()
            else:
                tax.delete()
            messages.success(request, 'Tax removed successfully.')
        except Exception as e:
            messages.error(request, f'Error removing tax: {e}')
        return redirect('company:taxes')


# ════════════════════════ URL PATTERNS ════════════════════════════════════════

from django.urls import path

app_name = 'company'

urlpatterns = [
    path('settings/', CompanySettingsView.as_view(), name='settings'),
    path('switch/<uuid:company_id>/', SwitchCompanyView.as_view(), name='switch'),
    path('branches/', BranchListView.as_view(), name='branches'),
    path('branches/create/', BranchCreateView.as_view(), name='branch_create'),
    path('departments/', DepartmentListView.as_view(), name='departments'),
    path('departments/create/', DepartmentCreateView.as_view(), name='department_create'),
    path('users/', UserManagementView.as_view(), name='users'),
    path('users/invite/', InviteUserView.as_view(), name='user_invite'),
    path('fiscal-years/', FiscalYearListView.as_view(), name='fiscal_years'),
    path('fiscal-years/create/', FiscalYearCreateView.as_view(), name='fiscal_year_create'),
    path('currencies/', CurrencyListView.as_view(), name='currencies'),
    path('currencies/create/', CurrencyCreateView.as_view(), name='currency_create'),
    path('currencies/rates/create/', ExchangeRateCreateView.as_view(), name='exchange_rate_create'),
]
