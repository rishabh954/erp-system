from django.urls import path

from .statement_views import BankStatementCreateView, BankStatementListView
from .views import (
    AccountCreateView,
    AccountDetailView,
    AccountingDashboardView,
    APAgingReportView,
    ARAgingReportView,
    BalanceSheetView,
    BankAccountListView,
    BankReconciliationView,
    BudgetCreateView,
    BudgetDetailView,
    BudgetListView,
    ChartOfAccountsView,
    CostCenterCreateView,
    CostCenterDetailView,
    CostCenterListView,
    FinancialReportsView,
    GeneralLedgerView,
    JournalEntryCreateView,
    JournalEntryDetailView,
    JournalListView,
    PostJournalEntryView,
    ProfitAndLossView,
    TrialBalanceView,
)

app_name = "accounting"
urlpatterns = [
    path("dashboard/", AccountingDashboardView.as_view(), name="dashboard"),
    path("accounts/", ChartOfAccountsView.as_view(), name="chart_of_accounts"),
    path("accounts/create/", AccountCreateView.as_view(), name="account_create"),
    path("accounts/<uuid:pk>/", AccountDetailView.as_view(), name="account_detail"),
    path("journals/", JournalListView.as_view(), name="journals"),
    path("journals/create/", JournalEntryCreateView.as_view(), name="journal_create"),
    path(
        "journals/<uuid:pk>/", JournalEntryDetailView.as_view(), name="journal_detail"
    ),
    path(
        "journals/<uuid:pk>/post/", PostJournalEntryView.as_view(), name="journal_post"
    ),
    path("bank/", BankAccountListView.as_view(), name="bank_accounts"),
    path(
        "bank/statements/", BankStatementListView.as_view(), name="bank_statement_list"
    ),
    path(
        "bank/statements/import/",
        BankStatementCreateView.as_view(),
        name="bank_statement_import",
    ),
    path(
        "bank/reconciliation/",
        BankReconciliationView.as_view(),
        name="bank_reconciliation",
    ),
    path("reports/", FinancialReportsView.as_view(), name="reports"),
    path("reports/balance-sheet/", BalanceSheetView.as_view(), name="balance_sheet"),
    path("reports/profit-loss/", ProfitAndLossView.as_view(), name="profit_loss"),
    path("reports/trial-balance/", TrialBalanceView.as_view(), name="trial_balance"),
    path("reports/general-ledger/", GeneralLedgerView.as_view(), name="general_ledger"),
    path("reports/ar-aging/", ARAgingReportView.as_view(), name="ar_aging"),
    path("reports/ap-aging/", APAgingReportView.as_view(), name="ap_aging"),
    # Cost Centers & Budgets
    path("cost-centers/", CostCenterListView.as_view(), name="cost_centers"),
    path(
        "cost-centers/create/",
        CostCenterCreateView.as_view(),
        name="cost_center_create",
    ),
    path(
        "cost-centers/<uuid:pk>/",
        CostCenterDetailView.as_view(),
        name="cost_center_detail",
    ),
    path("budgets/", BudgetListView.as_view(), name="budgets"),
    path("budgets/create/", BudgetCreateView.as_view(), name="budget_create"),
    path("budgets/<uuid:pk>/", BudgetDetailView.as_view(), name="budget_detail"),
    path(
        "credit-note/issue/",
        __import__(
            "apps.accounting.views", fromlist=["IssueCreditNoteView"]
        ).IssueCreditNoteView.as_view(),
        name="issue_credit_note",
    ),
]
