from django.test import TestCase, Client
from django.urls import reverse
from decimal import Decimal
from apps.company.models import Company
from apps.authentication.models import User, UserCompany
from apps.inventory.models import Product, Warehouse, StockRecord
from apps.purchase.models import Vendor, PurchaseOrder, PurchaseOrderLine

class GoodsReceiptStockUpdateTest(TestCase):
    def setUp(self):
        # Create test company
        self.company = Company.objects.create(name='Test Company')
        
        # Create test user
        self.user = User.objects.create_user(
            email='test@example.com',
            password='password123',
            first_name='Test',
            last_name='User',
            primary_company=self.company
        )
        UserCompany.objects.create(user=self.user, company=self.company)
        
        # Create test inventory data
        self.product = Product.objects.create(
            company=self.company,
            name='Test Widget',
            sku='WGT-001'
        )
        self.warehouse = Warehouse.objects.create(
            company=self.company,
            name='Main Warehouse',
            code='MAIN'
        )
        
        # Create test purchase data
        self.vendor = Vendor.objects.create(
            company=self.company,
            name='Test Vendor'
        )
        self.po = PurchaseOrder.objects.create(
            company=self.company,
            vendor=self.vendor,
            order_date='2026-06-01',
            status=PurchaseOrder.Status.CONFIRMED,
            number='PO-1001'
        )
        self.po_line = PurchaseOrderLine.objects.create(
            purchase_order=self.po,
            product=self.product,
            description='Test Widget Line',
            quantity=Decimal('10.00'),
            unit_price=Decimal('5.00')
        )
        
        # Setup client
        self.client = Client()
        self.client.login(email='test@example.com', password='password123')

    def test_goods_receipt_updates_stock(self):
        # Initial stock should be 0 or nonexistent
        self.assertFalse(StockRecord.objects.filter(product=self.product).exists())
        
        # Submit GRN form
        url = reverse('purchase:order_receive', args=[self.po.pk])
        response = self.client.post(url, {
            f'qty_{self.po_line.pk}': '10',
            f'batch_{self.po_line.pk}': 'BATCH123',
            'warehouse': self.warehouse.pk,
            'notes': 'Received fine'
        })
        
        # View redirects on success
        self.assertEqual(response.status_code, 302)
        
        # Check stock record
        stock_record = StockRecord.objects.get(product=self.product)
        self.assertEqual(stock_record.quantity_on_hand, Decimal('10.00'))
        self.assertEqual(stock_record.warehouse, self.warehouse)
