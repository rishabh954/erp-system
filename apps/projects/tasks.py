from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.notifications.tasks import send_bulk_notification
from apps.projects.models import Project, Task


@shared_task
def send_task_deadline_reminders():
    """
    Notify users of tasks due in 24 hours (i.e. due tomorrow).
    """
    tomorrow = timezone.now().date() + timedelta(days=1)

    # Find tasks due tomorrow that are not done or cancelled
    tasks = Task.objects.filter(due_date=tomorrow, assigned_to__isnull=False).exclude(
        status__in=[Task.Status.DONE, Task.Status.CANCELLED]
    )

    notifications = []
    for task in tasks:
        notifications.append(
            {
                "recipient_id": task.assigned_to_id,
                "title": "Task Deadline Reminder",
                "message": f"The task '{task.title}' in project '{task.project.name}' is due tomorrow.",
                "notification_type": "reminder",
                "action_url": f"/projects/tasks/{task.pk}/",
                "action_label": "View Task",
            }
        )

    if notifications:
        send_bulk_notification.delay(notifications)
        return f"Queued {len(notifications)} task deadline reminders."
    return "No tasks due tomorrow."


@shared_task
def auto_update_project_progress():
    """
    Recalculate project progress based on task completion %.
    """
    projects = Project.objects.filter(
        status__in=[
            Project.Status.PLANNING,
            Project.Status.ACTIVE,
            Project.Status.ON_HOLD,
        ]
    )

    updated_count = 0
    for project in projects:
        old_progress = project.progress
        new_progress = project.completion_percent  # Property on Project model

        if old_progress != new_progress:
            project.progress = new_progress
            project.save(update_fields=["progress"])
            updated_count += 1

            # Optionally check if progress is 100% and notify manager
            if new_progress == 100 and project.manager:
                send_bulk_notification.delay(
                    [
                        {
                            "recipient_id": project.manager_id,
                            "title": "Project Completed",
                            "message": f"All tasks in project '{project.name}' are now completed.",
                            "notification_type": "success",
                            "action_url": f"/projects/{project.pk}/",
                            "action_label": "View Project",
                        }
                    ]
                )

    return f"Updated progress for {updated_count} projects."
