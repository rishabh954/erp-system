from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.db.models import Q
from django.test import RequestFactory

from apps.authentication.middleware import SecurityMiddleware


@pytest.mark.django_db
def test_company_ip_restriction_uses_active_company_not_primary_company():
    user = SimpleNamespace(is_authenticated=True, pk=7, id=7, primary_company_id=1)
    active_company = SimpleNamespace(pk=2)
    request = RequestFactory().get("/")
    request.user = user
    request.session = SimpleNamespace(session_key="session-key")
    request.META["REMOTE_ADDR"] = "192.0.2.10"

    user_rules = Mock()
    user_rules.exists.return_value = False
    user_rules.filter.return_value = user_rules
    company_rules = Mock()
    company_rules.exists.return_value = True
    company_rules.filter.return_value.values_list.return_value = ["192.0.2.10"]

    with (
        patch("apps.authentication.middleware.get_active_company", return_value=active_company),
        patch("django.core.cache.cache") as cache,
        patch("apps.authentication.middleware.IPRestriction.objects.filter", side_effect=[user_rules, company_rules]) as filter_rules,
        patch(
            "apps.authentication.middleware.UserSession.objects.get_or_create",
            return_value=(None, True),
        ),
    ):
        cache.get.return_value = None
        middleware = SecurityMiddleware(lambda req: "ok")
        assert middleware(request) == "ok"

    filter_rules.assert_any_call(user=request.user)
    filter_rules.assert_any_call(company_id=2, user__isnull=True)
    user_rules.filter.assert_called_once()
    user_rules.filter.assert_called_once_with(
        Q(company_id=2) | Q(company__isnull=True)
    )
    assert request.user.primary_company_id != active_company.pk


def test_authentication_middleware_uses_shared_trusted_proxy_resolution(rf):
    from django.test import override_settings

    request = rf.get("/", HTTP_X_FORWARDED_FOR="198.51.100.7")
    request.META["REMOTE_ADDR"] = "203.0.113.9"
    with override_settings(TRUSTED_PROXY_IPS=None):
        assert SecurityMiddleware(lambda req: None).get_client_ip(request) == "203.0.113.9"
