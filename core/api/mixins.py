
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from core.permissions import HasModulePermission
from core.tenancy import get_active_company


class TenantScopedViewSetMixin:
    """
    Mixin for DRF ViewSets to enforce strict tenant isolation.
    Resolves the company after DRF authentication and validates active membership.
    Returns an empty queryset if user or company is missing.
    """

    permission_classes = [IsAuthenticated, HasModulePermission]

    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return qs.none()

        company = get_active_company(self.request)
        if not company:
            return qs.none()
        self.request.company = company

        if hasattr(qs.model, "company"):
            consolidated = self.request.query_params.get("consolidated") == "true"
            if consolidated:
                permission = getattr(self, "required_permission", "")
                module = permission.partition(".")[0]
                if (
                    not module
                    or not user.has_module_permission(
                        module, "consolidate", company=company
                    )
                ):
                    raise PermissionDenied(
                        "You do not have permission to view consolidated data."
                    )
                company_ids = company.get_all_subsidiary_ids()
                qs = qs.filter(company_id__in=company_ids)
            else:
                qs = qs.filter(company=company)

        # Filter soft-deleted if model supports is_deleted
        if hasattr(qs.model, "is_deleted"):
            qs = qs.filter(is_deleted=False)

        return qs

    def perform_create(self, serializer):
        company = get_active_company(self.request)
        if not company:
            raise PermissionDenied("No active company membership.")
        self.request.company = company
        if hasattr(serializer.Meta.model, "company"):
            serializer.save(company=company)
        else:
            serializer.save()
