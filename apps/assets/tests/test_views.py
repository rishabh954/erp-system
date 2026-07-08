from datetime import date

import pytest
from django.urls import reverse

from apps.assets.models import Asset

pytestmark = pytest.mark.django_db


def test_asset_crud(client, user, company):
    client.force_login(user)

    # Create
    create_url = reverse("assets:create")
    res = client.post(
        create_url,
        {
            "name": "Test Asset CRUD",
            "asset_type": Asset.Type.EQUIPMENT,
            "purchase_date": str(date.today()),
            "purchase_price": "1000.00",
            "status": Asset.Status.ACTIVE,
        },
    )
    assert res.status_code == 302
    asset = Asset.objects.filter(name="Test Asset CRUD").first()
    assert asset is not None

    # Read Detail
    detail_url = reverse("assets:detail", kwargs={"pk": asset.pk})
    res = client.get(detail_url)
    assert res.status_code == 200

    # List
    list_url = reverse("assets:list")
    res = client.get(list_url)
    assert res.status_code == 200
    assert asset in res.context["object_list"]
