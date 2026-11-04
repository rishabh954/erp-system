import json

import pytest
from django.urls import reverse

from apps.authentication.models import UserCompany
from apps.workflow.models import (
    ApprovalDelegation,
    WorkflowDefinition,
    WorkflowStep,
)
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_workflow_definition_rejects_missing_whitespace_and_invalid_choice(
    client, user, company
):
    client.force_login(user)
    url = reverse("workflow:create")
    for data in (
        {"name": " ", "trigger_model": "PurchaseOrder"},
        {"name": "Valid", "trigger_model": "  "},
        {"name": "Valid", "trigger_model": "PurchaseOrder", "trigger_event": "bogus"},
    ):
        response = client.post(url, data)
        assert response.status_code == 302
        assert not WorkflowDefinition.objects.filter(company=company).exists()


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"name": " "}, "Step name is required"),
        ({"name": "Approval", "step_type": "bogus"}, "valid step type"),
        (
            {"name": "Approval", "approver_type": "bogus"},
            "valid approver type",
        ),
        (
            {"name": "Approval", "approver_type": "role", "approver_role": "finance",
             "min_amount": "NaN"},
            "valid number",
        ),
    ],
)
def test_workflow_step_rejects_invalid_input_without_writes(
    client, user, company, data, error
):
    client.force_login(user)
    workflow = WorkflowDefinition.objects.create(
        company=company,
        name="Purchase approval",
        trigger_model="PurchaseOrder",
    )
    payload = {
        "name": "Approval",
        "step_type": "approval",
        "approver_type": "role",
        "approver_role": "finance_manager",
        "escalation_hours": "24",
    }
    payload.update(data)
    response = client.post(
        reverse("workflow:step_create", kwargs={"workflow_pk": workflow.pk}),
        payload,
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 400
    assert error.lower() in response.json()["error"].lower()
    assert workflow.steps.count() == 0


def test_workflow_step_rejects_foreign_tenant_approver_without_writes(
    client, user, company
):
    client.force_login(user)
    other_company = CompanyFactory()
    foreign_user = UserFactory(primary_company=other_company)
    UserCompany.objects.create(
        user=foreign_user, company=other_company, role=foreign_user.role
    )
    workflow = WorkflowDefinition.objects.create(
        company=company,
        name="Purchase approval",
        trigger_model="PurchaseOrder",
    )
    response = client.post(
        reverse("workflow:step_create", kwargs={"workflow_pk": workflow.pk}),
        {
            "name": "Approval",
            "step_type": "approval",
            "approver_type": "user",
            "approver_user": str(foreign_user.pk),
        },
        HTTP_X_REQUESTED_WITH="XMLHttpRequest",
    )
    assert response.status_code == 400
    assert "from this company" in response.json()["error"]
    assert workflow.steps.count() == 0


def test_workflow_designer_layout_validation_is_atomic(client, user, company):
    client.force_login(user)
    workflow = WorkflowDefinition.objects.create(
        company=company,
        name="Purchase approval",
        trigger_model="PurchaseOrder",
        canvas_layout={"original": True},
    )
    step = WorkflowStep.objects.create(
        workflow=workflow, name="Approval", step_order=1, canvas_x=5, canvas_y=6
    )
    response = client.post(
        reverse("workflow:designer_save", kwargs={"pk": workflow.pk}),
        data=json.dumps(
            {
                "layout": {"changed": True},
                "nodes": [
                    {"id": str(step.pk), "x": 50, "y": 60},
                    {"id": "not-a-step", "x": 70, "y": 80},
                ],
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 400
    workflow.refresh_from_db()
    step.refresh_from_db()
    assert workflow.canvas_layout == {"original": True}
    assert (step.canvas_x, step.canvas_y) == (5, 6)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"delegatee": ""}, "delegatee is required"),
        ({"start_date": " "}, "start date is required"),
        ({"start_date": "not-a-date"}, "valid start date"),
        ({"end_date": "2026-01-01"}, "before start date"),
    ],
)
def test_delegation_rejects_invalid_input_without_writes(
    client, user, company, overrides, error
):
    client.force_login(user)
    colleague = UserFactory(primary_company=company)
    UserCompany.objects.create(
        user=colleague, company=company, role=colleague.role
    )
    payload = {
        "delegatee": str(colleague.pk),
        "start_date": "2026-11-04",
        "end_date": "2026-11-05",
    }
    payload.update(overrides)
    response = client.post(reverse("workflow:delegation_create"), payload)
    assert response.status_code == 302
    assert not ApprovalDelegation.objects.filter(company=company).exists()


def test_delegation_rejects_foreign_delegatee_and_workflow(client, user, company):
    client.force_login(user)
    other_company = CompanyFactory()
    foreign_user = UserFactory(primary_company=other_company)
    UserCompany.objects.create(
        user=foreign_user, company=other_company, role=foreign_user.role
    )
    foreign_workflow = WorkflowDefinition.objects.create(
        company=other_company, name="Foreign", trigger_model="PurchaseOrder"
    )
    colleague = UserFactory(primary_company=company)
    UserCompany.objects.create(
        user=colleague, company=company, role=colleague.role
    )
    payload = {
        "delegatee": str(foreign_user.pk),
        "start_date": "2026-11-04",
        "end_date": "2026-11-05",
    }
    response = client.post(reverse("workflow:delegation_create"), payload)
    assert response.status_code == 302
    assert not ApprovalDelegation.objects.filter(company=company).exists()

    payload["delegatee"] = str(colleague.pk)
    payload["workflow"] = str(foreign_workflow.pk)
    response = client.post(reverse("workflow:delegation_create"), payload)
    assert response.status_code == 302
    assert not ApprovalDelegation.objects.filter(company=company).exists()
