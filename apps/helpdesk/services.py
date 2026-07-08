from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.helpdesk.models import Ticket, TicketReply
from core.services import BaseService


class TicketService(BaseService):
    @transaction.atomic
    def create_ticket(self, data, user):
        """Creates a new helpdesk ticket."""
        category_id = data.get("category")

        ticket = Ticket(
            company=self.company,
            title=data["title"],
            description=data["description"],
            category_id=category_id,
            customer_id=data.get("customer"),
            requester=user,
            priority=data.get("priority", Ticket.Priority.MEDIUM),
            source=data.get("source", Ticket.Source.PORTAL),
            status=Ticket.Status.OPEN,
        )

        if category_id:
            from apps.helpdesk.models import TicketCategory

            category = TicketCategory.objects.get(pk=category_id)
            if category.auto_assign_to:
                ticket.assigned_to = category.auto_assign_to
            ticket.sla_due_at = timezone.now() + timedelta(hours=category.sla_hours)

        ticket.number = BaseService.generate_sequence_number(
            "TKT", Ticket, self.company.pk
        )
        ticket.save()

        self.log_activity(
            action="created",
            module="helpdesk",
            resource_type="Ticket",
            resource_id=ticket.pk,
            description=f"Ticket {ticket.number} created by {user.get_full_name() if hasattr(user, 'get_full_name') else user.email}",
        )
        return ticket

    @transaction.atomic
    def assign_ticket(self, ticket, user, assigned_to):
        """Assigns a ticket to a user."""
        ticket.assigned_to = assigned_to
        if ticket.status == Ticket.Status.OPEN:
            ticket.status = Ticket.Status.IN_PROGRESS
        ticket.save(update_fields=["assigned_to", "status"])

        self.log_activity(
            action="assigned",
            module="helpdesk",
            resource_type="Ticket",
            resource_id=ticket.pk,
            description=f"Ticket {ticket.number} assigned to {assigned_to.get_full_name() if hasattr(assigned_to, 'get_full_name') else assigned_to.email} by {user.get_full_name() if hasattr(user, 'get_full_name') else user.email}",
        )

        from apps.notifications.tasks import send_bulk_notification

        send_bulk_notification.delay(
            recipient_ids=[assigned_to.pk],
            title="Ticket Assigned",
            message=f"Ticket {ticket.number} has been assigned to you.",
            notification_type="info",
            company_id=str(self.company.pk),
        )

        return ticket

    @transaction.atomic
    def add_comment(self, ticket, user, content, is_internal=False):
        """Adds a reply/comment to a ticket."""
        reply = TicketReply.objects.create(
            company=self.company,
            ticket=ticket,
            author=user,
            content=content,
            is_internal=is_internal,
        )

        if (
            not ticket.first_response_at
            and not is_internal
            and user != ticket.requester
        ):
            ticket.first_response_at = timezone.now()
            ticket.save(update_fields=["first_response_at"])

        if user == ticket.requester and ticket.status == Ticket.Status.PENDING:
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.save(update_fields=["status"])

        return reply

    @transaction.atomic
    def resolve_ticket(self, ticket, user, resolution):
        """Resolves a ticket."""
        ticket.status = Ticket.Status.RESOLVED
        ticket.resolution = resolution
        ticket.resolved_at = timezone.now()
        ticket.save(update_fields=["status", "resolution", "resolved_at"])

        self.log_activity(
            action="resolved",
            module="helpdesk",
            resource_type="Ticket",
            resource_id=ticket.pk,
            description=f"Ticket {ticket.number} resolved by {user.get_full_name() if hasattr(user, 'get_full_name') else user.email}",
        )
        return ticket
