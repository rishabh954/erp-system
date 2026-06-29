"""Enterprise AI URLs — /ai/"""
from django.urls import path
from .views import (
    AIHubView,
    # Chat
    ChatView, ChatNewConversationView, ChatSendMessageView, ChatDeleteConversationView,
    # NLP Reports
    NLPReportView, NLPReportQueryView,
    # Forecasting
    ForecastView, ForecastDataView,
    # OCR
    OCRUploadView, OCRResultView, OCRStatusView,
    # Insights
    CustomerInsightsView, GenerateCustomerInsightsView,
    # Purchase
    PurchaseRecommendationView, GeneratePurchaseRecommendationsView,
    # Expense
    ExpenseCategorisationView, CategoriseExpensesView,
    # Financial Summary
    FinancialSummaryView, GenerateFinancialSummaryView,
    # Dashboard Assistant
    DashboardAssistantView,
    # Settings
    AISettingsView,
)

app_name = 'ai'

urlpatterns = [
    # Hub
    path('', AIHubView.as_view(), name='hub'),

    # Chat
    path('chat/', ChatView.as_view(), name='chat'),
    path('chat/<uuid:conv_id>/', ChatView.as_view(), name='chat_conversation'),
    path('chat/new/', ChatNewConversationView.as_view(), name='chat_new'),
    path('chat/<uuid:conv_id>/send/', ChatSendMessageView.as_view(), name='chat_send'),
    path('chat/<uuid:conv_id>/delete/', ChatDeleteConversationView.as_view(), name='chat_delete'),

    # NLP Reports
    path('reports/', NLPReportView.as_view(), name='nlp_reports'),
    path('reports/query/', NLPReportQueryView.as_view(), name='nlp_query'),

    # Forecasting (Sales / Inventory / Demand)
    path('forecast/', ForecastView.as_view(), name='forecast'),
    path('forecast/data/', ForecastDataView.as_view(), name='forecast_data'),

    # OCR
    path('ocr/', OCRUploadView.as_view(), name='ocr'),
    path('ocr/<uuid:pk>/', OCRResultView.as_view(), name='ocr_result'),
    path('ocr/<uuid:pk>/status/', OCRStatusView.as_view(), name='ocr_status'),

    # Customer Insights
    path('insights/', CustomerInsightsView.as_view(), name='insights'),
    path('insights/generate/', GenerateCustomerInsightsView.as_view(), name='insights_generate'),

    # Purchase Recommendations
    path('purchase-recommendations/', PurchaseRecommendationView.as_view(), name='purchase_recommendations'),
    path('purchase-recommendations/generate/', GeneratePurchaseRecommendationsView.as_view(), name='purchase_recommendations_generate'),

    # Expense Categorisation
    path('expense-categorisation/', ExpenseCategorisationView.as_view(), name='expense_categorisation'),
    path('expense-categorisation/process/', CategoriseExpensesView.as_view(), name='categorise_expenses'),

    # Financial Summary
    path('financial-summary/', FinancialSummaryView.as_view(), name='financial_summary'),
    path('financial-summary/generate/', GenerateFinancialSummaryView.as_view(), name='financial_summary_generate'),

    # Dashboard Assistant (widget API)
    path('assistant/', DashboardAssistantView.as_view(), name='dashboard_assistant'),

    # Settings
    path('settings/', AISettingsView.as_view(), name='settings'),
]
