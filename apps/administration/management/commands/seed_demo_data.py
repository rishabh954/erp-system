import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from faker import Faker

from apps.authentication.models import User
from apps.company.models import Company
from apps.crm.models import Customer
from apps.helpdesk.models import Ticket, TicketCategory
from apps.inventory.models import (
    Product,
    ProductCategory,
    StockRecord,
    UnitOfMeasure,
    Warehouse,
)
from apps.manufacturing.models import (
    BillOfMaterial,
    BillOfMaterialLine,
    ManufacturingOrder,
)
from apps.purchase.models import PurchaseOrder, PurchaseOrderLine, Vendor
from apps.sales.models import SalesOrder, SalesOrderLine


class Command(BaseCommand):
    help = "Seeds the database with realistic demo data across all modules"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing demo data before seeding",
        )
        parser.add_argument(
            "--yes-i-know-this-is-destructive",
            action="store_true",
            dest="confirmed",
            help="Required in production (DEBUG=False) to prevent accidental seeding",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings

        # ── Production safety guard ──────────────────────────────────────────
        # Seeding demo data in production creates a known superuser account
        # (admin@acme.com / admin) and can overwrite real business data.
        # Block unless the operator explicitly passes --yes-i-know-this-is-destructive.
        if not settings.DEBUG and not options.get("confirmed"):
            self.stderr.write(
                self.style.ERROR(
                    "REFUSED: seed_demo_data will not run against a production database "
                    "(DEBUG=False) without explicit confirmation.\n"
                    "If you truly intend to seed a non-DEBUG environment, re-run with:\n"
                    "  --yes-i-know-this-is-destructive\n"
                    "WARNING: This will create the demo admin@acme.com / admin account."
                )
            )
            return

        fake = Faker()

        self.stdout.write(self.style.SUCCESS("Starting data seeding process..."))

        # 1. Company Setup
        company_name = "Acme Manufacturing Corp"
        if options["clear"]:
            self.stdout.write("Clearing existing Acme data...")
            Company.objects.filter(name=company_name).delete()

        company, created = Company.objects.get_or_create(
            name=company_name,
            defaults={"domain": "acme.test", "currency": "USD", "is_active": True},
        )
        self.stdout.write(self.style.SUCCESS(f"Company '{company.name}' ready."))

        # 2. Admin User
        admin_email = "admin@acme.com"
        admin_user = User.objects.filter(email=admin_email).first()
        if not admin_user:
            admin_user = User.objects.create_superuser(
                email=admin_email,
                password="admin",  # nosec B106
                first_name="Super",
                last_name="Admin",
            )
            admin_user.companies.add(company)
            admin_user.primary_company = company
            admin_user.save()
            self.stdout.write(
                self.style.SUCCESS("Admin user created (admin@acme.com / admin)")
            )

        # Add a couple of staff users
        staff = []
        for i in range(3):
            email = f"staff{i}@acme.com"
            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    "first_name": fake.first_name(),
                    "last_name": fake.last_name(),
                    "is_staff": True,
                    "role": "manager",
                },
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
            cust = Customer.objects.create(
                company=company,
                name=fake.company(),
                email=fake.company_email(),
                phone=fake.phone_number(),
                website=fake.url(),
                industry=fake.job(),
            )
            customers.append(cust)

        vendors = []
        for _ in range(10):
            vendor = Vendor.objects.create(
                company=company,
                name=fake.company() + " Supplier",
                email=fake.company_email(),
                phone=fake.phone_number(),
                payment_terms=30,
            )
            vendors.append(vendor)

        # 4. Inventory (Categories, UoMs, Warehouses, Products)
        self.stdout.write("Generating Inventory Data...")
        uom_pcs, _ = UnitOfMeasure.objects.get_or_create(
            company=company, name="Pieces", symbol="pcs"
        )
        cat_rm, _ = ProductCategory.objects.get_or_create(
            company=company, name="Raw Materials"
        )
        cat_fg, _ = ProductCategory.objects.get_or_create(
            company=company, name="Finished Goods"
        )

        warehouse, _ = Warehouse.objects.get_or_create(
            company=company, name="Main Factory Warehouse", code="MAIN"
        )

        # Products - Raw Materials
        raw_materials = []
        for i in range(15):
            rm = Product.objects.create(
                company=company,
                name=f"Component {fake.word().capitalize()}",
                sku=f"RM-{fake.random_int(1000, 9999)}",
                product_type="stockable",
                category=cat_rm,
                uom=uom_pcs,
                cost_price=Decimal(random.randint(1, 50)),
                sale_price=Decimal("0.00"),
                can_be_sold=False,
                can_be_purchased=True,
            )
            raw_materials.append(rm)
            # Add some stock
            StockRecord.objects.create(
                company=company,
                product=rm,
                warehouse=warehouse,
                quantity_on_hand=Decimal(random.randint(100, 1000)),
                average_cost=rm.cost_price,
            )

        # Products - Finished Goods
        finished_goods = []
        for i in range(5):
            fg = Product.objects.create(
                company=company,
                name=f"Acme {fake.word().capitalize()} Product",
                sku=f"FG-{fake.random_int(1000, 9999)}",
                product_type="stockable",
                category=cat_fg,
                uom=uom_pcs,
                cost_price=Decimal(random.randint(100, 300)),
                sale_price=Decimal(random.randint(400, 800)),
                can_be_sold=True,
                can_be_purchased=False,
            )
            finished_goods.append(fg)
            StockRecord.objects.create(
                company=company,
                product=fg,
                warehouse=warehouse,
                quantity_on_hand=Decimal(random.randint(0, 50)),
                average_cost=fg.cost_price,
            )

        # 5. Manufacturing (BOMs & MOs)
        self.stdout.write("Generating Manufacturing Data...")
        for fg in finished_goods:
            bom = BillOfMaterial.objects.create(
                company=company, product=fg, quantity=Decimal("1.00")
            )
            # Pick 3 random components
            comps = random.sample(raw_materials, 3)
            for comp in comps:
                BillOfMaterialLine.objects.create(
                    bom=bom,
                    component=comp,
                    quantity=Decimal(random.randint(1, 5)),
                    scrap_percentage=Decimal(random.randint(0, 5)),
                )

            # Create a Manufacturing Order for it
            status = random.choice(["draft", "confirmed", "in_progress", "done"])
            ManufacturingOrder.objects.create(
                company=company,
                product=fg,
                bom=bom,
                quantity_to_produce=Decimal(random.randint(10, 100)),
                status=status,
                planned_start_date=timezone.now().date()
                + timedelta(days=random.randint(-10, 10)),
            )

        # 6. Sales Orders
        self.stdout.write("Generating Sales Orders...")
        for i in range(15):
            order = SalesOrder.objects.create(
                company=company,
                customer=random.choice(customers),
                sales_rep=random.choice(staff),
                order_date=timezone.now().date()
                - timedelta(days=random.randint(1, 30)),
                status=random.choice(
                    ["draft", "confirmed", "shipped", "invoiced", "cancelled"]
                ),
            )
            # Add lines
            for _ in range(random.randint(1, 4)):
                prod = random.choice(finished_goods)
                SalesOrderLine.objects.create(
                    sales_order=order,
                    product=prod,
                    description=prod.name,
                    quantity=Decimal(random.randint(1, 20)),
                    unit_price=prod.sale_price,
                )
            order.recalculate_totals()

        # 7. Purchase Orders
        self.stdout.write("Generating Purchase Orders...")
        for i in range(10):
            order = PurchaseOrder.objects.create(
                company=company,
                vendor=random.choice(vendors),
                order_date=timezone.now().date()
                - timedelta(days=random.randint(1, 15)),
                status=random.choice(["draft", "confirmed", "received", "billed"]),
            )
            for _ in range(random.randint(1, 5)):
                prod = random.choice(raw_materials)
                PurchaseOrderLine.objects.create(
                    purchase_order=order,
                    product=prod,
                    description=prod.name,
                    quantity=Decimal(random.randint(50, 500)),
                    unit_price=prod.cost_price,
                )
            order.recalculate_totals()

        # 8. Helpdesk Tickets
        self.stdout.write("Generating Helpdesk Tickets...")
        cat_support, _ = TicketCategory.objects.get_or_create(
            company=company, name="General Support", sla_hours=24
        )
        for i in range(12):
            Ticket.objects.create(
                company=company,
                title=fake.sentence(),
                description=fake.paragraph(nb_sentences=3),
                category=cat_support,
                requester=admin_user,  # using admin as requester for simplicity
                assigned_to=random.choice(staff + [None]),
                priority=random.choice(["low", "medium", "high", "critical"]),
                status=random.choice(["open", "in_progress", "resolved", "closed"]),
                source="portal",
            )

        self.stdout.write(
            self.style.SUCCESS("Database seeding completed successfully!")
        )
        self.stdout.write("You can now log in with: admin@acme.com / admin")
