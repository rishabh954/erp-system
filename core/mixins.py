from core.permissions import HttpMethodPermissionMixin
from core.tenancy import get_active_company


class CompanyMixin(HttpMethodPermissionMixin):
    """
    Standard mixin for class-based views to enforce company scoping.

    Returns the active company after validating the current user's membership.

    Never returns ``None`` silently — if no company can be resolved the view
    raises a ``PermissionDenied`` error rather than leaking wrong-company data.
    """

    def company(self):
        company = get_active_company(self.request)
        if company:
            return company
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(
            "No active company context. Please select a company before continuing."
        )
