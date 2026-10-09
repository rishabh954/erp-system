import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.administration.models import SystemSetting
from apps.company.models import SequenceCounter
from apps.crm.models import Customer, Lead
from apps.sales.models import Coupon, DiscountRule, ProductBundle
from core.factories import CompanyFactory
from core.services import BaseService

pytestmark = pytest.mark.django_db


def test_coupon_and_bundle_codes_are_unique_per_company(company):
    other_company = CompanyFactory()
    rule_a = DiscountRule.objects.create(
        company=company,
        name="Rule A",
        discount_type=DiscountRule.DiscountType.FIXED,
        value=10,
    )
    rule_b = DiscountRule.objects.create(
        company=other_company,
        name="Rule B",
        discount_type=DiscountRule.DiscountType.FIXED,
        value=10,
    )
    Coupon.objects.create(company=company, discount_rule=rule_a, code="SPRING")
    Coupon.objects.create(
        company=other_company, discount_rule=rule_b, code="SPRING"
    )
    ProductBundle.objects.create(company=company, name="A", code="KIT")
    ProductBundle.objects.create(company=other_company, name="B", code="KIT")

    with pytest.raises(IntegrityError), transaction.atomic():
        Coupon.objects.create(company=company, discount_rule=rule_a, code="SPRING")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductBundle.objects.create(company=company, name="Duplicate", code="KIT")


def test_sequence_uses_numeric_suffix_and_reserves_counter(company):
    Lead.objects.create(company=company, name="Nine", number="DOC-9")
    Lead.objects.create(company=company, name="Ten", number="DOC-10")

    assert BaseService.generate_sequence_number("DOC", Lead, company.pk) == "DOC-00011"
    assert BaseService.generate_sequence_number("DOC", Lead, company.pk) == "DOC-00012"
    counter = SequenceCounter.objects.get(company=company, prefix="DOC")
    assert counter.last_value == 12


def test_leads_and_customers_receive_company_unique_identifiers(company):
    other_company = CompanyFactory()
    lead_a = Lead.objects.create(company=company, name="A")
    lead_b = Lead.objects.create(company=company, name="B")
    lead_other = Lead.objects.create(company=other_company, name="Other")
    customer_a = Customer.objects.create(company=company, name="Customer A")
    customer_b = Customer.objects.create(company=company, name="Customer B")
    customer_other = Customer.objects.create(
        company=other_company, name="Other Customer"
    )

    assert lead_a.number != lead_b.number
    assert lead_a.number == lead_other.number
    assert customer_a.customer_code != customer_b.customer_code
    assert customer_a.customer_code == customer_other.customer_code


def test_system_settings_are_scoped_to_the_active_company(client, user, company):
    other_company = CompanyFactory()
    setting_a = SystemSetting.objects.create(
        company=company, key="company_theme", value="blue"
    )
    setting_b = SystemSetting.objects.create(
        company=other_company, key="company_theme", value="green"
    )
    client.force_login(user)
    session = client.session
    session["active_company_id"] = str(company.pk)
    session.save()

    response = client.get(reverse("administration:system_settings"))
    assert response.status_code == 200
    assert b"blue" in response.content
    assert b"green" not in response.content

    response = client.post(
        reverse("administration:system_settings"),
        {"action": "update", "setting_company_theme": "red"},
    )
    assert response.status_code == 302
    setting_a.refresh_from_db()
    setting_b.refresh_from_db()
    assert setting_a.value == "red"
    assert setting_b.value == "green"
    assert SystemSetting.get("company_theme", company=company) == "red"
    assert SystemSetting.get("company_theme", company=other_company) == "green"
