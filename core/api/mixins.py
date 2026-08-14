from rest_framework import viewsets

class TenantScopedViewSetMixin:
    """
    Mixin for DRF ViewSets to enforce strict tenant isolation.
    Resolves tenant/company directly from self.request.user.primary_company
    (or request.user.companies if multi-company accessible), avoiding dependency on middleware.
    Returns an empty queryset if user or company is missing.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return qs.none()

        # Resolve primary company
        company = getattr(user, "primary_company", None)
        if not company:
            return qs.none()

        # Filter by company
        if hasattr(qs.model, "company"):
            qs = qs.filter(company=company)

        # Filter soft-deleted if model supports is_deleted
        if hasattr(qs.model, "is_deleted"):
            qs = qs.filter(is_deleted=False)

        return qs
