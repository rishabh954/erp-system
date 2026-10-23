import pytest
from django.contrib.contenttypes.models import ContentType

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowStep


def make_admin(company, email):
    user = User.objects.create_user(
        email=email,
        password="password",
        first_name="Company",
        last_name="Admin",
        role=User.Role.COMPANY_ADMIN,
    )
    UserCompany.objects.create(
        user=user,
        company=company,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    return user


@pytest.mark.django_db
def test_workflow_notification_step_must_belong_to_instance_tenant(monkeypatch):
    from apps.notifications.tasks import process_workflow_step, send_bulk_notification

    company_a = Company.objects.create(name="Workflow Notifications A")
    company_b = Company.objects.create(name="Workflow Notifications B")
    user_a = make_admin(company_a, "workflow-a@example.com")
    make_admin(company_b, "workflow-b@example.com")

    workflow_a = WorkflowDefinition.objects.create(
        company=company_a,
        name="A workflow",
        trigger_model="Invoice",
    )
    workflow_b = WorkflowDefinition.objects.create(
        company=company_b,
        name="B workflow",
        trigger_model="Invoice",
    )
    step_a = WorkflowStep.objects.create(
        workflow=workflow_a,
        name="Notify A",
        step_order=1,
        step_type=WorkflowStep.StepType.NOTIFICATION,
        approver_type=WorkflowStep.ApproverType.ROLE,
        approver_role=User.Role.COMPANY_ADMIN,
        action_config={"notification_title": "A notification"},
    )
    step_b = WorkflowStep.objects.create(
        workflow=workflow_b,
        name="Notify B",
        step_order=1,
        step_type=WorkflowStep.StepType.NOTIFICATION,
        approver_type=WorkflowStep.ApproverType.ROLE,
        approver_role=User.Role.COMPANY_ADMIN,
        action_config={"notification_title": "B notification"},
    )
    instance_a = WorkflowInstance.objects.create(
        company=company_a,
        definition=workflow_a,
        current_step=step_a,
        content_type=ContentType.objects.get_for_model(Company),
        object_id=str(company_a.pk),
        initiated_by=user_a,
    )
    queued = []
    monkeypatch.setattr(send_bulk_notification, "delay", lambda **kwargs: queued.append(kwargs))

    process_workflow_step.run(str(instance_a.pk), str(step_b.pk))
    assert queued == []

    process_workflow_step.run(str(instance_a.pk), str(step_a.pk))
    assert len(queued) == 1
    assert queued[0]["company_id"] == str(company_a.pk)
    assert queued[0]["recipient_ids"] == [user_a.pk]
    assert queued[0]["title"] == "A notification"
