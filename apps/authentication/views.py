"""
Authentication Views
Login, Logout, Register, 2FA, Password Reset, Profile Management
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from core.permissions import PermissionRequiredMixin
from django.views.generic import TemplateView

from .forms import (
    ChangePasswordForm,
    LoginForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    ProfileUpdateForm,
    RegisterForm,
    TwoFactorVerifyForm,
)
from .models import (
    ActivityLog,
    EmailVerificationToken,
    PasswordResetToken,
    User,
    UserSession,
)
from .services import AuthService

logger = logging.getLogger(__name__)


# ─── Login ────────────────────────────────────────────────────────────────────


class LoginView(View):
    template_name = "authentication/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard:index")
        form = LoginForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        form = LoginForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        remember_me = form.cleaned_data.get("remember_me", False)

        # Check if user exists and is inactive before attempting authentication
        try:
            user_check = User.objects.get(email=email)
            if not user_check.is_active:
                messages.error(
                    request,
                    "Your account is currently inactive or pending administrator approval.",
                )
                return render(request, self.template_name, {"form": form})
        except User.DoesNotExist:
            pass

        user = authenticate(request, username=email, password=password)

        if user is None:
            # Log failed attempt
            try:
                u = User.objects.get(email=email)
                u.failed_login_attempts += 1
                if u.failed_login_attempts >= 5:
                    u.locked_until = timezone.now() + timedelta(minutes=30)
                    messages.error(
                        request,
                        _(
                            "Account locked for 30 minutes due to multiple failed attempts."
                        ),
                    )
                u.save(update_fields=["failed_login_attempts", "locked_until"])
            except User.DoesNotExist:
                pass
            ActivityLog.objects.create(
                action="failed_login", description=f"Failed login for {email}"
            )
            messages.error(request, _("Invalid email or password."))
            return render(request, self.template_name, {"form": form})

        if user.is_locked:
            messages.error(
                request,
                _("Your account is temporarily locked. Please try again later."),
            )
            return render(request, self.template_name, {"form": form})

        # 2FA check
        if user.two_factor_enabled:
            request.session["2fa_user_id"] = str(user.pk)
            request.session["2fa_remember_me"] = remember_me
            return redirect("auth:two_factor_verify")

        # Successful login
        self._complete_login(request, user, remember_me)
        return redirect(request.GET.get("next", "dashboard:index"))

    def _complete_login(self, request, user, remember_me):
        login(request, user)
        if not remember_me:
            request.session.set_expiry(0)  # Expire on browser close
        else:
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)

        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_ip = self._get_ip(request)
        user.save(
            update_fields=["failed_login_attempts", "locked_until", "last_login_ip"]
        )

        # Save session record
        UserSession.objects.create(
            user=user,
            session_key=request.session.session_key or "",
            ip_address=self._get_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            expires_at=timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE),
        )

        ActivityLog.objects.create(
            user=user,
            company=user.primary_company,
            action="login",
            module="auth",
            ip_address=self._get_ip(request),
        )

    @staticmethod
    def _get_ip(request):
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")


# ─── Logout ───────────────────────────────────────────────────────────────────


class LogoutView(LoginRequiredMixin, View):
    required_permission = "authentication.read"
    def post(self, request):
        ActivityLog.objects.create(
            user=request.user,
            company=request.user.primary_company,
            action="logout",
            module="auth",
        )
        UserSession.objects.filter(
            user=request.user, session_key=request.session.session_key
        ).update(is_active=False)
        logout(request)
        messages.success(request, _("You have been logged out successfully."))
        return redirect("auth:login")


# ─── Two-Factor Authentication ────────────────────────────────────────────────


class TwoFactorVerifyView(View):
    template_name = "authentication/two_factor.html"

    def get(self, request):
        if "2fa_user_id" not in request.session:
            return redirect("auth:login")
        return render(request, self.template_name, {"form": TwoFactorVerifyForm()})

    def post(self, request):
        if "2fa_user_id" not in request.session:
            return redirect("auth:login")

        form = TwoFactorVerifyForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        user_id = request.session.get("2fa_user_id")
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return redirect("auth:login")

        code = form.cleaned_data["code"]
        service = AuthService()

        if service.verify_2fa_code(user, code):
            remember_me = request.session.pop("2fa_remember_me", False)
            request.session.pop("2fa_user_id", None)
            LoginView._complete_login(self, request, user, remember_me)
            return redirect("dashboard:index")
        else:
            messages.error(request, _("Invalid verification code. Please try again."))
            return render(request, self.template_name, {"form": form})


# ─── Registration ─────────────────────────────────────────────────────────────


class RegisterView(View):
    template_name = "authentication/register.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect("dashboard:index")
        return render(request, self.template_name, {"form": RegisterForm()})

    def post(self, request):
        form = RegisterForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        user = form.save(commit=False)
        user.is_active = False  # Require admin approval before login
        user.set_password(form.cleaned_data["password1"])
        user.save()

        service = AuthService()
        service.send_email_verification(user, request)

        messages.success(
            request,
            "Account created! An administrator must approve your account before you can log in. Please check your email to verify your address.",
        )
        return redirect("auth:login")


# ─── Email Verification ───────────────────────────────────────────────────────


class EmailVerifyView(View):
    def get(self, request, token):
        record = get_object_or_404(EmailVerificationToken, token=token, is_used=False)

        if record.is_expired:
            messages.error(
                request, _("Verification link has expired. Please request a new one.")
            )
            return redirect("auth:login")

        record.user.is_email_verified = True
        record.user.save(update_fields=["is_email_verified"])
        record.is_used = True
        record.save(update_fields=["is_used"])

        messages.success(request, _("Email verified successfully! You can now log in."))
        return redirect("auth:login")


# ─── Password Reset ───────────────────────────────────────────────────────────


class PasswordResetRequestView(View):
    template_name = "authentication/password_reset_request.html"

    def get(self, request):
        return render(request, self.template_name, {"form": PasswordResetRequestForm()})

    def post(self, request):
        form = PasswordResetRequestForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})

        email = form.cleaned_data["email"]
        try:
            user = User.objects.get(email=email, is_active=True)
            service = AuthService()
            service.send_password_reset_email(user, request)
        except User.DoesNotExist:
            pass  # Don't reveal if email exists

        messages.success(
            request,
            _("If an account with that email exists, a reset link has been sent."),
        )
        return redirect("auth:login")


class PasswordResetConfirmView(View):
    template_name = "authentication/password_reset_confirm.html"

    def get(self, request, token):
        record = get_object_or_404(PasswordResetToken, token=token)
        if not record.is_valid:
            messages.error(
                request, _("This reset link has expired or already been used.")
            )
            return redirect("auth:password_reset")
        return render(
            request,
            self.template_name,
            {"form": PasswordResetConfirmForm(), "token": token},
        )

    def post(self, request, token):
        record = get_object_or_404(PasswordResetToken, token=token)
        if not record.is_valid:
            messages.error(
                request, _("This reset link has expired or already been used.")
            )
            return redirect("auth:password_reset")

        form = PasswordResetConfirmForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "token": token})

        user = record.user
        user.set_password(form.cleaned_data["password1"])
        user.save()
        record.is_used = True
        record.save(update_fields=["is_used"])

        ActivityLog.objects.create(user=user, action="password_reset", module="auth")
        messages.success(request, _("Password reset successfully. You can now log in."))
        return redirect("auth:login")


# ─── Profile ──────────────────────────────────────────────────────────────────


class ProfileView(LoginRequiredMixin, TemplateView):
    required_permission = "authentication.read"
    template_name = "authentication/profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["profile_form"] = ProfileUpdateForm(instance=self.request.user)
        ctx["password_form"] = ChangePasswordForm(user=self.request.user)
        ctx["activity_logs"] = ActivityLog.objects.filter(
            user=self.request.user
        ).order_by("-created_at")[:20]
        ctx["active_sessions"] = UserSession.objects.filter(
            user=self.request.user, is_active=True
        ).order_by("-last_activity")
        return ctx


class ProfileUpdateView(LoginRequiredMixin, View):
    required_permission = "authentication.update"
    def post(self, request):
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            ActivityLog.objects.create(
                user=request.user,
                company=request.user.primary_company,
                action="profile_update",
                module="auth",
            )
            messages.success(request, _("Profile updated successfully."))
        else:
            messages.error(request, _("Please correct the errors below."))
        return redirect("auth:profile")


class ChangePasswordView(LoginRequiredMixin, View):
    required_permission = "authentication.read"
    def post(self, request):
        form = ChangePasswordForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            ActivityLog.objects.create(
                user=request.user,
                company=request.user.primary_company,
                action="password_change",
                module="auth",
            )
            messages.success(request, _("Password changed successfully."))
        else:
            messages.error(request, _("Please correct the errors below."))
        return redirect("auth:profile")


# ─── Session Management ───────────────────────────────────────────────────────


class RevokeSessionView(LoginRequiredMixin, View):
    required_permission = "authentication.read"
    def post(self, request, session_id):
        session = get_object_or_404(UserSession, pk=session_id, user=request.user)
        session.is_active = False
        session.save(update_fields=["is_active"])
        messages.success(request, _("Session revoked successfully."))
        return redirect("auth:profile")


class RevokeAllSessionsView(LoginRequiredMixin, View):
    required_permission = "authentication.read"
    def post(self, request):
        current_key = request.session.session_key
        UserSession.objects.filter(user=request.user, is_active=True).exclude(
            session_key=current_key
        ).update(is_active=False)
        messages.success(request, _("All other sessions have been revoked."))
        return redirect("auth:profile")


# ─── Activity Log API ─────────────────────────────────────────────────────────


class ActivityLogView(LoginRequiredMixin, View):
    required_permission = "authentication.read"
    def get(self, request):
        logs = (
            ActivityLog.objects.filter(user=request.user)
            .values("action", "module", "description", "ip_address", "created_at")
            .order_by("-created_at")[:50]
        )
        return JsonResponse({"logs": list(logs)}, safe=False)
