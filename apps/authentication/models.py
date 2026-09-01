"""
Authentication Models
Custom User model with RBAC, 2FA, multi-company support
"""

import uuid

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _

from core.fields import EncryptedCharField


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("role", User.Role.SUPER_ADMIN)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom User model. Uses email as username.
    Supports multi-company assignment and RBAC.
    """

    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", _("Super Admin")
        COMPANY_ADMIN = "company_admin", _("Company Admin")
        HR_MANAGER = "hr_manager", _("HR Manager")
        FINANCE_MANAGER = "finance_manager", _("Finance Manager")
        SALES_MANAGER = "sales_manager", _("Sales Manager")
        PURCHASE_MANAGER = "purchase_manager", _("Purchase Manager")
        INVENTORY_MANAGER = "inventory_manager", _("Inventory Manager")
        PROJECT_MANAGER = "project_manager", _("Project Manager")
        EMPLOYEE = "employee", _("Employee")
        CUSTOMER_PORTAL = "customer_portal", _("Customer Portal User")

    # Identity
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, db_index=True)
    username = models.CharField(max_length=150, unique=True, blank=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)

    # Role & Status
    role = models.CharField(
        max_length=30, choices=Role.choices, default=Role.EMPLOYEE, db_index=True
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)

    # Multi-company
    companies = models.ManyToManyField(
        "company.Company",
        through="UserCompany",
        related_name="users",
        blank=True,
    )
    primary_company = models.ForeignKey(
        "company.Company",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="primary_users",
    )

    # Preferences
    language = models.CharField(max_length=10, default="en")
    timezone = models.CharField(max_length=50, default="UTC")
    theme = models.CharField(
        max_length=10, choices=[("light", "Light"), ("dark", "Dark")], default="light"
    )
    date_format = models.CharField(max_length=20, default="YYYY-MM-DD")

    # 2FA
    two_factor_enabled = models.BooleanField(default=False)
    two_factor_method = models.CharField(
        max_length=10,
        choices=[("totp", "Authenticator App")],
        default="totp",
    )
    # TOTP seed stored encrypted at rest using Fernet symmetric encryption.
    # The EncryptedCharField transparently encrypts on write and decrypts on
    # read.  Plain-text values already in the DB are returned unchanged until
    # the user re-saves their 2FA settings (graceful migration path).
    # max_length=500 accommodates the Fernet ciphertext overhead (~160 chars
    # for a 32-char secret).
    totp_secret = EncryptedCharField(max_length=500, blank=True)

    # Activity
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_active = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    date_joined = models.DateTimeField(default=dj_timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "auth_users"
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        indexes = [
            models.Index(fields=["email", "is_active"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_locked(self):
        if self.locked_until and self.locked_until > dj_timezone.now():
            return True
        return False

    @property
    def active_user_companies(self):
        return self.usercompany_set.filter(is_active=True)

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)

    def get_permissions_for_module(self, module):
        """Return user's effective permissions for a module."""
        return ModulePermission.objects.filter(role=self.role, module=module).first()

    def has_module_permission(self, module, action):
        perm = self.get_permissions_for_module(module)
        if not perm:
            return self.is_superuser
        return getattr(perm, f"can_{action}", False)


class UserCompany(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey("company.Company", on_delete=models.CASCADE)
    role = models.CharField(
        max_length=30, choices=User.Role.choices, default=User.Role.EMPLOYEE
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_user_company"
        unique_together = ("user", "company")

    def __str__(self):
        return f"{self.user.email} - {self.company.name}"


class LoginHistory(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="login_history"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=[("success", "Success"), ("failed", "Failed")]
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_login_history"
        ordering = ["-timestamp"]



class IPRestriction(models.Model):
    company = models.ForeignKey(
        "company.Company", on_delete=models.CASCADE, null=True, blank=True
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    ip_address = models.GenericIPAddressField()
    is_allowed = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_ip_restriction"


class PasswordPolicy(models.Model):
    company = models.OneToOneField(
        "company.Company", on_delete=models.CASCADE, related_name="password_policy"
    )
    min_length = models.PositiveSmallIntegerField(default=8)
    require_uppercase = models.BooleanField(default=True)
    require_numbers = models.BooleanField(default=True)
    require_special = models.BooleanField(default=True)
    expiry_days = models.PositiveSmallIntegerField(
        default=90, help_text="0 means no expiry"
    )
    max_failed_logins = models.PositiveSmallIntegerField(default=5)
    lockout_time_minutes = models.PositiveSmallIntegerField(default=30)

    class Meta:
        db_table = "auth_password_policy"


class Role(models.Model):
    """Custom role with granular permissions (beyond the built-in role choices)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        "company.Company", on_delete=models.CASCADE, related_name="roles"
    )
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("company", "code")
        db_table = "auth_roles"

    def __str__(self):
        return f"{self.name} ({self.company})"


class Permission(models.Model):
    """Granular permission definition per module."""

    class Action(models.TextChoices):
        CREATE = "create", _("Create")
        READ = "read", _("Read")
        UPDATE = "update", _("Update")
        DELETE = "delete", _("Delete")
        APPROVE = "approve", _("Approve")
        EXPORT = "export", _("Export")
        IMPORT = "import", _("Import")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    module = models.CharField(max_length=50, db_index=True)
    resource = models.CharField(max_length=100)
    action = models.CharField(max_length=20, choices=Action.choices)
    is_allowed = models.BooleanField(default=True)

    class Meta:
        unique_together = ("role", "module", "resource", "action")
        db_table = "auth_permissions_custom"

    def __str__(self):
        return f"{self.role.name}: {self.action} {self.module}.{self.resource}"


class ModulePermission(models.Model):
    """Quick RBAC matrix: role → module → CRUD+Approve+Export."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=30, choices=User.Role.choices, db_index=True)
    module = models.CharField(max_length=50, db_index=True)
    can_create = models.BooleanField(default=False)
    can_read = models.BooleanField(default=True)
    can_update = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    can_export = models.BooleanField(default=False)
    can_import = models.BooleanField(default=False)
    can_manage_users = models.BooleanField(default=False)

    class Meta:
        unique_together = ("role", "module")
        db_table = "auth_module_permissions"

    def __str__(self):
        return f"{self.role} | {self.module}"


class PasswordResetToken(models.Model):
    """Secure password reset tokens."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = "auth_password_reset_tokens"

    @property
    def is_expired(self):
        return dj_timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired


class EmailVerificationToken(models.Model):
    """Email verification tokens."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = "auth_email_verification_tokens"


class ActivityLog(models.Model):
    """Audit trail for all user actions."""

    class ActionType(models.TextChoices):
        LOGIN = "login", _("Login")
        LOGOUT = "logout", _("Logout")
        PASSWORD_CHANGE = "password_change", _("Password Change")
        PASSWORD_RESET = "password_reset", _("Password Reset")
        PROFILE_UPDATE = "profile_update", _("Profile Update")
        CREATE = "create", _("Create")
        UPDATE = "update", _("Update")
        DELETE = "delete", _("Delete")
        VIEW = "view", _("View")
        EXPORT = "export", _("Export")
        IMPORT = "import", _("Import")
        APPROVE = "approve", _("Approve")
        REJECT = "reject", _("Reject")
        FAILED_LOGIN = "failed_login", _("Failed Login")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="activity_logs"
    )
    company = models.ForeignKey("company.Company", null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=30, choices=ActionType.choices, db_index=True)
    module = models.CharField(max_length=50, blank=True, db_index=True)
    resource_type = models.CharField(max_length=100, blank=True)
    resource_id = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    extra_data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "auth_activity_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["module", "action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user} | {self.action} | {self.created_at:%Y-%m-%d %H:%M}"


class UserSession(models.Model):
    """Track active sessions per user."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "auth_user_sessions"

    def __str__(self):
        return f"{self.user} — {self.ip_address}"
