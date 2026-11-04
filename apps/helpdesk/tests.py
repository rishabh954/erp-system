import pytest
from django.urls import reverse

from apps.authentication.models import User, UserCompany
from apps.helpdesk.models import Ticket, TicketCategory, TicketReply
from apps.helpdesk.services import TicketService
from core.factories import CompanyFactory, UserFactory


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
@pytest.mark.parametrize(
    "data",
    [
        {"title": "   ", "description": "Description"},
        {"title": "Valid title", "description": "  "},
        {"title": "Bad choice", "description": "Description", "priority": "urgent?"},
    ],
)
def test_ticket_service_rejects_invalid_data_without_writes(company, user, data):
    service = TicketService(company=company)
    before = Ticket.objects.filter(company=company).count()

    with pytest.raises(ValueError):
        service.create_ticket(data, user)

    assert Ticket.objects.filter(company=company).count() == before


@pytest.mark.django_db
def test_helpdesk_create_rejects_invalid_choice_without_writes(client, user, company):
    client.force_login(user)
    before = Ticket.objects.filter(company=company).count()

    response = client.post(
        reverse("helpdesk:ticket_create"),
        {"title": "Invalid priority", "description": "Issue", "priority": "urgent?"},
    )

    assert response.status_code == 302
    assert Ticket.objects.filter(company=company).count() == before


@pytest.mark.django_db
def test_helpdesk_create_rejects_foreign_category_without_writes(
    client, user, company
):
    client.force_login(user)
    other_company = CompanyFactory()
    foreign_category = TicketCategory.objects.create(
        company=other_company, name="Foreign", sla_hours=8
    )
    before = Ticket.objects.filter(company=company).count()

    response = client.post(
        reverse("helpdesk:ticket_create"),
        {
            "title": "Cross-company",
            "description": "Issue",
            "category": str(foreign_category.pk),
        },
    )

    assert response.status_code == 404
    assert Ticket.objects.filter(company=company).count() == before


@pytest.mark.django_db
def test_helpdesk_reply_rejects_foreign_assignee_without_partial_write(
    client, user, company, ticket_category
):
    client.force_login(user)
    ticket = TicketService(company=company).create_ticket(
        {"title": "Existing", "description": "Issue", "category": ticket_category.pk},
        user,
    )
    other_company = CompanyFactory()
    foreign_user = UserFactory(primary_company=other_company)
    UserCompany.objects.create(
        user=foreign_user,
        company=other_company,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    before = TicketReply.objects.filter(ticket=ticket).count()
    old_status = ticket.status

    response = client.post(
        reverse("helpdesk:ticket_reply", kwargs={"pk": ticket.pk}),
        {"content": "Should not persist", "assigned_to": str(foreign_user.pk)},
    )

    ticket.refresh_from_db()
    assert response.status_code == 302
    assert TicketReply.objects.filter(ticket=ticket).count() == before
    assert ticket.status == old_status
    assert ticket.assigned_to is None


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
