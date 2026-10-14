import pytest

from apps.helpdesk.models import Ticket, TicketCategory
from apps.helpdesk.services import TicketService


@pytest.fixture
def ticket_category(db, company):
    return TicketCategory.objects.create(
        company=company, name="General Support", sla_hours=24
    )


@pytest.fixture
def helpdesk_services(db, company, user):
    return {
        "ticket_service": TicketService(company=company),
        "company": company,
        "user": user,
    }


@pytest.mark.django_db
def test_ticket_service_create(helpdesk_services, ticket_category):
    service = helpdesk_services["ticket_service"]
    user = helpdesk_services["user"]

    data = {
        "title": "Test Ticket",
        "description": "I have a problem",
        "category": ticket_category.pk,
    }

    ticket = service.create_ticket(data, user)
    assert ticket.pk is not None
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.title == "Test Ticket"
    assert ticket.requester == user
    assert ticket.number is not None


@pytest.mark.django_db
def test_ticket_service_rejects_other_company_category(company, user):
    from apps.company.models import Company, Currency

    currency, _ = Currency.objects.get_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$"},
    )
    other = Company.objects.create(
        name="Other Helpdesk Co",
        legal_name="Other Helpdesk Co Ltd",
        company_type="LLC",
        fiscal_year_start="01-01",
        default_currency=currency,
    )
    foreign_category = TicketCategory.objects.create(
        company=other, name="Foreign", sla_hours=8
    )
    service = TicketService(company=company)
    with pytest.raises(ValueError, match="category"):
        service.create_ticket(
            {
                "title": "Cross tenant",
                "description": "Should fail",
                "category": foreign_category.pk,
            },
            user,
        )


@pytest.mark.django_db
def test_ticket_service_assign_and_comment(helpdesk_services, ticket_category):
    service = helpdesk_services["ticket_service"]
    user = helpdesk_services["user"]

    # Create ticket
    ticket = service.create_ticket({"title": "T1", "description": "D1"}, user)

    # Assign ticket
    assigned = service.assign_ticket(ticket, user, user)
    assert assigned.status == Ticket.Status.IN_PROGRESS
    assert assigned.assigned_to == user

    # Add comment
    reply = service.add_comment(ticket, user, "Looking into this", is_internal=False)
    assert reply.pk is not None
    assert reply.content == "Looking into this"


@pytest.mark.django_db
def test_ticket_service_resolve(helpdesk_services):
    service = helpdesk_services["ticket_service"]
    user = helpdesk_services["user"]

    ticket = service.create_ticket({"title": "T2", "description": "D2"}, user)

    resolved = service.resolve_ticket(ticket, user, "Fixed the issue")
    assert resolved.status == Ticket.Status.RESOLVED
    assert resolved.resolution == "Fixed the issue"
    assert resolved.resolved_at is not None
