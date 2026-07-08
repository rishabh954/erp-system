import factory

from apps.accounting.models import Account, Journal
from apps.authentication.models import User
from apps.company.models import Company
from apps.crm.models import Customer
from apps.inventory.models import Product, Warehouse
from apps.purchase.models import Vendor


class CompanyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Company

    name = factory.Faker("company")
    company_type = Company.CompanyType.LLC


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name")
    last_name = factory.Faker("last_name")
    role = User.Role.EMPLOYEE
    is_active = True

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        password = extracted if extracted else "password123"
        self.set_password(password)
        if create:
            self.save()


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    company = factory.SubFactory(CompanyFactory)
    name = factory.Faker("word")
    sku = factory.Sequence(lambda n: f"SKU-{n}")
    product_type = Product.ProductType.STOCKABLE


class WarehouseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Warehouse

    company = factory.SubFactory(CompanyFactory)
    name = factory.Faker("company")
    code = factory.Sequence(lambda n: f"WH-{n}")


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer

    company = factory.SubFactory(CompanyFactory)
    name = factory.Faker("name")
    email = factory.Sequence(lambda n: f"customer{n}@example.com")


class VendorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Vendor

    company = factory.SubFactory(CompanyFactory)
    name = factory.Faker("company")
    vendor_code = factory.Sequence(lambda n: f"VEN-{n}")


class AccountFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Account

    company = factory.SubFactory(CompanyFactory)
    name = factory.Faker("word")
    code = factory.Sequence(lambda n: f"ACC-{n}")
    account_type = Account.AccountType.ASSET


class JournalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Journal

    company = factory.SubFactory(CompanyFactory)
    name = factory.Faker("word")
    code = factory.Sequence(lambda n: f"JNL-{n}")
    journal_type = Journal.JournalType.GENERAL
