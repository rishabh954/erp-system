import zoneinfo

from django.utils import timezone


class TimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz_name = None
        if request.user.is_authenticated:
            company = getattr(request.user, "primary_company", None)
            if company and company.timezone:
                tz_name = company.timezone
        if tz_name:
            try:
                tz = zoneinfo.ZoneInfo(tz_name)
                timezone.activate(tz)
            except (zoneinfo.ZoneInfoNotFoundError, KeyError):
                timezone.deactivate()  # fall back to settings.TIME_ZONE
        else:
            timezone.deactivate()
        response = self.get_response(request)
        timezone.deactivate()  # always reset after response to prevent leaking
        return response
