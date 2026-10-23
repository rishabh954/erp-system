from datetime import date
from decimal import Decimal

import pytest

from apps.assets.models import Asset, AssetCategory, DepreciationEntry
from apps.company.models import Company


def make_asset(company, category, name):
    return Asset.objects.create(
        company=company,
        category=category,
        name=name,
        purchase_date=date.today(),
        purchase_cost=Decimal("1200.00"),
        salvage_value=Decimal("0.00"),
        useful_life_years=10,
        current_value=Decimal("1200.00"),
    )


@pytest.mark.django_db
def test_depreciation_task_is_company_scoped_and_idempotent():
    from apps.assets.tasks import process_depreciation

    company_a = Company.objects.create(name="Assets A")
    company_b = Company.objects.create(name="Assets B")
    category_a = AssetCategory.objects.create(company=company_a, name="Equipment")
    category_b = AssetCategory.objects.create(company=company_b, name="Equipment")
    asset_a = make_asset(company_a, category_a, "Asset A")
    asset_b = make_asset(company_b, category_b, "Asset B")

    assert process_depreciation.run() == 2
    assert process_depreciation.run() == 0

    asset_a.refresh_from_db()
    asset_b.refresh_from_db()
    assert asset_a.current_value == Decimal("1190.00")
    assert asset_a.accumulated_depreciation == Decimal("10.00")
    assert asset_b.current_value == Decimal("1190.00")
    assert DepreciationEntry.objects.filter(
        company=company_a, asset=asset_a
    ).count() == 1
    assert DepreciationEntry.objects.filter(
        company=company_b, asset=asset_b
    ).count() == 1
