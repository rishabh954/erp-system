import uuid

from django.http import HttpResponseForbidden
from django.utils import timezone

from core.tenancy import get_active_company


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


class AuditContextMiddleware:
    """Attach request-scoped audit metadata generated from headers or the current session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.logging import set_logging_context

        request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex
        correlation_id = request.headers.get('X-Correlation-ID') or request_id
        session_id = getattr(request.session, 'session_key', None) if hasattr(request, 'session') else None
        user_agent = request.headers.get('User-Agent', '')
        http_method = request.method

        request.request_id = request_id
        request.correlation_id = correlation_id
        request.session_id = session_id
        request.user_agent = user_agent
        request.http_method = http_method

        set_logging_context(
            request_id=request_id,
            correlation_id=correlation_id,
            session_id=session_id,
            user_agent=user_agent,
            http_method=http_method,
        )

        response = self.get_response(request)
        return response


class RequestLoggingMiddleware:
    """Populates contextvars for the logging filter."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.logging import clear_logging_context, set_logging_context

        user_id = str(request.user.pk) if hasattr(request, "user") and request.user.is_authenticated else "anonymous"  # noqa: E501
        company_id = str(request.company.pk) if hasattr(request, "company") and request.company else "none"  # noqa: E501

        request_id = getattr(request, 'request_id', None) or request.headers.get('X-Request-ID') or uuid.uuid4().hex
        correlation_id = getattr(request, 'correlation_id', None) or request.headers.get('X-Correlation-ID') or request_id
        session_id = getattr(request, 'session_id', None) or (request.session.session_key if hasattr(request, 'session') and getattr(request.session, 'session_key', None) else None)
        user_agent = getattr(request, 'user_agent', None) or request.headers.get('User-Agent', '')
        http_method = getattr(request, 'http_method', None) or request.method

        set_logging_context(
            user_id=user_id,
            company_id=company_id,
            request_path=request.path,
            client_ip=_get_client_ip(request),
            request_id=request_id,
            correlation_id=correlation_id,
            session_id=session_id,
            user_agent=user_agent,
            http_method=http_method,
        )

        response = self.get_response(request)
        clear_logging_context()
        return response


class TenantMiddleware:
    """Resolve and inject the validated active company into `request.company`."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None

        # Unauthenticated requests have no company
        if not getattr(request, 'user', None) or not request.user.is_authenticated:
            return self.get_response(request)

        company = get_active_company(request)
        request.company = company
        if company and hasattr(request, "session"):
            request.session["active_company_id"] = str(company.pk)
        return self.get_response(request)


class ModulePermissionMiddleware:
    """Enforce module permissions declared by class-based views and ViewSets."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        # DRF authenticates inside APIView.dispatch, after Django middleware.
        view_class = getattr(view_func, "view_class", None)
        if view_class is None:
            return None

        view_initkwargs = getattr(view_func, "view_initkwargs", None) or getattr(
            view_func, "initkwargs", {}
        )
        view = view_class(**view_initkwargs)
        view.setup(request, *view_args, **view_kwargs)
        view.action_map = getattr(view_func, "actions", {})
        view.action = view.action_map.get(request.method.lower())

        get_required_permission = getattr(view, "get_required_permission", None)
        if callable(get_required_permission):
            required_permission = get_required_permission(request)
        else:
            required_permission = getattr(view_class, "required_permission", None)

        if not required_permission:
            return None
        if not request.user.is_authenticated:
            return None

        permission_parts = required_permission.split(".")
        if len(permission_parts) != 2:
            return HttpResponseForbidden()
        module, action = permission_parts
        if not request.user.has_module_permission(
            module, action, company=get_active_company(request)
        ):
            return HttpResponseForbidden()
        return None


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
