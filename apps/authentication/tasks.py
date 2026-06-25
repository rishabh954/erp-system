"""
Authentication Celery Tasks
"""
from celery import shared_task
import logging

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_sessions():
    from apps.authentication.models import UserSession
    from django.utils import timezone
    count = UserSession.objects.filter(expires_at__lt=timezone.now()).delete()[0]
    logger.info(f'Deleted {count} expired sessions')


@shared_task
def cleanup_old_audit_logs():
    from apps.authentication.models import ActivityLog
    from django.conf import settings
    from django.utils import timezone
    from datetime import timedelta
    days = settings.ERP_SETTINGS.get('AUDIT_LOG_RETENTION_DAYS', 365)
    cutoff = timezone.now() - timedelta(days=days)
    count = ActivityLog.objects.filter(created_at__lt=cutoff).delete()[0]
    logger.info(f'Deleted {count} old audit log entries')


@shared_task
def cleanup_expired_tokens():
    from apps.authentication.models import PasswordResetToken, EmailVerificationToken
    from django.utils import timezone
    pr = PasswordResetToken.objects.filter(expires_at__lt=timezone.now(), is_used=False).update(is_used=True)
    ev = EmailVerificationToken.objects.filter(expires_at__lt=timezone.now(), is_used=False).update(is_used=True)
    logger.info(f'Expired {pr} password reset tokens, {ev} email verification tokens')
