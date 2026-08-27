from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounting.models import Account, Journal, JournalEntry, JournalItem
from apps.company.models import (
    Company,
    IntercompanyRule,
    IntercompanySettlement,
    IntercompanyTransaction,
)


class IntercompanyAccountingService:
    """Creates balanced postings between two companies to simulate Odoo-style intercompany accounting."""

    @staticmethod
    def get_or_create_intercompany_journal(company):
        journal, _ = Journal.objects.get_or_create(
            company=company,
            code="IC",
            defaults={
                "name": "Intercompany Journal",
                "journal_type": "general",
            },
        )
        return journal

    @staticmethod
    @transaction.atomic
    def create_transaction(source_company, target_company, amount, reference, description=""):
        if source_company == target_company:
            raise ValueError("Intercompany transaction must be between different companies")

        rule = IntercompanyRule.objects.filter(
            source_company=source_company,
            target_company=target_company,
            is_active=True,
        ).first()
        if rule is None:
            rule = IntercompanyRule.objects.create(
                source_company=source_company,
                target_company=target_company,
                settlement_method="netting",
                auto_posting_enabled=True,
                allow_cross_currency=True,
            )

        amount = Decimal(str(amount))
        tx = IntercompanyTransaction.objects.create(
            source_company=source_company,
            target_company=target_company,
            amount=amount,
            reference=reference,
            description=description or f"Intercompany transaction {reference}",
            currency=source_company.default_currency or target_company.default_currency,
            status=IntercompanyTransaction.Status.POSTED,
            posted_at=timezone.now(),
        )

        source_journal = IntercompanyAccountingService.get_or_create_intercompany_journal(source_company)
        target_journal = IntercompanyAccountingService.get_or_create_intercompany_journal(target_company)

        source_ar = source_company.default_receivable_account or Account.objects.filter(
            company=source_company,
            account_subtype="accounts_receivable",
        ).first()
        source_ap = source_company.default_payable_account or Account.objects.filter(
            company=source_company,
            account_subtype="accounts_payable",
        ).first()
        target_ar = target_company.default_receivable_account or Account.objects.filter(
            company=target_company,
            account_subtype="accounts_receivable",
        ).first()
        target_ap = target_company.default_payable_account or Account.objects.filter(
            company=target_company,
            account_subtype="accounts_payable",
        ).first()

        if source_ar is None:
            source_ar = Account.objects.create(
                company=source_company,
                code="1200",
                name="Intercompany Receivable",
                account_type="asset",
                account_subtype="accounts_receivable",
            )
            source_company.default_receivable_account = source_ar
            source_company.save(update_fields=["default_receivable_account"])

        if source_ap is None:
            source_ap = Account.objects.create(
                company=source_company,
                code="2100",
                name="Intercompany Payable",
                account_type="liability",
                account_subtype="accounts_payable",
            )
            source_company.default_payable_account = source_ap
            source_company.save(update_fields=["default_payable_account"])

        if target_ar is None:
            target_ar = Account.objects.create(
                company=target_company,
                code="1201",
                name="Intercompany Receivable",
                account_type="asset",
                account_subtype="accounts_receivable",
            )
            target_company.default_receivable_account = target_ar
            target_company.save(update_fields=["default_receivable_account"])

        if target_ap is None:
            target_ap = Account.objects.create(
                company=target_company,
                code="2101",
                name="Intercompany Payable",
                account_type="liability",
                account_subtype="accounts_payable",
            )
            target_company.default_payable_account = target_ap
            target_company.save(update_fields=["default_payable_account"])

        source_entry = JournalEntry.objects.create(
            company=source_company,
            journal=source_journal,
            date=timezone.now().date(),
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            total_debit=amount,
            total_credit=amount,
        )
        JournalItem.objects.create(
            journal_entry=source_entry,
            account=source_ar,
            description=description or reference,
            debit=amount,
            credit=Decimal("0.00"),
        )
        JournalItem.objects.create(
            journal_entry=source_entry,
            account=source_ap,
            description=description or reference,
            debit=Decimal("0.00"),
            credit=amount,
        )
        source_entry.post()

        target_entry = JournalEntry.objects.create(
            company=target_company,
            journal=target_journal,
            date=timezone.now().date(),
            reference=reference,
            status=JournalEntry.Status.DRAFT,
            total_debit=amount,
            total_credit=amount,
        )
        JournalItem.objects.create(
            journal_entry=target_entry,
            account=target_ap,
            description=description or reference,
            debit=Decimal("0.00"),
            credit=amount,
        )
        JournalItem.objects.create(
            journal_entry=target_entry,
            account=target_ar,
            description=description or reference,
            debit=amount,
            credit=Decimal("0.00"),
        )
        target_entry.post()

        return tx

    @staticmethod
    @transaction.atomic
    def match_open_transactions(company_a, company_b):
        """Net open intercompany transactions between two companies and mark them settled."""
        outgoing = list(
            IntercompanyTransaction.objects.filter(
                source_company=company_a,
                target_company=company_b,
                status=IntercompanyTransaction.Status.POSTED,
            )
        )
        incoming = list(
            IntercompanyTransaction.objects.filter(
                source_company=company_b,
                target_company=company_a,
                status=IntercompanyTransaction.Status.POSTED,
            )
        )

        total_outgoing = sum((tx.amount for tx in outgoing), Decimal("0.00"))
        total_incoming = sum((tx.amount for tx in incoming), Decimal("0.00"))
        net_amount = total_outgoing - total_incoming

        if net_amount >= Decimal("0.00"):
            settlement_source = company_a
            settlement_target = company_b
            settlement_value = net_amount
        else:
            settlement_source = company_b
            settlement_target = company_a
            settlement_value = abs(net_amount)

        settlement = IntercompanySettlement.objects.create(
            source_company=settlement_source,
            target_company=settlement_target,
            net_amount=settlement_value,
            description="Auto-settlement of open intercompany transactions",
            status=IntercompanySettlement.Status.SETTLED,
            settled_at=timezone.now(),
        )

        IntercompanyTransaction.objects.filter(
            pk__in=[tx.pk for tx in outgoing + incoming],
            status=IntercompanyTransaction.Status.POSTED,
        ).update(status=IntercompanyTransaction.Status.SETTLED)

        return [settlement]
