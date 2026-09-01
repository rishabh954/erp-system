"""
Gap Hardening Regression Tests
================================
Covers the remaining gaps closed after the initial production hardening pass:

  GAP-1  TOTP secret stored in plain text → EncryptedCharField
  GAP-2  cancel_order releases full reservation even when order was partially shipped
  GAP-3  seed_demo_data runs without guard in production (DEBUG=False)
  GAP-4  TRUSTED_PROXY_IPS not documented / wired into settings
  GAP-6  FiscalYear.save() race condition — two concurrent saves both set is_current=True
  GAP-7  ActiveUserMiddleware updated last_active before the response was returned
  GAP-9  Integration credential env-vars absent from settings
"""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from apps.authentication.models import UserCompany
from core.factories import CompanyFactory, UserFactory

pytestmark = pytest.mark.django_db


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def company(db):
    return CompanyFactory()


@pytest.fixture
def user(db, company):
    from apps.authentication.models import User
    u = UserFactory(primary_company=company, role=User.Role.COMPANY_ADMIN)
    UserCompany.objects.get_or_create(user=u, company=company, defaults={"is_active": True})
    return u


@pytest.fixture
def currency(db):
    from apps.company.models import Currency
    c, _ = Currency.objects.get_or_create(
        code="USD", defaults={"name": "US Dollar", "symbol": "$", "is_base": True}
    )
    return c


@pytest.fixture
def warehouse(db, company):
    from apps.inventory.models import Warehouse
    return Warehouse.objects.create(company=company, name="Main WH", code="MAIN")


@pytest.fixture
def product(db, company):
    from apps.inventory.models import Product
    return Product.objects.create(
        company=company,
        name="Widget",
        sku="WDG-001",
        product_type="stockable",
        cost_price=Decimal("10"),
        sale_price=Decimal("20"),
    )


# ─── GAP-1: TOTP secret encryption ────────────────────────────────────────────

class TestTOTPSecretEncryption:
    def test_totp_secret_field_is_encrypted_char_field(self):
        """User.totp_secret must be an EncryptedCharField, not a plain CharField."""
        from apps.authentication.models import User
        from core.fields import EncryptedCharField
        field = User._meta.get_field("totp_secret")
        assert isinstance(field, EncryptedCharField), (
            f"totp_secret is {type(field).__name__}, expected EncryptedCharField. "
            "TOTP seeds stored in plain text are readable from any DB dump."
        )

    def test_totp_secret_is_encrypted_in_db(self, user):
        """The raw value in the DB must not equal the plaintext secret."""
        from django.db import connection
        secret = "JBSWY3DPEHPK3PXP"
        user.totp_secret = secret
        user.save(update_fields=["totp_secret"])

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT totp_secret FROM auth_users WHERE id = %s",
                [user.pk.hex],
            )
            row = cursor.fetchone()
            raw_db_value = row[0] if row else None

        assert raw_db_value != secret, (
            "totp_secret is stored as plain text in the database — encryption not working"
        )
        # Fernet tokens start with 'gAA'
        assert raw_db_value.startswith("gAA"), (
            f"DB value '{raw_db_value[:10]}...' does not look like a Fernet token"
        )

    def test_totp_secret_decrypts_correctly_on_read(self, user):
        """Reading the field back must return the original plaintext secret."""
        from apps.authentication.models import User
        secret = "JBSWY3DPEHPK3PXP"
        user.totp_secret = secret
        user.save(update_fields=["totp_secret"])

        refreshed = User.objects.get(pk=user.pk)
        assert refreshed.totp_secret == secret, (
            "totp_secret did not round-trip correctly through encryption/decryption"
        )

    def test_existing_plaintext_totp_secret_returned_as_is(self, user):
        """Plain-text values already in the DB (pre-migration) must be returned unchanged."""
        from django.db import connection
        plain_value = "PLAINTEXT_SECRET"
        # Write directly to bypass ORM encryption
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE auth_users SET totp_secret = %s WHERE id = %s",
                [plain_value, user.pk.hex],
            )

        from apps.authentication.models import User
        refreshed = User.objects.get(pk=user.pk)
        # decrypt_value falls through for non-Fernet strings
        assert refreshed.totp_secret == plain_value, (
            "Pre-encryption plain-text secrets should be returned as-is (graceful migration)"
        )

    def test_totp_secret_max_length_accommodates_ciphertext(self):
        """max_length must be >= 500 to hold Fernet ciphertext for a 32-char secret."""
        from apps.authentication.models import User
        field = User._meta.get_field("totp_secret")
        assert field.max_length >= 500, (
            f"totp_secret max_length={field.max_length}; need ≥500 for Fernet ciphertext"
        )


# ─── GAP-2: Partial cancellation reservation logic ────────────────────────────

class TestPartialCancellationReservation:
    def _make_order_with_reservation(self, company, user, product, warehouse):
        """Helper: confirmed order with 10 units reserved, 3 already delivered."""
        from apps.crm.models import Customer
        from apps.inventory.models import StockRecord
        from apps.sales.models import SalesOrder, SalesOrderLine

        # Put 20 units in stock and reserve 10
        record, _ = StockRecord.objects.get_or_create(
            company=company,
            product=product,
            warehouse=warehouse,
            defaults={"quantity_on_hand": Decimal("20"), "quantity_reserved": Decimal("0")},
        )
        record.quantity_on_hand = Decimal("20")
        record.quantity_reserved = Decimal("10")
        record.save()

        customer = Customer.objects.create(company=company, name="Test Customer")
        order = SalesOrder.objects.create(
            company=company,
            customer=customer,
            order_date=date.today(),
            status=SalesOrder.Status.PROCESSING,
        )
        line = SalesOrderLine.objects.create(
            sales_order=order,
            description="Widget",
            product=product,
            quantity=Decimal("10"),
            unit_price=Decimal("20"),
            qty_delivered=Decimal("3"),  # 3 already shipped
        )
        return order, line, record

    def test_cancel_releases_only_unshipped_quantity(self, company, user, product, warehouse):
        """cancel_order must release (ordered - delivered), not the full ordered qty."""
        from apps.sales.services import SalesOrderService

        order, line, record = self._make_order_with_reservation(
            company, user, product, warehouse
        )
        initial_reserved = record.quantity_reserved  # 10

        service = SalesOrderService(user=user, company=company)
        service.cancel_order(order, reason="test")

        record.refresh_from_db()
        # 10 ordered - 3 delivered = 7 should be released
        # So reserved should be: 10 - 7 = 3 (covers the 3 already delivered and not returned)
        expected_reserved = max(initial_reserved - (line.quantity - line.qty_delivered), 0)
        assert record.quantity_reserved == expected_reserved, (
            f"After partial cancellation: expected quantity_reserved={expected_reserved}, "
            f"got {record.quantity_reserved}. Full reservation was incorrectly released."
        )

    def test_cancel_does_not_produce_negative_reserved(self, company, user, product, warehouse):
        """quantity_reserved must never go negative after cancellation."""
        from apps.sales.services import SalesOrderService

        order, line, record = self._make_order_with_reservation(
            company, user, product, warehouse
        )
        # Manually set reserved lower than what would be released to test the clamp
        record.quantity_reserved = Decimal("2")
        record.save()

        service = SalesOrderService(user=user, company=company)
        service.cancel_order(order, reason="over-release test")

        record.refresh_from_db()
        assert record.quantity_reserved >= 0, (
            f"quantity_reserved went negative: {record.quantity_reserved}"
        )

    def test_cancel_draft_order_skips_reservation_release(self, company, user, product, warehouse):
        """Draft orders were never confirmed, so no reservation release should happen."""
        from apps.crm.models import Customer
        from apps.inventory.models import StockRecord
        from apps.sales.models import SalesOrder, SalesOrderLine
        from apps.sales.services import SalesOrderService

        record, _ = StockRecord.objects.get_or_create(
            company=company, product=product, warehouse=warehouse,
            defaults={"quantity_on_hand": Decimal("20"), "quantity_reserved": Decimal("5")},
        )
        record.quantity_reserved = Decimal("5")
        record.save()

        customer = Customer.objects.create(company=company, name="Draft Customer")
        order = SalesOrder.objects.create(
            company=company, customer=customer, order_date=date.today(),
            status=SalesOrder.Status.DRAFT,
        )
        SalesOrderLine.objects.create(
            sales_order=order, description="Widget", product=product,
            quantity=Decimal("5"), unit_price=Decimal("20"),
        )

        service = SalesOrderService(user=user, company=company)
        service.cancel_order(order, reason="draft cancel")

        record.refresh_from_db()
        assert record.quantity_reserved == Decimal("5"), (
            "Draft order cancellation incorrectly modified quantity_reserved"
        )


# ─── GAP-3: seed_demo_data production guard ───────────────────────────────────

class TestSeedDemoDataProductionGuard:
    def test_seed_command_blocked_when_debug_false_no_confirm(self):
        """seed_demo_data must refuse to run in production without --yes-i-know-this-is-destructive."""
        from django.core.management import call_command

        stderr = StringIO()
        with patch("django.conf.settings.DEBUG", False):
            call_command("seed_demo_data", stderr=stderr)

        output = stderr.getvalue()
        assert "REFUSED" in output, (
            "seed_demo_data did not print a REFUSED message when DEBUG=False "
            "and --yes-i-know-this-is-destructive was not passed"
        )

    def test_seed_command_blocked_message_mentions_flag(self):
        """The refusal message must name the bypass flag."""
        from django.core.management import call_command

        stderr = StringIO()
        with patch("django.conf.settings.DEBUG", False):
            call_command("seed_demo_data", stderr=stderr)

        assert "yes-i-know-this-is-destructive" in stderr.getvalue()

    def test_seed_command_runs_in_debug_mode(self):
        """In DEBUG mode the guard must not block execution."""
        from django.core.management import call_command

        from apps.company.models import Company

        stdout = StringIO()
        with patch("django.conf.settings.DEBUG", True):
            # Will actually seed — we just verify it doesn't hit the REFUSED path
            call_command("seed_demo_data", stdout=stdout)

        assert "REFUSED" not in stdout.getvalue()
        # Verify the demo company was actually created
        assert Company.objects.filter(name="Acme Manufacturing Corp").exists()

    def test_seed_command_runs_with_explicit_confirm(self):
        """With --yes-i-know-this-is-destructive the guard must be bypassed even in non-DEBUG."""
        from django.core.management import call_command

        from apps.company.models import Company

        stdout = StringIO()
        with patch("django.conf.settings.DEBUG", False):
            call_command(
                "seed_demo_data",
                confirmed=True,
                stdout=stdout,
            )

        assert "REFUSED" not in stdout.getvalue()
        assert Company.objects.filter(name="Acme Manufacturing Corp").exists()


# ─── GAP-6: FiscalYear race condition ─────────────────────────────────────────

class TestFiscalYearCurrentGuard:
    def test_only_one_fiscal_year_current_after_sequential_save(self, company):
        """Setting a new fiscal year as current must clear the old one."""
        from apps.company.models import FiscalYear

        fy1 = FiscalYear.objects.create(
            company=company,
            name="FY2023",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            is_current=True,
        )
        fy2 = FiscalYear.objects.create(
            company=company,
            name="FY2024",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            is_current=True,
        )

        fy1.refresh_from_db()
        fy2.refresh_from_db()

        assert fy2.is_current is True
        assert fy1.is_current is False, (
            "FY2023 still marked is_current=True after FY2024 was set as current"
        )

    def test_exactly_one_fiscal_year_current_per_company(self, company):
        """After saving multiple fiscal years, exactly one must be current."""
        from apps.company.models import FiscalYear

        for i, year in enumerate([2022, 2023, 2024]):
            FiscalYear.objects.create(
                company=company,
                name=f"FY{year}",
                start_date=date(year, 1, 1),
                end_date=date(year, 12, 31),
                is_current=(i == 2),  # only 2024 is current
            )

        current_count = FiscalYear.objects.filter(
            company=company, is_current=True
        ).count()
        assert current_count == 1, (
            f"Expected exactly 1 current fiscal year, found {current_count}"
        )

    def test_fiscal_year_save_uses_select_for_update(self):
        """FiscalYear.save() source must contain select_for_update to prevent races."""
        import inspect

        from apps.company.models import FiscalYear
        source = inspect.getsource(FiscalYear.save)
        assert "select_for_update" in source, (
            "FiscalYear.save() does not use select_for_update — "
            "concurrent saves can produce multiple is_current=True rows"
        )

    def test_non_current_fiscal_year_save_unchanged(self, company):
        """Saving a non-current fiscal year must not affect existing current year."""
        from apps.company.models import FiscalYear

        current_fy = FiscalYear.objects.create(
            company=company,
            name="FY2024",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            is_current=True,
        )
        non_current = FiscalYear.objects.create(
            company=company,
            name="FY2023",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            is_current=False,
        )

        # Update the non-current one without changing is_current
        non_current.name = "FY2023 Updated"
        non_current.save()

        current_fy.refresh_from_db()
        assert current_fy.is_current is True, (
            "Saving a non-current fiscal year incorrectly cleared the current one"
        )


# ─── GAP-4/5/9: Settings env-var completeness ─────────────────────────────────

class TestSettingsEnvVarCompleteness:
    """Verify all integration credentials are wired to env vars in settings."""

    def test_razorpay_settings_present(self):
        from django.conf import settings
        assert hasattr(settings, "RAZORPAY_KEY_ID"), "RAZORPAY_KEY_ID missing from settings"
        assert hasattr(settings, "RAZORPAY_KEY_SECRET"), "RAZORPAY_KEY_SECRET missing from settings"

    def test_shiprocket_settings_present(self):
        from django.conf import settings
        assert hasattr(settings, "SHIPROCKET_EMAIL"), "SHIPROCKET_EMAIL missing from settings"
        assert hasattr(settings, "SHIPROCKET_PASSWORD"), "SHIPROCKET_PASSWORD missing from settings"

    def test_twilio_settings_present(self):
        from django.conf import settings
        assert hasattr(settings, "TWILIO_ACCOUNT_SID"), "TWILIO_ACCOUNT_SID missing from settings"
        assert hasattr(settings, "TWILIO_AUTH_TOKEN"), "TWILIO_AUTH_TOKEN missing from settings"
        assert hasattr(settings, "TWILIO_SMS_FROM"), "TWILIO_SMS_FROM missing from settings"

    def test_whatsapp_settings_present(self):
        from django.conf import settings
        assert hasattr(settings, "WHATSAPP_ACCESS_TOKEN"), "WHATSAPP_ACCESS_TOKEN missing from settings"
        assert hasattr(settings, "WHATSAPP_PHONE_NUMBER_ID"), "WHATSAPP_PHONE_NUMBER_ID missing from settings"

    def test_trusted_proxy_ips_setting_present(self):
        from django.conf import settings
        # Must exist (even if None)
        assert hasattr(settings, "TRUSTED_PROXY_IPS"), "TRUSTED_PROXY_IPS missing from settings"

    def test_google_credentials_path_setting_present(self):
        from django.conf import settings
        assert hasattr(settings, "GOOGLE_CREDENTIALS_PATH"), (
            "GOOGLE_CREDENTIALS_PATH missing from settings — "
            "no env-var override path for Google service account key"
        )

    def test_no_hardcoded_integration_credentials_in_settings(self):
        """settings.py must not contain hardcoded API keys or tokens."""
        import pathlib
        settings_source = pathlib.Path("config/settings.py").read_text()
        forbidden_patterns = [
            "rzp_live_",     # Razorpay live key prefix
            "sk_live_",      # Stripe live secret key prefix
            "ACxxxxxxxx",    # Twilio placeholder (would indicate copy-paste error)
        ]
        for pattern in forbidden_patterns:
            assert pattern not in settings_source, (
                f"Found '{pattern}' in settings.py — potential hardcoded credential"
            )

    def test_integration_credentials_default_to_empty_string(self):
        """Integration credentials must default to '' (falsy) not a placeholder value."""
        from django.conf import settings
        credentials_to_check = [
            "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET",
            "SHIPROCKET_EMAIL", "SHIPROCKET_PASSWORD",
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
            "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID",
        ]
        for setting_name in credentials_to_check:
            value = getattr(settings, setting_name, None)
            # In the test environment these will be empty strings (no .env loaded)
            # The important thing is they are falsy — not "mock" or "changeme"
            assert not value or value not in ("mock", "changeme", "placeholder"), (
                f"settings.{setting_name} = '{value}' looks like a placeholder"
            )


# ─── GAP-7: ActiveUserMiddleware timing (update after response) ────────────────

class TestActiveUserMiddlewarePostResponse:
    def test_last_active_updated_after_response_returned(self, rf, user):
        """last_active must be updated AFTER get_response() returns, not before."""
        from django.core.cache import cache

        from core.middleware import ActiveUserMiddleware

        call_order = []

        def tracking_get_response(request):
            call_order.append("response")
            return MagicMock(status_code=200)

        middleware = ActiveUserMiddleware(tracking_get_response)
        request = rf.get("/")
        request.user = user

        # Patch _update_last_active to record when it's called
        @staticmethod
        def tracking_update(user_pk):
            call_order.append("db_update")

        with patch.object(ActiveUserMiddleware, "_update_last_active", new=tracking_update):
            cache.delete(f"last_active:{user.pk}")
            middleware(request)

        assert call_order == ["response", "db_update"], (
            f"Expected ['response', 'db_update'], got {call_order}. "
            "last_active is being updated BEFORE the response is returned."
        )
        cache.delete(f"last_active:{user.pk}")
