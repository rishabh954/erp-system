import hashlib
from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import path, reverse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.api_authentication import (
    APIKeyAuthentication,
    APIKeyScopePermission,
)
from apps.administration.models import APIKey
from apps.authentication.models import UserCompany
from core.factories import CompanyFactory
from core.tenancy import get_active_company


def make_key(company, user, raw="erp_test-key-material",
             status=APIKey.Status.ACTIVE, expires_at=None, scopes=None):
    return APIKey.objects.create(
        company=company,
        name="test key",
        key=hashlib.sha256(raw.encode()).hexdigest(),
        key_prefix=raw[:12],
        status=status,
        expires_at=expires_at,
        scopes=scopes or ["sales.read"],
        created_by=user,
    )


class APIKeyProbe(APIView):
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [APIKeyScopePermission]
    required_permission = "sales.read"

    def get(self, request):
        company = get_active_company(request)
        return Response({"company": str(company.pk) if company else None})


urlpatterns = [path("key-probe/", APIKeyProbe.as_view(), name="api-key-probe")]


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_api_key_auth_binds_company_and_stores_only_hash(client, company, user, caplog):
    raw = "erp_test-key-material"
    key = make_key(company, user, raw=raw)
    response = client.get(reverse("api-key-probe"), HTTP_AUTHORIZATION=f"Api-Key {raw}")
    assert response.status_code == 200
    assert response.json()["company"] == str(company.pk)
    key.refresh_from_db()
    assert key.key == hashlib.sha256(raw.encode()).hexdigest()
    assert key.key != raw
    assert key.request_count == 1
    assert key.last_used_at is not None
    assert raw not in caplog.text


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
@pytest.mark.parametrize(
    "status,expires_at,raw",
    [
        (APIKey.Status.REVOKED, None, "erp_test-key-material"),
        (APIKey.Status.ACTIVE, timezone.now() - timedelta(seconds=5), "erp_test-key-material"),
        (APIKey.Status.ACTIVE, None, "erp_wrong-key-material"),
    ],
)
def test_api_key_invalid_keys_are_rejected(client, company, user, status, expires_at, raw):
    make_key(company, user, expires_at=expires_at, status=status)
    response = client.get(reverse("api-key-probe"), HTTP_X_API_KEY=raw)
    assert response.status_code == 401


@pytest.mark.django_db
@override_settings(ROOT_URLCONF=__name__)
def test_api_key_tenant_overrides_other_selected_company(client, company, user):
    other = CompanyFactory()
    UserCompany.objects.create(user=user, company=other, role=user.role)
    raw = "erp_test-key-material"
    make_key(company, user, raw=raw)
    response = client.get(
        reverse("api-key-probe"),
        HTTP_AUTHORIZATION=f"Api-Key {raw}",
        HTTP_X_ACTIVE_COMPANY=str(other.pk),
    )
    assert response.status_code == 200
    assert response.json()["company"] == str(company.pk)
