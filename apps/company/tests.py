from django.conf import settings
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company


class TimezoneTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.company = Company.objects.create(
            name="Test Company TZ", timezone="Asia/Kolkata"
        )
        self.user = User.objects.create_user(
            email="tzuser@example.com",
            password="password123",
            first_name="TZ",
            last_name="User",
            role=User.Role.COMPANY_ADMIN,
        )
        UserCompany.objects.create(user=self.user, company=self.company, is_active=True)
        self.user.primary_company = self.company
        self.user.save()

    def test_timezone_middleware_activates_company_tz(self):
        """Simulate an authenticated request through TimezoneMiddleware."""
        self.client.login(email="tzuser@example.com", password="password123")

        # We can inspect the timezone during a view using a mock or a simple view,
        # or we can just hit a page and verify context, but a direct test is better.
        # Actually, let's just make a simple view or use a mock.
        # Since we want to assert during request processing, let's mock get_response.
        from django.http import HttpResponse

        from apps.company.middleware import TimezoneMiddleware

        def dummy_get_response(request):
            # Assert timezone is activated inside the request
            self.assertEqual(timezone.get_current_timezone_name(), "Asia/Kolkata")
            return HttpResponse()

        middleware = TimezoneMiddleware(dummy_get_response)

        from django.test.client import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user
        request.session = {}

        response = middleware(request)
        self.assertEqual(response.status_code, 200)

    def test_timezone_deactivates_after_response(self):
        """Verify no timezone leaks between requests."""
        from django.http import HttpResponse

        from apps.company.middleware import TimezoneMiddleware

        def dummy_get_response(request):
            return HttpResponse()

        middleware = TimezoneMiddleware(dummy_get_response)

        from django.test.client import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user

        middleware(request)

        # After response, it should be back to settings.TIME_ZONE
        self.assertEqual(timezone.get_current_timezone_name(), settings.TIME_ZONE)

    def test_invalid_timezone_rejected_in_form(self):
        """POST 'timezone=NotReal/Timezone' to the company settings view."""
        self.client.login(email="tzuser@example.com", password="password123")
        url = reverse("company:settings")
        response = self.client.post(
            url, {"name": "Test Company TZ", "timezone": "NotReal/Timezone"}
        )

        self.company.refresh_from_db()
        self.assertEqual(self.company.timezone, "Asia/Kolkata")

        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("Invalid timezone" in str(m) for m in messages))

    def test_anonymous_request_uses_utc(self):
        """Simulate an unauthenticated request."""
        from django.contrib.auth.models import AnonymousUser
        from django.http import HttpResponse

        from apps.company.middleware import TimezoneMiddleware

        def dummy_get_response(request):
            self.assertEqual(timezone.get_current_timezone_name(), settings.TIME_ZONE)
            return HttpResponse()

        middleware = TimezoneMiddleware(dummy_get_response)

        from django.test.client import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = AnonymousUser()

        middleware(request)
