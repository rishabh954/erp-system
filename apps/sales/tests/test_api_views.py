from datetime import date
from types import SimpleNamespace

from apps.sales.api.views import InvoiceSerializer


def test_invoice_serializer_get_is_overdue_no_crash():
    serializer = InvoiceSerializer()
    obj = SimpleNamespace(status="sent", due_date=date(2000, 1, 1))
    # Calling this directly should not raise NameError for timezone
    is_overdue = serializer.get_is_overdue(obj)
    assert is_overdue is True
