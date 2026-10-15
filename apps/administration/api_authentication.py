import hashlib
import hmac

from django.db.models import F
from django.utils import timezone
from rest_framework import authentication, exceptions, permissions


class APIKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Api-Key"

    def authenticate(self, request):
        raw_key = request.headers.get("X-API-Key", "").strip()
        authorization = request.headers.get("Authorization", "").strip()
        if not raw_key and authorization.lower().startswith(self.keyword.lower() + " "):
            raw_key = authorization.split(None, 1)[1].strip()
        if not raw_key:
            return None
        if len(raw_key) > 256:
            raise exceptions.AuthenticationFailed("Invalid API key.")

        from apps.administration.models import APIKey
        from apps.authentication.models import UserCompany

        prefix = raw_key[:12]
        key = APIKey.objects.select_related("company", "created_by").filter(
            key_prefix=prefix
        ).first()
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        if (
            key is None
            or not hmac.compare_digest(key.key, digest)
            or key.status != APIKey.Status.ACTIVE
            or (key.expires_at and key.expires_at <= timezone.now())
            or key.created_by is None
            or not key.created_by.is_active
            or (
                not key.created_by.is_superuser
                and not UserCompany.objects.filter(
                    user=key.created_by, company=key.company, is_active=True
                ).exists()
            )
        ):
            raise exceptions.AuthenticationFailed("Invalid API key.")

        APIKey.objects.filter(pk=key.pk, company_id=key.company_id).update(
            last_used_at=timezone.now(), request_count=F("request_count") + 1
        )
        request.api_key = key
        request.company = key.company
        request._request.api_key = key
        request._request.company = key.company
        request._request._authenticated_api_key_company = key.company
        return key.created_by, key

    def authenticate_header(self, request):
        return self.keyword


class APIKeyScopePermission(permissions.BasePermission):
    """DRF permission helper for views that declare required_permission."""

    def has_permission(self, request, view):
        key = getattr(request, "auth", None)
        if not isinstance(key, self._api_key_model()):
            return True
        required = getattr(view, "required_permission", None)
        if not required or "." not in required:
            return False
        module, action = required.split(".", 1)
        if not key.created_by.has_module_permission(
            module, action, company=key.company
        ):
            return False
        scopes = key.scopes or []
        if "*" in scopes or required in scopes:
            return True
        if action == "read" and f"read:{module}" in scopes:
            return True
        if action in {"create", "update", "delete", "approve", "import", "export"}:
            return f"write:{module}" in scopes
        return False

    @staticmethod
    def _api_key_model():
        from apps.administration.models import APIKey

        return APIKey
