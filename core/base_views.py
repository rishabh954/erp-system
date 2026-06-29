from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from .base_mixins import CompanyScopedMixin, AuditCreateMixin, AuditUpdateMixin, RolePermissionMixin

class BaseListView(LoginRequiredMixin, CompanyScopedMixin, ListView):
    """Standard list view with company scoping and pagination."""
    paginate_by = 25
    template_name = 'core/generic_list.html'

class BaseDetailView(LoginRequiredMixin, CompanyScopedMixin, DetailView):
    """Standard detail view with company scoping."""
    template_name = 'core/generic_detail.html'

class BaseCreateView(LoginRequiredMixin, CompanyScopedMixin, AuditCreateMixin, CreateView):
    """Standard create view with audit trail injection."""
    template_name = 'core/generic_form.html'

class BaseUpdateView(LoginRequiredMixin, CompanyScopedMixin, AuditUpdateMixin, UpdateView):
    """Standard update view with audit trail injection."""
    template_name = 'core/generic_form.html'

class BaseDeleteView(LoginRequiredMixin, CompanyScopedMixin, DeleteView):
    """Standard delete view with company scoping."""
    template_name = 'core/generic_confirm_delete.html'
