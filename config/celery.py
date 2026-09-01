"""
Celery Application Configuration
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('erp')
# Load ALL Celery config (including CELERY_BEAT_SCHEDULE) from Django settings.
# Do NOT set app.conf.beat_schedule here — it would be overwritten by
# config_from_object anyway, and maintaining two places caused operational
# tasks to be silently dropped. All beat tasks live in settings.CELERY_BEAT_SCHEDULE.
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
