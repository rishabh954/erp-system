from core.permissions import PermissionRequiredMixin


class CompanyMixin(PermissionRequiredMixin):
    """
    Standard mixin for class-based views to enforce company scoping.
    Provides self.company() returning the user's primary company.
    """
    def company(self):
        return self.request.user.primary_company
