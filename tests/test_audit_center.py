import pytest
from django.urls import reverse

from apps.administration.models import AuditEvent
from apps.administration.services import AuditRedactionService, AuditService


@pytest.mark.django_db
class TestAuditCenter:
    def test_audit_event_records_company_and_actor(self, company, user):
        event = AuditService.record(
            company=company,
            user=user,
            action="LOGIN_SUCCESS",
            category="AUTHENTICATION",
            module="authentication",
            event_type="login_success",
            model_name="User",
            object_id=str(user.pk),
            object_repr=str(user),
            status="SUCCESS",
            severity="HIGH",
            risk_score=20,
        )

        assert isinstance(event, AuditEvent)
        assert event.company == company
        assert event.actor_user == user
        assert event.action == "LOGIN_SUCCESS"
        assert event.status == "SUCCESS"

    def test_redaction_service_masks_sensitive_fields(self):
        payload = {
            "password": "secret",
            "totp_secret": "abc123",
            "token": "token-value",
            "nested": {"api_key": "key-1"},
        }

        redacted = AuditRedactionService.redact(payload)

        assert redacted["password"] == "[REDACTED]"
        assert redacted["totp_secret"] == "[REDACTED]"
        assert redacted["token"] == "[REDACTED]"
        assert redacted["nested"]["api_key"] == "[REDACTED]"

    def test_audit_service_records_change_tracking(self, company, user):
        event = AuditService.record_update(
            company=company,
            user=user,
            model_name="User",
            object_id=str(user.pk),
            object_repr=str(user),
            old_values={"status": "draft"},
            new_values={"status": "active"},
            changed_fields={"status": {"old": "draft", "new": "active"}},
            module="authentication",
            action="PROFILE_UPDATE",
            category="AUTHENTICATION",
        )

        assert event.changed_fields["status"]["new"] == "active"
        assert event.previous_hash or event.event_hash

    def test_audit_center_view_lists_company_events(self, client, company, user):
        AuditService.record(
            company=company,
            user=user,
            action="LOGIN_SUCCESS",
            category="AUTHENTICATION",
            module="authentication",
            event_type="login_success",
            model_name="User",
            object_id=str(user.pk),
            object_repr=str(user),
        )

        client.force_login(user)
        response = client.get(reverse("administration:audit_center"))

        assert response.status_code == 200
        assert "events" in response.context
        assert any(event.action == "LOGIN_SUCCESS" for event in response.context["events"])
