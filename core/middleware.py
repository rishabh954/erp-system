from django.utils import timezone


def _get_client_ip(request) -> str:
    """
    Extract the real client IP address.

    Only trusts X-Forwarded-For when the direct REMOTE_ADDR is in the
    TRUSTED_PROXY_IPS setting (a set/list of proxy IP strings).  This prevents
    clients from spoofing their IP by sending a crafted X-Forwarded-For header
    when there is no trusted reverse-proxy in front of the application.

    Configure in settings.py:
        TRUSTED_PROXY_IPS = {'10.0.0.1', '10.0.0.2'}   # your load balancer IPs
    Set to None (the default) to trust ALL proxies — suitable only when
    the app is always behind a known proxy and REMOTE_ADDR is reliable.
    """
    from django.conf import settings

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        trusted = getattr(settings, "TRUSTED_PROXY_IPS", None)
        remote = request.META.get("REMOTE_ADDR", "")
        # Trust XFF only if TRUSTED_PROXY_IPS is unconfigured (legacy) OR
        # the direct connection comes from a known proxy.
        if trusted is None or remote in trusted:
            return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class AuditLogMiddleware:
    """Captures user IP and user-agent for audit logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    @staticmethod
    def get_client_ip(request) -> str:
        return _get_client_ip(request)


class RequestLoggingMiddleware:
    """Populates contextvars for the logging filter."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.logging import clear_logging_context, set_logging_context

        user_id = str(request.user.pk) if hasattr(request, "user") and request.user.is_authenticated else "anonymous"  # noqa: E501
        company_id = str(request.company.pk) if hasattr(request, "company") and request.company else "none"  # noqa: E501

        set_logging_context(
            user_id=user_id,
            company_id=company_id,
            request_path=request.path,
            client_ip=_get_client_ip(request),
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
    """
    Updates user's last_active timestamp on each request.

    To avoid a DB write on every single request (high load = O(n) writes/sec),
    we use a short-lived cache key per user.  The DB is only updated when the
    cache key is absent, i.e. at most once per LAST_ACTIVE_UPDATE_INTERVAL
    seconds (default: 5 minutes).
    """

    CACHE_TTL = 300  # seconds between DB updates (5 minutes)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if request.user.is_authenticated:
            self._update_last_active(request.user.pk)

        return response

    @staticmethod
    def _update_last_active(user_pk):
        from django.core.cache import cache

        from apps.authentication.models import User

        cache_key = f"last_active:{user_pk}"
        if cache.get(cache_key):
            # Already updated recently — skip the DB write
            return
        User.objects.filter(pk=user_pk).update(last_active=timezone.now())
        cache.set(cache_key, 1, timeout=ActiveUserMiddleware.CACHE_TTL)

