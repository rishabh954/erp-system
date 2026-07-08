from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import CompanyScoped, NotesMixin, SequenceMixin

# ═══════════════════════════════ HELP DESK ════════════════════════════════════


class TicketCategory(CompanyScoped):
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sla_hours = models.PositiveSmallIntegerField(default=24)
    auto_assign_to = models.ForeignKey(
        "authentication.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "helpdesk_categories"

    def __str__(self):
        return self.name


class Ticket(CompanyScoped, SequenceMixin, NotesMixin):
    class Status(models.TextChoices):
        OPEN = "open", _("Open")
        IN_PROGRESS = "in_progress", _("In Progress")
        PENDING = "pending", _("Pending Customer")
        RESOLVED = "resolved", _("Resolved")
        CLOSED = "closed", _("Closed")
        REOPENED = "reopened", _("Reopened")

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        CRITICAL = "critical", _("Critical")

    class Source(models.TextChoices):
        EMAIL = "email", _("Email")
        PORTAL = "portal", _("Customer Portal")
        PHONE = "phone", _("Phone")
        CHAT = "chat", _("Live Chat")
        INTERNAL = "internal", _("Internal")

    title = models.CharField(max_length=500)
    description = models.TextField()
    category = models.ForeignKey(
        TicketCategory, null=True, blank=True, on_delete=models.SET_NULL
    )
    customer = models.ForeignKey(
        "crm.Customer", null=True, blank=True, on_delete=models.SET_NULL
    )
    requester = models.ForeignKey(
        "authentication.User",
        on_delete=models.PROTECT,
        related_name="submitted_tickets",
    )
    assigned_to = models.ForeignKey(
        "authentication.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    priority = models.CharField(
        max_length=10, choices=Priority.choices, default=Priority.MEDIUM
    )
    source = models.CharField(
        max_length=15, choices=Source.choices, default=Source.PORTAL
    )
    sla_due_at = models.DateTimeField(null=True, blank=True)
    sla_breached = models.BooleanField(default=False)
    first_response_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True)
    satisfaction_rating = models.PositiveSmallIntegerField(null=True, blank=True)
    tags = models.JSONField(default=list)

    class Meta:
        db_table = "helpdesk_tickets"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "status", "priority"]),
        ]

    def __str__(self):
        return f"{self.number} | {self.title}"


class TicketReply(CompanyScoped):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="replies")
    author = models.ForeignKey("authentication.User", on_delete=models.CASCADE)
    content = models.TextField()
    is_internal = models.BooleanField(default=False)
    attachment = models.FileField(upload_to="tickets/", null=True, blank=True)

    class Meta:
        db_table = "helpdesk_replies"
        ordering = ["created_at"]


class KnowledgeBaseArticle(CompanyScoped):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        ARCHIVED = "archived", _("Archived")

    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=500)
    content = models.TextField()
    category = models.ForeignKey(
        TicketCategory, null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    author = models.ForeignKey("authentication.User", on_delete=models.PROTECT)
    views = models.PositiveIntegerField(default=0)
    helpful_votes = models.PositiveIntegerField(default=0)
    tags = models.JSONField(default=list)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "helpdesk_kb_articles"
        unique_together = ("company", "slug")
