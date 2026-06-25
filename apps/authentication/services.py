"""
Authentication Service Layer
2FA, email verification, password reset token generation
"""

import secrets
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.conf import settings

from .models import User, PasswordResetToken, EmailVerificationToken


class AuthService:

    def verify_2fa_code(self, user: User, code: str) -> bool:
        """Verify TOTP or static 2FA code."""
        if user.two_factor_method == 'totp':
            try:
                import pyotp
                # Retrieve the TOTP secret from django-otp device
                from django_otp.plugins.otp_totp.models import TOTPDevice
                device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
                if not device:
                    return False
                totp = pyotp.TOTP(device.key)
                return totp.verify(code, valid_window=1)
            except Exception:
                return False
        elif user.two_factor_method == 'email':
            # Session-stored OTP (set at login time)
            return False  # implement via session OTP
        return False

    def send_email_verification(self, user: User, request=None):
        """Generate and email a verification token."""
        token_str = secrets.token_urlsafe(48)
        EmailVerificationToken.objects.filter(user=user, is_used=False).update(is_used=True)
        record = EmailVerificationToken.objects.create(
            user=user,
            token=token_str,
            expires_at=timezone.now() + timedelta(hours=24),
        )

        verify_url = self._build_url(request, f'/auth/verify-email/{token_str}/')

        from apps.notifications.tasks import send_email_task
        send_email_task.delay(
            to_email=user.email,
            to_name=user.full_name,
            subject='Verify your email address',
            template='email_verification',
            context={
                'user_name': user.first_name,
                'verify_url': verify_url,
                'expires_hours': 24,
            },
        )

    def send_password_reset_email(self, user: User, request=None):
        """Generate and email a password reset token."""
        token_str = secrets.token_urlsafe(48)
        # Invalidate existing tokens
        PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)
        PasswordResetToken.objects.create(
            user=user,
            token=token_str,
            expires_at=timezone.now() + timedelta(hours=2),
            ip_address=self._get_ip(request),
        )

        reset_url = self._build_url(request, f'/auth/password-reset/confirm/{token_str}/')

        from apps.notifications.tasks import send_email_task
        send_email_task.delay(
            to_email=user.email,
            to_name=user.full_name,
            subject='Reset your password',
            template='password_reset',
            context={
                'user_name': user.first_name,
                'reset_url': reset_url,
                'expires_hours': 2,
            },
        )

    @staticmethod
    def _build_url(request, path: str) -> str:
        if request:
            return request.build_absolute_uri(path)
        site_url = getattr(settings, 'ERP_SETTINGS', {}).get('SITE_URL', 'http://localhost:8000')
        return f"{site_url.rstrip('/')}{path}"

    @staticmethod
    def _get_ip(request) -> str:
        if not request:
            return ''
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')
