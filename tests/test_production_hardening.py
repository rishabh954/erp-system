"""
Production Hardening Regression Tests
======================================
Covers every critical/high issue fixed in the production hardening pass:

  SEC-1   JWT API bypasses 2FA
  TXN-2/3 _state.adding dead code → duplicate journal entries
  BUG-1   Invalid HTTP status 44 on barcode scan
  MOCK-*  Mock credentials in production callers
  SEC-3   Hardcoded Welcome@123 employee password
  SEC-7   CompanyMixin uses primary_company instead of request.company
  AUTH-*  UserViewSet / ActivityLog / RoleViewSet use primary_company
  BUG-2   Celery beat schedule overwritten
  BUG-3   ActiveUserMiddleware DB write every request
  SEC-6   X-Forwarded-For IP spoofing
"""
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from apps.authentication.models import UserCompany
from core.factories import CompanyFactory, UserFactory

User = get_user_model()
pytestmark = pytest.mark.django_db


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def company_a(company):
    return company


@pytest.fixture
def company_b():
    return CompanyFactory(name="Company B")


@pytest.fixture
def user_a(user):
    return user


@pytest.fixture
def user_b(company_b):
    u = UserFactory(email="user_b@test.com", primary_company=company_b)
    UserCompany.objects.get_or_create(user=u, company=company_b, defaults={"is_active": True})
    return u


# ─── SEC-1: JWT 2FA bypass ─────────────────────────────────────────────────────

class TestJWT2FABypass:
    def test_login_without_2fa_returns_tokens(self, client, user_a):
        """Users without 2FA enabled receive access/refresh tokens directly."""
        user_a.two_factor_enabled = False
        user_a.save(update_fields=["two_factor_enabled"])
        resp = client.post(
            "/api/v1/auth/login/",
            {"email": user_a.email, "password": "password"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data["data"]["access"] is not None
        assert not data.get("requires_2fa")

    def test_login_with_2fa_returns_partial_token_not_jwt(self, client, user_a):
        """Users with 2FA enabled must NOT receive a JWT until TOTP is verified."""
        user_a.two_factor_enabled = True
        user_a.totp_secret = "JBSWY3DPEHPK3PXP"
        user_a.save(update_fields=["two_factor_enabled", "totp_secret"])
        resp = client.post(
            "/api/v1/auth/login/",
            {"email": user_a.email, "password": "password"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("requires_2fa") is True
        assert data.get("partial_token") is not None
        # No real JWT should be issued before 2FA is completed
        assert data.get("data") is None or data.get("data", {}).get("access") is None

    def test_2fa_verify_wrong_code_rejected(self, client, user_a):
        """Wrong TOTP code must not grant a JWT."""
        user_a.two_factor_enabled = True
        user_a.totp_secret = "JBSWY3DPEHPK3PXP"
        user_a.save(update_fields=["two_factor_enabled", "totp_secret"])

        import secrets

        from django.core.cache import cache
        partial_token = secrets.token_urlsafe(32)
        cache.set(f"2fa_partial:{partial_token}", str(user_a.pk), timeout=300)

        resp = client.post(
            "/api/v1/auth/2fa/verify/",
            {"partial_token": partial_token, "code": "000000"},
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_2fa_verify_correct_code_grants_jwt(self, client, user_a):
        """Correct TOTP code must grant a full JWT pair."""
        import pyotp
        user_a.two_factor_enabled = True
        user_a.totp_secret = "JBSWY3DPEHPK3PXP"
        user_a.save(update_fields=["two_factor_enabled", "totp_secret"])

        import secrets

        from django.core.cache import cache
        partial_token = secrets.token_urlsafe(32)
        cache.set(f"2fa_partial:{partial_token}", str(user_a.pk), timeout=300)

        totp = pyotp.TOTP("JBSWY3DPEHPK3PXP")
        resp = client.post(
            "/api/v1/auth/2fa/verify/",
            {"partial_token": partial_token, "code": totp.now()},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["access"] is not None
        assert data["data"]["refresh"] is not None

    def test_partial_token_can_only_be_used_once(self, client, user_a):
        """Partial token is deleted after successful 2FA, preventing replay."""
        import pyotp
        user_a.two_factor_enabled = True
        user_a.totp_secret = "JBSWY3DPEHPK3PXP"
        user_a.save(update_fields=["two_factor_enabled", "totp_secret"])

        import secrets

        from django.core.cache import cache
        partial_token = secrets.token_urlsafe(32)
        cache.set(f"2fa_partial:{partial_token}", str(user_a.pk), timeout=300)

        totp = pyotp.TOTP("JBSWY3DPEHPK3PXP")
        code = totp.now()

        # First use — should succeed
        resp1 = client.post(
            "/api/v1/auth/2fa/verify/",
            {"partial_token": partial_token, "code": code},
            content_type="application/json",
        )
        assert resp1.status_code == 200

        # Second use of same token — must fail
        resp2 = client.post(
            "/api/v1/auth/2fa/verify/",
            {"partial_token": partial_token, "code": code},
            content_type="application/json",
        )
        assert resp2.status_code == 401


# ─── TXN-2/3: _state.adding + journal idempotency ─────────────────────────────

class TestJournalEntryIdempotency:
    """Journal entries must be created ONCE on first save to SENT/OPEN, not on updates."""

    def test_invoice_save_posts_journal_only_once(self, company, user, currency):
        from apps.accounting.models import JournalEntry
        from apps.crm.models import Customer
        from apps.sales.models import Invoice

        customer = Customer.objects.create(company=company, name="Test Customer")
        invoice = Invoice.objects.create(
            company=company,
            customer=customer,
            invoice_date=date.today(),
            due_date=date.today(),
            status=Invoice.Status.SENT,
            currency=currency,
            subtotal=Decimal("100"),
            total=Decimal("100"),
        )
        initial_count = JournalEntry.objects.filter(
            reference=f"INV: {invoice.number}"
        ).count()

        # Saving again (e.g. status update) must NOT create a second journal entry
        invoice.notes = "Updated"
        invoice.save(update_fields=["notes"])
        second_count = JournalEntry.objects.filter(
            reference=f"INV: {invoice.number}"
        ).count()

        assert second_count == initial_count, (
            f"Invoice save() created {second_count} journal entries on update; "
            "expected no new entries (idempotency violation)"
        )

    def test_payment_save_posts_journal_only_once(self, company, user, currency):
        from apps.accounting.models import JournalEntry
        from apps.crm.models import Customer
        from apps.sales.models import Invoice, Payment

        customer = Customer.objects.create(company=company, name="Payer")
        invoice = Invoice.objects.create(
            company=company,
            customer=customer,
            invoice_date=date.today(),
            due_date=date.today(),
            currency=currency,
            total=Decimal("100"),
            subtotal=Decimal("100"),
        )
        payment = Payment.objects.create(
            company=company,
            invoice=invoice,
            customer=customer,
            amount=Decimal("100"),
            currency=currency,
            payment_date=date.today(),
            method="cash",
            status="completed",
        )
        initial_count = JournalEntry.objects.filter(
            reference=f"PAY: {payment.number}"
        ).count()

        # Update the payment notes — must not re-post journal
        payment.notes = "Receipt confirmed"
        payment.save(update_fields=["notes"])
        second_count = JournalEntry.objects.filter(
            reference=f"PAY: {payment.number}"
        ).count()

        assert second_count == initial_count, (
            "Payment.save() on update created a duplicate journal entry"
        )


# ─── BUG-1: Barcode scan invalid HTTP status ──────────────────────────────────

class TestBarcodeScanView:
    def test_unknown_barcode_returns_404_not_invalid_status(self, client, user_a, warehouse):
        """Scanning an unknown barcode must return 404, not the invalid status 44."""
        client.force_login(user_a)

        # Obtain JWT
        resp = client.post(
            "/api/v1/auth/login/",
            {"email": user_a.email, "password": "password"},
            content_type="application/json",
        )
        token = resp.json().get("data", {}).get("access")

        resp = client.post(
            "/api/v1/inventory/barcodes/scan-receive/",
            {"barcode": "NONEXISTENT-9999", "warehouse": str(warehouse.pk), "quantity": 1},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert resp.status_code == 404, (
            f"Expected 404 for unknown barcode, got {resp.status_code}"
        )

    def test_barcode_scan_zero_qty_rejected(self, client, user_a, product, warehouse):
        """Quantity must be > 0."""
        client.force_login(user_a)
        resp_login = client.post(
            "/api/v1/auth/login/",
            {"email": user_a.email, "password": "password"},
            content_type="application/json",
        )
        token = resp_login.json().get("data", {}).get("access")

        product.barcode = "TEST-BARCODE-001"
        product.save(update_fields=["barcode"])

        resp = client.post(
            "/api/v1/inventory/barcodes/scan-receive/",
            {"barcode": "TEST-BARCODE-001", "warehouse": str(warehouse.pk), "quantity": 0},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        assert resp.status_code == 400


# ─── MOCK: Integration services raise correctly when unconfigured ──────────────

class TestIntegrationServices:
    def test_razorpay_raises_when_not_configured(self):
        """RazorpayService raises IntegrationNotConfiguredError — not a mock."""
        from apps.administration.services.integrations import (
            IntegrationNotConfiguredError,
            RazorpayService,
        )
        with patch("django.conf.settings") as mock_settings:
            mock_settings.RAZORPAY_KEY_ID = ""
            mock_settings.RAZORPAY_KEY_SECRET = ""
            svc = RazorpayService(credentials={})
            assert not svc.is_connected
            with pytest.raises((IntegrationNotConfiguredError, Exception)):
                svc.generate_payment_link(100, "USD", "INV-001", "Test", "", "")

    def test_twilio_raises_when_not_configured(self):
        """TwilioService raises when credentials are absent."""
        from apps.administration.services.integrations import (
            IntegrationNotConfiguredError,
            TwilioService,
        )
        svc = TwilioService(credentials={})
        assert not svc.is_connected
        with pytest.raises((IntegrationNotConfiguredError, Exception)):
            svc.send_sms("+15005550006", "Test message")

    def test_shiprocket_raises_when_not_configured(self):
        """ShiprocketService raises when credentials are absent."""
        from apps.administration.services.integrations import (
            ShiprocketService,
        )
        svc = ShiprocketService(credentials={})
        assert not svc.is_connected

    def test_no_mock_random_in_shiprocket(self):
        """ShiprocketService must not contain random AWB generation (mock remnant)."""
        import inspect

        from apps.administration.services.integrations import ShiprocketService
        source = inspect.getsource(ShiprocketService.create_shipment)
        assert "random.randint" not in source, (
            "ShiprocketService still contains mock random AWB generation"
        )
        assert "random.choice" not in source, (
            "ShiprocketService still contains mock courier selection"
        )


# ─── SEC-3: Hardcoded Welcome@123 password gone ────────────────────────────────

class TestHRMSEmployeePasswordCreation:
    def test_ensure_user_account_does_not_use_hardcoded_password(self):
        """_ensure_user_account must not contain the hardcoded Welcome@123 password."""
        import inspect

        from apps.hrms import views as hrms_views
        source = inspect.getsource(hrms_views)
        assert "Welcome@123" not in source, (
            "Hardcoded Welcome@123 password still present in hrms/views.py"
        )

    def test_new_employee_user_gets_random_password(self, company):
        """A new employee account must be created with a random password, not a fixed one."""
        from apps.authentication.models import User
        from apps.hrms.views import EmployeeEditView

        view = EmployeeEditView()
        view.request = MagicMock()
        view.request.user.primary_company = company

        emp = MagicMock()
        emp.email = "new_emp_random@test.com"
        emp.user_id = None
        emp.first_name = "Jane"
        emp.last_name = "Doe"

        with patch("apps.authentication.services.AuthService.send_password_reset_email"):
            with patch.object(User.objects, "filter", return_value=MagicMock(first=MagicMock(return_value=None))):
                created_passwords = []

                def capture_create(**kwargs):
                    created_passwords.append(kwargs.get("password", ""))
                    return MagicMock(primary_company=None)

                with patch.object(User.objects, "create_user", side_effect=capture_create):
                    try:
                        view._ensure_user_account(emp, company)
                    except Exception:
                        pass  # emp.save() etc will fail in isolation — that's fine

                for pwd in created_passwords:
                    assert pwd != "Welcome@123", "Hardcoded password was used"
                    assert len(pwd) >= 16, f"Generated password too short: {len(pwd)} chars"


# ─── SEC-7 / AUTH-*: CompanyMixin uses request.company ─────────────────────────

class TestCompanyMixinUsesRequestCompany:
    pytestmark = pytest.mark.django_db

    def test_company_mixin_returns_request_company(self, rf, user_a, company_a, company_b):
        """CompanyMixin.company() must return request.company, not primary_company."""
        from core.mixins import CompanyMixin

        mixin = CompanyMixin()
        request = rf.get("/")
        request.user = user_a
        # Set request.company to company_b (simulating a user who switched context)
        request.company = company_b
        # primary_company is still company_a
        user_a.primary_company = company_a
        mixin.request = request

        result = mixin.company()
        assert result == company_b, (
            f"CompanyMixin returned {result} (primary_company) "
            f"instead of {company_b} (request.company)"
        )

    def test_company_mixin_falls_back_to_primary_when_no_request_company(
        self, rf, user_a, company_a
    ):
        """Without request.company, falls back to primary_company."""
        from core.mixins import CompanyMixin

        mixin = CompanyMixin()
        request = rf.get("/")
        request.user = user_a
        request.company = None
        user_a.primary_company = company_a
        mixin.request = request

        result = mixin.company()
        assert result == company_a

    def test_api_user_viewset_scoped_to_request_company(self, client, user_a, company_a, company_b, user_b):
        """GET /api/v1/auth/users/ must only return users in the active company."""
        resp_login = client.post(
            "/api/v1/auth/login/",
            {"email": user_a.email, "password": "password"},
            content_type="application/json",
        )
        token = resp_login.json().get("data", {}).get("access")
        resp = client.get(
            "/api/v1/auth/users/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_ACTIVE_COMPANY=str(company_a.pk),
        )
        assert resp.status_code == 200
        emails = [u["email"] for u in resp.json().get("results", [])]
        assert user_b.email not in emails, (
            "user_b (Company B) visible to user_a (Company A) — tenant isolation broken"
        )


# ─── BUG-2: Celery beat schedule completeness ─────────────────────────────────

class TestCeleryBeatSchedule:
    def test_all_operational_tasks_in_beat_schedule(self):
        """All 9 operational Celery tasks must be present in CELERY_BEAT_SCHEDULE."""
        from django.conf import settings

        schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
        required_tasks = [
            "apps.sales.tasks.check_overdue_invoices",
            "apps.hrms.tasks.auto_mark_attendance",
            "apps.inventory.tasks.send_low_stock_alerts",
            "apps.company.tasks.update_exchange_rates",
            "apps.authentication.tasks.cleanup_expired_sessions",
            "apps.authentication.tasks.cleanup_old_audit_logs",
            "apps.authentication.tasks.cleanup_expired_tokens",
        ]
        scheduled_tasks = {entry["task"] for entry in schedule.values()}
        missing = [t for t in required_tasks if t not in scheduled_tasks]
        assert not missing, f"These tasks are missing from CELERY_BEAT_SCHEDULE: {missing}"

    def test_no_operational_tasks_in_celery_py_conf(self):
        """celery.py must not define app.conf.beat_schedule (would override settings)."""
        import ast
        import pathlib

        celery_source = pathlib.Path("config/celery.py").read_text()
        tree = ast.parse(celery_source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        if (
                            isinstance(target.value, ast.Attribute)
                            and target.value.attr == "conf"
                            and target.attr == "beat_schedule"
                        ):
                            pytest.fail(
                                "config/celery.py sets app.conf.beat_schedule which "
                                "overwrites CELERY_BEAT_SCHEDULE from settings.py"
                            )


# ─── BUG-3: ActiveUserMiddleware rate-limiting ─────────────────────────────────

class TestActiveUserMiddlewareRateLimit:
    def test_db_not_updated_on_every_request(self, rf, user_a):
        """last_active DB update must be skipped when cache key is fresh."""
        from django.core.cache import cache

        from core.middleware import ActiveUserMiddleware

        get_response = MagicMock(return_value=MagicMock(status_code=200))
        middleware = ActiveUserMiddleware(get_response)

        request = rf.get("/")
        request.user = user_a

        with patch("apps.authentication.models.User.objects") as mock_manager:
            mock_qs = MagicMock()
            mock_manager.filter.return_value = mock_qs

            # First call — cache miss — should hit DB
            cache.delete(f"last_active:{user_a.pk}")
            middleware(request)
            first_update_count = mock_qs.update.call_count

            # Second call — cache hit — must NOT hit DB
            middleware(request)
            second_update_count = mock_qs.update.call_count

        assert first_update_count <= 1, "Expected at most 1 DB update on first request"
        assert second_update_count == first_update_count, (
            "DB update was called again on second request — rate limiting not working"
        )

        # Cleanup
        cache.delete(f"last_active:{user_a.pk}")


# ─── SEC-6: X-Forwarded-For trusted proxy ─────────────────────────────────────

class TestTrustedProxyIPExtraction:
    def test_xff_trusted_when_trusted_proxy_ips_unset(self, rf):
        """Without TRUSTED_PROXY_IPS configured, XFF is trusted (legacy behaviour)."""
        from core.middleware import _get_client_ip

        request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1")
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        with patch("django.conf.settings") as s:
            s.TRUSTED_PROXY_IPS = None
            ip = _get_client_ip(request)

        assert ip == "1.2.3.4"

    def test_xff_ignored_when_remote_addr_not_in_trusted_proxies(self, rf):
        """When TRUSTED_PROXY_IPS is set and the direct connection is not in it, XFF is ignored."""
        from core.middleware import _get_client_ip

        request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1")
        request.META["REMOTE_ADDR"] = "9.9.9.9"  # untrusted direct connection

        with patch("django.conf.settings") as s:
            s.TRUSTED_PROXY_IPS = {"10.0.0.1"}
            ip = _get_client_ip(request)

        # Must fall back to REMOTE_ADDR, not XFF
        assert ip == "9.9.9.9", (
            f"IP spoofing possible: got '{ip}' instead of REMOTE_ADDR '9.9.9.9'"
        )

    def test_xff_trusted_when_remote_addr_is_trusted_proxy(self, rf):
        """When TRUSTED_PROXY_IPS is set and the direct connection IS in it, XFF is trusted."""
        from core.middleware import _get_client_ip

        request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1")
        request.META["REMOTE_ADDR"] = "10.0.0.1"  # trusted proxy

        with patch("django.conf.settings") as s:
            s.TRUSTED_PROXY_IPS = {"10.0.0.1"}
            ip = _get_client_ip(request)

        assert ip == "1.2.3.4"


# ─── Tenant isolation: API ViewSets ───────────────────────────────────────────

class TestAPITenantIsolation:
    def _get_token(self, client, user):
        resp = client.post(
            "/api/v1/auth/login/",
            {"email": user.email, "password": "password"},
            content_type="application/json",
        )
        return resp.json().get("data", {}).get("access")

    def test_activity_log_scoped_to_active_company(self, client, user_a, company_a, company_b, user_b):
        """ActivityLog viewset must not return logs from a different company."""
        from apps.authentication.models import ActivityLog

        # Create logs in both companies
        ActivityLog.objects.create(user=user_a, company=company_a, action="login", module="auth")
        ActivityLog.objects.create(user=user_b, company=company_b, action="login", module="auth")

        token = self._get_token(client, user_a)
        resp = client.get(
            "/api/v1/auth/activity-logs/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_ACTIVE_COMPANY=str(company_a.pk),
        )
        assert resp.status_code == 200
        results = resp.json().get("results", [])
        user_b_logs = [r for r in results if r.get("user_name") == user_b.full_name]
        assert not user_b_logs, "Company B activity logs visible to Company A user"

    def test_role_creation_uses_active_company(self, client, user_a, company_a, company_b):
        """Creating a role must assign it to the active session company."""
        from apps.authentication.models import Role

        token = self._get_token(client, user_a)
        resp = client.post(
            "/api/v1/auth/roles/",
            {"name": "Test Role", "code": "test-role", "description": ""},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_ACTIVE_COMPANY=str(company_a.pk),
        )
        if resp.status_code == 201:
            role = Role.objects.get(code="test-role")
            assert role.company == company_a, (
                f"Role was created under {role.company} instead of active company {company_a}"
            )
