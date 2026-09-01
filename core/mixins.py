from core.permissions import HttpMethodPermissionMixin


class CompanyMixin(HttpMethodPermissionMixin):
    """
    Standard mixin for class-based views to enforce company scoping.

    Returns the *active* company for the current request as set by
    ``TenantMiddleware`` (``request.company``).  Falls back to
    ``user.primary_company`` only when no session/header company is present
    (e.g. during single-company setups) so existing behaviour is preserved.

    Never returns ``None`` silently — if no company can be resolved the view
    raises a ``PermissionDenied`` error rather than leaking wrong-company data.
    """

    def company(self):
        # Prefer the company resolved and validated by TenantMiddleware
        company = getattr(self.request, "company", None)
        if company:
            return company
        # Fallback: single-company users whose TenantMiddleware set primary_company
        company = getattr(self.request.user, "primary_company", None)
        if company:
            return company
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied(
            "No active company context. Please select a company before continuing."
        )

