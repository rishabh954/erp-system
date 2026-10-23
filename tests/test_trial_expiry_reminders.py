from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.authentication.models import User, UserCompany
from apps.company.models import Company


@pytest.mark.django_db
def test_trial_expiry_reminders_skip_revoked_company_admin_memberships():
    from apps.company.tasks import send_trial_expiry_reminders
    from apps.notifications.tasks import send_email_task

    company = Company.objects.create(
        name="Trial company",
        status=Company.Status.TRIAL,
        trial_ends_at=timezone.now() + timedelta(days=2),
    )
    active_admin = User.objects.create_user(
        email="active-admin@example.com",
        password="password",
        first_name="Active",
        last_name="Admin",
        role=User.Role.COMPANY_ADMIN,
    )
    revoked_admin = User.objects.create_user(
        email="revoked-admin@example.com",
        password="password",
        first_name="Revoked",
        last_name="Admin",
        role=User.Role.COMPANY_ADMIN,
    )
    UserCompany.objects.create(
        user=active_admin,
        company=company,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    UserCompany.objects.create(
        user=revoked_admin,
        company=company,
        role=User.Role.COMPANY_ADMIN,
        is_active=False,
    )

    with patch.object(send_email_task, "delay") as enqueue_email:
        send_trial_expiry_reminders.run()

    enqueue_email.assert_called_once()
    assert enqueue_email.call_args.kwargs["to_email"] == active_admin.email
    assert enqueue_email.call_args.kwargs["company_id"] == str(company.pk)
