#!/usr/bin/env python
"""
Minimal script to verify sales view logic without pytest overhead.
This confirms that company scoping is properly enforced.
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DB_HOST", "sqlite")
os.environ.setdefault("DB_ENGINE", "django.db.backends.sqlite3")

django.setup()

from datetime import date, timedelta
from decimal import Decimal
from django.test import RequestFactory, TestCase
from django.contrib.auth.models import AnonymousUser

from apps.authentication.models import User, UserCompany
from apps.company.models import Company, Currency
from apps.crm.models import Customer
from apps.sales.models import Invoice
from apps.sales.views import InvoiceDetailView, RecordPaymentView
from core.factories import CompanyFactory, UserFactory


def test_invoice_cross_company_isolation():
    """Verify that accessing another company's invoice returns 404."""
    print("\n[TEST] Invoice cross-company isolation...")
    
    # Create two companies
    company_a = CompanyFactory(name="Company A")
    company_b = CompanyFactory(name="Company B")
    
    # Create admin user for Company A
    user_a = UserFactory(
        email="admin_a@example.com",
        primary_company=company_a,
        role=User.Role.COMPANY_ADMIN,
    )
    UserCompany.objects.create(
        user=user_a,
        company=company_a,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    
    # Create currency
    currency, _ = Currency.objects.get_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "is_base": True},
    )
    
    # Create customer in Company B
    customer_b = Customer.objects.create(company=company_b, name="Customer B")
    
    # Create invoice in Company B
    invoice_b = Invoice.objects.create(
        company=company_b,
        customer=customer_b,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=Invoice.Status.SENT,
        currency=currency,
        subtotal=Decimal("999.00"),
        total=Decimal("999.00"),
        balance_due=Decimal("999.00"),
    )
    
    # Mock a request with Company A user
    factory = RequestFactory()
    request = factory.get(f"/sales/invoices/{invoice_b.pk}/")
    request.user = user_a
    request.company = company_a  # User is logged into Company A
    request.session = {"active_company_id": str(company_a.pk)}
    
    # Try to access invoice from Company B via InvoiceDetailView
    view = InvoiceDetailView()
    view.request = request
    view.kwargs = {"pk": str(invoice_b.pk)}
    
    try:
        obj = view.get_object()
        print("❌ FAIL: Should have raised Http404 but got object:", obj)
        return False
    except Exception as e:
        if "404" in str(type(e).__name__) or "Http404" in str(type(e).__name__):
            print("✓ PASS: Correctly raised Http404 for cross-company access")
            return True
        else:
            print(f"❌ FAIL: Wrong exception type: {type(e).__name__}: {e}")
            return False


def test_invoice_own_company_access():
    """Verify that accessing own company's invoice works."""
    print("\n[TEST] Invoice own-company access...")
    
    # Create one company
    company_a = CompanyFactory(name="Company A")
    
    # Create admin user for Company A
    user_a = UserFactory(
        email="admin_a2@example.com",
        primary_company=company_a,
        role=User.Role.COMPANY_ADMIN,
    )
    UserCompany.objects.create(
        user=user_a,
        company=company_a,
        role=User.Role.COMPANY_ADMIN,
        is_active=True,
    )
    
    # Create currency
    currency, _ = Currency.objects.get_or_create(
        code="USD",
        defaults={"name": "US Dollar", "symbol": "$", "is_base": True},
    )
    
    # Create customer in Company A
    customer_a = Customer.objects.create(company=company_a, name="Customer A")
    
    # Create invoice in Company A
    invoice_a = Invoice.objects.create(
        company=company_a,
        customer=customer_a,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        status=Invoice.Status.SENT,
        currency=currency,
        subtotal=Decimal("200.00"),
        total=Decimal("200.00"),
        balance_due=Decimal("200.00"),
    )
    
    # Mock a request with Company A user
    factory = RequestFactory()
    request = factory.get(f"/sales/invoices/{invoice_a.pk}/")
    request.user = user_a
    request.company = company_a  # User is logged into Company A
    request.session = {"active_company_id": str(company_a.pk)}
    
    # Try to access invoice from Company A via InvoiceDetailView
    view = InvoiceDetailView()
    view.request = request
    view.kwargs = {"pk": str(invoice_a.pk)}
    
    try:
        obj = view.get_object()
        print(f"✓ PASS: Successfully retrieved own invoice: {obj.number}")
        return True
    except Exception as e:
        print(f"❌ FAIL: Should not have raised exception but got: {type(e).__name__}: {e}")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("SALES VIEW LOGIC VERIFICATION")
    print("=" * 70)
    
    results = []
    results.append(test_invoice_cross_company_isolation())
    results.append(test_invoice_own_company_access())
    
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    if passed == total:
        print("✓ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)
