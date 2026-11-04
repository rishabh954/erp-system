from datetime import date
from decimal import Decimal

import pytest
from django.http import QueryDict

from apps.inventory.models import Product
from apps.purchase.models import (
    Bill,
    GoodsReceipt,
    GoodsReceiptLine,
    Payment,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    Vendor,
)
from apps.purchase.services import (
    PaymentService,
    PurchaseOrderService,
    PurchaseRequestService,
)
from core.factories import CompanyFactory


def form_data(**values):
    data = QueryDict("", mutable=True)
    for key, value in values.items():
        if isinstance(value, list):
            data.setlist(key, [str(item) for item in value])
        else:
            data[key] = str(value)
    return data


def request_data(**overrides):
    values = {
        "title": "Office supplies",
        "priority": "high",
        "product[]": [""],
        "description[]": ["Paper"],
        "quantity[]": ["2"],
        "estimated_unit_price[]": ["3.25"],
    }
    values.update(overrides)
    return form_data(**values)


def order_data(vendor_obj, warehouse_obj, product_obj, **overrides):
    values = {
        "vendor": vendor_obj.pk,
        "warehouse": warehouse_obj.pk,
        "order_date": "2026-11-04",
        "payment_terms": "30",
        "product[]": [product_obj.pk],
        "description[]": ["Paper"],
        "quantity[]": ["2"],
        "unit_price[]": ["3.25"],
        "discount_percent[]": ["0"],
        "tax[]": [""],
    }
    values.update(overrides)
    return form_data(**values)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"title": "   "}, "title is required"),
        ({"priority": "urgent-ish"}, "valid purchase request priority"),
        ({"quantity[]": ["not-a-number"]}, "valid number"),
        ({"quantity[]": ["0"]}, "at least"),
        ({"estimated_unit_price[]": [""]}, "required"),
    ],
)
def test_purchase_request_rejects_invalid_input_without_writes(
    company, user, overrides, error
):
    before = PurchaseRequest.objects.count()
    with pytest.raises(ValueError, match=error):
        PurchaseRequestService(company=company, user=user).create_request(
            request_data(**overrides), user
        )
    assert PurchaseRequest.objects.count() == before
    assert PurchaseRequestLine.objects.count() == 0


@pytest.mark.django_db
def test_purchase_request_rejects_foreign_product_without_writes(company, user):
    other_company = CompanyFactory()
    foreign_product = Product.objects.create(
        company=other_company, name="Foreign", sku="FOREIGN", product_type="stockable"
    )
    with pytest.raises(ValueError, match="product for this company"):
        PurchaseRequestService(company=company, user=user).create_request(
            request_data(**{"product[]": [foreign_product.pk]}), user
        )
    assert not PurchaseRequest.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_purchase_request_invalid_update_rolls_back_existing_header_and_lines(
    company, user, product
):
    request = PurchaseRequest.objects.create(
        company=company, title="Original", requested_by=user
    )
    line = PurchaseRequestLine.objects.create(
        request=request,
        product=product,
        description="Original line",
        quantity=Decimal("1"),
        estimated_unit_price=Decimal("2"),
        estimated_total=Decimal("2"),
    )
    with pytest.raises(ValueError, match="valid number"):
        PurchaseRequestService(company=company, user=user).update_request(
            request,
            request_data(title="Changed", **{"quantity[]": ["invalid"]}),
        )
    request.refresh_from_db()
    assert request.title == "Original"
    assert list(request.lines.values_list("pk", flat=True)) == [line.pk]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"vendor": ""}, "active vendor is required"),
        ({"order_date": "not-a-date"}, "valid order date"),
        ({"payment_terms": "30.5"}, "whole number"),
        ({"quantity[]": ["NaN"]}, "valid number"),
        ({"discount_percent[]": ["101"]}, "no more than"),
        ({"tax[]": ["not-a-tax"]}, "tax for this company"),
    ],
)
def test_purchase_order_rejects_invalid_input_without_writes(
    company, user, vendor, warehouse, product, overrides, error
):
    before = PurchaseOrder.objects.count()
    with pytest.raises(ValueError, match=error):
        PurchaseOrderService(company=company, user=user).create_order(
            order_data(vendor, warehouse, product, **overrides), user
        )
    assert PurchaseOrder.objects.count() == before
    assert PurchaseOrderLine.objects.count() == 0


@pytest.mark.django_db
def test_purchase_order_rejects_foreign_tenant_relations_without_writes(
    company, user, vendor, warehouse, product
):
    foreign_company = CompanyFactory()
    foreign_product = Product.objects.create(
        company=foreign_company,
        name="Foreign",
        sku="FOREIGN",
        product_type="stockable",
    )
    with pytest.raises(ValueError, match="product for this company"):
        PurchaseOrderService(company=company, user=user).create_order(
            order_data(vendor, warehouse, product, **{"product[]": [foreign_product.pk]}),
            user,
        )
    assert not PurchaseOrder.objects.filter(company=company).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("quantity", "error"),
    [
        (" ", "is required"),
        ("abc", "valid number"),
        ("-1", "at least"),
        ("1.00001", "decimal places"),
    ],
)
def test_goods_receipt_invalid_quantity_writes_nothing(
    company, user, vendor, warehouse, product, quantity, error
):
    order = PurchaseOrder.objects.create(
        company=company,
        vendor=vendor,
        order_date=date.today(),
        status=PurchaseOrder.Status.CONFIRMED,
    )
    line = PurchaseOrderLine.objects.create(
        purchase_order=order,
        product=product,
        description="Paper",
        quantity=Decimal("3"),
        unit_price=Decimal("2"),
    )
    with pytest.raises(ValueError, match=error):
        PurchaseOrderService(company=company, user=user).create_goods_receipt(
            order, form_data(warehouse=warehouse.pk, **{f"qty_{line.pk}": quantity}), user
        )
    assert not GoodsReceipt.objects.filter(company=company).exists()
    assert not GoodsReceiptLine.objects.exists()
    line.refresh_from_db()
    assert line.qty_received == 0


@pytest.mark.django_db
def test_goods_receipt_rejects_foreign_warehouse_without_writes(
    company, user, vendor, product
):
    from apps.inventory.models import Warehouse

    foreign_company = CompanyFactory()
    foreign_warehouse = Warehouse.objects.create(
        company=foreign_company, name="Foreign", code="FOREIGN"
    )
    order = PurchaseOrder.objects.create(
        company=company,
        vendor=vendor,
        order_date=date.today(),
        status=PurchaseOrder.Status.CONFIRMED,
    )
    line = PurchaseOrderLine.objects.create(
        purchase_order=order,
        product=product,
        description="Paper",
        quantity=Decimal("3"),
        unit_price=Decimal("2"),
    )
    with pytest.raises(ValueError, match="(?i)warehouse not found for this company"):
        PurchaseOrderService(company=company, user=user).create_goods_receipt(
            order,
            form_data(warehouse=foreign_warehouse.pk, **{f"qty_{line.pk}": "1"}),
            user,
        )
    assert not GoodsReceipt.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_goods_receipt_prevalidates_all_lines_before_any_stock_or_receipt_writes(
    company, user, vendor, warehouse, product
):
    order = PurchaseOrder.objects.create(
        company=company,
        vendor=vendor,
        order_date=date.today(),
        status=PurchaseOrder.Status.CONFIRMED,
    )
    first = PurchaseOrderLine.objects.create(
        purchase_order=order,
        product=product,
        description="First",
        quantity=Decimal("3"),
        unit_price=Decimal("2"),
    )
    second = PurchaseOrderLine.objects.create(
        purchase_order=order,
        product=product,
        description="Second",
        quantity=Decimal("3"),
        unit_price=Decimal("2"),
    )
    with pytest.raises(ValueError, match="valid number"):
        PurchaseOrderService(company=company, user=user).create_goods_receipt(
            order,
            form_data(
                warehouse=warehouse.pk,
                **{f"qty_{first.pk}": "1", f"qty_{second.pk}": "bad"},
            ),
            user,
        )
    assert not GoodsReceipt.objects.filter(company=company).exists()
    assert not GoodsReceiptLine.objects.exists()
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.qty_received == second.qty_received == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"amount": ""}, "required"),
        ({"amount": "NaN"}, "valid number"),
        ({"amount": "0"}, "greater than zero"),
        ({"amount": "101"}, "exceed the bill balance"),
        ({"method": "crypto"}, "valid payment method"),
        ({"payment_date": "not-a-date"}, "valid payment date"),
    ],
)
def test_vendor_payment_rejects_invalid_input_without_writes(
    company, vendor, user, overrides, error
):
    bill = Bill.objects.create(
        company=company,
        vendor=vendor,
        bill_date=date.today(),
        due_date=date.today(),
        total=Decimal("100"),
        balance_due=Decimal("100"),
    )
    Bill.objects.filter(pk=bill.pk).update(status=Bill.Status.OPEN)
    data = {"amount": "25", "method": "bank_transfer", "payment_date": "2026-11-04"}
    data.update(overrides)
    with pytest.raises(ValueError, match=error):
        PaymentService(company=company, user=user).record_vendor_payment(
            bill, form_data(**data)
        )
    assert Payment.objects.count() == 0
    bill.refresh_from_db()
    assert bill.balance_due == Decimal("100")


@pytest.mark.django_db
def test_vendor_payment_rejects_bill_from_another_company(
    company, vendor, user
):
    foreign_company = CompanyFactory()
    foreign_vendor = Vendor.objects.create(company=foreign_company, name="Foreign")
    bill = Bill.objects.create(
        company=foreign_company,
        vendor=foreign_vendor,
        bill_date=date.today(),
        due_date=date.today(),
        total=Decimal("100"),
        balance_due=Decimal("100"),
    )
    Bill.objects.filter(pk=bill.pk).update(status=Bill.Status.OPEN)
    with pytest.raises(ValueError, match="Bill not found for this company"):
        PaymentService(company=company, user=user).record_vendor_payment(
            bill,
            form_data(
                amount="10", method="bank_transfer", payment_date="2026-11-04"
            ),
        )
    assert Payment.objects.count() == 0
