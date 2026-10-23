from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.crm.models import Lead
from apps.purchase.models import PurchaseOrder, Vendor


def make_company_admin(company, email):
    user = User.objects.create_user(
        email=email,
        password="password",
        first_name="Company",
        last_name="Admin",
        is_superuser=True,
        primary_company=company,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.SUPER_ADMIN,
        is_active=True,
    )
    return user


@pytest.mark.django_db
def test_crm_follow_up_queues_company_bound_notification_per_lead():
    from apps.crm.tasks import follow_up_leads
    from apps.notifications.tasks import send_bulk_notification

    company_a = Company.objects.create(name="CRM A")
    company_b = Company.objects.create(name="CRM B")
    user_a = make_company_admin(company_a, "crm-a@example.com")
    user_b = make_company_admin(company_b, "crm-b@example.com")
    lead_a = Lead.objects.create(company=company_a, name="Stale A", assigned_to=user_a)
    lead_b = Lead.objects.create(company=company_b, name="Stale B", assigned_to=user_b)
    stale_date = timezone.now() - timedelta(days=10)
    Lead.objects.filter(pk__in=[lead_a.pk, lead_b.pk]).update(created_at=stale_date)

    with patch.object(send_bulk_notification, "delay") as delay:
        result = follow_up_leads.run()

    assert result == "Queued 2 lead follow-up notifications."
    assert delay.call_count == 2
    calls = {call.kwargs["company_id"]: call.kwargs for call in delay.call_args_list}
    assert calls[str(company_a.pk)]["recipient_ids"] == [user_a.pk]
    assert calls[str(company_b.pk)]["recipient_ids"] == [user_b.pk]
    assert calls[str(company_a.pk)]["action_url"] == f"/crm/leads/{lead_a.pk}/"
    assert calls[str(company_b.pk)]["action_url"] == f"/crm/leads/{lead_b.pk}/"


@pytest.mark.django_db
def test_crm_score_recalculation_skips_inactive_companies():
    from apps.crm.tasks import calculate_lead_scores

    active_company = Company.objects.create(name="Active CRM")
    inactive_company = Company.objects.create(
        name="Inactive CRM", status=Company.Status.INACTIVE
    )
    active_lead = Lead.objects.create(
        company=active_company,
        name="Active Lead",
        status=Lead.Status.NEW,
        probability=99,
    )
    inactive_lead = Lead.objects.create(
        company=inactive_company,
        name="Inactive Lead",
        status=Lead.Status.NEW,
        probability=99,
    )

    result = calculate_lead_scores.run()

    active_lead.refresh_from_db()
    inactive_lead.refresh_from_db()
    assert result == "Updated probability for 1 leads."
    assert active_lead.probability == 10
    assert inactive_lead.probability == 99


@pytest.mark.django_db
def test_accounting_monthly_report_notification_uses_task_contract_and_tenant():
    from apps.accounting.tasks import generate_monthly_reports
    from apps.notifications.tasks import send_bulk_notification

    company = Company.objects.create(name="Monthly Report Company")
    admin = make_company_admin(company, "monthly@example.com")

    with patch.object(send_bulk_notification, "delay") as delay:
        result = generate_monthly_reports.run(company_id=str(company.pk))

    assert result == "Monthly report notification sent to 1 users."
    delay.assert_called_once()
    kwargs = delay.call_args.kwargs
    assert kwargs["recipient_ids"] == [admin.pk]
    assert kwargs["company_id"] == str(company.pk)
    assert kwargs["title"].startswith("Monthly P&L Report (")
    assert kwargs["action_url"] == "/accounting/reports/profit-and-loss/"


@pytest.mark.django_db
def test_accounting_overdue_payment_notifications_do_not_cross_companies():
    from apps.accounting.tasks import check_overdue_payments
    from apps.notifications.tasks import send_bulk_notification

    company_a = Company.objects.create(name="Purchase A")
    company_b = Company.objects.create(name="Purchase B")
    admin_a = make_company_admin(company_a, "purchase-a@example.com")
    admin_b = make_company_admin(company_b, "purchase-b@example.com")
    vendor_a = Vendor.objects.create(company=company_a, name="Vendor A")
    vendor_b = Vendor.objects.create(company=company_b, name="Vendor B")
    due_date = timezone.localdate() - timedelta(days=1)
    order_a = PurchaseOrder.objects.create(
        company=company_a,
        vendor=vendor_a,
        status=PurchaseOrder.Status.CONFIRMED,
        order_date=due_date,
        expected_delivery=due_date,
        balance_due="125.00",
    )
    order_b = PurchaseOrder.objects.create(
        company=company_b,
        vendor=vendor_b,
        status=PurchaseOrder.Status.CONFIRMED,
        order_date=due_date,
        expected_delivery=due_date,
        balance_due="250.00",
    )

    with patch.object(send_bulk_notification, "delay") as delay:
        result = check_overdue_payments.run()

    assert result == "Queued 2 overdue payment notifications."
    assert delay.call_count == 2
    calls = {call.kwargs["company_id"]: call.kwargs for call in delay.call_args_list}
    assert calls[str(company_a.pk)]["recipient_ids"] == [admin_a.pk]
    assert calls[str(company_b.pk)]["recipient_ids"] == [admin_b.pk]
    assert calls[str(company_a.pk)]["action_url"] == f"/purchase/orders/{order_a.pk}/"
    assert calls[str(company_b.pk)]["action_url"] == f"/purchase/orders/{order_b.pk}/"
