from unittest.mock import MagicMock, patch

import pytest

from apps.inventory.services import DeliveryService


@pytest.mark.django_db
def test_ship_delivery_logger_no_crash(mocker):
    # Setup mock delivery and mock stock service
    delivery = MagicMock()
    delivery.status = "ready"
    delivery.lines.all.return_value = []

    # We mock select_for_update to return the same magic mock
    mocker.patch('apps.inventory.models.DeliveryOrder.objects.select_for_update', return_value=MagicMock(get=MagicMock(return_value=delivery)))

    # We mock ShiprocketService to raise an Exception and see if logger crashes
    with patch('apps.administration.services.integrations.ShiprocketService') as MockShiprocket:
        instance = MockShiprocket.return_value
        instance.create_shipment.side_effect = Exception("API error")

        service = DeliveryService(company=MagicMock(), user=MagicMock())
        # Even with API error, it should not raise NameError for logger
        service.ship_delivery(delivery, user=MagicMock())
