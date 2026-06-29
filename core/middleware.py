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
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class TenantMiddleware:
    """Injects current company into request based on user's primary_company."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        if request.user.is_authenticated:
            request.company = request.user.primary_company
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
