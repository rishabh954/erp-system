from django import template

from core.services import CurrencyService

register = template.Library()


@register.filter(name="currency")
def currency(value, company=None):
    """
    Formats a numeric value into a currency string based on the given company's settings.
    Usage: {{ amount|currency:current_company }}
    If company is None, falls back to default formatting.
    """  # noqa: E501
    try:
        if value is None:
            return ""
        return CurrencyService.format(value, company)
    except Exception:
        return value
