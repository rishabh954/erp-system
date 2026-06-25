import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import CompanyScoped, SequenceMixin, NotesMixin, CurrencyMixin


# ═══════════════════════════════ PROJECT MANAGEMENT ═══════════════════════════

class Project(CompanyScoped, SequenceMixin, NotesMixin, CurrencyMixin):

    class Status(models.TextChoices):
        PLANNING = 'planning', _('Planning')
        ACTIVE = 'active', _('Active')
        ON_HOLD = 'on_hold', _('On Hold')
        COMPLETED = 'completed', _('Completed')
        CANCELLED = 'cancelled', _('Cancelled')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')
        CRITICAL = 'critical', _('Critical')

    name = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    customer = models.ForeignKey('crm.Customer', null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PLANNING, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    actual_start = models.DateField(null=True, blank=True)
    actual_end = models.DateField(null=True, blank=True)
    budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    actual_cost = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    progress = models.PositiveSmallIntegerField(default=0)  # 0-100%
    manager = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='managed_projects',
    )
    team_members = models.ManyToManyField('authentication.User', through='ProjectMember', related_name='projects')
    is_billable = models.BooleanField(default=False)

    class Meta:
        db_table = 'projects_projects'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.number} | {self.name}"

    @property
    def completion_percent(self):
        tasks = self.tasks.filter(is_deleted=False)
        if not tasks.exists():
            return 0
        done = tasks.filter(status='done').count()
        return int(done / tasks.count() * 100)


class ProjectMember(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    user = models.ForeignKey('authentication.User', on_delete=models.CASCADE)
    role = models.CharField(max_length=100, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    hours_allocated = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    class Meta:
        db_table = 'projects_members'
        unique_together = ('project', 'user')


class Milestone(CompanyScoped):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='milestones')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    due_date = models.DateField()
    completed_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    budget = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'projects_milestones'
        ordering = ['due_date']


class Task(CompanyScoped, NotesMixin):

    class Status(models.TextChoices):
        BACKLOG = 'backlog', _('Backlog')
        TODO = 'todo', _('To Do')
        IN_PROGRESS = 'in_progress', _('In Progress')
        IN_REVIEW = 'in_review', _('In Review')
        DONE = 'done', _('Done')
        CANCELLED = 'cancelled', _('Cancelled')

    class Priority(models.TextChoices):
        LOW = 'low', _('Low')
        MEDIUM = 'medium', _('Medium')
        HIGH = 'high', _('High')
        URGENT = 'urgent', _('Urgent')

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='tasks')
    milestone = models.ForeignKey(Milestone, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    parent_task = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='subtasks')
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.TODO, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_to = models.ForeignKey(
        'authentication.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='assigned_tasks',
    )
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    estimated_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    actual_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    position = models.PositiveIntegerField(default=0)  # for Kanban ordering
    tags = models.JSONField(default=list)

    class Meta:
        db_table = 'projects_tasks'
        ordering = ['position', '-created_at']

    def __str__(self):
        return f"{self.project.number} | {self.title}"


class TaskComment(CompanyScoped):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey('authentication.User', on_delete=models.CASCADE)
    content = models.TextField()
    attachment = models.FileField(upload_to='tasks/comments/', null=True, blank=True)

    class Meta:
        db_table = 'projects_task_comments'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.task.title[:30]} — {self.author.full_name}"


class TimeLog(CompanyScoped):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='time_logs')
    user = models.ForeignKey('authentication.User', on_delete=models.CASCADE)
    date = models.DateField()
    hours = models.DecimalField(max_digits=6, decimal_places=2)
    description = models.TextField(blank=True)
    is_billable = models.BooleanField(default=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = 'projects_time_logs'
