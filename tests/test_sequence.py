import pytest
import concurrent.futures
from django.db import transaction
from apps.sales.models import Invoice
from apps.company.models import Company
from apps.authentication.models import User

@pytest.mark.django_db
class TestSequenceMixin:
    @pytest.fixture
    def setup_data(self):
        company = Company.objects.create(name="Sequence Test Company")
        user = User.objects.create_superuser("seq@test.com", "pass", first_name="Seq", last_name="User", primary_company=company)
        from apps.crm.models import Customer
        customer = Customer.objects.create(name="Cust", company=company)
        return {"company": company, "user": user, "customer": customer}

    def test_sequence_sorting(self, setup_data):
        company = setup_data["company"]
        customer = setup_data["customer"]
        user = setup_data["user"]
        
        from django.utils import timezone
        today = timezone.localdate()

        # Create INV-0001
        inv1 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)
        inv1.number = "INV-0001"
        inv1.save()

        # Create INV-9999
        inv9999 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)
        inv9999.number = "INV-9999"
        inv9999.save()
        
        # Test generation uses INV-10000
        inv10000 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)
        # Using a fresh Invoice instance to call generate_number since it's an instance method
        generated_num = inv10000.generate_number("INV", Invoice)
        assert generated_num == "INV-10000"

        inv10000.number = generated_num
        inv10000.save()

        # Ensure next one is INV-10001
        inv10001 = Invoice(company=company, customer=customer, created_by=user, updated_by=user, invoice_date=today, due_date=today)
        assert inv10001.generate_number("INV", Invoice) == "INV-10001"

