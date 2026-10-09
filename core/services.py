import logging
from decimal import Decimal
from typing import Any, Generic, TypeVar

from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=models.Model)


# ─── Base Repository ──────────────────────────────────────────────────────────


class BaseRepository(Generic[T]):  # noqa: UP046
    """
    Generic repository providing standard CRUD operations.
    All app-specific repositories extend this.
    """

    def __init__(self, model: type[T]):
        self.model = model

    def get_queryset(self) -> models.QuerySet:
        return self.model.objects.all()

    def get_by_id(self, pk) -> T | None:
        try:
            return self.get_queryset().get(pk=pk)
        except self.model.DoesNotExist:
            return None

    def get_by_company(self, company_id, **filters) -> models.QuerySet:
        return self.get_queryset().filter(company_id=company_id, **filters)

    def create(self, **data) -> T:
        instance = self.model(**data)
        instance.full_clean()
        instance.save()
        return instance

    def update(self, instance: T, **data) -> T:
        for field, value in data.items():
            setattr(instance, field, value)
        instance.full_clean()
        instance.save()
        return instance

    def delete(self, instance: T, user=None) -> None:
        if hasattr(instance, "delete") and callable(instance.delete):
            instance.delete(deleted_by=user)
        else:
            instance.delete()

    def bulk_create(self, instances: list[T]) -> list[T]:
        return self.model.objects.bulk_create(instances)

    def filter(self, **kwargs) -> models.QuerySet:
        return self.get_queryset().filter(**kwargs)

    def exists(self, **kwargs) -> bool:
        return self.get_queryset().filter(**kwargs).exists()

    def count(self, **kwargs) -> int:
        return self.get_queryset().filter(**kwargs).count()


# ─── Base Service ─────────────────────────────────────────────────────────────


class BaseService:
    """
    Base service class. All domain services extend this.
    Provides common helpers: audit logging, notifications, permission checks.
    """

    def __init__(self, user=None, company=None):
        self.user = user
        self.company = company

    def check_permission(self, module: str, action: str):
        """Raise PermissionDenied if user lacks permission."""
        if self.user and not self.user.is_superuser:
            if not self.user.has_module_permission(
                module, action, company=self.company
            ):
                raise PermissionDenied(
                    f"You do not have permission to {action} in module '{module}'"
                )

    def log_activity(
        self,
        action: str,
        module: str,
        resource_type: str = "",
        resource_id: Any = "",
        description: str = "",
        extra_data: dict = None,
    ):
        """Write an activity log entry."""
        from apps.authentication.models import ActivityLog

        try:
            ActivityLog.objects.create(
                user=self.user,
                company=self.company,
                action=action,
                module=module,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else "",
                description=description,
                extra_data=extra_data or {},
            )
        except Exception as e:
            logger.warning(f"Failed to write activity log: {e}")

    def send_notification(
        self,
        recipient,
        title: str,
        message: str,
        notification_type: str = "info",
        action_url: str = "",
        action_label: str = "",
        related_object=None,
    ):
        """Queue a notification through the central notification service."""
        from apps.notifications.services import NotificationService

        try:
            NotificationService.send(
                recipient=recipient,
                title=title,
                message=message,
                notification_type=notification_type,
                channels=["in_app"],
                action_url=action_url,
                action_label=action_label,
                company=self.company,
                related_object=related_object,
            )
        except Exception as e:
            logger.warning(f"Failed to create notification: {e}")

    def send_email(
        self,
        to_email: str,
        subject: str,
        template: str,
        context: dict,
        to_name: str = "",
    ):
        """Queue an email via the central notification service."""
        from apps.notifications.services import NotificationService

        NotificationService.send_email(
            recipient=to_email,
            subject=subject,
            message=context.get("message", ""),
            template=template,
            context=context,
            company=self.company,
            notification_type="info",
            recipient_name=to_name,
            use_preferences=False,
        )

    @staticmethod
    def generate_sequence_number(
        prefix: str, model_class, company_id, field_name: str = "number"
    ) -> str:
        """Atomically reserve the next numeric suffix for a company and prefix."""
        from apps.company.models import SequenceCounter

        with transaction.atomic():
            counter, _ = SequenceCounter.objects.get_or_create(
                company_id=company_id, prefix=prefix
            )
            counter = SequenceCounter.objects.select_for_update().get(pk=counter.pk)
            manager = getattr(model_class, "all_objects", None)
            if manager is None:
                manager = model_class._base_manager
            existing_numbers = manager.filter(
                company_id=company_id,
                **{f"{field_name}__startswith": f"{prefix}-"},
            ).values_list(field_name, flat=True)
            highest_suffix = 0
            prefix_with_separator = f"{prefix}-"
            for number in existing_numbers:
                suffix = number[len(prefix_with_separator) :]
                if suffix.isascii() and suffix.isdecimal():
                    highest_suffix = max(highest_suffix, int(suffix))

            counter.last_value = max(counter.last_value, highest_suffix) + 1
            counter.save(update_fields=["last_value"])
            seq = counter.last_value
            return f"{prefix}-{seq:05d}"


# ─── Currency Service ──────────────────────────────────────────────────────────


class CurrencyService:
    """
    Centralized service for formatting and converting currency.
    Follows enterprise software patterns for multi-currency handling.
    """

    @classmethod
    def get_company_currency(cls, company: Any | None) -> Any | None:
        """Retrieves the default currency for a given company."""
        if (
            company
            and hasattr(company, "default_currency")
            and company.default_currency
        ):
            return company.default_currency
        return None

    @classmethod
    def format(
        cls,
        amount: Decimal | float | int | str | None,
        company: Any | None = None,
    ) -> str:
        """
        Format a monetary amount according to the company's currency settings.
        Example: $1,234.56 or 1.234,56 €
        """
        if amount is None or amount == "":
            amount = Decimal("0.00")

        try:
            val = Decimal(str(amount))
        except (ValueError, TypeError):
            val = Decimal("0.00")

        currency = cls.get_company_currency(company)

        if not currency:
            return f"${val:,.2f}"

        symbol = currency.symbol
        decimals = currency.decimal_places

        format_str = f"{{:,.{decimals}f}}"
        formatted_val = format_str.format(val)

        return f"{symbol}{formatted_val}"

    @classmethod
    def convert_currency(
        cls, amount: Decimal, from_currency: Any, to_currency: Any, date=None
    ) -> Decimal:
        """
        Convert amount from one currency to another using ExchangeRates.
        """
        if from_currency == to_currency:
            return amount

        date = date or timezone.now().date()

        from apps.company.models import ExchangeRate

        rate_record = ExchangeRate.objects.filter(
            from_currency=from_currency,
            to_currency=to_currency,
            effective_date__lte=date,
        ).first()

        if rate_record:
            return amount * rate_record.rate

        inverse_rate = ExchangeRate.objects.filter(
            from_currency=to_currency,
            to_currency=from_currency,
            effective_date__lte=date,
        ).first()

        if inverse_rate and inverse_rate.rate:
            return amount / inverse_rate.rate

        raise ValueError(
            f"No exchange rate found from {from_currency.code} to {to_currency.code}"
        )

    @classmethod
    def format_for_pdf(cls, amount: Decimal, company: Any | None) -> str:
        return cls.format(amount, company)

    @classmethod
    def format_for_excel(cls, amount: Decimal) -> float:
        return float(amount)
