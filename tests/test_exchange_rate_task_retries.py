import json
from unittest.mock import patch

import pytest

from apps.company.models import Currency, ExchangeRate


@pytest.mark.django_db
def test_exchange_rate_task_retries_provider_failures():
    from apps.company.tasks import update_exchange_rates

    Currency.objects.update_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "is_base": True},
    )

    failure = OSError("provider unavailable")
    with patch("urllib.request.urlopen", side_effect=failure):
        with patch.object(update_exchange_rates, "retry", side_effect=failure) as retry:
            with pytest.raises(OSError, match="provider unavailable"):
                update_exchange_rates.run()
    retry.assert_called_once()


@pytest.mark.django_db
def test_exchange_rate_task_updates_rates_from_provider_response():
    from apps.company.tasks import update_exchange_rates

    base, _ = Currency.objects.update_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "is_base": True},
    )
    target, _ = Currency.objects.update_or_create(
        code="EUR", defaults={"name": "Euro", "symbol": "€", "is_active": True}
    )
    response = {
        "rates": {"EUR": 0.92},
    }

    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = (
            json.dumps(response).encode()
        )
        update_exchange_rates.run()

    rate = ExchangeRate.objects.get(from_currency=base, to_currency=target)
    assert str(rate.rate) == "0.920000"
    assert rate.source == "api"
