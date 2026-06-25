"""
Company Celery Tasks - Exchange Rate Updates
"""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def update_exchange_rates():
    """Fetch and update exchange rates from an external API."""
    from apps.company.models import Currency, ExchangeRate
    from datetime import date

    today = date.today()
    base_currency = Currency.objects.filter(is_base=True).first()
    if not base_currency:
        logger.warning('No base currency configured. Skipping exchange rate update.')
        return

    try:
        import urllib.request
        import json
        # Using exchangerate.host (free tier, no API key needed)
        url = f'https://api.exchangerate.host/latest?base={base_currency.code}'
        with urllib.request.urlopen(url, timeout=10) as response:
            data = json.loads(response.read())

        rates = data.get('rates', {})
        currencies = Currency.objects.filter(is_active=True).exclude(pk=base_currency.pk)

        updated = 0
        for currency in currencies:
            rate = rates.get(currency.code)
            if rate:
                ExchangeRate.objects.update_or_create(
                    from_currency=base_currency,
                    to_currency=currency,
                    effective_date=today,
                    defaults={'rate': rate, 'source': 'api'},
                )
                updated += 1

        logger.info(f'Updated {updated} exchange rates for {today}')

    except Exception as e:
        logger.error(f'Exchange rate update failed: {e}')


@shared_task
def send_trial_expiry_reminders():
    """Remind companies approaching trial expiration."""
    from apps.company.models import Company
    from apps.notifications.tasks import send_email_task
    from django.utils import timezone
    from datetime import timedelta

    soon = timezone.now() + timedelta(days=3)
    expiring = Company.objects.filter(
        status='trial',
        trial_ends_at__lte=soon,
        trial_ends_at__gte=timezone.now(),
        is_deleted=False,
    )

    for company in expiring:
        admins = company.users.filter(role='company_admin', is_active=True)
        for admin in admins:
            days_left = (company.trial_ends_at.date() - timezone.now().date()).days
            send_email_task.delay(
                to_email=admin.email,
                to_name=admin.full_name,
                subject=f'Your trial expires in {days_left} day(s)',
                template='trial_expiry',
                context={
                    'user_name': admin.first_name,
                    'company_name': company.name,
                    'days_left': days_left,
                    'trial_end': str(company.trial_ends_at.date()),
                },
                company_id=str(company.pk),
            )
