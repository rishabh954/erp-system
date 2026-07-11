
import re

import pytest

from apps.authentication.models import User
from apps.company.models import Company
from apps.sales.models import Invoice
from core.services import BaseService


@pytest.mark.django_db
class TestSequenceMixin:
    @pytest.fixture
    def setup_data(self):
        company = Company.objects.create(name="Sequence Test Company")
        user = User.objects.create_superuser("seq@test.com", "pass", first_name="Seq", last_name="User", primary_company=company)  # noqa: E501
        from apps.crm.models import Customer
        customer = Customer.objects.create(name="Cust", company=company)
        return {"company": company, "user": user, "customer": customer}

    def test_sequence_sorting(self, setup_data):
        """generate_sequence_number always increments from the highest existing number
        and uses 5-digit zero-padding (INV-00001 format)."""
        company = setup_data["company"]
        customer = setup_data["customer"]
        user = setup_data["user"]

        from django.utils import timezone
        today = timezone.localdate()

        # Seed: INV-00001
        inv1 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)  # noqa: E501
        inv1.number = "INV-00001"
        inv1.save()

        # Seed: INV-09999
        inv9999 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)  # noqa: E501
        inv9999.number = "INV-09999"
        inv9999.save()

        # Next should be INV-10000
        generated_num = BaseService.generate_sequence_number("INV", Invoice, company.pk)
        assert generated_num == "INV-10000"

        inv10000 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)  # noqa: E501
        inv10000.number = generated_num
        inv10000.save()

        # And after that INV-10001
        next_num = BaseService.generate_sequence_number("INV", Invoice, company.pk)
        assert next_num == "INV-10001"


@pytest.mark.django_db
def test_document_number_format_consistency(company, user):
    """All document modules must produce numbers in PREFIX-NNNNN (5-digit) format."""
    # 5-digit pattern: prefix chars + hyphen + exactly 5 digits
    pattern = re.compile(r"^[A-Z][A-Z0-9\-]+-\d{5}$")

    test_cases = [
        ("INV", Invoice),
    ]

    for prefix, model_class in test_cases:
        num = BaseService.generate_sequence_number(prefix, model_class, company.pk)
        assert pattern.match(num), (
            f"Number '{num}' for {model_class.__name__} does not match expected "
            f"format PREFIX-NNNNN (5 digits). All modules must use consistent padding."
        )

