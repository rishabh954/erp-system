from django.urls import path
from .views import (
    CompanyCreateView, CompanySettingsView, SwitchCompanyView,
    BranchListView, BranchCreateView,
    DepartmentListView, DepartmentCreateView,
    UserManagementView, InviteUserView, UserUpdateView, UserRemoveView,
    FiscalYearListView, FiscalYearCreateView,
    CurrencyListView, CurrencyCreateView, ExchangeRateCreateView,
    CurrencyUpdateView, CurrencyDeleteView,
    UomListView, UomCreateView, UomUpdateView, UomDeleteView,
    TaxListView, TaxCreateView, TaxUpdateView, TaxDeleteView
)
app_name = 'company'
urlpatterns = [
    path('create/', CompanyCreateView.as_view(), name='create'),
    path('settings/', CompanySettingsView.as_view(), name='settings'),
    path('switch/<uuid:company_id>/', SwitchCompanyView.as_view(), name='switch'),
    path('branches/', BranchListView.as_view(), name='branches'),
    path('branches/create/', BranchCreateView.as_view(), name='branch_create'),
    path('departments/', DepartmentListView.as_view(), name='departments'),
    path('departments/create/', DepartmentCreateView.as_view(), name='department_create'),
    path('users/', UserManagementView.as_view(), name='users'),
    path('users/invite/', InviteUserView.as_view(), name='user_invite'),
    path('users/<uuid:pk>/edit/', UserUpdateView.as_view(), name='user_update'),
    path('users/<uuid:pk>/remove/', UserRemoveView.as_view(), name='user_remove'),
    path('fiscal-years/', FiscalYearListView.as_view(), name='fiscal_years'),
    path('fiscal-years/create/', FiscalYearCreateView.as_view(), name='fiscal_year_create'),
    path('currencies/', CurrencyListView.as_view(), name='currencies'),
    path('currencies/create/', CurrencyCreateView.as_view(), name='currency_create'),
    path('currencies/<uuid:pk>/edit/', CurrencyUpdateView.as_view(), name='currency_update'),
    path('currencies/<uuid:pk>/delete/', CurrencyDeleteView.as_view(), name='currency_delete'),
    path('currencies/rates/create/', ExchangeRateCreateView.as_view(), name='exchange_rate_create'),
    
    # Units of Measure
    path('uoms/', UomListView.as_view(), name='uoms'),
    path('uoms/create/', UomCreateView.as_view(), name='uom_create'),
    path('uoms/<uuid:pk>/edit/', UomUpdateView.as_view(), name='uom_update'),
    path('uoms/<uuid:pk>/delete/', UomDeleteView.as_view(), name='uom_delete'),

    # Taxes
    path('taxes/', TaxListView.as_view(), name='taxes'),
    path('taxes/create/', TaxCreateView.as_view(), name='tax_create'),
    path('taxes/<uuid:pk>/edit/', TaxUpdateView.as_view(), name='tax_update'),
    path('taxes/<uuid:pk>/delete/', TaxDeleteView.as_view(), name='tax_delete'),
]
