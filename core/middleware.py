from django.utils import timezone


class AuditLogMiddleware:
    """Captures user IP and user-agent for audit logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    @staticmethod
    def get_client_ip(request) -> str:
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "")


class RequestLoggingMiddleware:
    """Populates contextvars for the logging filter."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.logging import clear_logging_context, set_logging_context

        user_id = str(request.user.pk) if hasattr(request, "user") and request.user.is_authenticated else "anonymous"  # noqa: E501
        company_id = str(request.company.pk) if hasattr(request, "company") and request.company else "none"  # noqa: E501

        # In case the company is set in another middleware running AFTER this one,
        # we still do our best here, or we place RequestLoggingMiddleware after TenantMiddleware.  # noqa: E501

        set_logging_context(
            user_id=user_id,
            company_id=company_id,
            request_path=request.path,
            client_ip=AuditLogMiddleware.get_client_ip(request)
        )

        response = self.get_response(request)

        clear_logging_context()

        return response


class TenantMiddleware:
    """Resolve and inject the active company into `request.company`.

    Resolution order:
    1. `X-Active-Company` header (HTTP_X_ACTIVE_COMPANY)
    2. `request.session['active_company_id']`
    3. If user has exactly one active `UserCompany` membership, use it.
    4. Fallback to `user.primary_company` only if membership is valid.

    Membership is verified via `UserCompany.is_active` to prevent cross-company access.
    Superusers bypass membership checks.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None

        # Unauthenticated requests have no company
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return self.get_response(request)

        # Lazy imports to avoid circular dependencies
        from apps.authentication.models import UserCompany
        from apps.company.models import Company

        company_id = None

        # 1) Header override
        header_company = request.META.get('HTTP_X_ACTIVE_COMPANY')
        if header_company:
            company_id = header_company

        # 2) Session persisted active company
        if not company_id and hasattr(request, 'session'):
            company_id = request.session.get('active_company_id')

        # Helper to set request.company and persist session
        def _set_company(obj):
            request.company = obj
            try:
                if hasattr(request, 'session'):
                    request.session['active_company_id'] = str(obj.pk)
            except Exception:
                # Don't fail the whole request due to session write issues
                pass

        # If an explicit company id is provided, resolve and validate membership
        if company_id:
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist:
                request.company = None
                return self.get_response(request)

            # allow superusers to view any company
            if request.user.is_superuser or UserCompany.objects.filter(user_id=request.user.pk, company_id=company.pk, is_active=True).exists():
                _set_company(company)
            else:
                request.company = None

            return self.get_response(request)

        # No explicit company: try to infer from memberships
        memberships = UserCompany.objects.filter(user_id=request.user.pk, is_active=True).select_related('company')
        membership_count = memberships.count()

        if membership_count == 1:
            _set_company(memberships.first().company)
            return self.get_response(request)

        # Multiple memberships: prefer primary_company if valid
        primary = getattr(request.user, 'primary_company', None)
        if primary and (request.user.is_superuser or UserCompany.objects.filter(user=request.user, company=primary, is_active=True).exists()):
            _set_company(primary)
            return self.get_response(request)

        # No deterministic company found; leave as None (views/services must enforce checks)
        request.company = None
        return self.get_response(request)


class ActiveUserMiddleware:
    """Updates user's last_active timestamp on each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from apps.authentication.models import User

            User.objects.filter(pk=request.user.pk).update(last_active=timezone.now())
        return self.get_response(request)
