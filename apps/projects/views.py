"""
Project Management Views
Projects, Tasks, Milestones, Kanban Board, Time Logging
"""

from core.permissions import PermissionRequiredMixin
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import DetailView, ListView, View

from core.services import BaseService

from .models import Project, ProjectMember, Task, TaskComment, TimeLog


class CompanyMixin(PermissionRequiredMixin):
    def company(self):
        return self.request.user.primary_company


class ProjectListView(CompanyMixin, ListView):
    required_permission = "projects.read"
    template_name = "projects/list.html"
    context_object_name = "projects"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            Project.objects.filter(company=self.company(), is_deleted=False)
            .select_related("manager", "customer")
            .annotate(
                task_count=Count("tasks", filter=Q(tasks__is_deleted=False)),
                done_count=Count(
                    "tasks", filter=Q(tasks__status="done", tasks__is_deleted=False)
                ),
            )
            .order_by("-created_at")
        )

        q = self.request.GET.get("q", "")
        status = self.request.GET.get("status", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(number__icontains=q))
        if status:
            qs = qs.filter(status=status)

        # Non-managers see only their projects
        if self.request.user.role not in (
            "project_manager",
            "company_admin",
            "super_admin",
        ):
            qs = qs.filter(
                Q(manager=self.request.user) | Q(team_members=self.request.user)
            ).distinct()
        return qs

    def get(self, request, *args, **kwargs):
        # Sidebar "Kanban Board" link fallback — redirect to first available project's kanban
        if request.GET.get("open_kanban"):
            first_proj = (
                Project.objects.filter(
                    company=self.company(),
                    is_deleted=False,
                    status__in=["active", "planning", "on_hold"],
                )
                .order_by("-created_at")
                .first()
            )
            if first_proj:
                return redirect("projects:kanban", pk=first_proj.pk)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Project.Status.choices
        ctx["active_count"] = Project.objects.filter(
            company=self.company(), status="active", is_deleted=False
        ).count()
        return ctx


class ProjectDetailView(CompanyMixin, DetailView):
    required_permission = "projects.read"
    template_name = "projects/detail.html"
    context_object_name = "project"

    def get_object(self):
        return get_object_or_404(
            Project, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        project = self.object
        ctx["milestones"] = project.milestones.filter(is_deleted=False).order_by(
            "due_date"
        )
        ctx["tasks"] = (
            project.tasks.filter(is_deleted=False)
            .select_related("assigned_to", "milestone")
            .order_by("status", "position")
        )
        ctx["members"] = ProjectMember.objects.filter(project=project).select_related(
            "user"
        )
        ctx["time_logs"] = (
            TimeLog.objects.filter(task__project=project, is_deleted=False)
            .select_related("user", "task")
            .order_by("-date")[:20]
        )
        ctx["total_hours"] = (
            TimeLog.objects.filter(task__project=project, is_deleted=False).aggregate(
                t=Sum("hours")
            )["t"]
            or 0
        )
        ctx["budget_used_pct"] = (
            int(project.actual_cost / project.budget * 100) if project.budget else 0
        )
        return ctx


class ProjectCreateView(CompanyMixin, View):
    required_permission = "projects.create"
    template_name = "projects/form.html"

    def get(self, request):
        from apps.authentication.models import User
        from apps.crm.models import Customer

        c = self.company()
        return render(
            request,
            self.template_name,
            {
                "customers": Customer.objects.filter(
                    company=c, is_deleted=False
                ).order_by("name"),
                "users": User.objects.filter(companies=c, is_active=True).order_by(
                    "first_name"
                ),
                "status_choices": Project.Status.choices,
                "priority_choices": Project.Priority.choices,
            },
        )

    def post(self, request):
        data = request.POST
        company = self.company()
        try:
            project = Project(
                company=company,
                name=data["name"],
                description=data.get("description", ""),
                customer_id=data.get("customer") or None,
                status=data.get("status", "planning"),
                priority=data.get("priority", "medium"),
                start_date=data.get("start_date") or None,
                end_date=data.get("end_date") or None,
                budget=float(data.get("budget", 0)),
                manager=request.user,
                is_billable=data.get("is_billable") == "on",
            )
            project.number = BaseService.generate_sequence_number(
                "PRJ", Project, company.pk
            )
            project.save()

            # Add manager as member
            ProjectMember.objects.create(
                project=project, user=request.user, role="Manager"
            )

            messages.success(request, f"Project {project.number} created.")
            return redirect("projects:detail", pk=project.pk)
        except Exception as e:
            messages.error(request, f"Error: {e}")
            return redirect("projects:list")


# ─── Tasks ────────────────────────────────────────────────────────────────────


class KanbanBoardView(CompanyMixin, DetailView):
    required_permission = "projects.read"
    template_name = "projects/kanban.html"
    context_object_name = "project"

    def get_object(self):
        return get_object_or_404(
            Project, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        project = self.object
        statuses = [s[0] for s in Task.Status.choices]
        columns = {}
        for s in statuses:
            columns[s] = {
                "label": dict(Task.Status.choices)[s],
                "tasks": Task.objects.filter(
                    project=project, status=s, is_deleted=False, parent_task=None
                )
                .select_related("assigned_to")
                .order_by("position"),
            }
        ctx["columns"] = columns
        ctx["status_choices"] = Task.Status.choices
        ctx["priority_choices"] = Task.Priority.choices
        from apps.authentication.models import User

        ctx["team_members"] = User.objects.filter(
            projectmember__project=project, is_active=True
        )
        return ctx


class TaskMoveView(CompanyMixin, View):
    required_permission = "projects.read"
    """AJAX endpoint to move task between Kanban columns."""

    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, company=self.company(), is_deleted=False)
        new_status = request.POST.get("status")
        if new_status and new_status in dict(Task.Status.choices):
            task.status = new_status
            if new_status == "done":
                task.completed_at = timezone.now()
            task.save(update_fields=["status", "completed_at"])
            return JsonResponse({"ok": True, "status": new_status})
        return JsonResponse({"ok": False, "error": "Invalid status"}, status=400)


class TaskCreateView(CompanyMixin, View):
    required_permission = "projects.create"
    def get(self, request):
        from django.forms import DateInput, modelform_factory

        TaskForm = modelform_factory(
            Task,
            fields=[
                "project",
                "title",
                "description",
                "status",
                "priority",
                "assigned_to",
                "due_date",
                "estimated_hours",
            ],
            widgets={"due_date": DateInput(attrs={"type": "date"})},
        )
        form = TaskForm()
        form.fields["project"].queryset = Project.objects.filter(
            company=self.company(), is_deleted=False
        )
        from apps.authentication.models import User

        form.fields["assigned_to"].queryset = User.objects.filter(
            projectmember__project__company=self.company(), is_active=True
        ).distinct()
        return render(request, "projects/tasks/form.html", {"form": form})

    def post(self, request):
        data = request.POST
        company = self.company()
        project = get_object_or_404(Project, pk=data["project"], company=company)
        task = Task(
            company=company,
            project=project,
            title=data["title"],
            description=data.get("description", ""),
            status=data.get("status", "todo"),
            priority=data.get("priority", "medium"),
            assigned_to_id=data.get("assigned_to") or None,
            due_date=data.get("due_date") or None,
            estimated_hours=float(data.get("estimated_hours") or 0),
        )
        task.save()
        messages.success(request, "Task created.")
        return redirect("projects:kanban", pk=project.pk)


class MyTasksView(CompanyMixin, ListView):
    required_permission = "projects.read"
    template_name = "projects/my_tasks.html"
    context_object_name = "tasks"

    def get_queryset(self):
        return (
            Task.objects.filter(
                company=self.company(),
                assigned_to=self.request.user,
                is_deleted=False,
                status__in=["todo", "in_progress", "in_review"],
            )
            .select_related("project", "milestone")
            .order_by("due_date", "priority")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_hours_logged"] = (
            TimeLog.objects.filter(user=self.request.user, is_deleted=False).aggregate(
                t=Sum("hours")
            )["t"]
            or 0
        )
        ctx["overdue_count"] = (
            self.get_queryset().filter(due_date__lt=timezone.localdate()).count()
        )
        return ctx


class TaskDetailView(CompanyMixin, DetailView):
    required_permission = "projects.read"
    template_name = "projects/task_detail.html"
    context_object_name = "task"

    def get_object(self):
        return get_object_or_404(
            Task, pk=self.kwargs["pk"], company=self.company(), is_deleted=False
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["comments"] = self.object.comments.filter(is_deleted=False).select_related(
            "author"
        )
        ctx["time_logs"] = self.object.time_logs.filter(
            is_deleted=False
        ).select_related("user")
        ctx["subtasks"] = self.object.subtasks.filter(is_deleted=False)
        ctx["total_logged"] = (
            self.object.time_logs.filter(is_deleted=False).aggregate(t=Sum("hours"))[
                "t"
            ]
            or 0
        )
        return ctx


class AddCommentView(CompanyMixin, View):
    required_permission = "projects.read"
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, company=self.company(), is_deleted=False)
        content = request.POST.get("content", "").strip()
        if content:
            TaskComment.objects.create(
                company=self.company(),
                task=task,
                author=request.user,
                content=content,
            )
        return redirect("projects:task_detail", pk=pk)


class LogTimeView(CompanyMixin, View):
    required_permission = "projects.read"
    def post(self, request, pk):
        task = get_object_or_404(Task, pk=pk, company=self.company(), is_deleted=False)
        hours = float(request.POST.get("hours", 0))
        if hours > 0:
            TimeLog.objects.create(
                company=self.company(),
                task=task,
                user=request.user,
                date=timezone.localdate(),
                hours=hours,
                description=request.POST.get("description", ""),
                is_billable=request.POST.get("is_billable") == "on",
            )
            task.actual_hours = (task.actual_hours or 0) + hours
            task.save(update_fields=["actual_hours"])
        return redirect("projects:task_detail", pk=pk)


# ════════════════════════ AGILE & RISK VIEWS ══════════════════════════════════

from .models import ProjectRisk, Sprint
from .services import ProjectTrackingService


class AgileBoardView(CompanyMixin, DetailView):
    required_permission = "projects.read"
    template_name = "projects/agile_board.html"
    context_object_name = "sprint"

    def get_queryset(self):
        return Sprint.objects.filter(project__company=self.company())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sprint = self.object
        ctx["tasks"] = sprint.tasks.filter(is_deleted=False).order_by(
            "position", "-created_at"
        )
        ctx["burndown"] = ProjectTrackingService.get_sprint_burndown(sprint.id)
        return ctx


class ProjectGanttDataView(CompanyMixin, View):
    required_permission = "projects.read"
    def get(self, request, pk):
        project = get_object_or_404(Project, pk=pk, company=self.company())
        tasks = (
            project.tasks.filter(is_deleted=False)
            .exclude(start_date__isnull=True)
            .exclude(due_date__isnull=True)
        )
        data = []
        for t in tasks:
            data.append(
                {
                    "id": str(t.id),
                    "text": t.title,
                    "start_date": t.start_date.strftime("%Y-%m-%d"),
                    "end_date": t.due_date.strftime("%Y-%m-%d"),
                    "progress": (
                        1
                        if t.status == "done"
                        else 0.5 if t.status in ["in_progress", "in_review"] else 0
                    ),
                    "parent": str(t.parent_task_id) if t.parent_task_id else None,
                }
            )
        return JsonResponse({"data": data})


class ProjectRiskListView(CompanyMixin, ListView):
    required_permission = "projects.read"
    template_name = "projects/risks/list.html"
    context_object_name = "risks"

    def get_queryset(self):
        project_id = self.kwargs.get("pk")
        return ProjectRisk.objects.filter(
            project_id=project_id, project__company=self.company()
        )


class ProjectRiskDetailView(CompanyMixin, DetailView):
    required_permission = "projects.read"
    template_name = "projects/risks/detail.html"
    context_object_name = "risk"

    def get_queryset(self):
        return ProjectRisk.objects.filter(project__company=self.company())
