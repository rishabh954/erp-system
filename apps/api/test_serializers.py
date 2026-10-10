import pytest
from django.test import RequestFactory
from rest_framework.exceptions import ValidationError

from apps.api.serializers import ErpSalesOrderSerializer
from apps.authentication.models import User, UserCompany
from apps.crm.models import Customer
from apps.company.models import Company

pytestmark = pytest.mark.django_db


def test_sales_order_serializer_rejects_customer_from_another_company():
    company_a = Company.objects.create(name="Serializer Tenant A")
    company_b = Company.objects.create(name="Serializer Tenant B")
    user = User.objects.create_user(
        email="serializer-tenant-a@example.com",
        password="test-password",
        role=User.Role.COMPANY_ADMIN,
        primary_company=company_a,
    )
    UserCompany.objects.create(
        user=user,
        company=company_a,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    customer_a = Customer.objects.create(company=company_a, name="Tenant A Customer")
    customer_b = Customer.objects.create(company=company_b, name="Tenant B Customer")

    request = RequestFactory().post("/api/v1/sales/orders/")
    request.user = user
    request.session = {}
    serializer = ErpSalesOrderSerializer(context={"request": request})

    assert serializer.fields["customer"].run_validation(customer_a.pk) == customer_a
    with pytest.raises(ValidationError):
        serializer.fields["customer"].run_validation(customer_b.pk)
