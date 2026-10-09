import logging

from rest_framework import serializers

from core.tenancy import get_active_company

logger = logging.getLogger(__name__)


class TenantScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """
    Enterprise DRF Relation Field enforcing strict multi-tenant isolation.
    Validates that the selected related object belongs strictly to the
    requesting user's active tenant context.
    Prevents cross-tenant foreign key injection (IDOR attacks).
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        if queryset is None:
            return queryset

        request = self.context.get("request")
        if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
            return queryset.none()

        company = get_active_company(request)
        if not company:
            if request.user.is_superuser:
                return queryset
            return queryset.none()

        # Filter queryset by tenant if the model is company-scoped
        if hasattr(queryset.model, "company"):
            return queryset.filter(company=company)

        return queryset


class TenantModelSerializer(serializers.ModelSerializer):
    """
    Base ModelSerializer that automatically scopes all PrimaryKeyRelatedField relations
    to the active tenant, eliminating relational cross-company IDOR vulnerabilities.
    """

    serializer_related_field = TenantScopedPrimaryKeyRelatedField
