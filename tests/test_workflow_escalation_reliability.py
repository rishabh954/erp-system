from datetime import timedelta
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.workflow.engine import WorkflowEngine
from apps.workflow.models import (
    WorkflowDefinition,
    WorkflowEscalationLog,
    WorkflowInstance,
    WorkflowStep,
)


def make_company_user(company, email):
    user = User.objects.create_user(
        email=email,
        password="password",
        first_name="Workflow",
        last_name="User",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    return user


def make_escalated_instance(company, initiator, escalation_to):
    definition = WorkflowDefinition.objects.create(
        company=company,
        name=f"Workflow {company.name}",
        trigger_model="Company",
        notify_in_app=False,
        notify_email=False,
    )
    step = WorkflowStep.objects.create(
        workflow=definition,
        name="Escalated approval",
        step_order=1,
        approver_type=WorkflowStep.ApproverType.USER,
        approver_user=initiator,
        escalation_enabled=True,
        escalation_hours=1,
        escalation_action=WorkflowStep.EscalationAction.REASSIGN,
        escalation_to=escalation_to,
    )
    instance = WorkflowInstance.objects.create(
        company=company,
        definition=definition,
        current_step=step,
        status=WorkflowInstance.Status.IN_PROGRESS,
        content_type=ContentType.objects.get_for_model(Company),
        object_id=str(company.pk),
        initiated_by=initiator,
        current_step_started_at=timezone.now() - timedelta(hours=2),
    )
    return instance, step


@pytest.mark.django_db
def test_escalation_reassignment_is_company_scoped_and_runs_once():
    active_company = Company.objects.create(name="Escalation Active")
    inactive_company = Company.objects.create(
        name="Escalation Inactive", status=Company.Status.INACTIVE
    )
    active_initiator = make_company_user(active_company, "active-init@example.com")
    active_backup = make_company_user(active_company, "active-backup@example.com")
    inactive_initiator = make_company_user(
        inactive_company, "inactive-init@example.com"
    )
    inactive_backup = make_company_user(
        inactive_company, "inactive-backup@example.com"
    )
    active_instance, active_step = make_escalated_instance(
        active_company, active_initiator, active_backup
    )
    inactive_instance, _ = make_escalated_instance(
        inactive_company, inactive_initiator, inactive_backup
    )

    WorkflowEngine.check_and_escalate()
    WorkflowEngine.check_and_escalate()

    active_instance.refresh_from_db()
    inactive_instance.refresh_from_db()
    assert active_instance.status == WorkflowInstance.Status.ESCALATED
    assert inactive_instance.status == WorkflowInstance.Status.IN_PROGRESS
    assert WorkflowEscalationLog.objects.filter(
        instance=active_instance, step=active_step, action_taken="reassign"
    ).count() == 1
    assert not WorkflowEscalationLog.objects.filter(
        instance=inactive_instance
    ).exists()


@pytest.mark.django_db
def test_escalation_task_retries_instead_of_swallowing_engine_failure():
    from apps.workflow.tasks import check_escalations

    with (
        patch.object(
            WorkflowEngine, "check_and_escalate", side_effect=RuntimeError("db error")
        ),
        patch.object(check_escalations, "retry", side_effect=Retry()) as retry,
        pytest.raises(Retry),
    ):
        check_escalations.run()
    retry.assert_called_once()
