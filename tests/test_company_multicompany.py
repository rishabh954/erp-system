from decimal import Decimal

import pytest

from apps.company.models import (
    Company,
    CompanyAccountingConfig,
    IntercompanyRule,
    IntercompanySettlement,
    IntercompanyTransaction,
    LegalEntity,
)
from apps.company.services import IntercompanyAccountingService

pytestmark = pytest.mark.django_db


def test_company_hierarchy_tracks_all_subsidiaries():
    parent = Company.objects.create(name="Group Parent")
    child_a = Company.objects.create(name="Subsidiary A", parent=parent)
    child_b = Company.objects.create(name="Subsidiary B", parent=parent)

    ids = set(parent.get_all_subsidiary_ids())

    assert parent.id in ids
    assert child_a.id in ids
    assert child_b.id in ids


def test_legal_entity_and_accounting_config_are_company_scoped():
    company = Company.objects.create(name="Acme Legal")

    legal_entity = LegalEntity.objects.create(
        company=company,
        legal_name="Acme Legal Ltd",
        entity_type="subsidiary",
        country="US",
        tax_id="TAX-001",
    )
    config = CompanyAccountingConfig.objects.create(
        company=company,
        tax_country="US",
        accounting_policy="accrual",
        intercompany_posting_enabled=True,
        is_consolidation_enabled=True,
    )

    assert legal_entity.company == company
    assert config.company == company
    assert legal_entity.display_name.startswith("Acme Legal Ltd")
    assert config.can_post_on_date("2026-08-26") is True


def test_intercompany_rule_allows_group_posting_between_companies():
    source = Company.objects.create(name="Company A")
    target = Company.objects.create(name="Company B")

    rule = IntercompanyRule.objects.create(
        source_company=source,
        target_company=target,
        settlement_method="netting",
        auto_posting_enabled=True,
        allow_cross_currency=True,
    )

    assert rule.source_company == source
    assert rule.target_company == target
    assert rule.is_active
    assert str(rule) == "Company A -> Company B"


def test_intercompany_transaction_posts_balanced_entries_for_both_companies():
    from apps.accounting.models import Account, JournalEntry

    source = Company.objects.create(name="Source Company")
    target = Company.objects.create(name="Target Company")

    source_ar = Account.objects.create(
        company=source,
        code="1200",
        name="Source AR",
        account_type="asset",
        account_subtype="accounts_receivable",
    )
    source_ap = Account.objects.create(
        company=source,
        code="2100",
        name="Source AP",
        account_type="liability",
        account_subtype="accounts_payable",
    )
    target_ar = Account.objects.create(
        company=target,
        code="1201",
        name="Target AR",
        account_type="asset",
        account_subtype="accounts_receivable",
    )
    target_ap = Account.objects.create(
        company=target,
        code="2101",
        name="Target AP",
        account_type="liability",
        account_subtype="accounts_payable",
    )
    source.default_receivable_account = source_ar
    source.default_payable_account = source_ap
    target.default_receivable_account = target_ar
    target.default_payable_account = target_ap
    source.save(update_fields=["default_receivable_account", "default_payable_account"])
    target.save(update_fields=["default_receivable_account", "default_payable_account"])

    tx = IntercompanyAccountingService.create_transaction(
        source_company=source,
        target_company=target,
        amount=Decimal("250.50"),
        reference="IC-001",
    )

    assert tx.status == IntercompanyTransaction.Status.POSTED
    assert tx.amount == Decimal("250.50")
    assert JournalEntry.objects.filter(company=source, reference="IC-001").exists()
    assert JournalEntry.objects.filter(company=target, reference="IC-001").exists()

    source_entries = JournalEntry.objects.filter(company=source, reference="IC-001")
    target_entries = JournalEntry.objects.filter(company=target, reference="IC-001")
    assert source_entries.first().total_debit == Decimal("250.50")
    assert target_entries.first().total_credit == Decimal("250.50")


def test_group_consolidation_aggregates_child_company_balances():
    from apps.accounting.models import Account

    parent = Company.objects.create(name="Group Parent")
    child_a = Company.objects.create(name="Child A", parent=parent)
    child_b = Company.objects.create(name="Child B", parent=parent)

    Account.objects.create(
        company=child_a,
        code="1000",
        name="Cash A",
        account_type="asset",
        current_balance=Decimal("120.00"),
    )
    Account.objects.create(
        company=child_b,
        code="1000",
        name="Cash B",
        account_type="asset",
        current_balance=Decimal("80.00"),
    )

    totals = parent.get_consolidated_account_totals()

    assert totals["1000"] == Decimal("200.00")
    assert parent.get_all_subsidiary_ids() == [parent.id, child_a.id, child_b.id]


def test_intercompany_matching_sets_off_balances_between_companies():
    source = Company.objects.create(name="Source Company")
    target = Company.objects.create(name="Target Company")

    tx_a = IntercompanyTransaction.objects.create(
        source_company=source,
        target_company=target,
        amount=Decimal("250.00"),
        reference="IC-101",
        status=IntercompanyTransaction.Status.POSTED,
    )
    tx_b = IntercompanyTransaction.objects.create(
        source_company=target,
        target_company=source,
        amount=Decimal("140.00"),
        reference="IC-102",
        status=IntercompanyTransaction.Status.POSTED,
    )

    settlements = IntercompanyAccountingService.match_open_transactions(source, target)

    tx_a.refresh_from_db()
    tx_b.refresh_from_db()

    assert len(settlements) == 1
    assert settlements[0].net_amount == Decimal("110.00")
    assert settlements[0].status == IntercompanySettlement.Status.SETTLED
    assert tx_a.status == IntercompanyTransaction.Status.SETTLED
    assert tx_b.status == IntercompanyTransaction.Status.SETTLED


def test_group_consolidated_report_summarizes_company_balances():
    parent = Company.objects.create(name="HQ Group")
    child_a = Company.objects.create(name="Child A", parent=parent)
    child_b = Company.objects.create(name="Child B", parent=parent)

    from apps.accounting.models import Account

    Account.objects.create(
        company=child_a,
        code="1000",
        name="Cash A",
        account_type="asset",
        current_balance=Decimal("150.00"),
    )
    Account.objects.create(
        company=child_b,
        code="1000",
        name="Cash B",
        account_type="asset",
        current_balance=Decimal("50.00"),
    )
    Account.objects.create(
        company=child_b,
        code="2000",
        name="Payables B",
        account_type="liability",
        current_balance=Decimal("25.00"),
    )

    report = parent.get_group_consolidated_report()

    assert report["assets"]["1000"] == Decimal("200.00")
    assert report["liabilities"]["2000"] == Decimal("25.00")
    assert report["company_count"] == 3
