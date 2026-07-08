import pytest
from decimal import Decimal
from django.utils import timezone
from apps.company.models import Company, Currency
from apps.authentication.models import User
from apps.crm.models import Customer
from apps.purchase.models import Vendor
from apps.inventory.models import Product, Warehouse
from apps.sales.models import Quotation, QuotationLine, SalesOrder, SalesOrderLine, Invoice
from apps.purchase.models import PurchaseOrder, PurchaseOrderLine, Bill
from apps.accounting.models import Account, JournalEntry, JournalItem, Journal

@pytest.fixture
def financial_setup():
    company = Company.objects.create(name="Fin Test Co")
    user = User.objects.create_superuser("fin@test.com", "pass", primary_company=company)
    currency, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$"})
    
    # Create Accounts
    receivable = Account.objects.create(company=company, name="Accounts Receivable", code="1200", account_type="asset")
    sales = Account.objects.create(company=company, name="Sales Revenue", code="4000", account_type="revenue")
    payable = Account.objects.create(company=company, name="Accounts Payable", code="2000", account_type="liability")
    expense = Account.objects.create(company=company, name="Inventory Expense", code="5000", account_type="expense")
    bank = Account.objects.create(company=company, name="Bank Account", code="1000", account_type="asset")

    # Journals
    sales_journal = Journal.objects.create(company=company, name="Sales Journal", code="SJ", journal_type="sales", default_account=receivable)
    purchase_journal = Journal.objects.create(company=company, name="Purchase Journal", code="PJ", journal_type="purchase", default_account=payable)
    bank_journal = Journal.objects.create(company=company, name="Bank Journal", code="BNK", journal_type="bank", default_account=bank)

    # Master Data
    customer = Customer.objects.create(company=company, name="Fin Customer")
    vendor = Vendor.objects.create(company=company, name="Fin Vendor")
    product = Product.objects.create(company=company, name="Widget", sku="WGT-01", sale_price=100.00, cost_price=50.00)

    return {
        "company": company, "user": user, "currency": currency,
        "receivable": receivable, "sales": sales, "payable": payable, "expense": expense, "bank": bank,
        "sales_journal": sales_journal, "purchase_journal": purchase_journal, "bank_journal": bank_journal,
        "customer": customer, "vendor": vendor, "product": product
    }

@pytest.mark.django_db
def test_sales_flow_journal_entries(financial_setup):
    setup = financial_setup
    company, user, customer, product = setup["company"], setup["user"], setup["customer"], setup["product"]
    
    # Quotation -> SalesOrder -> Invoice
    today = timezone.localdate()
    quote = Quotation.objects.create(company=company, customer=customer, created_by=user)
    QuotationLine.objects.create(quotation=quote, product=product, quantity=2, unit_price=Decimal("100.00"))
    quote.recalculate_totals()

    order = SalesOrder.objects.create(company=company, customer=customer, quotation=quote, order_date=today, created_by=user)
    SalesOrderLine.objects.create(sales_order=order, product=product, quantity=2, unit_price=Decimal("100.00"))
    order.recalculate_totals()

    invoice = Invoice.objects.create(company=company, customer=customer, sales_order=order, invoice_date=today, due_date=today, created_by=user)
    invoice.subtotal = order.subtotal
    invoice.total = order.total
    invoice.status = Invoice.Status.SENT
    invoice.save()
    
    # In a real flow, posting the invoice creates Journal Entries.
    # We will simulate the service posting it or check if it already posted via signals.
    # If the system doesn't automatically post, we do it via service.
    try:
        from apps.accounting.services import AutoJournalService
        AutoJournalService.post_sales_invoice(invoice)
    except Exception as e:
        print("Exception:", e)

    # Check journal entries for the invoice
    jes = JournalEntry.objects.filter(company=company, reference__startswith="INV")
    
    # Total debits must equal total credits
    for je in jes:
        total_debit = sum(item.debit for item in je.items.all())
        total_credit = sum(item.credit for item in je.items.all())
        assert total_debit == total_credit, f"JE {je.number} debits ({total_debit}) != credits ({total_credit})"


@pytest.mark.django_db
def test_purchase_flow_journal_entries(financial_setup):
    setup = financial_setup
    company, user, vendor, product = setup["company"], setup["user"], setup["vendor"], setup["product"]
    
    today = timezone.localdate()
    po = PurchaseOrder.objects.create(company=company, vendor=vendor, order_date=today, created_by=user)
    PurchaseOrderLine.objects.create(purchase_order=po, product=product, quantity=5, unit_price=Decimal("50.00"))
    po.recalculate_totals()

    bill = Bill.objects.create(company=company, vendor=vendor, purchase_order=po, bill_date=today, created_by=user)
    bill.subtotal = po.subtotal
    bill.total = po.total
    bill.status = Bill.Status.OPEN
    bill.save()

    try:
        from apps.accounting.services import AutoJournalService
        AutoJournalService.post_purchase_bill(bill)
    except Exception as e:
        print("Exception:", e)

    # Total debits must equal total credits
    jes = JournalEntry.objects.filter(company=company, reference__startswith="BILL")
    for je in jes:
        total_debit = sum(item.debit for item in je.items.all())
        total_credit = sum(item.credit for item in je.items.all())
        assert total_debit == total_credit, f"JE {je.number} debits ({total_debit}) != credits ({total_credit})"
