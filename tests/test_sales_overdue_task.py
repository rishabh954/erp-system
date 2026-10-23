from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.company.models import Company
from apps.crm.models import Customer
from apps.sales.models import Invoice


def make_overdue_invoice(company, customer, status=Invoice.Status.SENT):
    today = timezone.localdate()
    invoice = Invoice.objects.create(
        company=company,
        customer=customer,
        status=Invoice.Status.DRAFT,
        invoice_date=today - timedelta(days=15),
        due_date=today - timedelta(days=1),
        total="100.00",
        balance_due="100.00",
    )
    Invoice.objects.filter(pk=invoice.pk).update(status=status)
    invoice.status = status
    return invoice


@pytest.mark.django_db
def test_overdue_invoice_task_scopes_status_and_email_to_company(
    django_capture_on_commit_callbacks,
):
    from apps.notifications.tasks import send_email_task
    from apps.sales.tasks import check_overdue_invoices

    company_a = Company.objects.create(name="Overdue A")
    company_b = Company.objects.create(name="Overdue B")
    customer_a = Customer.objects.create(
        company=company_a, name="Customer A", email="a@example.com"
    )
    customer_b = Customer.objects.create(
        company=company_b, name="Customer B", email="b@example.com"
    )
    invoice_a = make_overdue_invoice(company_a, customer_a)
    invoice_b = make_overdue_invoice(company_b, customer_b, Invoice.Status.PARTIAL)

    with patch.object(send_email_task, "delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            processed = check_overdue_invoices.run()

    assert processed == 2
    invoice_a.refresh_from_db()
    invoice_b.refresh_from_db()
    assert invoice_a.status == Invoice.Status.OVERDUE
    assert invoice_b.status == Invoice.Status.OVERDUE
    assert delay.call_count == 2
    calls = {call.kwargs["company_id"]: call.kwargs for call in delay.call_args_list}
    assert calls[str(company_a.pk)]["to_email"] == customer_a.email
    assert calls[str(company_b.pk)]["to_email"] == customer_b.email

    # A subsequent scheduled run must not repeat a reminder for transitioned rows.
    with patch.object(send_email_task, "delay") as repeated_delay:
        assert check_overdue_invoices.run() == 0
    repeated_delay.assert_not_called()


@pytest.mark.django_db
def test_overdue_invoice_without_customer_email_is_marked_without_queueing():
    from apps.notifications.tasks import send_email_task
    from apps.sales.tasks import check_overdue_invoices

    company = Company.objects.create(name="No Email Company")
    customer = Customer.objects.create(company=company, name="No Email Customer")
    invoice = make_overdue_invoice(company, customer)

    with patch.object(send_email_task, "delay") as delay:
        assert check_overdue_invoices.run() == 1

    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.OVERDUE
    delay.assert_not_called()
