from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from core.middleware import TenantMiddleware


def _add_session_to_request(request):
    middleware = SessionMiddleware(lambda req: None)
    middleware.process_request(request)
    request.session.save()


class TenantMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email="user@example.com",
            password="testpass123",
            first_name="Test",
            last_name="User",
        )

        self.company_a = Company.objects.create(name="Company A")
        self.company_b = Company.objects.create(name="Company B")

    def _get_response(self, request):
        return HttpResponse(str(getattr(request, 'company').pk if getattr(request, 'company', None) else 'none'))

    def test_header_active_company_sets_request_company(self):
        # Give membership to company A
        UserCompany.objects.create(user=self.user, company=self.company_a, is_active=True)

        request = self.factory.get('/')
        _add_session_to_request(request)
        request.user = self.user
        request.META['HTTP_X_ACTIVE_COMPANY'] = str(self.company_a.pk)

        middleware = TenantMiddleware(self._get_response)
        response = middleware(request)

        self.assertEqual(response.content.decode(), str(self.company_a.pk))

    def test_header_for_non_member_does_not_set_company(self):
        # User is not a member of company B
        UserCompany.objects.create(user=self.user, company=self.company_a, is_active=True)

        request = self.factory.get('/')
        _add_session_to_request(request)
        request.user = self.user
        request.META['HTTP_X_ACTIVE_COMPANY'] = str(self.company_b.pk)

        middleware = TenantMiddleware(self._get_response)
        response = middleware(request)

        self.assertEqual(response.content.decode(), 'none')

    def test_session_active_company_used(self):
        UserCompany.objects.create(user=self.user, company=self.company_b, is_active=True)

        request = self.factory.get('/')
        _add_session_to_request(request)
        request.user = self.user
        request.session['active_company_id'] = str(self.company_b.pk)

        middleware = TenantMiddleware(self._get_response)
        response = middleware(request)

        self.assertEqual(response.content.decode(), str(self.company_b.pk))

    def test_single_membership_infers_company(self):
        UserCompany.objects.create(user=self.user, company=self.company_a, is_active=True)

        request = self.factory.get('/')
        _add_session_to_request(request)
        request.user = self.user

        middleware = TenantMiddleware(self._get_response)
        response = middleware(request)

        self.assertEqual(response.content.decode(), str(self.company_a.pk))
