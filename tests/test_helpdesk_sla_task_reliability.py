from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company
from apps.helpdesk.models import Ticket
from core.factories import UserFactory


@pytest.mark.django_db
def test_sla_breach_task_is_idempotent_and_notifies_only_ticket_company(
    company, user, django_capture_on_commit_callbacks
):
    from apps.helpdesk.tasks import check_sla_breaches
    from apps.notifications.tasks import send_bulk_notification

    company_b = Company.objects.create(name="Helpdesk B")
    user_b = UserFactory(primary_company=company_b, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.create(
        user=user_b, company=company_b, role=User.Role.COMPANY_ADMIN
    )
    due_at = timezone.now() - timedelta(hours=1)
    ticket_a = Ticket.objects.create(
        company=company,
        requester=user,
        assigned_to=user_b,
        title="Tenant A ticket",
        description="SLA expired",
        sla_due_at=due_at,
    )
    ticket_b = Ticket.objects.create(
        company=company_b,
        requester=user_b,
        title="Tenant B ticket",
        description="SLA expired",
        sla_due_at=due_at,
    )

    with patch.object(send_bulk_notification, "delay") as enqueue:
        with django_capture_on_commit_callbacks(execute=True):
            assert check_sla_breaches.run() == 2
        assert check_sla_breaches.run() == 0

    ticket_a.refresh_from_db()
    ticket_b.refresh_from_db()
    assert ticket_a.sla_breached and ticket_b.sla_breached
    assert enqueue.call_count == 2
    notifications = {call.kwargs["company_id"]: call.kwargs for call in enqueue.call_args_list}
    assert notifications[str(company.pk)]["recipient_ids"] == [str(user.pk)]
    assert notifications[str(company_b.pk)]["recipient_ids"] == [str(user_b.pk)]
