"""
Authentication Celery Tasks
"""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_sessions():
    from django.utils import timezone

    from apps.authentication.models import UserSession

    count = UserSession.objects.filter(expires_at__lt=timezone.now()).delete()[0]
    logger.info(f"Deleted {count} expired sessions")


@shared_task
def cleanup_old_audit_logs():
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from apps.authentication.models import ActivityLog

    days = settings.ERP_SETTINGS.get("AUDIT_LOG_RETENTION_DAYS", 365)
    cutoff = timezone.now() - timedelta(days=days)
    count = ActivityLog.objects.filter(created_at__lt=cutoff).delete()[0]
    logger.info(f"Deleted {count} old audit log entries")


@shared_task
def cleanup_expired_tokens():
    from django.utils import timezone

    from apps.authentication.models import EmailVerificationToken, PasswordResetToken

    pr = PasswordResetToken.objects.filter(
        expires_at__lt=timezone.now(), is_used=False
    ).update(is_used=True)
    ev = EmailVerificationToken.objects.filter(
        expires_at__lt=timezone.now(), is_used=False
    ).update(is_used=True)
    logger.info(f"Expired {pr} password reset tokens, {ev} email verification tokens")
