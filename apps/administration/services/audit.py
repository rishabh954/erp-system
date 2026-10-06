import hashlib
import json
from typing import Any

from django.utils import timezone

from apps.administration.models import AuditCategory, AuditEvent
from core.logging import _correlation_id, _request_id, _session_id


class AuditRedactionService:
    """Central redaction for sensitive values stored in audit payloads."""

    SENSITIVE_KEYS = (
        "password",
        "password_hash",
        "token",
        "refresh_token",
        "access_token",
        "secret_key",
        "api_key",
        "otp",
        "totp_secret",
        "credit_card",
        "bank_account",
        "security_answer",
        "private_key",
    )

    @classmethod
    def _matches_sensitive_key(cls, key: str) -> bool:
        normalized = str(key).lower()
        return any(fragment in normalized for fragment in cls.SENSITIVE_KEYS)

    @classmethod
    def redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            redacted = {}
            for key, item in value.items():
                if cls._matches_sensitive_key(str(key)):
                    redacted[key] = "[REDACTED]"
                else:
                    redacted[key] = cls.redact(item)
            return redacted
        if isinstance(value, list):
            return [cls.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls.redact(item) for item in value)
        return value

    @classmethod
    def redact_for_audit(cls, value: Any) -> Any:
        return cls.redact(value)


class AuditIntegrityService:
    """Generate and verify simple hash-chain integrity markers for events."""

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def hash_event(cls, event_payload: dict, previous_hash: str | None = None) -> str:
        payload = dict(event_payload)
        payload["previous_hash"] = previous_hash or ""
        digest = hashlib.sha256(cls._canonical_json(payload).encode("utf-8")).hexdigest()
        return digest

    @classmethod
    def verify_event(cls, event: AuditEvent) -> bool:
        if not event.previous_hash and not event.event_hash:
            return True
        expect = cls.hash_event(
            {
                "action": event.action,
                "category": event.category,
                "module": event.module,
                "event_type": event.event_type,
                "status": event.status,
                "risk_score": event.risk_score,
                "old_values": event.old_values,
                "new_values": event.new_values,
                "changed_fields": event.changed_fields,
                "metadata": event.metadata,
            },
            event.previous_hash,
        )
        return event.event_hash == expect

    @classmethod
    def verify_chain(cls, events):
        previous_hash = None
        for event in events:
            expected = cls.hash_event(
                {
                    "action": event.action,
                    "category": event.category,
                    "module": event.module,
                    "event_type": event.event_type,
                    "status": event.status,
                    "risk_score": event.risk_score,
                    "old_values": event.old_values,
                    "new_values": event.new_values,
                    "changed_fields": event.changed_fields,
                    "metadata": event.metadata,
                },
                previous_hash,
            )
            if event.event_hash and event.event_hash != expected:
                return False
            previous_hash = event.event_hash or previous_hash
        return True

    @classmethod
    def detect_tampering(cls, events):
        return not cls.verify_chain(events)


class AuditService:
    """High-level central audit pipeline for request, model, workflow, API, and business events."""

    @staticmethod
    def _request_context():
        request_id = _request_id.get() or None
        correlation_id = _correlation_id.get() or request_id
        session_id = _session_id.get() or None
        from django.core.handlers.wsgi import WSGIRequest
        from django.http import HttpRequest
        try:
            import contextvars
            frame = contextvars.copy_context()
            _ = frame
        except Exception:
            pass
        return {
            "request_id": request_id,
            "correlation_id": correlation_id,
            "session_id": session_id,
        }

    @classmethod
    def _build_event(cls, *, company=None, branch=None, department=None, user=None, actor_type=None,
                     action="", category=AuditCategory.SYSTEM, module="", event_type="",
                     model_name="", object_id="", object_reference="", object_repr="",
                     old_values=None, new_values=None, changed_fields=None, request_id=None,
                     correlation_id=None, session_id=None, ip_address=None, user_agent=None,
                     endpoint=None, http_method=None, status="SUCCESS", result=None,
                     error_code="", severity="INFO", risk_score=0, risk_reason="",
                     metadata=None, reason="", service_account="", actor_identifier="",
                     previous_hash=None, **kwargs):
        context = cls._request_context()
        old_values = AuditRedactionService.redact(old_values or {})
        new_values = AuditRedactionService.redact(new_values or {})
        changed_fields = AuditRedactionService.redact(changed_fields or {})
        metadata = AuditRedactionService.redact(metadata or {})
        safe_result = AuditRedactionService.redact(result or {})
        request_id = str(request_id or context.get("request_id") or "")
        correlation_id = str(correlation_id or context.get("correlation_id") or request_id or "")
        session_id = str(session_id or context.get("session_id") or "")
        event = AuditEvent.objects.create(
            company=company,
            branch=branch,
            department=department,
            actor_type=actor_type or (AuditEvent.ActorType.USER if user else AuditEvent.ActorType.SYSTEM),
            actor_user=user,
            service_account=service_account,
            actor_identifier=actor_identifier or (str(user.pk) if user else ""),
            action=action,
            category=category,
            module=module,
            event_type=event_type,
            model_name=model_name,
            object_id=str(object_id),
            object_reference=object_reference,
            object_repr=object_repr,
            old_values=old_values,
            new_values=new_values,
            changed_fields=changed_fields,
            request_id=request_id,
            correlation_id=correlation_id,
            session_id=session_id,
            ip_address=ip_address,
            user_agent=user_agent or "",
            endpoint=endpoint or "",
            http_method=http_method or "",
            status=status,
            result=safe_result,
            error_code=error_code,
            severity=severity,
            risk_score=int(risk_score or 0),
            risk_reason=risk_reason,
            metadata=metadata,
            reason=reason,
            previous_hash=previous_hash or "",
        )
        previous = event.previous_hash or ""
        payload = {
            "action": event.action,
            "category": event.category,
            "module": event.module,
            "event_type": event.event_type,
            "status": event.status,
            "risk_score": event.risk_score,
            "old_values": event.old_values,
            "new_values": event.new_values,
            "changed_fields": event.changed_fields,
            "metadata": event.metadata,
        }
        event.event_hash = AuditIntegrityService.hash_event(payload, previous)
        event.save(update_fields=["event_hash"])
        return event

    @classmethod
    def record(cls, **kwargs):
        return cls._build_event(**kwargs)

    @classmethod
    def record_create(cls, **kwargs):
        kwargs.setdefault("status", "SUCCESS")
        kwargs.setdefault("severity", "INFO")
        kwargs.setdefault("risk_score", 5)
        return cls.record(**kwargs)

    @classmethod
    def record_update(cls, **kwargs):
        kwargs.setdefault("status", "SUCCESS")
        kwargs.setdefault("severity", "MEDIUM")
        kwargs.setdefault("risk_score", 10)
        return cls.record(**kwargs)

    @classmethod
    def record_delete(cls, **kwargs):
        kwargs.setdefault("status", "SUCCESS")
        kwargs.setdefault("severity", "HIGH")
        kwargs.setdefault("risk_score", 20)
        return cls.record(**kwargs)

    @classmethod
    def record_view(cls, **kwargs):
        kwargs.setdefault("status", "SUCCESS")
        kwargs.setdefault("severity", "LOW")
        kwargs.setdefault("risk_score", 5)
        return cls.record(**kwargs)

    @classmethod
    def record_login(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.AUTHENTICATION)
        kwargs.setdefault("event_type", "login")
        kwargs.setdefault("severity", "MEDIUM")
        return cls.record(**kwargs)

    @classmethod
    def record_logout(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.AUTHENTICATION)
        kwargs.setdefault("event_type", "logout")
        return cls.record(**kwargs)

    @classmethod
    def record_export(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.DATA_EXPORT)
        kwargs.setdefault("event_type", "export")
        kwargs.setdefault("severity", "HIGH")
        kwargs.setdefault("risk_score", 25)
        kwargs.setdefault("status", "SUCCESS")
        return cls.record(**kwargs)

    @classmethod
    def record_import(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.DATA_IMPORT)
        kwargs.setdefault("event_type", "import")
        return cls.record(**kwargs)

    @classmethod
    def record_download(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.DOCUMENTS)
        kwargs.setdefault("event_type", "download")
        return cls.record(**kwargs)

    @classmethod
    def record_print(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.DOCUMENTS)
        kwargs.setdefault("event_type", "print")
        return cls.record(**kwargs)

    @classmethod
    def record_approval(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.WORKFLOW)
        kwargs.setdefault("event_type", "approval")
        kwargs.setdefault("severity", "HIGH")
        return cls.record(**kwargs)

    @classmethod
    def record_rejection(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.WORKFLOW)
        kwargs.setdefault("event_type", "rejection")
        return cls.record(**kwargs)

    @classmethod
    def record_security_event(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.SECURITY)
        kwargs.setdefault("severity", "HIGH")
        return cls.record(**kwargs)

    @classmethod
    def record_api_event(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.API)
        return cls.record(**kwargs)

    @classmethod
    def record_celery_event(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.CELERY)
        return cls.record(**kwargs)

    @classmethod
    def record_ai_action(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.AI)
        return cls.record(**kwargs)

    @classmethod
    def record_business_event(cls, **kwargs):
        kwargs.setdefault("category", AuditCategory.BUSINESS_DATA)
        kwargs.setdefault("severity", "MEDIUM")
        return cls.record(**kwargs)
