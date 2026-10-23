from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.projects.models import Project, Task
from core.factories import UserFactory


@pytest.mark.django_db
def test_deadline_reminders_use_tenant_scoped_notification_signature(
    company, user
):
    from apps.notifications.tasks import send_bulk_notification
    from apps.projects.tasks import send_task_deadline_reminders

    company_b = Company.objects.create(name="Projects B")
    user_b = UserFactory(primary_company=company_b, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.create(
        user=user_b, company=company_b, role=User.Role.COMPANY_ADMIN
    )
    project_a = Project.objects.create(company=company, name="Project A")
    project_b = Project.objects.create(company=company_b, name="Project B")
    due = timezone.now().date() + timedelta(days=1)
    task_a = Task.objects.create(
        company=company,
        project=project_a,
        assigned_to=user,
        title="Task A",
        due_date=due,
    )
    Task.objects.create(
        company=company_b,
        project=project_b,
        assigned_to=user_b,
        title="Task B",
        due_date=due,
    )
    # Cross-company assignment must not result in a tenant-mismatched alert.
    Task.objects.create(
        company=company,
        project=project_a,
        assigned_to=user_b,
        title="Misassigned task",
        due_date=due,
    )

    with patch.object(send_bulk_notification, "delay") as enqueue:
        result = send_task_deadline_reminders.run()

    assert result == "Queued 2 task deadline reminders."
    assert enqueue.call_count == 2
    by_company = {call.kwargs["company_id"]: call.kwargs for call in enqueue.call_args_list}
    assert by_company[str(company.pk)]["recipient_ids"] == [str(user.pk)]
    assert by_company[str(company.pk)]["action_url"] == f"/projects/tasks/{task_a.pk}/"
    assert by_company[str(company_b.pk)]["recipient_ids"] == [str(user_b.pk)]


@pytest.mark.django_db
def test_project_progress_uses_company_tasks_and_notifies_once(
    company, user, django_capture_on_commit_callbacks
):
    from apps.notifications.tasks import send_bulk_notification
    from apps.projects.tasks import auto_update_project_progress

    company_b = Company.objects.create(name="Progress B")
    user_b = UserFactory(primary_company=company_b, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.create(
        user=user_b, company=company_b, role=User.Role.COMPANY_ADMIN
    )
    project_a = Project.objects.create(
        company=company, name="Completed project", manager=user
    )
    project_b = Project.objects.create(
        company=company_b, name="Active project", manager=user_b
    )
    Task.objects.create(
        company=company,
        project=project_a,
        title="Done task",
        status=Task.Status.DONE,
    )
    Task.objects.create(
        company=company_b,
        project=project_a,
        title="Foreign task",
        status=Task.Status.TODO,
    )
    Task.objects.create(
        company=company_b,
        project=project_b,
        title="Open task",
        status=Task.Status.TODO,
    )

    with patch.object(send_bulk_notification, "delay") as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            assert auto_update_project_progress.run() == "Updated progress for 1 projects."
        assert auto_update_project_progress.run() == "Updated progress for 0 projects."

    project_a.refresh_from_db()
    project_b.refresh_from_db()
    assert project_a.progress == 100
    assert project_b.progress == 0
    enqueue.assert_called_once_with(
        recipient_ids=[str(user.pk)],
        title="Project Completed",
        message="All tasks in project 'Completed project' are now completed.",
        notification_type="success",
        action_url=f"/projects/{project_a.pk}/",
        company_id=str(company.pk),
    )
