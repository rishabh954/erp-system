from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.analytics.models import SavedReport, ScheduledReport
from apps.analytics.tasks import run_scheduled_report, run_scheduled_reports_daily
from apps.helpdesk.tasks import check_sla_breaches

pytestmark = pytest.mark.django_db


def test_periodic_task_schedule_references_existing_tasks():
    task_names = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}

    expected = {
        "apps.helpdesk.tasks.check_sla_breaches",
        "analytics.run_scheduled_reports_daily",
        "apps.crm.tasks.calculate_lead_scores",
        "apps.crm.tasks.follow_up_leads",
        "apps.hrms.tasks.reset_annual_leave_balances",
        "apps.accounting.tasks.check_overdue_payments",
        "apps.company.tasks.send_trial_expiry_reminders",
        "apps.authentication.tasks.cleanup_expired_sessions",
        "apps.authentication.tasks.cleanup_old_audit_logs",
        "ai.refresh_sales_forecast",
        "ai.refresh_inventory_forecast",
        "apps.accounting.tasks.generate_monthly_reports_for_all_companies",
    }
    assert expected <= task_names
    assert check_sla_breaches.name in task_names


@pytest.mark.django_db(transaction=True)
def test_due_scheduled_reports_are_queued_and_rescheduled(company, user, monkeypatch):
    report = SavedReport.objects.create(
        name="Daily report",
        module=SavedReport.Module.INVOICES,
        created_by=user,
        company=company,
    )
    schedule = ScheduledReport.objects.create(
        report=report,
        frequency=ScheduledReport.Frequency.DAILY,
        recipients="reports@example.com",
        created_by=user,
        next_run=timezone.now() - timedelta(minutes=1),
    )
    queued = []
    monkeypatch.setattr(run_scheduled_report, "delay", queued.append)

    count = run_scheduled_reports_daily()

    schedule.refresh_from_db()
    assert count == 1
    assert queued == [str(schedule.pk)]
    assert schedule.next_run > timezone.now()


@pytest.mark.django_db(transaction=True)
def test_new_monthly_report_schedule_is_not_run_immediately(company, user, monkeypatch):
    report = SavedReport.objects.create(
        name="Monthly report",
        module=SavedReport.Module.INVOICES,
        created_by=user,
        company=company,
    )
    schedule = ScheduledReport.objects.create(
        report=report,
        frequency=ScheduledReport.Frequency.MONTHLY,
        recipients="reports@example.com",
        created_by=user,
    )
    queued = []
    monkeypatch.setattr(run_scheduled_report, "delay", queued.append)

    count = run_scheduled_reports_daily()

    schedule.refresh_from_db()
    assert count == 0
    assert queued == []
    assert schedule.next_run > timezone.now()
