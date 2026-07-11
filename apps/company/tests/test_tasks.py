import pytest

from apps.company.tasks import update_exchange_rates


@pytest.mark.django_db
def test_update_exchange_rates_no_crash():
    # Calling this directly should not raise NameError for timezone
    update_exchange_rates()
