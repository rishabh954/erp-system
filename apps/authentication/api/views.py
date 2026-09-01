"""
Authentication REST API
JWT login, user management, RBAC endpoints
"""

import logging

from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.api.serializers import (
    ActivityLogSerializer,
    ChangePasswordSerializer,
    CustomTokenObtainSerializer,
    ModulePermissionSerializer,
    RoleSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)
from apps.authentication.models import ActivityLog, ModulePermission, Role, User
from core.permissions import IsCompanyAdminOrSuperAdmin, IsSuperAdmin

logger = logging.getLogger(__name__)

# --- API Views ----------------------------------------------------------------


class LoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = CustomTokenObtainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_data = serializer.validated_data

        # 2FA required — return partial token only; no JWT issued yet
        if user_data.get("requires_2fa"):
            return Response(
                {
                    "success": True,
                    "requires_2fa": True,
                    "partial_token": user_data["partial_token"],
                    "message": "2FA verification required. Submit your TOTP code to /api/v1/auth/2fa/verify/.",
                },
                status=status.HTTP_200_OK,
            )

        user = User.objects.get(email=request.data["email"])

        # Update login metadata
        user.failed_login_attempts = 0
        user.last_login_ip = self._get_ip(request)
        user.save(update_fields=["failed_login_attempts", "last_login_ip"])

        ActivityLog.objects.create(
            user=user,
            company=user.primary_company,
            action="login",
            module="auth",
            ip_address=self._get_ip(request),
        )

        return Response(
            {
                "success": True,
                "data": {
                    "access": user_data["access"],
                    "refresh": user_data["refresh"],
                    "user": user_data["user"],
                },
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_ip(request):
        from django.conf import settings
        trusted = getattr(settings, "TRUSTED_PROXY_IPS", None)
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            remote = request.META.get("REMOTE_ADDR", "")
            if trusted is None or remote in trusted:
                return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


class TwoFactorVerifyAPIView(APIView):
    """Exchange a partial_token + TOTP code for a full JWT pair."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import pyotp
        from django.core.cache import cache

        partial_token = request.data.get("partial_token")
        totp_code = request.data.get("code")

        if not partial_token or not totp_code:
            return Response(
                {"error": "partial_token and code are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cache_key = f"2fa_partial:{partial_token}"
        user_pk = cache.get(cache_key)
        if not user_pk:
            return Response(
                {"error": "Invalid or expired token. Please log in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            return Response(
                {"error": "User not found."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user.two_factor_enabled or not user.totp_secret:
            return Response(
                {"error": "2FA is not configured for this account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code, valid_window=1):
            return Response(
                {"error": "Invalid 2FA code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Code is valid — delete the partial token so it cannot be reused
        cache.delete(cache_key)

        refresh = RefreshToken.for_user(user)

        user.failed_login_attempts = 0
        user.last_login_ip = LoginAPIView._get_ip(request)
        user.save(update_fields=["failed_login_attempts", "last_login_ip"])

        ActivityLog.objects.create(
            user=user,
            company=user.primary_company,
            action="login",
            module="auth",
            ip_address=LoginAPIView._get_ip(request),
        )

        return Response(
            {
                "success": True,
                "data": {
                    "access": str(refresh.access_token),
                    "refresh": str(refresh),
                    "user": UserSerializer(user).data,
                },
            },
            status=status.HTTP_200_OK,
        )


class LogoutAPIView(APIView):
    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception as e:
            logger.warning("Failed to blacklist token: %s", e)

        ActivityLog.objects.create(
            user=request.user,
            company=request.user.primary_company,
            action="logout",
            module="auth",
        )
        return Response({"success": True, "message": "Logged out successfully."})


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action in ["create", "toggle_active", "reset_password", "destroy"]:
            return [IsCompanyAdminOrSuperAdmin()]
        return [permissions.IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "create":
            return UserCreateSerializer
        if self.action in ["update", "partial_update"]:
            return UserUpdateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN or user.is_superuser:
            return User.objects.all()
        # Use request.company (set by TenantMiddleware) so multi-company
        # users always see data for their *active* company, not just their primary.
        company = getattr(self.request, "company", None) or user.primary_company
        if not company:
            return User.objects.none()
        return User.objects.filter(companies=company)

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if self.action in ["update", "partial_update", "destroy"]:
            if (
                request.user != obj
                and request.user.role
                not in [User.Role.SUPER_ADMIN, User.Role.COMPANY_ADMIN]
                and not request.user.is_superuser
            ):
                self.permission_denied(
                    request, message="You do not have permission to edit this user."
                )

    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        if request.method == "GET":
            serializer = UserSerializer(request.user)
            return Response(serializer.data)
        serializer = UserUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"])
    def change_password(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not request.user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"error": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save()

        # Re-generate tokens
        refresh = RefreshToken.for_user(request.user)
        return Response(
            {
                "success": True,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )

    @action(detail=False, methods=["get"])
    def activity_logs(self, request):
        logs = ActivityLog.objects.filter(user=request.user).order_by("-created_at")[
            :50
        ]
        serializer = ActivityLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def toggle_active(self, request, pk=None):
        user = self.get_object()
        if user == request.user:
            return Response(
                {"error": "Cannot deactivate your own account."}, status=400
            )
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        return Response({"success": True, "is_active": user.is_active})

    @action(detail=True, methods=["post"])
    def reset_password(self, request, pk=None):
        """Admin-initiated password reset link."""
        from apps.authentication.services import AuthService

        user = self.get_object()
        service = AuthService()
        service.send_password_reset_email(user, request)
        return Response({"success": True, "message": "Password reset email sent."})


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsCompanyAdminOrSuperAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.SUPER_ADMIN or user.is_superuser:
            return Role.objects.all()
        company = getattr(self.request, "company", None) or user.primary_company
        if not company:
            return Role.objects.none()
        return Role.objects.filter(company=company)

    def perform_create(self, serializer):
        company = getattr(self.request, "company", None) or self.request.user.primary_company
        if not company:
            from rest_framework.exceptions import ValidationError
            raise ValidationError("No active company context. Cannot create a role.")
        serializer.save(company=company)


class ModulePermissionViewSet(viewsets.ModelViewSet):
    serializer_class = ModulePermissionSerializer
    queryset = ModulePermission.objects.all()

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [IsSuperAdmin()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = super().get_queryset()
        role_param = self.request.query_params.get("role")

        # Only superusers can see all module permissions.
        # Other users can only see the module permissions for their current role.
        if user.role != User.Role.SUPER_ADMIN and not user.is_superuser:
            qs = qs.filter(role=user.role)
        elif role_param:
            qs = qs.filter(role=role_param)

        return qs


class ActivityLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ActivityLogSerializer

    def get_queryset(self):
        user = self.request.user
        company = getattr(self.request, "company", None) or user.primary_company
        if not company:
            return ActivityLog.objects.none()
        qs = ActivityLog.objects.filter(company=company).order_by(
            "-created_at"
        )
        # Filter by current user unless admin
        if (
            user.role not in (User.Role.SUPER_ADMIN, User.Role.COMPANY_ADMIN)
            and not user.is_superuser
        ):
            qs = qs.filter(user=user)
        return qs
