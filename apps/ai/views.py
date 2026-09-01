"""
Enterprise AI — Views
All 13 AI features with streaming chat, SSE, OCR, forecasting, insights, and NLP reports.
"""

import json
import logging

from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from apps.ai.models import AIConversation, AIInsight, AIMessage, NLPReport, OCRDocument
from core.mixins import CompanyMixin

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# AI HUB DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════


class AIHubView(CompanyMixin, TemplateView):
    required_permission_module = "ai"
    template_name = "ai/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        user = self.request.user

        from apps.ai.models import AIConfiguration

        config, _ = AIConfiguration.objects.get_or_create(company=company)
        ctx["openai_configured"] = bool(config.get_openai_key())
        ctx["gemini_configured"] = bool(config.get_gemini_key())
        ctx["ai_available"] = ctx["openai_configured"] or ctx["gemini_configured"]

        ctx["conversation_count"] = AIConversation.objects.filter(
            company=company, user=user, is_archived=False
        ).count()
        ctx["ocr_count"] = OCRDocument.objects.filter(company=company).count()
        ctx["insight_count"] = AIInsight.objects.filter(company=company).count()
        ctx["nlp_count"] = NLPReport.objects.filter(company=company).count()

        ctx["recent_conversations"] = AIConversation.objects.filter(
            company=company, user=user, is_archived=False
        ).order_by("-created_at")[:5]
        ctx["recent_insights"] = AIInsight.objects.filter(company=company).order_by(
            "-generated_at"
        )[:5]

        return ctx


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 1: AI CHAT ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════


class ChatView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/chat.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        company = self.company()
        conv_id = self.kwargs.get("conv_id")

        if conv_id:
            ctx["conversation"] = get_object_or_404(
                AIConversation, id=conv_id, company=company, user=self.request.user
            )
            ctx["messages_list"] = ctx["conversation"].messages.order_by("created_at")
        else:
            ctx["conversation"] = None
            ctx["messages_list"] = []

        ctx["conversations"] = AIConversation.objects.filter(
            company=company, user=self.request.user, is_archived=False
        ).order_by("-created_at")[:20]
        return ctx


class ChatNewConversationView(CompanyMixin, View):
    required_permission = "ai.create"
    def post(self, request):
        conv = AIConversation.objects.create(
            company=self.company(),
            user=request.user,
            title=request.POST.get("title", "New Conversation"),
            context=request.POST.get("context", "general"),
        )
        return JsonResponse({"id": str(conv.id), "title": conv.title})


class ChatSendMessageView(CompanyMixin, View):
    required_permission = "ai.approve"
    """POST: send a message, return streaming SSE response."""

    def post(self, request, conv_id):
        from apps.ai.services import LLMService

        conv = get_object_or_404(
            AIConversation, id=conv_id, company=self.company(), user=request.user
        )
        user_text = request.POST.get("message", "").strip()
        if not user_text:
            return JsonResponse({"error": "Empty message"}, status=400)

        # Save user message
        AIMessage.objects.create(conversation=conv, role="user", content=user_text)

        # Build message history (last 10 turns)
        history = list(conv.messages.order_by("-created_at")[:20])
        history.reverse()
        messages_payload = [{"role": m.role, "content": m.content} for m in history]

        # Auto-name conversation if first message
        if conv.messages.count() == 1:
            conv.title = user_text[:60]
            conv.save(update_fields=["title"])

        def event_stream():
            full_response = ""
            try:
                for chunk in LLMService.chat(
                    messages_payload, conv.context, stream=True, max_tokens=1500,
                    company=self.company(),
                ):
                    full_response += chunk
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
            except Exception as e:
                logger.error(f"Unexpected error: {str(e)}", exc_info=True)
                yield f"data: {json.dumps({'error': 'An unexpected error occurred.'})}\n\n"
            finally:
                # Save assistant message
                if full_response:
                    AIMessage.objects.create(
                        conversation=conv,
                        role="assistant",
                        content=full_response,
                    )
                yield "data: [DONE]\n\n"

        return StreamingHttpResponse(
            event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )


class ChatDeleteConversationView(CompanyMixin, View):
    required_permission = "ai.delete"
    def post(self, request, conv_id):
        conv = get_object_or_404(
            AIConversation, id=conv_id, company=self.company(), user=request.user
        )
        conv.is_archived = True
        conv.save(update_fields=["is_archived"])
        return JsonResponse({"status": "ok"})


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 2: NATURAL LANGUAGE REPORTS
# ══════════════════════════════════════════════════════════════════════════════


class NLPReportView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/nlp_report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["recent_queries"] = NLPReport.objects.filter(
            company=self.company(), user=self.request.user
        ).order_by("-created_at")[:10]
        ctx["example_questions"] = [
            "Show me the top 10 customers by revenue this month",
            "Which products are below reorder level?",
            "List all overdue invoices",
            "Who are the highest-spending customers in the last 30 days?",
            "Show pending purchase orders",
            "Which employees joined this quarter?",
        ]
        return ctx


class NLPReportQueryView(CompanyMixin, View):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    """AJAX: process an NL question and return results."""

    def post(self, request):
        from apps.ai.services import NLPReportService

        question = request.POST.get("question", "").strip()
        if not question:
            return JsonResponse({"error": "Empty question"}, status=400)

        try:
            result = NLPReportService.process_question(question, self.company())

            report = NLPReport.objects.create(
                company=self.company(),
                user=request.user,
                question=question,
                generated_query=json.dumps(result.get("intent", {})),
                result_data={"rows": result.get("results", [])},
                result_count=result.get("count", 0),
                chart_config=result.get("chart_config", {}),
                tokens_used=result.get("tokens_used", 0),
                execution_ms=result.get("execution_ms", 0),
            )

            return JsonResponse(
                {
                    "id": str(report.id),
                    "narrative": result.get("narrative", ""),
                    "results": result.get("results", []),
                    "count": result.get("count", 0),
                    "intent": result.get("intent", {}),
                    "chart_config": result.get("chart_config", {}),
                    "execution_ms": result.get("execution_ms", 0),
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURES 3, 4, 5: FORECASTING (Sales, Inventory, Demand)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/forecast.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["forecast_type"] = self.request.GET.get("type", "sales")
        ctx["period"] = self.request.GET.get("period", "30")
        return ctx


class ForecastDataView(CompanyMixin, View):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    """AJAX: return forecast data JSON for Chart.js."""

    def get(self, request):
        from apps.ai.services import ForecastingService

        ftype = request.GET.get("type", "sales")
        days = int(request.GET.get("days", 30))

        try:
            if ftype == "sales":
                data = ForecastingService.sales_forecast(
                    self.company(), days_ahead=days
                )
            elif ftype == "inventory":
                data = ForecastingService.inventory_forecast(
                    self.company(), days_ahead=days
                )
            elif ftype == "demand":
                product_id = request.GET.get("product_id")
                data = ForecastingService.demand_prediction(
                    self.company(), product_id=product_id, days_ahead=days
                )
            else:
                data = {"error": "Unknown forecast type"}

            return JsonResponse(data)
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURES 6, 7: INVOICE & RECEIPT OCR
# ══════════════════════════════════════════════════════════════════════════════


class OCRUploadView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/ocr_upload.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["recent_docs"] = OCRDocument.objects.filter(
            company=self.company()
        ).order_by("-created_at")[:10]
        return ctx

    def post(self, request):
        from apps.ai.tasks import process_ocr_document

        doc_type = request.POST.get("doc_type", "invoice")
        file = request.FILES.get("file")

        if not file:
            messages.error(request, "No file uploaded.")
            return redirect("ai:ocr")

        doc = OCRDocument.objects.create(
            company=self.company(),
            uploaded_by=request.user,
            doc_type=doc_type,
            original_file=file,
            status=OCRDocument.Status.PENDING,
        )

        # Process synchronously if Celery not available, else async
        try:
            from django.conf import settings

            if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                process_ocr_document(str(doc.id))
            else:
                process_ocr_document.delay(str(doc.id))
        except Exception:
            from apps.ai.services import OCRService

            result = OCRService.extract(doc.original_file, doc_type=doc_type)
            doc.extracted_data = result.get("extracted_data", {})
            doc.raw_text = result.get("raw_text", "")
            doc.confidence = result.get("confidence", 0.0)
            doc.processing_time_ms = result.get("processing_time_ms", 0)
            doc.status = OCRDocument.Status.DONE
            doc.save()

        messages.success(request, "Document uploaded and processing started.")
        return redirect("ai:ocr_result", pk=doc.pk)


class OCRResultView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/ocr_result.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["doc"] = get_object_or_404(
            OCRDocument, pk=self.kwargs["pk"], company=self.company()
        )
        return ctx


class OCRStatusView(CompanyMixin, View):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    """AJAX: poll OCR status."""

    def get(self, request, pk):
        doc = get_object_or_404(OCRDocument, pk=pk, company=self.company())
        return JsonResponse(
            {
                "status": doc.status,
                "extracted_data": doc.extracted_data,
                "confidence": doc.confidence,
            }
        )


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 8: CUSTOMER INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════


class CustomerInsightsView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/insights.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Check cache
        cached = (
            AIInsight.objects.filter(
                company=self.company(),
                insight_type="customer",
                expires_at__gte=timezone.now(),
            )
            .order_by("-generated_at")
            .first()
        )

        if cached:
            ctx["insight"] = cached
            ctx["from_cache"] = True
        else:
            ctx["insight"] = None
            ctx["from_cache"] = False

        ctx["insight_type"] = "customer"
        ctx["recent_insights"] = AIInsight.objects.filter(
            company=self.company(), insight_type="customer"
        ).order_by("-generated_at")[:5]
        return ctx


class GenerateCustomerInsightsView(CompanyMixin, View):
    required_permission = "ai.approve"
    def post(self, request):
        from datetime import timedelta

        from apps.ai.services import CustomerInsightService

        try:
            result = CustomerInsightService.analyse_customers(self.company())

            insight = AIInsight.objects.create(
                company=self.company(),
                insight_type="customer",
                title=f"Customer Segments — {timezone.now().strftime('%B %Y')}",
                narrative=result.get("narrative", ""),
                data_snapshot={
                    "segments": {
                        k: len(v) for k, v in result.get("segments", {}).items()
                    },
                    "total": result.get("total_customers", 0),
                },
                tokens_used=result.get("tokens_used", 0),
                expires_at=timezone.now() + timedelta(hours=24),
            )
            return JsonResponse(
                {
                    "status": "ok",
                    "narrative": insight.narrative,
                    "segments": result.get("segment_counts", {}),
                    "total": result.get("total_customers", 0),
                    "details": {
                        k: v[:5] for k, v in result.get("segments", {}).items()
                    },
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 9: PURCHASE RECOMMENDATIONS
# ══════════════════════════════════════════════════════════════════════════════


class PurchaseRecommendationView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/purchase_recommendations.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["insight_type"] = "purchase"
        return ctx


class GeneratePurchaseRecommendationsView(CompanyMixin, View):
    required_permission = "ai.approve"
    def get(self, request):
        from apps.ai.services import PurchaseRecommendationService

        try:
            recommendations = PurchaseRecommendationService.recommend(self.company())
            return JsonResponse(
                {"recommendations": recommendations, "count": len(recommendations)}
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 10: EXPENSE CATEGORISATION
# ══════════════════════════════════════════════════════════════════════════════


class ExpenseCategorisationView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/expense_categorisation.html"


class CategoriseExpensesView(CompanyMixin, View):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    def post(self, request):
        from apps.ai.services import ExpenseCategorisationService

        try:
            data = json.loads(request.body)
            descriptions = data.get("descriptions", [])
            if not descriptions:
                return JsonResponse({"error": "No descriptions provided"}, status=400)

            results = ExpenseCategorisationService.categorise(descriptions, company=self.company())
            return JsonResponse({"results": results})
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 11: FINANCIAL SUMMARY
# ══════════════════════════════════════════════════════════════════════════════


class FinancialSummaryView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/financial_summary.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["latest_insight"] = (
            AIInsight.objects.filter(company=self.company(), insight_type="financial")
            .order_by("-generated_at")
            .first()
        )
        return ctx


class GenerateFinancialSummaryView(CompanyMixin, View):
    required_permission = "ai.approve"
    def post(self, request):
        from datetime import timedelta

        from apps.ai.services import FinancialSummaryService

        try:
            result = FinancialSummaryService.generate_summary(self.company())
            insight = AIInsight.objects.create(
                company=self.company(),
                insight_type="financial",
                title=f"Financial Summary — {result['metrics'].get('period', 'Current Month')}",
                narrative=result["narrative"],
                data_snapshot=result["metrics"],
                tokens_used=result.get("tokens_used", 0),
                expires_at=timezone.now() + timedelta(days=7),
            )
            return JsonResponse(
                {
                    "narrative": insight.narrative,
                    "metrics": result["metrics"],
                    "generated_at": insight.generated_at.isoformat(),
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 12: DASHBOARD ASSISTANT (widget API)
# ══════════════════════════════════════════════════════════════════════════════


class DashboardAssistantView(CompanyMixin, View):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    """AJAX endpoint for the floating dashboard assistant widget."""

    def post(self, request):
        from apps.ai.services import DashboardAssistantService

        try:
            data = json.loads(request.body)
            question = data.get("question", "").strip()
            dashboard_ctx = data.get("context", {})

            if not question:
                return JsonResponse({"error": "Empty question"}, status=400)

            answer = DashboardAssistantService.answer(
                question, dashboard_ctx, self.company()
            )
            return JsonResponse({"answer": answer})
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}", exc_info=True)
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 13: AI SETTINGS & ADMIN
# ══════════════════════════════════════════════════════════════════════════════


class AISettingsView(CompanyMixin, TemplateView):
    required_permission = "ai.read"

    def get_required_permission(self, request=None):
        if request:
            if request.method == "POST":
                return "ai.create"
            elif request.method in ["PUT", "PATCH"]:
                return "ai.update"
            elif request.method == "DELETE":
                return "ai.delete"
        return self.required_permission
    template_name = "ai/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.ai.forms import AIConfigurationForm
        from apps.ai.models import AIConfiguration

        company = self.company()
        config, _ = AIConfiguration.objects.get_or_create(company=company)
        if "form" not in kwargs:
            ctx["form"] = AIConfigurationForm(instance=config)

        # Reflect DB key status (DB key OR .env key = configured)
        ctx["openai_key_set"] = bool(config.get_openai_key())
        ctx["gemini_key_set"] = bool(config.get_gemini_key())

        from django.conf import settings as _s
        ctx["twilio_set"] = bool(
            config.twilio_account_sid or getattr(_s, "TWILIO_ACCOUNT_SID", "")
        )
        ctx["model"] = config.openai_model or "gpt-4o-mini"

        ctx["total_conversations"] = AIConversation.objects.filter(
            company=company
        ).count()
        ctx["total_ocr"] = OCRDocument.objects.filter(company=company).count()
        ctx["total_insights"] = AIInsight.objects.filter(company=company).count()
        ctx["total_nlp"] = NLPReport.objects.filter(company=company).count()

        # Token usage
        from django.db.models import Sum

        ctx["tokens_used"] = (
            AIMessage.objects.filter(conversation__company=company).aggregate(
                t=Sum("tokens_used")
            )["t"]
            or 0
        )
        return ctx

    def post(self, request, *args, **kwargs):
        from apps.ai.forms import AIConfigurationForm
        from apps.ai.models import AIConfiguration

        config, created = AIConfiguration.objects.get_or_create(company=self.company())
        form = AIConfigurationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "AI configuration updated successfully.")
            return redirect("ai:settings")

        return self.render_to_response(self.get_context_data(form=form))
