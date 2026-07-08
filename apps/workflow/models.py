"""
Enterprise Workflow Engine — Models
Supports: Unlimited Levels, Conditional Approval, Escalation,
          Delegation, WhatsApp + Email Notifications, Visual Designer
"""

import uuid

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped

# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW DEFINITION  (template, reusable per company)
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowDefinition(CompanyScoped):
    """
    A reusable workflow template. Supports unlimited approval levels,
    conditional branching, and multi-channel notifications.
    """

    class TriggerEvent(models.TextChoices):
        ON_SUBMIT = "on_submit", "On Submit"
        ON_CREATE = "on_create", "On Create"
        ON_AMOUNT = "on_amount", "Amount Threshold"
        ON_STATUS_CHANGE = "on_status_change", "On Status Change"
        MANUAL = "manual", "Manual Trigger"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    trigger_model = models.CharField(
        max_length=100, db_index=True, help_text="Model class name, e.g. 'LeaveRequest'"
    )
    trigger_event = models.CharField(
        max_length=30, choices=TriggerEvent.choices, default=TriggerEvent.ON_SUBMIT
    )
    is_active = models.BooleanField(default=True)

    # Global conditions evaluated BEFORE starting workflow
    conditions = models.JSONField(
        default=dict, help_text='{"amount__gte": 5000, "department_id": 3}'
    )

    # Visual designer canvas layout (stored as JSON)
    canvas_layout = models.JSONField(
        default=dict, help_text="Stores node positions for visual designer"
    )

    # Notification channels
    notify_email = models.BooleanField(default=True)
    notify_whatsapp = models.BooleanField(default=False)
    notify_in_app = models.BooleanField(default=True)

    class Meta:
        db_table = "workflow_definitions"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.trigger_model})"


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW STEP  (one node in the approval graph)
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowStep(models.Model):

    class StepType(models.TextChoices):
        APPROVAL = "approval", "Approval"
        NOTIFICATION = "notification", "Send Notification"
        CONDITION = "condition", "Condition (Branch)"
        ACTION = "action", "Auto Action"

    class ApproverType(models.TextChoices):
        USER = "user", "Specific User"
        ROLE = "role", "By Role"
        MANAGER = "manager", "Direct Manager"
        DEPARTMENT_HEAD = "department_head", "Department Head"
        DYNAMIC = "dynamic", "Dynamic (from record field)"

    class EscalationAction(models.TextChoices):
        NOTIFY = "notify", "Notify Again"
        REASSIGN = "reassign", "Reassign to Backup Approver"
        AUTO_APPROVE = "auto_approve", "Auto-Approve"
        AUTO_REJECT = "auto_reject", "Auto-Reject"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        WorkflowDefinition, on_delete=models.CASCADE, related_name="steps"
    )
    name = models.CharField(max_length=200)
    step_order = models.PositiveSmallIntegerField()
    step_type = models.CharField(
        max_length=20, choices=StepType.choices, default=StepType.APPROVAL
    )

    # ── Approver config ───────────────────────────────────────────────────────
    approver_type = models.CharField(
        max_length=20,
        choices=ApproverType.choices,
        blank=True,
        default=ApproverType.USER,
    )
    approver_user = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workflow_approver_steps",
    )
    approver_role = models.CharField(max_length=50, blank=True)
    approver_field = models.CharField(
        max_length=100,
        blank=True,
        help_text="Field on the document to use as approver, e.g. 'manager'",
    )

    # ── Conditional routing ───────────────────────────────────────────────────
    # When step_type=condition, these rules decide which branch to take
    condition_rules = models.JSONField(
        default=list,
        help_text='[{"field":"amount","operator":"gte","value":10000,"next_step_order":3}]',
    )

    # ── Amount condition ──────────────────────────────────────────────────────
    min_amount = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    max_amount = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )

    # ── Department / Branch scoping ───────────────────────────────────────────
    department = models.ForeignKey(
        "company.Department", null=True, blank=True, on_delete=models.SET_NULL
    )
    branch = models.ForeignKey(
        "company.Branch", null=True, blank=True, on_delete=models.SET_NULL
    )

    # ── Escalation ────────────────────────────────────────────────────────────
    escalation_enabled = models.BooleanField(default=False)
    escalation_hours = models.PositiveIntegerField(
        default=24, help_text="Trigger escalation after N hours of inactivity"
    )
    escalation_action = models.CharField(
        max_length=20, choices=EscalationAction.choices, default=EscalationAction.NOTIFY
    )
    escalation_to = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workflow_escalation_steps",
        help_text="Reassign to this user on escalation",
    )

    # ── Step metadata ─────────────────────────────────────────────────────────
    is_required = models.BooleanField(default=True)
    action_config = models.JSONField(default=dict)

    # Visual designer position
    canvas_x = models.IntegerField(default=0)
    canvas_y = models.IntegerField(default=0)

    class Meta:
        db_table = "workflow_steps"
        ordering = ["step_order"]

    def __str__(self):
        return f"[{self.step_order}] {self.name}"


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW INSTANCE  (one running execution per document)
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowInstance(CompanyScoped):

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        IN_PROGRESS = "in_progress", _("In Progress")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        ESCALATED = "escalated", _("Escalated")
        CANCELLED = "cancelled", _("Cancelled")

    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.PROTECT)
    current_step = models.ForeignKey(
        WorkflowStep,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_instances",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=100)
    related_object = GenericForeignKey("content_type", "object_id")

    initiated_by = models.ForeignKey(
        "authentication.User",
        on_delete=models.PROTECT,
        related_name="initiated_workflows",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    current_step_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the current step was assigned — used for escalation timing",
    )

    class Meta:
        db_table = "workflow_instances"
        ordering = ["-created_at"]

    def __str__(self):
        return f"WF-{str(self.id)[:8]} [{self.status}]"


# ══════════════════════════════════════════════════════════════════════════════
# WORKFLOW ACTION  (log of every approval/rejection/delegation)
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowAction(CompanyScoped):

    class Action(models.TextChoices):
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")
        DELEGATED = "delegated", _("Delegated")
        ESCALATED = "escalated", _("Escalated")
        RETURNED = "returned", _("Returned for Clarification")
        NOTED = "noted", _("Noted (FYI)")

    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, related_name="actions"
    )
    step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT)
    actor = models.ForeignKey(
        "authentication.User",
        on_delete=models.PROTECT,
        related_name="workflow_actions_taken",
    )
    action = models.CharField(max_length=15, choices=Action.choices)
    comment = models.TextField(blank=True)
    acted_at = models.DateTimeField(auto_now_add=True)

    # Delegation fields
    delegated_to = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workflow_delegated_to",
    )

    # Attachment / evidence
    attachment = models.FileField(
        upload_to="workflow/attachments/", null=True, blank=True
    )

    class Meta:
        db_table = "workflow_actions"
        ordering = ["acted_at"]

    def __str__(self):
        return f"{self.actor} → {self.action} on {self.instance}"


# ══════════════════════════════════════════════════════════════════════════════
# APPROVAL DELEGATION
# ══════════════════════════════════════════════════════════════════════════════


class ApprovalDelegation(CompanyScoped):
    delegator = models.ForeignKey(
        "authentication.User", on_delete=models.CASCADE, related_name="delegations_made"
    )
    delegatee = models.ForeignKey(
        "authentication.User",
        on_delete=models.CASCADE,
        related_name="delegations_received",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    # Optional: limit delegation to specific workflow definitions
    workflow = models.ForeignKey(
        WorkflowDefinition,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="If set, only delegates for this specific workflow",
    )

    class Meta:
        db_table = "workflow_delegations"
        ordering = ["-start_date"]

    def __str__(self):
        return (
            f"{self.delegator} → {self.delegatee} ({self.start_date} – {self.end_date})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION TEMPLATE  (per-step email/WhatsApp templates)
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowNotificationTemplate(models.Model):

    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        SMS = "sms", "SMS"
        IN_APP = "in_app", "In-App"

    class Event(models.TextChoices):
        STEP_ASSIGNED = "step_assigned", "Step Assigned (Pending Approval)"
        APPROVED = "approved", "Workflow Approved"
        REJECTED = "rejected", "Workflow Rejected"
        ESCALATED = "escalated", "Escalation Triggered"
        DELEGATED = "delegated", "Step Delegated"
        REMINDER = "reminder", "Reminder"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.ForeignKey(
        WorkflowDefinition,
        on_delete=models.CASCADE,
        related_name="notification_templates",
        null=True,
        blank=True,
    )
    step = models.ForeignKey(
        WorkflowStep,
        on_delete=models.CASCADE,
        related_name="notification_templates",
        null=True,
        blank=True,
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    event = models.CharField(max_length=30, choices=Event.choices)

    # Template supports Django-style variables: {{ document }}, {{ approver }}, {{ submitter }}
    subject = models.CharField(max_length=255, blank=True)
    body = models.TextField(
        help_text="Use {{ document }}, {{ approver }}, {{ submitter }}, {{ company }}, {{ approve_url }}, {{ reject_url }}"
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "workflow_notification_templates"

    def __str__(self):
        return f"{self.channel} / {self.event}"


# ══════════════════════════════════════════════════════════════════════════════
# ESCALATION LOG
# ══════════════════════════════════════════════════════════════════════════════


class WorkflowEscalationLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(
        WorkflowInstance, on_delete=models.CASCADE, related_name="escalation_logs"
    )
    step = models.ForeignKey(WorkflowStep, on_delete=models.PROTECT)
    escalated_at = models.DateTimeField(auto_now_add=True)
    action_taken = models.CharField(max_length=20)
    escalated_to = models.ForeignKey(
        "authentication.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "workflow_escalation_logs"
        ordering = ["-escalated_at"]
