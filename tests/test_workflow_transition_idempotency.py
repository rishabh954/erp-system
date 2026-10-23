from datetime import timedelta

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.crm.models import Lead
from apps.workflow.engine import WorkflowEngine
from apps.workflow.models import (
    ApprovalDelegation,
    WorkflowAction,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
)


def make_approver(company):
    user = User.objects.create_user(
        email=f"approver-{company.pk}@example.com",
        password="password",
        first_name="Workflow",
        last_name="Approver",
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


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action_method", "action_value", "final_status"),
    [
        (WorkflowEngine.approve, WorkflowAction.Action.APPROVED, WorkflowInstance.Status.APPROVED),
        (WorkflowEngine.reject, WorkflowAction.Action.REJECTED, WorkflowInstance.Status.REJECTED),
    ],
)
def test_stale_workflow_instance_cannot_record_duplicate_decision(
    action_method, action_value, final_status
):
    company = Company.objects.create(name=f"Workflow {action_value}")
    approver = make_approver(company)
    definition = WorkflowDefinition.objects.create(
        company=company,
        name="Single approval",
        trigger_model="Company",
        notify_in_app=False,
        notify_email=False,
    )
    step = WorkflowStep.objects.create(
        workflow=definition,
        name="Manager approval",
        step_order=1,
        approver_type=WorkflowStep.ApproverType.USER,
        approver_user=approver,
    )
    instance = WorkflowInstance.objects.create(
        company=company,
        definition=definition,
        current_step=step,
        status=WorkflowInstance.Status.IN_PROGRESS,
        content_type=ContentType.objects.get_for_model(Company),
        object_id=str(company.pk),
        initiated_by=approver,
    )

    assert action_method(instance, approver) is True
    with pytest.raises(ValueError, match="not in an approvable state"):
        action_method(instance, approver)

    instance.refresh_from_db()
    assert instance.status == final_status
    assert WorkflowAction.objects.filter(
        instance=instance, action=action_value
    ).count() == 1


@pytest.mark.django_db
def test_trigger_is_idempotent_for_active_company_document():
    company = Company.objects.create(name="Trigger Company")
    approver = make_approver(company)
    lead = Lead.objects.create(company=company, name="Workflow lead")
    definition = WorkflowDefinition.objects.create(
        company=company,
        name="Lead approval",
        trigger_model=Lead.__name__,
        trigger_event=WorkflowDefinition.TriggerEvent.ON_SUBMIT,
        notify_in_app=False,
        notify_email=False,
    )
    WorkflowStep.objects.create(
        workflow=definition,
        name="Manager approval",
        step_order=1,
        approver_type=WorkflowStep.ApproverType.USER,
        approver_user=approver,
    )

    instance = WorkflowEngine.trigger(
        lead, WorkflowDefinition.TriggerEvent.ON_SUBMIT, approver
    )
    duplicate = WorkflowEngine.trigger(
        lead, WorkflowDefinition.TriggerEvent.ON_SUBMIT, approver
    )

    assert instance is not None
    assert instance.status == WorkflowInstance.Status.IN_PROGRESS
    assert duplicate is None
    assert WorkflowInstance.objects.filter(
        company=company,
        content_type=ContentType.objects.get_for_model(Lead),
        object_id=str(lead.pk),
    ).count() == 1


@pytest.mark.django_db
def test_pending_approvers_ignore_delegations_from_other_companies():
    company_a = Company.objects.create(name="Delegation A")
    company_b = Company.objects.create(name="Delegation B")
    approver = make_approver(company_a)
    UserCompany.objects.create(
        user=approver,
        company=company_b,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    delegatee = make_approver(company_b)
    definition = WorkflowDefinition.objects.create(
        company=company_a,
        name="Local workflow",
        trigger_model="Company",
        notify_in_app=False,
        notify_email=False,
    )
    step = WorkflowStep.objects.create(
        workflow=definition,
        name="Local approval",
        step_order=1,
        approver_type=WorkflowStep.ApproverType.USER,
        approver_user=approver,
    )
    instance = WorkflowInstance.objects.create(
        company=company_a,
        definition=definition,
        current_step=step,
        status=WorkflowInstance.Status.IN_PROGRESS,
        content_type=ContentType.objects.get_for_model(Company),
        object_id=str(company_a.pk),
        initiated_by=approver,
    )
    today = timezone.localdate()
    ApprovalDelegation.objects.create(
        company=company_b,
        delegator=approver,
        delegatee=delegatee,
        start_date=today,
        end_date=today + timedelta(days=30),
        is_active=True,
        workflow=None,
    )

    assert WorkflowEngine.get_pending_approvers(instance) == [approver]
