from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.authentication.models import UserCompany
from apps.company.models import Company
from apps.notifications.tasks import send_bulk_notification
from apps.projects.models import Project, Task


@shared_task
def send_task_deadline_reminders():
    """
    Notify users of tasks due in 24 hours (i.e. due tomorrow).
    """
    tomorrow = timezone.now().date() + timedelta(days=1)

    queued = 0
    for company in Company.objects.filter(status="active", is_deleted=False):
        eligible_user_ids = UserCompany.objects.filter(
            company=company, is_active=True, user__is_active=True
        ).values_list("user_id", flat=True)
        tasks = Task.objects.filter(
            company=company,
            due_date=tomorrow,
            assigned_to_id__in=eligible_user_ids,
            is_deleted=False,
        ).exclude(status__in=[Task.Status.DONE, Task.Status.CANCELLED])

        for task in tasks.select_related("project"):
            send_bulk_notification.delay(
                recipient_ids=[str(task.assigned_to_id)],
                title="Task Deadline Reminder",
                message=(
                    f"The task '{task.title}' in project '{task.project.name}' "
                    "is due tomorrow."
                ),
                notification_type="reminder",
                action_url=f"/projects/tasks/{task.pk}/",
                company_id=str(company.pk),
            )
            queued += 1

    if queued:
        return f"Queued {queued} task deadline reminders."
    return "No tasks due tomorrow."


@shared_task
def auto_update_project_progress():
    """
    Recalculate project progress based on task completion %.
    """
    updated_count = 0
    for company in Company.objects.filter(status="active", is_deleted=False):
        project_ids = Project.objects.filter(
            company=company,
            status__in=[
                Project.Status.PLANNING,
                Project.Status.ACTIVE,
                Project.Status.ON_HOLD,
            ],
            is_deleted=False,
        ).values_list("pk", flat=True)

        for project_id in project_ids:
            with transaction.atomic():
                project = (
                    Project.objects.select_for_update()
                    .filter(company=company, pk=project_id, is_deleted=False)
                    .first()
                )
                if project is None:
                    continue

                task_counts = Task.objects.filter(
                    company=company, project=project, is_deleted=False
                ).aggregate(
                    total=Count("pk"),
                    done=Count("pk", filter=Q(status=Task.Status.DONE)),
                )
                total = task_counts["total"]
                new_progress = int(task_counts["done"] / total * 100) if total else 0
                if project.progress == new_progress:
                    continue

                project.progress = new_progress
                project.save(update_fields=["progress"])
                updated_count += 1

                if new_progress == 100 and project.manager_id:
                    recipients = UserCompany.objects.filter(
                        company=company,
                        user_id=project.manager_id,
                        is_active=True,
                        user__is_active=True,
                    ).values_list("user_id", flat=True)
                    if recipients:
                        notification = {
                            "recipient_ids": [str(user_id) for user_id in recipients],
                            "title": "Project Completed",
                            "message": f"All tasks in project '{project.name}' are now completed.",
                            "notification_type": "success",
                            "action_url": f"/projects/{project.pk}/",
                            "company_id": str(company.pk),
                        }
                        transaction.on_commit(
                            lambda payload=notification: send_bulk_notification.delay(
                                **payload
                            )
                        )

    return f"Updated progress for {updated_count} projects."
