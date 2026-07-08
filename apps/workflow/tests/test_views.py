import pytest
from django.urls import reverse

from apps.workflow.models import WorkflowDefinition

pytestmark = pytest.mark.django_db


def test_workflow_crud(client, user, company):
    client.force_login(user)

    # 1. Create Workflow Definition
    create_url = reverse("workflow:create")
    res = client.post(
        create_url,
        {
            "name": "Test Workflow",
            "content_type_model": "purchaseorder",
            "is_active": True,
        },
    )
    assert res.status_code == 302
    workflow = WorkflowDefinition.objects.filter(name="Test Workflow").first()
    assert workflow is not None

    # 2. List
    list_url = reverse("workflow:list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert workflow in res.context["object_list"]

    # 3. Designer View
    designer_url = reverse("workflow:designer", kwargs={"pk": workflow.pk})
    res = client.get(designer_url)
    assert res.status_code == 200
