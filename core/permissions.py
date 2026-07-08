from rest_framework import permissions

from apps.authentication.models import User


class IsCompanyAdminOrSuperAdmin(permissions.BasePermission):
    """
    Allows access only to Super Admins or Company Admins.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.role in [User.Role.SUPER_ADMIN, User.Role.COMPANY_ADMIN]
                or request.user.is_superuser
            )
        )


class IsSuperAdmin(permissions.BasePermission):
    """
    Allows access only to Super Admins.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.role == User.Role.SUPER_ADMIN or request.user.is_superuser
            )
        )


class HasModulePermission(permissions.BasePermission):
    """
    DRF permission class that checks user.has_module_permission().
    Requires view to have `required_permission` attribute set to "module.action"
    e.g. required_permission = "accounting.read"
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if hasattr(view, 'get_required_permission'):
            required_perm = view.get_required_permission(request)
        else:
            required_perm = getattr(view, 'required_permission', None)
        
        if not required_perm:
            # If no permission is explicitly required, fallback to basic auth check
            return True

        try:
            module, action = required_perm.split('.')
            return request.user.has_module_permission(module, action)
        except ValueError:
            return False


from django.contrib.auth.mixins import AccessMixin  # noqa: E402
from django.core.exceptions import ImproperlyConfigured  # noqa: E402


class PermissionRequiredMixin(AccessMixin):
    """
    Mixin for class-based views to enforce module permissions.
    Requires `required_permission` to be set on the view class.
    """
    required_permission = None

    def get_required_permission(self, request=None):
        if self.required_permission is None:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} is missing the required_permission attribute. "  # noqa: E501
                "Define required_permission = 'module.action' or override get_required_permission()."
            )
        return self.required_permission

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        required_perm = self.get_required_permission(request)
        try:
            module, action = required_perm.split('.')
            if not request.user.has_module_permission(module, action):
                return self.handle_no_permission()
        except ValueError:
            return self.handle_no_permission()

        return super().dispatch(request, *args, **kwargs)

