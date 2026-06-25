import uuid
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from core.models import CompanyScoped


# ═══════════════════════════════ WORKFLOW ENGINE ══════════════════════════════

class WorkflowDefinition(CompanyScoped):
    """Reusable workflow template."""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    trigger_model = models.CharField(max_length=100)  # e.g. 'hrms.LeaveRequest'
    trigger_event = models.CharField(max_length=50)   # e.g. 'on_submit'
    is_active = models.BooleanField(default=True)
    conditions = models.JSONField(default=dict)

    class Meta:
        db_table = 'workflow_definitions'

    def __str__(self):
        return f"{self.name} ({self.trigger_model})"


class WorkflowStep(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(WorkflowDefinition, on_delete=models.CASCADE, related_name='steps')
    name = models.CharField(max_length=200)
    step_order = models.PositiveSmallIntegerField()
    step_type = models.CharField(
        max_length=20,
        choices=[('approval', 'Approval'), ('notification', 'Send Notification'),
                 ('action', 'Auto Action'), ('condition', 'Condition')],
    )
    approver_type = models.CharField(
        max_length=20,
        choices=[('user', 'Specific User'), ('role', 'Role'), ('manager', 'Direct Manager'),
                 ('department_head', 'Department Head')],
        blank=True,
    )
    approver_user = models.ForeignKey('authentication.User', null=True, blank=True, on_delete=models.SET_NULL)
    approver_role = models.CharField(max_length=30, blank=True)
    action_config = models.JSONField(default=dict)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    department = models.ForeignKey('company.Department', null=True, blank=True, on_delete=models.SET_NULL)
    branch = models.ForeignKey('company.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    is_required = models.BooleanField(default=True)

    class Meta:
        db_table = 'workflow_steps'
        ordering = ['step_order']


class WorkflowInstance(CompanyScoped):
    """A running instance of a workflow for a specific record."""

    class Status(models.TextChoices):
        PENDING = 'pending', _('Pending')
        IN_PROGRESS = 'in_progress', _('In Progress')
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        CANCELLED = 'cancelled', _('Cancelled')

    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.PROTECT)
    current_step = models.ForeignKey(WorkflowStep, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=100)
    related_object = GenericForeignKey('content_type', 'object_id')
    initiated_by = models.ForeignKey('authentication.User', on_delete=models.PROTECT, related_name='initiated_workflows')
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'workflow_instances'


class WorkflowAction(CompanyScoped):
    """Record of each approval/rejection action on a workflow instance."""

    class Action(models.TextChoices):
        APPROVED = 'approved', _('Approved')
        REJECTED = 'rejected', _('Rejected')
        DELEGATED = 'delegated', _('Delegated')
        NOTED = 'noted', _('Noted')

    instance = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name='actions')
    step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT)
    actor = models.ForeignKey('authentication.User', on_delete=models.PROTECT)
    action = models.CharField(max_length=15, choices=Action.choices)
    comment = models.TextField(blank=True)
    acted_at = models.DateTimeField(auto_now_add=True)
    delegated_to = models.ForeignKey('authentication.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='delegated_actions')

    class Meta:
        db_table = 'workflow_actions'
        ordering = ['acted_at']


class ApprovalDelegation(CompanyScoped):
    """Records when a user delegates their approval authority to someone else."""
    delegator = models.ForeignKey('authentication.User', on_delete=models.CASCADE, related_name='delegations_made')
    delegatee = models.ForeignKey('authentication.User', on_delete=models.CASCADE, related_name='delegations_received')
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'workflow_delegations'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.delegator} -> {self.delegatee}"

