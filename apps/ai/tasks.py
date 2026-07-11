"""AI Module — Celery Background Tasks"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="ai.refresh_sales_forecast")
def refresh_sales_forecast():
    """Nightly: pre-compute and cache sales forecasts for all companies."""
    try:
        from datetime import timedelta

        from django.utils import timezone

        from apps.ai.models import AIForecast
        from apps.ai.services import ForecastingService
        from apps.company.models import Company

        for company in Company.objects.filter(is_active=True):
            for period, days in [("7d", 7), ("30d", 30), ("90d", 90)]:
                try:
                    data = ForecastingService.sales_forecast(company, days_ahead=days)
                    AIForecast.objects.update_or_create(
                        company=company,
                        forecast_type="sales",
                        period=period,
                        scope_model="",
                        scope_id="",
                        defaults={
                            "forecast_data": data,
                            "algorithm": data.get("metrics", {}).get(
                                "algorithm", "linear"
                            ),
                            "valid_until": timezone.now() + timedelta(hours=24),
                        },
                    )
                except Exception as e:
                    logger.error(f"Sales forecast failed for {company}: {e}")

        logger.info("Sales forecast refresh complete.")
    except Exception as e:
        logger.error(f"refresh_sales_forecast task error: {e}")


@shared_task(name="ai.refresh_inventory_forecast")
def refresh_inventory_forecast():
    """Nightly: pre-compute inventory reorder alerts."""
    try:
        from datetime import timedelta

        from django.utils import timezone

        from apps.ai.models import AIForecast
        from apps.ai.services import ForecastingService
        from apps.company.models import Company

        for company in Company.objects.filter(is_active=True):
            try:
                data = ForecastingService.inventory_forecast(company, days_ahead=30)
                AIForecast.objects.update_or_create(
                    company=company,
                    forecast_type="inventory",
                    period="30d",
                    scope_model="",
                    scope_id="",
                    defaults={
                        "forecast_data": data,
                        "algorithm": "linear_consumption",
                        "valid_until": timezone.now() + timedelta(hours=24),
                    },
                )
            except Exception as e:
                logger.error(f"Inventory forecast failed for {company}: {e}")

        logger.info("Inventory forecast refresh complete.")
    except Exception as e:
        logger.error(f"refresh_inventory_forecast task error: {e}")


@shared_task(name="ai.generate_financial_summaries")
def generate_financial_summaries():
    """Weekly: generate and cache AI financial summaries."""
    try:
        from datetime import timedelta

        from django.utils import timezone

        from apps.ai.models import AIInsight
        from apps.ai.services import FinancialSummaryService
        from apps.company.models import Company

        for company in Company.objects.filter(is_active=True):
            try:
                result = FinancialSummaryService.generate_summary(company)
                AIInsight.objects.create(
                    company=company,
                    insight_type="financial",
                    title=f"Financial Summary — {result['metrics'].get('period', 'Current Month')}",
                    narrative=result["narrative"],
                    data_snapshot=result["metrics"],
                    tokens_used=result.get("tokens_used", 0),
                    expires_at=timezone.now() + timedelta(days=7),
                )
            except Exception as e:
                logger.error(f"Financial summary failed for {company}: {e}")

        logger.info("Financial summaries generation complete.")
    except Exception as e:
        logger.error(f"generate_financial_summaries task error: {e}")


@shared_task(name="ai.process_ocr_document")
def process_ocr_document(doc_id: str):
    """Process a single OCR document asynchronously."""
    try:
        from apps.ai.models import OCRDocument
        from apps.ai.services import OCRService

        doc = OCRDocument.objects.get(id=doc_id)
        doc.status = OCRDocument.Status.PROCESSING
        doc.save(update_fields=["status"])

        result = OCRService.extract(doc.original_file, doc_type=doc.doc_type)

        doc.extracted_data = result.get("extracted_data", {})
        doc.raw_text = result.get("raw_text", "")
        doc.confidence = result.get("confidence", 0.0)
        doc.processing_time_ms = result.get("processing_time_ms", 0)
        doc.error_message = result.get("error", "")
        doc.status = (
            OCRDocument.Status.DONE
            if not result.get("error")
            else OCRDocument.Status.FAILED
        )
        doc.save()

        logger.info(f"OCR processed document {doc_id}: {doc.status}")
    except Exception as e:
        logger.error(f"OCR task failed for {doc_id}: {e}")
        try:
            from apps.ai.models import OCRDocument

            OCRDocument.objects.filter(id=doc_id).update(
                status=OCRDocument.Status.FAILED, error_message="An unexpected error occurred."
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to save report: %s", e)
