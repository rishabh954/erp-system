import pytest
from django.urls import reverse

from apps.projects.models import Project

pytestmark = pytest.mark.django_db


def test_project_crud(client, user, company):
    client.force_login(user)

    # Create
    create_url = reverse("projects:create")
    res = client.post(
        create_url,
        {
            "name": "Test Project CRUD",
            "status": Project.Status.PLANNING,
            "budget": "10000.00",
        },
    )
    assert res.status_code == 302
    proj = Project.objects.filter(name="Test Project CRUD").first()
    assert proj is not None

    # Read Detail
    detail_url = reverse("projects:detail", kwargs={"pk": proj.pk})
    res = client.get(detail_url)
    assert res.status_code == 200

    # List
    list_url = reverse("projects:list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert proj in res.context["object_list"]
