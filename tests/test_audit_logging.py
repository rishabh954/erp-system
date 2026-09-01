"""
Tests for Audit Logging System.
"""
import pytest

from apps.administration.models import AuditLog
from apps.crm.models import Customer


@pytest.mark.django_db
class TestAuditLogging:
    def test_audit_log_created_on_model_save(self, company):
        """Test: Creating an audited model creates an AuditLog with action and details"""
        customer = Customer.objects.create(
            company=company,
            name="Audit Test Customer",
            email="audit@example.com",
        )

        logs = AuditLog.objects.filter(model_name="Customer", object_id=str(customer.pk))
        assert logs.exists()
        log = logs.first()

        assert log.action == "create"
        assert log.company == company
        assert "Audit Test Customer" in log.object_repr
        assert str(log) == f"create on Customer by None at {log.timestamp}"
