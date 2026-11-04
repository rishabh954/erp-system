import pytest
from django.urls import reverse

from apps.crm.models import Customer
from apps.projects.models import Project, Task, TimeLog
from core.factories import CompanyFactory

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


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": "Missing choice", "status": "invalid"},
        {"name": "Invalid priority", "priority": "urgent?"},
        {"name": "Bad budget", "budget": "-1"},
    ],
)
def test_project_create_rejects_invalid_data_without_writes(
    client, user, company, payload
):
    client.force_login(user)
    before = Project.objects.filter(company=company).count()

    response = client.post(reverse("projects:create"), payload)

    assert response.status_code == 302
    assert Project.objects.filter(company=company).count() == before


def test_project_create_rejects_customer_from_another_company(client, user, company):
    client.force_login(user)
    other_company = CompanyFactory()
    customer = Customer.objects.create(company=other_company, name="Other customer")
    before = Project.objects.filter(company=company).count()

    response = client.post(
        reverse("projects:create"),
        {"name": "Cross-company", "customer": str(customer.pk)},
    )

    assert response.status_code == 302
    assert Project.objects.filter(company=company).count() == before


def test_project_create_preserves_default_choices(client, user, company):
    client.force_login(user)

    response = client.post(reverse("projects:create"), {"name": "Defaulted"})

    project = Project.objects.get(company=company, name="Defaulted")
    assert response.status_code == 302
    assert project.status == Project.Status.PLANNING
    assert project.priority == Project.Priority.MEDIUM


def test_task_create_rejects_foreign_project_without_writes(client, user, company):
    client.force_login(user)
    other_company = CompanyFactory()
    foreign_project = Project.objects.create(company=other_company, name="Foreign")
    before = Task.objects.filter(company=company).count()

    response = client.post(
        reverse("projects:task_create"),
        {"project": str(foreign_project.pk), "title": "Cross-company"},
    )

    assert response.status_code == 302
    assert Task.objects.filter(company=company).count() == before


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   ", "status": "todo"},
        {"title": "Bad status", "status": "not-a-status"},
        {"title": "Bad priority", "priority": "urgent?"},
        {"title": "Bad hours", "estimated_hours": "NaN"},
    ],
)
def test_task_create_rejects_invalid_data_without_writes(
    client, user, company, payload
):
    client.force_login(user)
    project = Project.objects.create(company=company, name="Task parent")
    payload["project"] = str(project.pk)
    before = Task.objects.filter(company=company).count()

    response = client.post(reverse("projects:task_create"), payload)

    assert response.status_code == 302
    assert Task.objects.filter(company=company).count() == before


@pytest.mark.parametrize("hours", ["", "   ", "0", "-1", "invalid", "1.234"])
def test_log_time_rejects_invalid_hours_without_partial_write(
    client, user, company, hours
):
    client.force_login(user)
    project = Project.objects.create(company=company, name="Time parent")
    task = Task.objects.create(company=company, project=project, title="Task")
    before = TimeLog.objects.filter(task=task).count()

    response = client.post(
        reverse("projects:task_log_time", kwargs={"pk": task.pk}),
        {"hours": hours},
    )

    task.refresh_from_db()
    assert response.status_code == 302
    assert TimeLog.objects.filter(task=task).count() == before
    assert task.actual_hours == 0
