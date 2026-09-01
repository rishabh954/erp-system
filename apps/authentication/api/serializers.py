from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import ActivityLog, ModulePermission, Role, User


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.ReadOnlyField()
    company_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "role",
            "is_active",
            "is_email_verified",
            "language",
            "timezone",
            "theme",
            "two_factor_enabled",
            "avatar",
            "last_active",
            "date_joined",
            "company_name",
        ]
        read_only_fields = ["id", "email", "date_joined", "last_active"]

    def get_company_name(self, obj):
        return obj.primary_company.name if obj.primary_company else None


class UserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "email",
            "first_name",
            "last_name",
            "phone",
            "password",
            "password_confirm",
            "role",
            "language",
            "timezone",
        ]

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError(
                {"password_confirm": "Passwords do not match."}  # nosec B105
            )
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "phone",
            "language",
            "timezone",
            "theme",
            "avatar",
        ]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords do not match."}  # nosec B105
            )
        return attrs


class CustomTokenObtainSerializer(serializers.Serializer):
    """JWT login with extra user data in response.

    When a user has 2FA enabled the response will NOT include access/refresh
    tokens.  Instead it returns ``requires_2fa: true`` and a short-lived
    ``partial_token`` that the client must exchange via the ``/2fa/verify/``
    endpoint after supplying a valid TOTP code.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        user = authenticate(username=email, password=password)
        if not user:
            # Increment failed login counter for API path (mirrors web login)
            from apps.authentication.models import User as _User
            _u = _User.objects.filter(email=email).first()
            if _u:
                _u.failed_login_attempts += 1
                policy = getattr(_u.primary_company, "password_policy", None)
                max_attempts = policy.max_failed_logins if policy else 5
                lockout_minutes = policy.lockout_time_minutes if policy else 30
                if _u.failed_login_attempts >= max_attempts:
                    from datetime import timedelta

                    from django.utils import timezone
                    _u.locked_until = timezone.now() + timedelta(minutes=lockout_minutes)
                _u.save(update_fields=["failed_login_attempts", "locked_until"])
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("Account is deactivated.")
        if user.is_locked:
            raise serializers.ValidationError("Account is temporarily locked.")

        # ── 2FA Gate ──────────────────────────────────────────────────────────
        if user.two_factor_enabled:
            # Issue a limited partial token (no scopes / short TTL).
            # The client must POST this + a TOTP code to /api/v1/auth/2fa/verify/
            # to receive a real access/refresh pair.
            import secrets

            from django.core.cache import cache
            partial_token = secrets.token_urlsafe(32)
            # Store user pk for 5 minutes – enough time to complete 2FA
            cache.set(f"2fa_partial:{partial_token}", str(user.pk), timeout=300)
            return {
                "requires_2fa": True,
                "partial_token": partial_token,
                "user": None,
                "access": None,
                "refresh": None,
            }

        refresh = RefreshToken.for_user(user)
        return {
            "requires_2fa": False,
            "partial_token": None,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": UserSerializer(user).data,
        }


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "user_name",
            "action",
            "module",
            "resource_type",
            "description",
            "ip_address",
            "created_at",
        ]

    def get_user_name(self, obj):
        return obj.user.full_name if obj.user else "System"


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "code", "description", "is_system", "created_at"]
        read_only_fields = ["id", "created_at"]


class ModulePermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModulePermission
        fields = [
            "id",
            "role",
            "module",
            "can_create",
            "can_read",
            "can_update",
            "can_delete",
            "can_approve",
            "can_export",
        ]
