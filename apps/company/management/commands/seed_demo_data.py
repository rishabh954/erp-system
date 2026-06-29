from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker
import random
from decimal import Decimal
from datetime import timedelta

from apps.company.models import Company
from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse, StockRecord, ProductCategory, UnitOfMeasure
from apps.crm.models import Customer
from apps.sales.models import SalesOrder, SalesOrderLine
from apps.purchase.models import PurchaseOrder, PurchaseOrderLine, Vendor
from apps.manufacturing.models import BillOfMaterial, BillOfMaterialLine, ManufacturingOrder
from apps.helpdesk.models import Ticket, TicketCategory

class Command(BaseCommand):
    help = 'Seeds the database with realistic demo data across all modules'

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Clear existing demo data before seeding')

    @transaction.atomic
    def handle(self, *args, **options):
        fake = Faker()
        
        self.stdout.write(self.style.SUCCESS("Starting data seeding process..."))
        
        # 1. Company Setup
        company_name = "Acme Manufacturing Corp"
        if options['clear']:
            self.stdout.write("Clearing existing Acme data...")
            Company.objects.filter(name=company_name).delete()
            
        company, created = Company.objects.get_or_create(
            name=company_name,
            defaults={
                'status': 'active'
            }
        )
        self.stdout.write(self.style.SUCCESS(f"Company '{company.name}' ready."))

        # 2. Admin User
        admin_email = "admin@acme.com"
        admin_user = User.objects.filter(email=admin_email).first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                email=admin_email,
                password="admin",
                first_name="Super",
                last_name="Admin"
            )
            admin_user.companies.add(company)
            admin_user.primary_company = company
            admin_user.save()
            self.stdout.write(self.style.SUCCESS(f"Admin user created (admin@acme.com / admin)"))
        
        # Add a couple of staff users
        staff = []
        for i in range(3):
            email = f"staff{i}@acme.com"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': fake.first_name(),
                    'last_name': fake.last_name(),
                    'is_staff': True,
                    'role': 'manager'
                }
            )
            if created:
                user.set_password("password")
                user.save()
                user.companies.add(company)
                user.primary_company = company
                user.save()
            staff.append(user)

        # 3. CRMs (Customers & Vendors)
        self.stdout.write("Generating Customers and Vendors...")
        customers = []
        for _ in range(20):
            cust, _ = Customer.objects.get_or_create(
                company=company,
                name=fake.company(),
                defaults={
                    'email': fake.company_email(),
                    'phone': fake.phone_number(),
                    'website': fake.url()
                }
            )
            customers.append(cust)
            
        vendors = []
        for _ in range(10):
            vendor, _ = Vendor.objects.get_or_create(
                company=company,
                name=fake.company() + " Supplier",
                defaults={
                    'email': fake.company_email(),
                    'phone': fake.phone_number(),
                    'payment_terms': 30
                }
            )
            vendors.append(vendor)

        # 4. Inventory (Categories, UoMs, Warehouses, Products)
        self.stdout.write("Generating Inventory Data...")
        uom_pcs, _ = UnitOfMeasure.objects.get_or_create(company=company, name="Pieces", defaults={'abbreviation': "pcs"})
        cat_rm, _ = ProductCategory.objects.get_or_create(company=company, name="Raw Materials")
        cat_fg, _ = ProductCategory.objects.get_or_create(company=company, name="Finished Goods")
        
        warehouse, _ = Warehouse.objects.get_or_create(company=company, name="Main Factory Warehouse", code="MAIN")
        
        # Products - Raw Materials
        raw_materials = []
        for i in range(15):
            rm, _ = Product.objects.get_or_create(
                company=company,
                sku=f"RM-100{i}",
                defaults={
                    'name': f"Component {fake.word().capitalize()}",
                    'product_type': 'stockable',
                    'category': cat_rm,
                    'uom': uom_pcs,
                    'cost_price': Decimal(random.randint(1, 50)),
                    'sale_price': Decimal('0.00')
                }
            )
            raw_materials.append(rm)
            # Add some stock
            StockRecord.objects.get_or_create(
                company=company,
                product=rm,
                warehouse=warehouse,
                defaults={
                    'quantity_on_hand': Decimal(random.randint(100, 1000)),
                    'average_cost': rm.cost_price
                }
            )

        # Products - Finished Goods
        finished_goods = []
        for i in range(5):
            fg, _ = Product.objects.get_or_create(
                company=company,
                sku=f"FG-200{i}",
                defaults={
                    'name': f"Acme {fake.word().capitalize()} Product",
                    'product_type': 'stockable',
                    'category': cat_fg,
                    'uom': uom_pcs,
                    'cost_price': Decimal(random.randint(100, 300)),
                    'sale_price': Decimal(random.randint(400, 800))
                }
            )
            finished_goods.append(fg)
            StockRecord.objects.get_or_create(
                company=company,
                product=fg,
                warehouse=warehouse,
                defaults={
                    'quantity_on_hand': Decimal(random.randint(0, 50)),
                    'average_cost': fg.cost_price
                }
            )

        # 5. Manufacturing (BOMs & MOs)
        run_id = fake.random_int(10000, 99999)
        self.stdout.write("Generating Manufacturing Data...")
        for idx, fg in enumerate(finished_goods):
            bom, created = BillOfMaterial.objects.get_or_create(
                company=company,
                product=fg,
                defaults={'quantity': Decimal('1.00')}
            )
            if created:
                comps = random.sample(raw_materials, 3)
                for comp in comps:
                    BillOfMaterialLine.objects.create(
                        bom=bom,
                        component=comp,
                        quantity=Decimal(random.randint(1, 5)),
                        scrap_percentage=Decimal(random.randint(0, 5))
                    )
            
            status = random.choice(['draft', 'confirmed', 'in_progress', 'done'])
            ManufacturingOrder.objects.create(
                company=company,
                number=f"MO-{run_id}-{idx}",
                product=fg,
                bom=bom,
                quantity_to_produce=Decimal(random.randint(10, 100)),
                status=status,
                planned_start_date=timezone.now().date() + timedelta(days=random.randint(-10, 10))
            )

        # 6. Sales Orders
        self.stdout.write("Generating Sales Orders...")
        for i in range(15):
            order = SalesOrder.objects.create(
                company=company,
                number=f"SO-{run_id}-{i}",
                customer=random.choice(customers),
                sales_rep=random.choice(staff),
                order_date=timezone.now().date() - timedelta(days=random.randint(1, 30)),
                status=random.choice(['draft', 'confirmed', 'shipped', 'invoiced', 'cancelled'])
            )
            for _ in range(random.randint(1, 4)):
                prod = random.choice(finished_goods)
                SalesOrderLine.objects.create(
                    sales_order=order,
                    product=prod,
                    description=prod.name,
                    quantity=Decimal(random.randint(1, 20)),
                    unit_price=prod.sale_price
                )
            order.recalculate_totals()

        # 7. Purchase Orders
        self.stdout.write("Generating Purchase Orders...")
        for i in range(10):
            order = PurchaseOrder.objects.create(
                company=company,
                number=f"PO-{run_id}-{i}",
                vendor=random.choice(vendors),
                order_date=timezone.now().date() - timedelta(days=random.randint(1, 15)),
                status=random.choice(['draft', 'confirmed', 'received', 'billed'])
            )
            for _ in range(random.randint(1, 5)):
                prod = random.choice(raw_materials)
                PurchaseOrderLine.objects.create(
                    purchase_order=order,
                    product=prod,
                    description=prod.name,
                    quantity=Decimal(random.randint(50, 500)),
                    unit_price=prod.cost_price
                )
            order.recalculate_totals()

        # 8. Helpdesk Tickets
        self.stdout.write("Generating Helpdesk Tickets...")
        cat_support, _ = TicketCategory.objects.get_or_create(company=company, name="General Support", defaults={'sla_hours': 24})
        for i in range(12):
            Ticket.objects.create(
                company=company,
                title=fake.sentence(),
                description=fake.paragraph(nb_sentences=3),
                category=cat_support,
                requester=admin_user, 
                assigned_to=random.choice(staff + [None]),
                priority=random.choice(['low', 'medium', 'high', 'critical']),
                status=random.choice(['open', 'in_progress', 'resolved', 'closed']),
                source='portal'
            )

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
        self.stdout.write("You can now log in with: admin@acme.com / admin")
