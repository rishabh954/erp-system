import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from apps.authentication.models import UserCompany
from apps.crm.models import Customer
from core.api.fields import TenantScopedPrimaryKeyRelatedField
from core.factories import CompanyFactory, UserFactory


@pytest.mark.django_db
def test_related_primary_key_field_rejects_other_company_object():
    company_a = CompanyFactory()
    company_b = CompanyFactory()
    user = UserFactory(primary_company=company_a)
    UserCompany.objects.create(user=user, company=company_a)
    local_customer = Customer.objects.create(company=company_a, name="Local")
    foreign_customer = Customer.objects.create(company=company_b, name="Foreign")

    request = APIRequestFactory().post("/api/v1/sales/invoices/")
    request.user = user
    request.META["HTTP_X_ACTIVE_COMPANY"] = str(company_a.pk)
    relation = TenantScopedPrimaryKeyRelatedField(queryset=Customer.objects.all())
    relation._context = {"request": request}

    assert relation.to_internal_value(local_customer.pk) == local_customer
    with pytest.raises(ValidationError):
        relation.to_internal_value(foreign_customer.pk)
