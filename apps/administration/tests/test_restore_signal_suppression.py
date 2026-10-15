import json
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import pytest
from django.db.models.signals import post_delete, post_save, pre_save
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.core.management import call_command

from apps.administration.models import AuditLog, WebhookDelivery
from apps.crm.models import Customer
from apps.inventory.models import (
    DeliveryOrder,
    DeliveryOrderLine,
    Product,
    StockMovement,
    StockRecord,
    Warehouse,
)
from apps.sales.models import CreditNote, Invoice, Payment
from apps.company.models import Currency
from apps.sales.models import InvoiceLine, SalesCommission, SalesOrder, SalesOrderLine
from apps.administration.models import WebhookEndpoint
from core.factories import CustomerFactory
from core.restore_context import is_restoring, restoring


@pytest.mark.django_db
def test_audit_receivers_ignore_raw_saves_and_deletes(company):
    customer = CustomerFactory(company=company)
    before = AuditLog.objects.filter(company=company).count()

    pre_save.send(sender=Customer, instance=customer, raw=True, using="default", update_fields=None)
    post_save.send(sender=Customer, instance=customer, created=False, raw=True, using="default", update_fields=None)
    post_delete.send(sender=Customer, instance=customer, raw=True, using="default")
    with restoring():
        post_delete.send(sender=Customer, instance=customer, using="default")

    assert AuditLog.objects.filter(company=company).count() == before


@pytest.mark.django_db
def test_commission_receivers_ignore_raw_and_restore_context(company):
    from apps.sales.signals import (
        adjust_sales_commission_for_credit_note,
        generate_paid_invoice_commission,
        generate_sales_commission,
    )

    invoice = Mock(status=Invoice.Status.PAID, invoice_id="inv", company_id=company.pk)
    payment = Mock(status=Payment.Status.COMPLETED, invoice_id="inv", invoice=invoice)
    credit_note = Mock(invoice_id="inv", company_id=company.pk, invoice=invoice)
    with patch("apps.sales.signals.sync_invoice_commission") as sync:
        generate_sales_commission(Payment, payment, raw=True)
        generate_paid_invoice_commission(Invoice, invoice, raw=True)
        adjust_sales_commission_for_credit_note(CreditNote, credit_note, raw=True)
        with restoring():
            assert is_restoring()
            generate_sales_commission(Payment, payment)
            generate_paid_invoice_commission(Invoice, invoice)
            adjust_sales_commission_for_credit_note(CreditNote, credit_note)
        assert not is_restoring()
        sync.assert_not_called()


@pytest.mark.django_db
def test_reorder_and_lead_score_receivers_ignore_raw_and_restore_context():
    from apps.crm.signals import update_lead_score
    from apps.inventory.signals import trigger_reorder_rules

    movement = Mock()
    activity = Mock()
    with patch("django.db.transaction.atomic") as atomic, patch.object(
        activity, "save"
    ) as save:
        trigger_reorder_rules(StockMovement, movement, created=True, raw=True)
        update_lead_score(None, activity, created=True, raw=True)
        with restoring():
            trigger_reorder_rules(StockMovement, movement, created=True)
            update_lead_score(None, activity, created=True)
        atomic.assert_not_called()
        save.assert_not_called()


@pytest.mark.django_db
def test_webhook_receivers_and_helpers_ignore_raw_and_restore_context(company):
    from apps.administration import signals
    from apps.administration.tasks import deliver_webhook, dispatch_webhook_event

    invoice = Mock(company_id=company.pk, pk="invoice-id", number="INV-1", status=Invoice.Status.SENT)
    callbacks = []
    with patch.object(signals.transaction, "on_commit", side_effect=callbacks.append) as on_commit:
        pre_save.send(sender=Invoice, instance=invoice, raw=True, using="default", update_fields=None)
        post_save.send(sender=Invoice, instance=invoice, created=True, raw=True, using="default", update_fields=None)
        signals._queue_webhook(invoice, "invoice.created", {}) if is_restoring() else None
        with restoring():
            pre_save.send(sender=Invoice, instance=invoice, raw=False, using="default", update_fields=None)
            post_save.send(sender=Invoice, instance=invoice, created=True, raw=False, using="default", update_fields=None)
            signals._queue_webhook(invoice, "invoice.created", {})
            signals._queue_webhook(invoice, "invoice.created", {})
            dispatch_webhook_event(str(company.pk), "invoice.created", {})
            deliver_webhook.run("missing", str(company.pk), "invoice.created", {})
        assert callbacks == []
        on_commit.assert_not_called()
    assert not WebhookDelivery.objects.filter(company=company).exists()


@pytest.mark.django_db
def test_notification_and_email_helpers_are_suppressed_during_restore(company, user):
    from apps.notifications.services import NotificationService

    with restoring():
        assert NotificationService.send(user, "title", "message", company=company) == []
        assert NotificationService.send_email(
            user, "subject", "message", company=company
        ) is None


@pytest.mark.django_db
def test_paid_invoice_commission_round_trips_without_restore_side_effects(
    company, user, tmp_path, django_capture_on_commit_callbacks
):
    from django.apps import apps
    from apps.administration.tasks import serialize_company_backup
    from apps.crm.models import Customer
    from apps.accounting.models import JournalEntry, JournalItem
    from apps.purchase.models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, Vendor
    from core.factories import AccountFactory, JournalFactory
    from core.restore_context import restoring

    customer = CustomerFactory(company=company)
    product = Product.objects.create(company=company, name="Restore stock item", sku="RESTORE-STOCK")
    warehouse = Warehouse.objects.create(company=company, name="Restore warehouse", code="RESTORE-WH")
    order = SalesOrder.objects.create(
        company=company,
        customer=customer,
        sales_rep=user,
        order_date=date(2026, 1, 1),
        status=SalesOrder.Status.CONFIRMED,
    )
    sales_line = SalesOrderLine.objects.create(
        sales_order=order, product=product, description="Shipped item", quantity=Decimal("1"), unit_price=Decimal("100")
    )
    invoice = Invoice.objects.create(
        company=company,
        customer=customer,
        sales_order=order,
        status=Invoice.Status.PAID,
        invoice_date=date(2026, 1, 1),
        due_date=date(2026, 1, 31),
        total=Decimal("100.00"),
        amount_paid=Decimal("100.00"),
        balance_due=Decimal("0.00"),
    )
    InvoiceLine.objects.create(
        invoice=invoice, description="Invoice item", quantity=Decimal("1"), unit_price=Decimal("100")
    )
    currency, _ = Currency.objects.get_or_create(
        code="USD", defaults={"name": "US Dollar", "symbol": "$"}
    )
    with patch("apps.accounting.services.AutoJournalService.post_sales_payment"):
        payment = Payment.objects.create(
            company=company,
            invoice=invoice,
            customer=customer,
            amount=Decimal("100.00"),
            currency=currency,
            payment_date=date(2026, 1, 2),
            method=Payment.Method.CASH,
            status=Payment.Status.COMPLETED,
        )
    commission = SalesCommission.objects.get(company=company, invoice=invoice, sales_rep=user)

    # Ship one item through the real service so the backup contains the delivery,
    # StockMovement and updated StockRecord produced by normal operations.
    stock = StockRecord.objects.create(
        company=company, product=product, warehouse=warehouse,
        quantity_on_hand=Decimal("5"), quantity_reserved=Decimal("1"),
    )
    delivery = DeliveryOrder.objects.create(
        company=company, sales_order=order, warehouse=warehouse,
        status=DeliveryOrder.Status.READY,
    )
    DeliveryOrderLine.objects.create(
        delivery_order=delivery, product=product, description="Shipped item",
        quantity_ordered=Decimal("1"), quantity_shipped=Decimal("1"),
    )
    with patch("apps.accounting.services.AutoJournalService.post_delivery"):
        delivery.ship(user)
    movement = StockMovement.objects.get(company=company, reference_id=str(delivery.pk))

    vendor = Vendor.objects.create(company=company, name="Restore vendor")
    purchase_order = PurchaseOrder.objects.create(
        company=company, vendor=vendor, warehouse=warehouse, order_date=date(2026, 1, 1),
        status=PurchaseOrder.Status.CONFIRMED,
    )
    po_line = PurchaseOrderLine.objects.create(
        purchase_order=purchase_order, product=product, description="Received item",
        quantity=Decimal("2"), unit_price=Decimal("3"),
    )
    receipt = GoodsReceipt.objects.create(
        company=company, purchase_order=purchase_order, warehouse=warehouse,
        receipt_date=date(2026, 1, 2), status=GoodsReceipt.Status.COMPLETED,
        received_by=user,
    )
    GoodsReceiptLine.objects.create(
        goods_receipt=receipt, po_line=po_line, quantity_received=Decimal("2"),
        quantity_accepted=Decimal("2"),
    )

    account = AccountFactory(company=company)
    journal = JournalFactory(company=company)
    entry = JournalEntry.objects.create(
        company=company, journal=journal, date=date(2026, 1, 2), reference="RESTORE-ENTRY"
    )
    journal_item = JournalItem.objects.create(
        journal_entry=entry, account=account, description="Restore ledger item", debit=Decimal("10")
    )
    endpoint = WebhookEndpoint.objects.create(
        company=company,
        name="restore test",
        url="https://hooks.example.test/",
        secret="never-in-backup",
        events=["*"],
        status=WebhookEndpoint.Status.ACTIVE,
    )
    payload = json.loads(serialize_company_backup(str(company.pk)))
    path = tmp_path / "commission-restore.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    expected_counts = payload["manifest"]["model_counts"]

    pending = [
        row for row in reversed(payload["objects"])
        if apps.get_model(row["model"])._meta.label_lower != "company.company"
    ]
    with restoring(), transaction.atomic():
        while pending:
            deferred = []
            for row in pending:
                model = apps.get_model(row["model"])
                try:
                    model._base_manager.filter(pk=row["pk"]).delete()
                except ProtectedError:
                    deferred.append(row)
            if len(deferred) == len(pending):
                raise AssertionError("Could not clear the tenant rows before restore.")
            pending = deferred

    assert not SalesCommission.objects.filter(company=company).exists()
    output = StringIO()
    with patch("apps.administration.tasks.dispatch_webhook_event") as dispatch, patch(
        "apps.administration.tasks.deliver_webhook.delay"
    ) as deliver, django_capture_on_commit_callbacks(execute=True):
        call_command("restore_company_backup", str(path), company=str(company.pk), stdout=output)

    restored_commission = SalesCommission.objects.get(company=company, invoice_id=invoice.pk)
    assert restored_commission.pk == commission.pk
    assert restored_commission.amount == commission.amount
    assert SalesCommission.objects.filter(company=company, invoice_id=invoice.pk).count() == 1
    assert payment.pk and endpoint.pk
    assert StockMovement.objects.filter(company=company, pk=movement.pk).count() == 1
    restored_stock = StockRecord.objects.get(company=company, product_id=product.pk, warehouse_id=warehouse.pk)
    assert restored_stock.quantity_on_hand == stock.quantity_on_hand - Decimal("1")
    assert GoodsReceipt.objects.filter(company=company, pk=receipt.pk).count() == 1
    assert JournalItem.objects.filter(journal_entry__company=company, pk=journal_item.pk).count() == 1
    assert AuditLog.objects.filter(company=company).count() == expected_counts.get("administration.auditlog", 0)
    assert not WebhookDelivery.objects.filter(company=company).exists()
    dispatch.assert_not_called()
    deliver.assert_not_called()
    for model_label, expected in expected_counts.items():
        model = apps.get_model(model_label)
        if model is not apps.get_model("company.Company"):
            from apps.administration.management.commands.restore_company_backup import _target_queryset
            assert _target_queryset(model, company.pk).count() == expected

    invoice.total = Decimal("101.00")
    invoice.save(update_fields=["total"])
    SalesCommission.objects.get(company=company, invoice_id=invoice.pk).hard_delete()
    with patch("apps.accounting.services.AutoJournalService.post_sales_payment"):
        Payment.objects.create(
            company=company,
            number="PAY-RESTORE-NEW",
            invoice=invoice,
            customer=customer,
            amount=Decimal("1.00"),
            currency=currency,
            payment_date=date(2026, 1, 3),
            method=Payment.Method.CASH,
            status=Payment.Status.COMPLETED,
        )
    assert SalesCommission.objects.filter(company=company, invoice_id=invoice.pk).count() == 1

    prior_audits = AuditLog.objects.filter(company=company).count()
    with patch("apps.administration.tasks.dispatch_webhook_event") as dispatch:
        with django_capture_on_commit_callbacks(execute=True):
            fresh_customer = CustomerFactory(company=company)
            Invoice.objects.create(
                company=company,
                customer=fresh_customer,
                invoice_date=date(2026, 2, 1),
                due_date=date(2026, 2, 28),
            )
        dispatch.assert_called_once()
    assert AuditLog.objects.filter(company=company).count() > prior_audits
