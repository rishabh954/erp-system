import pytest

from apps.company.models import Company
from apps.manufacturing.models import MaterialPlan
from apps.manufacturing.services import MRPService


@pytest.mark.django_db
def test_mrp_service_rejects_a_plan_from_another_company(company):
    other_company = Company.objects.create(name="Other MRP tenant")
    plan = MaterialPlan.objects.create(
        company=company,
        name="Tenant plan",
        target_date="2026-10-23",
    )

    with pytest.raises(ValueError, match="not found for this company"):
        MRPService.run_mrp(plan.pk, company_id=other_company.pk)

    plan.refresh_from_db()
    assert plan.status == MaterialPlan.Status.DRAFT
