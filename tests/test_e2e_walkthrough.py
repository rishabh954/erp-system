import pytest
from django.urls import reverse
from django.test import Client, LiveServerTestCase
from django.core.management import call_command
from decimal import Decimal
from apps.authentication.models import User
from apps.company.models import Currency, Company

class SmokeTest(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Seed permissions and currencies like the real DB
        call_command('seed_currencies')
        call_command('setup_permissions')

    def setUp(self):
        self.client = Client()

    def test_end_to_end_walkthrough(self):
        """
        Simulate the entire E2E flow:
        Register -> Create Company -> Create Product -> Create Customer 
        -> Create Sales Order -> Confirm -> Invoice -> Pay
        """
        # 1. Create initial user (User creation would normally go via signup, but we'll create directly here for the test)
        user = User.objects.create_user(
            email="e2e@example.com",
            password="password123",
            first_name="E2E",
            last_name="Tester"
        )
        
        # 2. Login
        login_success = self.client.login(email="e2e@example.com", password="password123")
        self.assertTrue(login_success)
        
        # 3. Create Company via UI Flow
        currency = Currency.objects.get(code='USD')
        company_data = {
            'name': 'E2E Corp',
            'legal_name': 'E2E Corporation Inc.',
            'company_type': 'LLC',
            'industry': 'Software',
            'fiscal_year_start': '01-01',
            'timezone': 'America/New_York',
            'default_currency': currency.id
        }
        resp = self.client.post(reverse('company:create'), company_data)
        self.assertEqual(resp.status_code, 302) # Redirects to dashboard
        
        # Update our reference to the logged in user to reflect the newly assigned primary_company
        user.refresh_from_db()
        company = user.primary_company
        self.assertIsNotNone(company)
        
        call_command('seed_default_coa', str(company.id))

        # 4. Create a Category
        category_data = {
            'name': 'E2E Category',
            'description': 'Test Category'
        }
        resp = self.client.post(reverse('inventory:category_create'), category_data)
        self.assertEqual(resp.status_code, 302)
        
        from apps.inventory.models import ProductCategory
        category = ProductCategory.objects.filter(company=company).first()
        
        # 5. Create Product
        product_data = {
            'name': 'E2E Product',
            'sku': 'E2E-001',
            'product_type': 'stockable',
            'category': category.id,
            'cost_price': '50.00',
            'sale_price': '100.00'
        }
        resp = self.client.post(reverse('inventory:product_create'), product_data)
        self.assertEqual(resp.status_code, 302)
        
        from apps.inventory.models import Product
        product = Product.objects.get(sku='E2E-001')

        # 6. Create Customer
        customer_data = {
            'name': 'E2E Customer',
            'email': 'customer@e2e.com',
            'phone': '123456789'
        }
        resp = self.client.post(reverse('crm:customer_create'), customer_data)
        self.assertEqual(resp.status_code, 302)

        from apps.crm.models import Customer
        customer = Customer.objects.get(email='customer@e2e.com')
        
        # 7. Create Sales Order
        # A Sales Order view usually requires inline formsets for lines. We'll simulate the POST payload.
        # Ensure we have stock first if we are confirming immediately
        from apps.inventory.services import StockService
        from apps.inventory.models import Warehouse
        warehouse = Warehouse.objects.create(company=company, name="E2E WH", is_active=True)
        StockService(user=user, company=company).receive_stock(
            product=product, warehouse=warehouse, qty=Decimal('10'), unit_cost=Decimal('50'),
            reference_type='Manual', reference_id='INIT'
        )

        so_data = {
            'customer': customer.id,
            'currency': currency.id,
            'order_date': '2026-07-01',
            'expected_date': '2026-07-10',
            'status': 'draft',
            # Formset for lines
            'lines-TOTAL_FORMS': '1',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '0',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-product': product.id,
            'lines-0-quantity': '2',
            'lines-0-unit_price': '100.00'
        }
        resp = self.client.post(reverse('sales:order_create'), so_data)
        self.assertEqual(resp.status_code, 302)
        
        from apps.sales.models import SalesOrder
        so = SalesOrder.objects.first()
        self.assertIsNotNone(so)
        
        # 8. Confirm Sales Order programmatically as normally done in the service layer when converting or via an action
        from apps.sales.services import SalesOrderService
        so = SalesOrderService(user=user, company=company).confirm_order(so)
        
        self.assertEqual(so.status, 'confirmed')

        # 9. Create Invoice from Order
        # There's likely an action or we can just create an invoice manually.
        invoice_data = {
            'customer': customer.id,
            'sales_order': so.id,
            'currency': currency.id,
            'invoice_date': '2026-07-02',
            'due_date': '2026-07-16',
            'status': 'draft',
            'lines-TOTAL_FORMS': '1',
            'lines-INITIAL_FORMS': '0',
            'lines-MIN_NUM_FORMS': '0',
            'lines-MAX_NUM_FORMS': '1000',
            'lines-0-product': product.id,
            'lines-0-quantity': '2',
            'lines-0-unit_price': '100.00'
        }
        resp = self.client.post(reverse('sales:invoice_create'), invoice_data)
        self.assertEqual(resp.status_code, 302)
        
        from apps.sales.models import Invoice, InvoiceLine
        invoice = Invoice.objects.first()
    
        # Ensure invoice has a total so payment doesn't fail or result in negative balance
        InvoiceLine.objects.create(
            invoice=invoice, product=product, description='E2E Item',
            quantity=Decimal('2'), unit_price=Decimal('100.00')
        )
        invoice.recalculate_totals()
    
        # Approve/Send Invoice
        invoice.status = 'sent'
        invoice.save(update_fields=['status'])
        
        # 10. Record Payment programmatically to see any exceptions
        from apps.sales.services import PaymentService
        payment_data = {
            'amount': '200.00',
            'payment_date': '2026-07-03',
            'method': 'bank_transfer',
            'reference': 'E2E-PAY-01'
        }
        PaymentService(user=user, company=company).record_payment(invoice, payment_data)
        
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal('200.00'))
        self.assertEqual(invoice.balance_due, Decimal('0.00'))
        
        # 11. Verify Journal Entries (Double Entry Math)
        from apps.accounting.models import JournalEntry, Account
        entries = JournalEntry.objects.filter(company=company)
        self.assertTrue(entries.count() > 0)
        
        # Basic accounting equation check
        for entry in entries:
            total_debits = sum(item.debit for item in entry.items.all())
            total_credits = sum(item.credit for item in entry.items.all())
            self.assertEqual(total_debits, total_credits)
