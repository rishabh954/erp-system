"""
Enterprise AI Module — Models
Stores conversations, messages, OCR results, forecasts, and insights.
"""

import uuid

from django.db import models

from core.fields import EncryptedCharField
from core.models import CompanyScoped

# ══════════════════════════════════════════════════════════════════════════════
# AI CONFIGURATION (per company)
# ══════════════════════════════════════════════════════════════════════════════


class AIConfiguration(CompanyScoped):
    """Per-company AI settings and feature toggles."""

    ai_provider = models.CharField(
        max_length=20,
        default="openai",
        choices=[
            ("openai", "OpenAI"),
            ("gemini", "Google Gemini"),
            ("disabled", "Disabled"),
        ],
    )
    openai_model = models.CharField(max_length=50, default="gpt-4o-mini")
    temperature = models.FloatField(default=0.3)
    max_tokens = models.IntegerField(default=2048)

    # API Keys (stored per-company; override .env values when set)
    openai_api_key = EncryptedCharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Your OpenAI secret key (sk-…). Overrides the server .env value.",
    )
    gemini_api_key = EncryptedCharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Your Google Gemini API key. Overrides the server .env value.",
    )
    twilio_account_sid = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Twilio Account SID for WhatsApp/SMS alerts.",
    )
    twilio_auth_token = EncryptedCharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Twilio Auth Token.",
    )
    twilio_phone_number = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Twilio 'from' phone number (e.g. +14155238886).",
    )

    # Feature toggles
    enable_chat = models.BooleanField(default=True)
    enable_nlp_reports = models.BooleanField(default=True)
    enable_forecasting = models.BooleanField(default=True)
    enable_ocr = models.BooleanField(default=True)
    enable_insights = models.BooleanField(default=True)
    enable_recommendations = models.BooleanField(default=True)

    # Usage tracking
    total_tokens_used = models.BigIntegerField(default=0)
    monthly_token_budget = models.BigIntegerField(default=1_000_000)

    class Meta:
        db_table = "ai_configurations"

    def __str__(self):
        return f"AI Config — {self.company}"

    def get_openai_key(self) -> str:
        """Return the DB key if set, otherwise fall back to .env."""
        from django.conf import settings as django_settings
        return self.openai_api_key or getattr(django_settings, "OPENAI_API_KEY", "") or ""

    def get_gemini_key(self) -> str:
        """Return the DB key if set, otherwise fall back to .env."""
        from django.conf import settings as django_settings
        return self.gemini_api_key or getattr(django_settings, "GEMINI_API_KEY", "") or ""


# ══════════════════════════════════════════════════════════════════════════════
# CHAT
# ══════════════════════════════════════════════════════════════════════════════


class AIConversation(CompanyScoped):
    """A chat session between a user and the AI."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "authentication.User", on_delete=models.CASCADE, related_name="ai_conversations"
    )
    title = models.CharField(max_length=200, blank=True)
    context = models.CharField(
        max_length=50,
        default="general",
        help_text="Module context: general, sales, finance, hr, inventory…",
    )
    total_tokens = models.IntegerField(default=0)
    is_archived = models.BooleanField(default=False)

    class Meta:
        db_table = "ai_conversations"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title or 'Conversation'} ({self.user})"


class AIMessage(models.Model):
    """A single turn in a conversation."""

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        AIConversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    tokens_used = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "ai_messages"
        ordering = ["created_at"]


# ══════════════════════════════════════════════════════════════════════════════
# OCR
# ══════════════════════════════════════════════════════════════════════════════


class OCRDocument(CompanyScoped):
    """Stores uploaded invoice/receipt images and their extracted data."""

    class DocType(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        RECEIPT = "receipt", "Receipt"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.ForeignKey(
        "authentication.User", on_delete=models.SET_NULL, null=True
    )
    doc_type = models.CharField(
        max_length=10, choices=DocType.choices, default=DocType.INVOICE
    )
    original_file = models.FileField(upload_to="ai/ocr/")
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING
    )

    # Extracted fields
    extracted_data = models.JSONField(
        default=dict,
        help_text='{"vendor":"","date":"","total":"","tax":"","currency":"","line_items":[]}',
    )
    raw_text = models.TextField(blank=True)
    confidence = models.FloatField(
        null=True, blank=True, help_text="Overall confidence score 0.0–1.0"
    )
    processing_time_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = "ai_ocr_documents"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.doc_type} OCR — {self.original_file.name}"


# ══════════════════════════════════════════════════════════════════════════════
# FORECASTS
# ══════════════════════════════════════════════════════════════════════════════


class AIForecast(CompanyScoped):
    """Cached ML forecast results."""

    class ForecastType(models.TextChoices):
        SALES = "sales", "Sales Forecast"
        INVENTORY = "inventory", "Inventory Forecast"
        DEMAND = "demand", "Demand Prediction"
        REVENUE = "revenue", "Revenue Forecast"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    forecast_type = models.CharField(max_length=15, choices=ForecastType.choices)
    period = models.CharField(
        max_length=20, default="30d", help_text="7d, 30d, 90d, 6m, 1y"
    )
    # Optional: scope to a product, customer, etc.
    scope_model = models.CharField(max_length=100, blank=True)
    scope_id = models.CharField(max_length=100, blank=True)

    forecast_data = models.JSONField(
        default=dict,
        help_text='{"labels":[],"predicted":[],"lower_bound":[],"upper_bound":[],"metrics":{}}',
    )
    algorithm = models.CharField(max_length=50, default="linear_regression")
    accuracy_score = models.FloatField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now=True)
    valid_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_forecasts"
        ordering = ["-generated_at"]


# ══════════════════════════════════════════════════════════════════════════════
# INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════


class AIInsight(CompanyScoped):
    """AI-generated narrative insights stored for reuse."""

    class InsightType(models.TextChoices):
        CUSTOMER = "customer", "Customer Insight"
        FINANCIAL = "financial", "Financial Summary"
        PURCHASE = "purchase", "Purchase Recommendation"
        EXPENSE = "expense", "Expense Analysis"
        DASHBOARD = "dashboard", "Dashboard Summary"
        SALES_TREND = "sales_trend", "Sales Trend"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    insight_type = models.CharField(max_length=20, choices=InsightType.choices)
    title = models.CharField(max_length=255)
    narrative = models.TextField()
    data_snapshot = models.JSONField(default=dict)
    scope_id = models.CharField(
        max_length=100, blank=True, help_text="Customer ID, product ID, etc. if scoped"
    )
    generated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    tokens_used = models.IntegerField(default=0)

    class Meta:
        db_table = "ai_insights"
        ordering = ["-generated_at"]

    def __str__(self):
        return f"{self.insight_type} — {self.title}"


# ══════════════════════════════════════════════════════════════════════════════
# NLP REPORT
# ══════════════════════════════════════════════════════════════════════════════


class NLPReport(CompanyScoped):
    """Stores natural-language query → SQL/data result pairs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey("authentication.User", on_delete=models.CASCADE)
    question = models.TextField()
    generated_query = models.TextField(
        blank=True, help_text="The ORM/SQL generated from the NL query"
    )
    result_data = models.JSONField(default=dict)
    result_count = models.IntegerField(default=0)
    chart_config = models.JSONField(default=dict, blank=True)
    tokens_used = models.IntegerField(default=0)
    execution_ms = models.IntegerField(default=0)

    class Meta:
        db_table = "ai_nlp_reports"
        ordering = ["-created_at"]

    def __str__(self):
        return self.question[:80]
