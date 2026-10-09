"""Helpers for resolving the tenant active for a request."""

from django.core.exceptions import ValidationError


def get_active_company(request):
    """Return the request's company only when the user is an active member."""
    raw_request = getattr(request, "_request", request)
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    from apps.authentication.models import UserCompany
    from apps.company.models import Company

    header_company = getattr(raw_request, "META", {}).get("HTTP_X_ACTIVE_COMPANY")
    session = getattr(raw_request, "session", None)
    session_company = session.get("active_company_id") if session is not None else None
    selected_id = header_company or session_company

    def has_access(company):
        return user.is_superuser or UserCompany.objects.filter(
            user=user, company=company, is_active=True
        ).exists()

    if selected_id:
        try:
            company_id = Company._meta.pk.to_python(selected_id)
            company = Company.objects.filter(pk=company_id).first()
        except ValidationError:
            return None
        if company and has_access(company):
            request.company = company
            raw_request.company = company
            return company
        return None

    company = getattr(request, "company", None) or getattr(
        raw_request, "company", None
    )
    if company:
        if has_access(company):
            request.company = company
            raw_request.company = company
            return company
        return None

    memberships = UserCompany.objects.filter(
        user=user, is_active=True
    ).select_related("company")
    if memberships.count() == 1:
        company = memberships.first().company
        request.company = company
        raw_request.company = company
        return company

    primary_company = getattr(user, "primary_company", None)
    if primary_company and has_access(primary_company):
        request.company = primary_company
        raw_request.company = primary_company
        return primary_company
    return None
