from rest_framework import permissions
from apps.authentication.models import User

class IsCompanyAdminOrSuperAdmin(permissions.BasePermission):
    """
    Allows access only to Super Admins or Company Admins.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (
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
            request.user and
            request.user.is_authenticated and
            (
                request.user.role == User.Role.SUPER_ADMIN
                or request.user.is_superuser
            )
        )

