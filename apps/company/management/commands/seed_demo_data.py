from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import random

try:
    from faker import Faker
    fake = Faker()
except ImportError:
    fake = None

class Command(BaseCommand):
    help = 'Seed the database with demo data'

    def handle(self, *args, **kwargs):
        if not fake:
            self.stdout.write(self.style.ERROR('Faker is not installed. Please run: pip install faker'))
            return
            
        self.stdout.write(self.style.NOTICE('Starting data seeding process...'))
        
        # Imports here to avoid app registry not ready errors
        from apps.company.models import Company, Branch, Department, Currency
        from apps.authentication.models import User, UserCompany
        from apps.hrms.models import Employee, JobTitle
        from apps.crm.models import Customer, Lead
        from apps.inventory.models import Product, Warehouse, UnitOfMeasure
        from apps.projects.models import Project, Task
        from apps.sales.models import SalesOrder, Quotation
        from django.db import transaction

        with transaction.atomic():
            # 1. Base Setup
            self.stdout.write('Seeding Company data...')
            currency, _ = Currency.objects.get_or_create(code='USD', defaults={'name': 'US Dollar', 'symbol': '$', 'exchange_rate': 1.0})
            
            company, created = Company.objects.get_or_create(
                name='Acme Corp Demo',
                defaults={
                    'trading_name': 'Acme Corporation',
                    'registration_number': 'ACME-12345',
                    'tax_id': 'TAX-98765',
                    'email': 'contact@acmecorp.demo',
                    'phone': '555-0100',
                    'website': 'https://acmecorp.demo',
                    'currency': currency,
                    'fiscal_year_start': 1
                }
            )
            
            branch_hq, _ = Branch.objects.get_or_create(
                company=company, name='Headquarters',
                defaults={'code': 'HQ', 'is_head_office': True}
            )
            
            dept_sales, _ = Department.objects.get_or_create(company=company, name='Sales', defaults={'code': 'SAL'})
            dept_it, _ = Department.objects.get_or_create(company=company, name='IT & Engineering', defaults={'code': 'ENG'})
            dept_hr, _ = Department.objects.get_or_create(company=company, name='Human Resources', defaults={'code': 'HR'})
            
            # 2. Users and HRMS
            self.stdout.write('Seeding Users and Employees...')
            job_engineer, _ = JobTitle.objects.get_or_create(company=company, name='Software Engineer')
            job_sales, _ = JobTitle.objects.get_or_create(company=company, name='Sales Representative')
            
            users = []
            for i in range(5):
                email = f'user{i}@acmecorp.demo'
                user, u_created = User.objects.get_or_create(
                    email=email,
                    defaults={
                        'first_name': fake.first_name(),
                        'last_name': fake.last_name(),
                        'role': User.Role.EMPLOYEE,
                        'primary_company': company
                    }
                )
                if u_created:
                    user.set_password('demo123')
                    user.save()
                    UserCompany.objects.create(user=user, company=company, branch=branch_hq)
                users.append(user)
                
                # Employee record
                Employee.objects.get_or_create(
                    company=company,
                    employee_id=f'EMP-{1000+i}',
                    defaults={
                        'user': user,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'department': dept_sales if i < 2 else dept_it,
                        'job_title': job_sales if i < 2 else job_engineer,
                        'joining_date': timezone.now().date() - timedelta(days=random.randint(100, 1000)),
                        'status': Employee.Status.ACTIVE
                    }
                )

            # 3. CRM & Inventory
            self.stdout.write('Seeding CRM and Inventory...')
            for i in range(5):
                Customer.objects.get_or_create(
                    company=company,
                    email=f'customer{i}@example.com',
                    defaults={
                        'name': fake.company(),
                        'phone': fake.phone_number(),
                        'customer_type': 'business',
                        'status': 'active'
                    }
                )
                Lead.objects.get_or_create(
                    company=company,
                    email=f'lead{i}@example.com',
                    defaults={
                        'name': fake.name(),
                        'company_name': fake.company(),
                        'status': Lead.Status.NEW,
                        'probability': random.randint(10, 80)
                    }
                )

            uom, _ = UnitOfMeasure.objects.get_or_create(company=company, name='Piece', code='PCS')
            warehouse, _ = Warehouse.objects.get_or_create(company=company, name='Main Warehouse', code='WH-MAIN')
            
            for i in range(5):
                Product.objects.get_or_create(
                    company=company,
                    sku=f'SKU-100{i}',
                    defaults={
                        'name': fake.word().capitalize() + ' Widget',
                        'type': 'stock',
                        'sale_price': random.randint(50, 500),
                        'cost_price': random.randint(10, 40),
                        'base_uom': uom
                    }
                )

            # 4. Projects
            self.stdout.write('Seeding Projects...')
            for i in range(2):
                project, _ = Project.objects.get_or_create(
                    company=company,
                    name=f'Implementation Project {i+1}',
                    defaults={
                        'status': Project.Status.ACTIVE,
                        'progress': random.randint(10, 90),
                        'start_date': timezone.now().date() - timedelta(days=30)
                    }
                )
                Task.objects.get_or_create(
                    company=company, project=project, title='Gather Requirements',
                    defaults={'status': Task.Status.DONE, 'assigned_to': users[0]}
                )
                Task.objects.get_or_create(
                    company=company, project=project, title='Development Phase 1',
                    defaults={'status': Task.Status.IN_PROGRESS, 'assigned_to': users[1]}
                )

        self.stdout.write(self.style.SUCCESS('Successfully seeded demo data!'))
