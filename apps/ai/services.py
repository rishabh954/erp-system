"""
Enterprise AI Services
Provides: LLM chat, OCR, ML forecasting, insights, NLP reports,
          customer analysis, purchase recommendations, expense categorisation.

All services degrade gracefully when OPENAI_API_KEY is not set.
"""

import io
import json
import logging
import re
import time
from collections.abc import Generator
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Lazy imports (no hard crash if libraries not installed) ──────────────────


def _get_openai():
    try:
        from openai import OpenAI

        api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
        if not api_key:
            return None
        return OpenAI(api_key=api_key)
    except ImportError:
        return None


def _get_gemini():
    try:
        import google.generativeai as genai

        key = getattr(settings, "GEMINI_API_KEY", "") or ""
        if not key:
            return None
        genai.configure(api_key=key)
        return genai.GenerativeModel("gemini-1.5-flash")
    except ImportError:
        return None


AI_NOT_CONFIGURED_MSG = (
    "🔧 AI is not configured yet. Please add your OPENAI_API_KEY to the .env file "
    "and restart the server. Visit /ai/settings/ for setup instructions."
)


# ══════════════════════════════════════════════════════════════════════════════
# LLM CLIENT  (OpenAI primary, Gemini fallback)
# ══════════════════════════════════════════════════════════════════════════════


class LLMService:
    """Unified interface for OpenAI and Gemini."""

    SYSTEM_PROMPT = """You are an intelligent ERP assistant for an enterprise business management system.
You have access to business context including sales, finance, HR, inventory, CRM, and projects data.
You answer questions clearly and concisely, help interpret data, generate insights, and assist with reports.
When you don't have specific data, say so clearly and suggest what data would help.
Format responses using markdown. Use tables for comparisons. Be professional and business-focused."""

    @classmethod
    def chat(
        cls,
        messages: list,
        context: str = "general",
        stream: bool = False,
        max_tokens: int = 1500,
    ) -> tuple[str, int] | Generator:
        """Send messages to LLM and return response."""
        client = _get_openai()

        if client:
            try:
                system_msg = [
                    {
                        "role": "system",
                        "content": cls.SYSTEM_PROMPT + f"\nContext module: {context}",
                    }
                ]
                all_messages = system_msg + messages

                if stream:
                    return cls._stream_openai(client, all_messages, max_tokens)

                response = client.chat.completions.create(
                    model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                    messages=all_messages,
                    max_tokens=max_tokens,
                    temperature=getattr(settings, "AI_TEMPERATURE", 0.3),
                )
                return response.choices[0].message.content, response.usage.total_tokens

            except Exception as e:
                logger.error(f"OpenAI error: {e}")
                # Fall through to Gemini
                gemini = _get_gemini()
                if gemini:
                    return cls._gemini_chat(gemini, messages)
                return AI_NOT_CONFIGURED_MSG, 0

        # Try Gemini
        gemini = _get_gemini()
        if gemini:
            return cls._gemini_chat(gemini, messages)

        if stream:

            def _no_config():
                yield AI_NOT_CONFIGURED_MSG

            return _no_config()

        return AI_NOT_CONFIGURED_MSG, 0

    @classmethod
    def _stream_openai(cls, client, messages: list, max_tokens: int) -> Generator:
        try:
            stream = client.chat.completions.create(
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                messages=messages,
                max_tokens=max_tokens,
                temperature=getattr(settings, "AI_TEMPERATURE", 0.3),
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta
                if hasattr(delta, "content") and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"OpenAI stream error: {e}")
            yield f"\n\n⚠️ Stream error: {"An unexpected error occurred."}"

    @classmethod
    def _gemini_chat(cls, model, messages: list):
        try:
            # Convert to Gemini format
            text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in messages)
            response = model.generate_content(text)
            return response.text, 0
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return AI_NOT_CONFIGURED_MSG, 0

    @classmethod
    def complete(cls, prompt: str, max_tokens: int = 800) -> str:
        """Single-shot completion."""
        result, _ = cls.chat(
            [{"role": "user", "content": prompt}], max_tokens=max_tokens
        )
        return result


# ══════════════════════════════════════════════════════════════════════════════
# OCR SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class OCRService:
    """
    Extracts structured data from invoice/receipt images.
    Uses OpenAI Vision (primary) or Tesseract (fallback).
    """

    INVOICE_PROMPT = """Extract all data from this invoice image and return ONLY valid JSON with this structure:
{
  "vendor": "Vendor name",
  "vendor_address": "Full address",
  "invoice_number": "INV-XXXX",
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "currency": "USD",
  "subtotal": 0.00,
  "tax_amount": 0.00,
  "total": 0.00,
  "line_items": [
    {"description": "", "quantity": 0, "unit_price": 0.00, "total": 0.00}
  ],
  "payment_terms": "",
  "notes": ""
}
Return ONLY the JSON object, no explanation."""

    RECEIPT_PROMPT = """Extract all data from this receipt image and return ONLY valid JSON:
{
  "merchant": "Store/merchant name",
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "currency": "USD",
  "subtotal": 0.00,
  "tax": 0.00,
  "total": 0.00,
  "payment_method": "cash/card/etc",
  "category_suggestion": "meals/travel/office/etc",
  "line_items": [{"description": "", "amount": 0.00}]
}
Return ONLY the JSON object, no explanation."""

    @classmethod
    def extract(cls, file_obj, doc_type: str = "invoice") -> dict:
        """Process uploaded file and extract structured data."""
        start = time.time()
        result = {
            "extracted_data": {},
            "raw_text": "",
            "confidence": 0.0,
            "processing_time_ms": 0,
            "error": "",
        }

        try:
            # Read image bytes
            if hasattr(file_obj, "read"):
                image_bytes = file_obj.read()
            else:
                with open(file_obj, "rb") as f:
                    image_bytes = f.read()

            # Try OpenAI Vision first
            client = _get_openai()
            if client:
                extracted = cls._extract_via_openai_vision(
                    client, image_bytes, doc_type
                )
                result["extracted_data"] = extracted
                result["confidence"] = 0.92
            else:
                # Fallback: Tesseract OCR
                extracted = cls._extract_via_tesseract(image_bytes, doc_type)
                result.update(extracted)

        except Exception as e:
            logger.error(f"OCR error: {e}")
            result["error"] = "An unexpected error occurred."

        result["processing_time_ms"] = int((time.time() - start) * 1000)
        return result

    @classmethod
    def _extract_via_openai_vision(
        cls, client, image_bytes: bytes, doc_type: str
    ) -> dict:
        import base64

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt = cls.INVOICE_PROMPT if doc_type == "invoice" else cls.RECEIPT_PROMPT

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=1500,
        )
        raw = response.choices[0].message.content.strip()
        # Clean markdown code blocks
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)

    @classmethod
    def _extract_via_tesseract(cls, image_bytes: bytes, doc_type: str) -> dict:
        try:
            import pytesseract
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes))
            raw_text = pytesseract.image_to_string(image)
            return {
                "raw_text": raw_text,
                "extracted_data": {
                    "raw_text": raw_text,
                    "note": "Tesseract OCR — manual review recommended",
                },
                "confidence": 0.6,
            }
        except ImportError:
            return {
                "raw_text": "",
                "extracted_data": {},
                "confidence": 0.0,
                "error": "OCR engine not available. Install pytesseract or configure OpenAI API key.",
            }


# ══════════════════════════════════════════════════════════════════════════════
# FORECASTING SERVICE  (scikit-learn + pandas — no API cost)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastingService:
    """
    ML-based forecasting using scikit-learn.
    numpy and pandas are already installed.
    """

    @classmethod
    def sales_forecast(cls, company, days_ahead: int = 30) -> dict:
        """Forecast total sales for the next N days."""
        try:
            import numpy as np
            from sklearn.linear_model import LinearRegression
            from sklearn.preprocessing import PolynomialFeatures

            from apps.sales.models import SalesOrder

            # Build historical series — last 90 days of daily sales
            end = timezone.now().date()
            start = end - timedelta(days=90)

            qs = SalesOrder.objects.filter(company=company, order_date__gte=start, order_date__lte=end)
            orders = qs.values("order_date").annotate(total=Sum("total"))

            # Fill in missing days with 0
            date_series: dict[str, float] = {}
            d = start
            while d <= end:
                date_series[str(d)] = 0.0
                d += timedelta(days=1)
            for o in orders:
                date_series[str(o["order_date"])] = float(o["total"] or 0)

            y = np.array(list(date_series.values()))
            x = np.arange(len(y)).reshape(-1, 1)

            # Polynomial regression for better fit
            poly = PolynomialFeatures(degree=2)
            x_poly = poly.fit_transform(x)
            model = LinearRegression()
            model.fit(x_poly, y)

            # Predict future
            future_x = np.arange(len(y), len(y) + days_ahead).reshape(-1, 1)
            future_x_poly = poly.transform(future_x)
            forecast_y: Any = model.predict(future_x_poly)

            # Cap minimum at 0
            forecast_y = np.maximum(forecast_y, 0)
            
            # Build labels
            future_dates = [
                (end + timedelta(days=i + 1)).strftime("%b %d")
                for i in range(days_ahead)
            ]
            historical_dates = [d for d in date_series.keys()]

            # Confidence bands (±15%)
            lower = [max(0, p * 0.85) for p in forecast_y]
            upper = [p * 1.15 for p in forecast_y]

            r2 = model.score(x_poly, y)

            return {
                "type": "sales",
                "period": f"{days_ahead}d",
                "historical_labels": historical_dates[-30:],
                "historical_values": y[-30:].tolist(),
                "forecast_labels": future_dates,
                "predicted": [float(p) for p in forecast_y],
                "lower_bound": [float(l) for l in lower],
                "upper_bound": [float(u) for u in upper],
                "metrics": {
                    "r2_score": round(r2, 3),
                    "algorithm": "Polynomial Regression (degree=2)",
                    "training_days": len(y),
                    "total_predicted": round(
                        sum(float(p) for p in forecast_y), 2
                    ),
                },
            }
        except Exception as e:
            logger.error(f"Sales forecast error: {e}")
            return cls._empty_forecast("sales", days_ahead, str(e))

    @classmethod
    def inventory_forecast(cls, company, days_ahead: int = 30) -> dict:
        """Predict which products will hit reorder points in N days."""
        try:
            from apps.inventory.models import Product

            products = Product.objects.filter(company=company, is_active=True)

            alerts = []
            for p in products:
                stock = float(p.total_stock or 0)
                reorder = float(p.reorder_point or 0)
                if reorder > 0:
                    # Simple linear consumption assumption
                    daily_rate = max(0.5, stock / 30)
                    days_until_reorder = (
                        (stock - reorder) / daily_rate if daily_rate > 0 else 999
                    )
                    if days_until_reorder <= days_ahead:
                        alerts.append(
                            {
                                "product_id": p.id,
                                "product": p.name,
                                "current_stock": stock,
                                "reorder_level": reorder,
                                "reorder_quantity": float(p.reorder_quantity or 0),
                                "days_until_reorder": max(0, round(days_until_reorder)),
                                "total": stock,
                                "urgency": (
                                    "critical" if days_until_reorder <= 7 else "warning"
                                ),
                            }
                        )

            alerts.sort(key=lambda x: float(x.get("days_until_reorder", 0)))

            return {
                "type": "inventory",
                "period": f"{days_ahead}d",
                "alerts": alerts,
                "total_alerts": len(alerts),
                "critical_count": sum(1 for a in alerts if a["urgency"] == "critical"),
                "metrics": {
                    "products_analysed": products.count(),
                    "algorithm": "Linear Consumption Model",
                },
            }
        except Exception as e:
            logger.error(f"Inventory forecast error: {e}")
            return {"type": "inventory", "alerts": [], "error": "An unexpected error occurred."}

    @classmethod
    def demand_prediction(cls, company, product_id=None, days_ahead: int = 30) -> dict:
        """Predict demand using exponential weighted moving average (EWMA)."""
        try:
            import numpy as np

            from apps.sales.models import SalesOrderLine

            filters = {"sales_order__company": company}
            if product_id:
                filters["product_id"] = product_id

            # Last 60 days of sales quantities per day
            end = timezone.now().date()
            start = end - timedelta(days=60)

            qs: Any = SalesOrderLine.objects.filter(
                sales_order__order_date__gte=start,
                sales_order__order_date__lte=end,
                **filters,
            )
            items = qs.values("sales_order__order_date").annotate(qty=Sum("quantity"))

            date_map = {}
            d = start
            while d <= end:
                date_map[str(d)] = 0
                d += timedelta(days=1)
            for item in items:
                date_map[str(item["sales_order__order_date"])] = float(item["qty"] or 0)

            values = np.array(list(date_map.values()))

            # EWMA forecast
            alpha = 0.3
            ewma = [values[0]]
            for v in values[1:]:
                ewma.append(alpha * v + (1 - alpha) * ewma[-1])

            last_ewma = ewma[-1]
            trend = (ewma[-1] - ewma[max(0, len(ewma) - 7)]) / 7  # 7-day trend

            future_labels = [
                (end + timedelta(days=i + 1)).strftime("%b %d")
                for i in range(days_ahead)
            ]
            predicted = [max(0, last_ewma + trend * (i + 1)) for i in range(days_ahead)]
            lower = [max(0, p * 0.8) for p in predicted]
            upper = [p * 1.2 for p in predicted]

            return {
                "type": "demand",
                "period": f"{days_ahead}d",
                "historical_labels": list(date_map.keys())[-30:],
                "historical_values": values[-30:].tolist(),
                "forecast_labels": future_labels,
                "predicted": predicted,
                "lower_bound": lower,
                "upper_bound": upper,
                "metrics": {
                    "algorithm": "EWMA (α=0.3)",
                    "daily_trend": round(trend, 2),
                    "avg_daily_demand": round(float(np.mean(values)), 2),
                },
            }
        except Exception as e:
            logger.error(f"Demand prediction error: {e}")
            return cls._empty_forecast("demand", days_ahead, str(e))

    @classmethod
    def _empty_forecast(cls, ftype: str, days: int, error: str = "") -> dict:
        return {
            "type": ftype,
            "period": f"{days}d",
            "historical_labels": [],
            "historical_values": [],
            "forecast_labels": [],
            "predicted": [],
            "lower_bound": [],
            "upper_bound": [],
            "metrics": {},
            "error": error,
        }


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOMER INSIGHTS SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class CustomerInsightService:
    """AI-powered customer segmentation and behaviour analysis."""

    @classmethod
    def analyse_customers(cls, company) -> dict:
        """Segment customers by RFM (Recency, Frequency, Monetary) value."""
        try:
            from apps.sales.models import SalesOrder

            now = timezone.now().date()
            orders = SalesOrder.objects.filter(company=company, status="approved")

            # RFM per customer
            customer_data = {}
            for order in orders.select_related("customer").values(
                "customer_id", "customer__name", "order_date", "total"
            ):
                cid = order["customer_id"]
                if cid not in customer_data:
                    customer_data[cid] = {
                        "name": order["customer__name"],
                        "orders": [],
                        "totals": [],
                    }
                customer_data[cid]["orders"].append(order["order_date"])
                customer_data[cid]["totals"].append(float(order["total"] or 0))

            segments = {
                "champions": [],
                "loyal": [],
                "at_risk": [],
                "new": [],
                "lost": [],
            }

            for cid, data in customer_data.items():
                last_order = max(data["orders"])
                recency = (now - last_order).days
                frequency = len(data["orders"])
                monetary = sum(data["totals"])

                # Simple segmentation rules
                if recency <= 30 and frequency >= 5 and monetary >= 10000:
                    seg = "champions"
                elif recency <= 60 and frequency >= 3:
                    seg = "loyal"
                elif recency <= 30 and frequency <= 2:
                    seg = "new"
                elif recency > 90:
                    seg = "lost"
                else:
                    seg = "at_risk"

                segments[seg].append(
                    {
                        "id": cid,
                        "name": data["name"],
                        "recency_days": recency,
                        "frequency": frequency,
                        "monetary": monetary,
                    }
                )

            # Generate AI narrative
            summary_data = {k: len(v) for k, v in segments.items()}
            prompt = f"""Analyse these customer segments for an ERP business and provide 3-4 actionable insights:
Segments: {json.dumps(summary_data)}
Total customers: {sum(summary_data.values())}
Focus on retention, growth opportunities, and risk mitigation. Be specific and practical."""

            narrative, tokens = LLMService.chat(
                [{"role": "user", "content": prompt}], "crm", max_tokens=500
            )

            return {
                "segments": segments,
                "segment_counts": summary_data,
                "total_customers": sum(summary_data.values()),
                "narrative": narrative,
                "tokens_used": tokens,
            }
        except Exception as e:
            logger.error(f"Customer insight error: {e}")
            return {"segments": {}, "narrative": f"Error: {e}", "error": "An unexpected error occurred."}


# ══════════════════════════════════════════════════════════════════════════════
# PURCHASE RECOMMENDATION SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class PurchaseRecommendationService:
    """Suggests purchase orders based on stock levels + demand forecast."""

    @classmethod
    def recommend(cls, company) -> list:
        """Return a list of recommended POs to create."""
        try:
            pass

            inventory_forecast = ForecastingService.inventory_forecast(
                company, days_ahead=14
            )
            alerts = inventory_forecast.get("alerts", [])

            if not alerts:
                return []

            # Build data for AI recommendation
            prompt = f"""You are a procurement assistant. Based on the following inventory alerts, 
suggest specific purchase orders with quantities and urgency levels.

Alerts (products needing restocking within 14 days):
{json.dumps(alerts[:10], indent=2)}

Return a JSON array of recommendations:
[
  {{
    "product_id": "...",
    "product_name": "...",
    "recommended_quantity": 0,
    "urgency": "critical/high/medium",
    "reason": "brief explanation",
    "suggested_lead_time_days": 0
  }}
]
Return ONLY the JSON array."""

            response, _ = LLMService.chat(
                [{"role": "user", "content": prompt}], "purchase", max_tokens=800
            )

            try:
                if isinstance(response, str) and response.strip().startswith("["):
                    recommendations = json.loads(response)
                else:
                    # Build recommendations from alerts directly
                    recommendations = [
                        {
                            "product_id": a["product_id"],
                            "product_name": a["product"],
                            "recommended_quantity": int(
                                a.get("reorder_quantity", 0)
                                or max(50, a["current_stock"] * 2)
                            ),
                            "urgency": a["urgency"],
                            "reason": f"Stock at {a['current_stock']} units, reorder level {a['reorder_level']} units, ~{a['days_until_reorder']} days remaining",
                            "suggested_lead_time_days": 7,
                        }
                        for a in alerts[:10]
                    ]
                return recommendations
            except (json.JSONDecodeError, Exception):
                return [
                    {
                        "product_name": a["product"],
                        "urgency": a["urgency"],
                        "recommended_quantity": int(
                            a.get("reorder_quantity", 50) or 50
                        ),
                        "reason": "Below reorder level",
                    }
                    for a in alerts[:10]
                ]

        except Exception as e:
            logger.error(f"Purchase recommendation error: {e}")
            return []


# ══════════════════════════════════════════════════════════════════════════════
# EXPENSE CATEGORISATION SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class ExpenseCategorisationService:
    """Automatically categorises expense descriptions to GL accounts."""

    CATEGORIES = [
        "Travel & Transport",
        "Meals & Entertainment",
        "Office Supplies",
        "Software & Subscriptions",
        "Marketing & Advertising",
        "Training & Education",
        "Professional Services",
        "Utilities",
        "Equipment & Maintenance",
        "Medical & Health",
        "Communication",
        "Rent & Facilities",
        "Other",
    ]

    @classmethod
    def categorise(cls, descriptions: list[str]) -> list[dict]:
        """Categorise a batch of expense descriptions."""
        if not descriptions:
            return []

        prompt = f"""Categorise each expense description into one of these categories:
{', '.join(cls.CATEGORIES)}

Expenses to categorise:
{json.dumps([{'id': i, 'description': d} for i, d in enumerate(descriptions)], indent=2)}

Return ONLY a JSON array:
[{{"id": 0, "description": "...", "category": "...", "confidence": 0.0-1.0, "gl_code": "5xxx"}}]"""

        response, _ = LLMService.chat(
            [{"role": "user", "content": prompt}], "expense", max_tokens=800
        )

        try:
            if isinstance(response, str):
                raw = response.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
                if raw.startswith("["):
                    return json.loads(raw)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to parse AI response: %s", e)

        # Fallback: simple keyword matching
        results = []
        for i, desc in enumerate(descriptions):
            desc_lower = desc.lower()
            cat = "Other"
            if any(
                w in desc_lower
                for w in ["flight", "hotel", "taxi", "uber", "travel", "fuel"]
            ):
                cat = "Travel & Transport"
            elif any(
                w in desc_lower
                for w in ["lunch", "dinner", "restaurant", "meal", "coffee"]
            ):
                cat = "Meals & Entertainment"
            elif any(
                w in desc_lower
                for w in [
                    "aws",
                    "google",
                    "microsoft",
                    "slack",
                    "subscription",
                    "software",
                ]
            ):
                cat = "Software & Subscriptions"
            elif any(
                w in desc_lower
                for w in ["pen", "paper", "printer", "stationery", "office"]
            ):
                cat = "Office Supplies"
            results.append(
                {
                    "id": i,
                    "description": desc,
                    "category": cat,
                    "confidence": 0.7,
                    "gl_code": "5000",
                }
            )
        return results

    @classmethod
    def categorise_single(cls, description: str) -> dict:
        results = cls.categorise([description])
        return results[0] if results else {"category": "Other", "confidence": 0.5}


# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL SUMMARY SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class FinancialSummaryService:
    """Generates AI narrative of financial health."""

    @classmethod
    def generate_summary(cls, company) -> dict:
        """Pull key financial metrics and generate a narrative."""
        try:
            metrics = cls._gather_metrics(company)

            prompt = f"""You are a CFO-level financial analyst. Write a concise, professional financial summary (3-4 paragraphs) based on these metrics:

{json.dumps(metrics, indent=2, default=str)}

Cover:
1. Revenue and profitability trends
2. Cash flow and liquidity position
3. Key risks or opportunities
4. Recommended actions

Use clear business language. Format with markdown headers."""

            narrative, tokens = LLMService.chat(
                [{"role": "user", "content": prompt}], "finance", max_tokens=600
            )

            return {
                "narrative": narrative,
                "metrics": metrics,
                "tokens_used": tokens,
                "generated_at": timezone.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Financial summary error: {e}")
            return {"narrative": AI_NOT_CONFIGURED_MSG, "metrics": {}, "error": "An unexpected error occurred."}

    @classmethod
    def _gather_metrics(cls, company) -> dict:
        from django.db.models import Sum

        now = timezone.localdate()
        month_start = now.replace(day=1)

        metrics = {}

        # Sales this month
        try:
            from apps.sales.models import Invoice, SalesOrder

            metrics["monthly_revenue"] = float(
                SalesOrder.objects.filter(
                    company=company, order_date__gte=month_start
                ).aggregate(t=Sum("total"))["t"]
                or 0
            )
            metrics["outstanding_invoices"] = float(
                Invoice.objects.filter(company=company, status="sent").aggregate(
                    t=Sum("total")
                )["t"]
                or 0
            )
            metrics["overdue_invoices"] = float(
                Invoice.objects.filter(
                    company=company, status="overdue"
                ).aggregate(t=Sum("total"))["t"]
                or 0
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to create Invoice for intent: %s", e)

        # Purchase this month
        try:
            from apps.purchase.models import PurchaseOrder

            metrics["monthly_purchases"] = float(
                PurchaseOrder.objects.filter(
                    company=company, order_date__gte=month_start
                ).aggregate(t=Sum("total"))["t"]
                or 0
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to check stock for intent: %s", e)

        # Expenses
        try:
            from apps.hrms.models import ExpenseClaim

            metrics["monthly_expenses"] = float(
                ExpenseClaim.objects.filter(
                    company=company, created_at__date__gte=month_start
                ).aggregate(t=Sum("total_amount"))["t"]
                or 0
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Failed to create Lead for intent: %s", e)

        metrics["period"] = f"{month_start.strftime('%B %Y')}"
        return metrics


# ══════════════════════════════════════════════════════════════════════════════
# NLP REPORT SERVICE
# ══════════════════════════════════════════════════════════════════════════════


class NLPReportService:
    """Converts natural language questions into ERP data queries."""

    MODULE_MAP = {
        "sales": {
            "model": "apps.sales.models.SalesOrder",
            "fields": "number, customer__name, order_date, total, status",
        },
        "invoice": {
            "model": "apps.sales.models.SalesInvoice",
            "fields": "number, customer__name, invoice_date, total, status",
        },
        "purchase": {
            "model": "apps.purchase.models.PurchaseOrder",
            "fields": "number, vendor__name, order_date, total, status",
        },
        "employee": {
            "model": "apps.hrms.models.Employee",
            "fields": "first_name, last_name, department__name, designation, status",
        },
        "inventory": {
            "model": "apps.inventory.models.Product",
            "fields": "name, sku, sale_price, category__name",
        },
        "lead": {
            "model": "apps.crm.models.Lead",
            "fields": "name, company, stage, assigned_to__first_name, estimated_value",
        },
    }

    @classmethod
    def process_question(cls, question: str, company) -> dict:
        """Understand a natural language question and return results."""
        start = time.time()

        # Step 1: Ask LLM what module and filters to use
        intent_prompt = f"""You are an ERP query assistant. Analyse this question and return JSON:

Question: "{question}"

Available modules: {list(cls.MODULE_MAP.keys())}

Return ONLY valid JSON:
{{
  "module": "sales|invoice|purchase|employee|inventory|lead",
  "intent": "list|count|sum|top|trend",
  "filters": {{}},
  "sort_by": "field_name",
  "limit": 20,
  "chart_type": "bar|line|pie|none",
  "human_summary": "Plain English description of what you'll query"
}}"""

        intent_raw, tokens = LLMService.chat(
            [{"role": "user", "content": intent_prompt}], "analytics", max_tokens=300
        )

        try:
            if isinstance(intent_raw, str):
                raw = intent_raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
                intent = json.loads(raw)
            else:
                intent = {}
        except Exception:
            intent = {
                "module": "sales",
                "intent": "list",
                "limit": 20,
                "human_summary": question,
            }

        # Step 2: Execute query
        results, count = cls._execute_query(intent, company)

        # Step 3: Generate narrative answer
        narrative_prompt = f"""Based on these query results, answer the question: "{question}"
Results summary: {count} records returned.
Sample data: {json.dumps(results[:5], default=str)}
Give a clear, concise business answer in 2-3 sentences."""

        narrative, n_tokens = LLMService.chat(
            [{"role": "user", "content": narrative_prompt}], "analytics", max_tokens=250
        )

        return {
            "question": question,
            "intent": intent,
            "results": results,
            "count": count,
            "narrative": narrative,
            "chart_config": cls._build_chart_config(intent, results),
            "tokens_used": tokens + n_tokens,
            "execution_ms": int((time.time() - start) * 1000),
        }

    @classmethod
    def _execute_query(cls, intent: dict, company) -> tuple[list, int]:
        try:
            module = intent.get("module", "sales")
            info = cls.MODULE_MAP.get(module, cls.MODULE_MAP["sales"])
            ModelPath = info["model"]
            app_label, model_name = ModelPath.rsplit(".", 1)
            # Dynamic import
            import importlib

            mod = importlib.import_module(app_label)
            Model = getattr(mod, model_name)

            qs = Model.objects.filter(company=company)
            limit = min(int(intent.get("limit", 20)), 100)

            if intent.get("sort_by"):
                try:
                    qs = qs.order_by(f"-{intent['sort_by']}")
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Failed to apply sort_by: %s", e)

            qs = qs[:limit]
            results = []
            for obj in qs:
                row = {}
                for field in info["fields"].split(", "):
                    try:
                        val = obj
                        for part in field.split("__"):
                            val = getattr(val, part, None)
                        row[field] = str(val) if val is not None else ""
                    except Exception:
                        row[field] = ""
                results.append(row)
            return results, len(results)
        except Exception as e:
            logger.error(f"NLP query execution error: {e}")
            return [], 0

    @classmethod
    def _build_chart_config(cls, intent: dict, results: list) -> dict:
        chart_type = intent.get("chart_type", "none")
        if chart_type == "none" or not results:
            return {}
        return {
            "type": chart_type,
            "data": results[:20],
        }


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════


class DashboardAssistantService:
    """Answers questions about current dashboard data."""

    @classmethod
    def answer(cls, question: str, dashboard_context: dict, company) -> str:
        prompt = f"""You are an ERP dashboard assistant. The user is viewing their business dashboard.

Current dashboard data:
{json.dumps(dashboard_context, default=str, indent=2)}

User question: "{question}"

Give a helpful, specific answer based on the dashboard data. If data is missing, say so.
Keep your response concise (2-4 sentences). Use markdown for emphasis."""

        response, _ = LLMService.chat(
            [{"role": "user", "content": prompt}], "dashboard", max_tokens=300
        )
        return response


# Helper import for Sum
def models_sum(field):
    from django.db.models import Sum

    return Sum(field)
