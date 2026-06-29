from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.db import models

class CompanyScopedMixin:
    """Ensures querysets are always filtered by the user's primary company."""
    
    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request.user, 'primary_company') and self.request.user.primary_company:
            return qs.filter(company=self.request.user.primary_company)
        return qs.none()

class AuditCreateMixin:
    """Automatically sets created_by, updated_by, and company on creation."""
    
    def form_valid(self, form):
        if hasattr(form.instance, 'company_id') and hasattr(self.request.user, 'primary_company'):
            form.instance.company = self.request.user.primary_company
        if hasattr(form.instance, 'created_by_id'):
            form.instance.created_by = self.request.user
        if hasattr(form.instance, 'updated_by_id'):
            form.instance.updated_by = self.request.user
        return super().form_valid(form)

class AuditUpdateMixin:
    """Automatically sets updated_by on update."""
    
    def form_valid(self, form):
        if hasattr(form.instance, 'updated_by_id'):
            form.instance.updated_by = self.request.user
        return super().form_valid(form)

class RolePermissionMixin(UserPassesTestMixin):
    """Checks if the user has a specific role or module permission."""
    required_roles = []
    required_module = None
    required_action = None

    def test_func(self):
        user = self.request.user
        if user.is_superuser:
            return True
            
        if self.required_roles and user.role not in self.required_roles:
            return False
            
        if self.required_module and self.required_action:
            if not user.has_module_permission(self.required_module, self.required_action):
                return False
                
        return True

    def handle_no_permission(self):
        raise PermissionDenied("You do not have permission to perform this action.")
