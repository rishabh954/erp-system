"""
Celery Application Configuration
"""
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('erp')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


# ─── Periodic Tasks (Beat) ─────────────────────────────────────────────────
app.conf.beat_schedule = {
    # Daily: Check overdue invoices and send reminders
    'check-overdue-invoices': {
        'task': 'apps.sales.tasks.check_overdue_invoices',
        'schedule': crontab(hour=8, minute=0),
    },
    # Daily: Process attendance auto-marking
    'auto-mark-attendance': {
        'task': 'apps.hrms.tasks.auto_mark_attendance',
        'schedule': crontab(hour=23, minute=59),
    },
    # Daily: Send low stock alerts
    'low-stock-alerts': {
        'task': 'apps.inventory.tasks.send_low_stock_alerts',
        'schedule': crontab(hour=9, minute=0),
    },
    # Daily: Update exchange rates
    'update-exchange-rates': {
        'task': 'apps.company.tasks.update_exchange_rates',
        'schedule': crontab(hour=0, minute=30),
    },
    # Weekly: Generate depreciation entries
    'process-depreciation': {
        'task': 'apps.assets.tasks.process_depreciation',
        'schedule': crontab(day_of_week=1, hour=2, minute=0),
    },
    # Daily: Check SLA breaches for tickets
    'check-sla-breaches': {
        'task': 'apps.helpdesk.tasks.check_sla_breaches',
        'schedule': crontab(minute='*/30'),
    },
    # Hourly: Clean up expired sessions
    'cleanup-sessions': {
        'task': 'apps.authentication.tasks.cleanup_expired_sessions',
        'schedule': crontab(minute=0),
    },
    # Daily: Cleanup old audit logs
    'cleanup-audit-logs': {
        'task': 'apps.authentication.tasks.cleanup_old_audit_logs',
        'schedule': crontab(hour=3, minute=0),
    },
}
