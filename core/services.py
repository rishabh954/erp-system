from typing import TypeVar, Generic, Optional, List, Dict, Any, Type
from django.db import models, transaction
from django.core.exceptions import ValidationError, PermissionDenied
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=models.Model)


# ─── Base Repository ──────────────────────────────────────────────────────────

class BaseRepository(Generic[T]):
    """
    Generic repository providing standard CRUD operations.
    All app-specific repositories extend this.
    """

    def __init__(self, model: Type[T]):
        self.model = model

    def get_queryset(self) -> models.QuerySet:
        return self.model.objects.all()

    def get_by_id(self, pk) -> Optional[T]:
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
        if hasattr(instance, 'delete') and callable(instance.delete):
            instance.delete(deleted_by=user)
        else:
            instance.delete()

    def bulk_create(self, instances: List[T]) -> List[T]:
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
            if not self.user.has_module_permission(module, action):
                raise PermissionDenied(
                    f"You do not have permission to {action} in module '{module}'"
                )

    def log_activity(self, action: str, module: str, resource_type: str = '',
                     resource_id: str = '', description: str = '', extra_data: dict = None):
        """Write an activity log entry."""
        from apps.authentication.models import ActivityLog
        try:
            ActivityLog.objects.create(
                user=self.user,
                company=self.company,
                action=action,
                module=module,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else '',
                description=description,
                extra_data=extra_data or {},
            )
        except Exception as e:
            logger.warning(f"Failed to write activity log: {e}")

    def send_notification(self, recipient, title: str, message: str,
                          notification_type: str = 'info', action_url: str = '',
                          action_label: str = '', related_object=None):
        """Queue an in-app notification."""
        from apps.notifications.models import Notification
        from django.contrib.contenttypes.models import ContentType
        try:
            kwargs = dict(
                company=self.company,
                recipient=recipient,
                notification_type=notification_type,
                title=title,
                message=message,
                action_url=action_url,
                action_label=action_label,
            )
            if related_object:
                kwargs['content_type'] = ContentType.objects.get_for_model(related_object)
                kwargs['object_id'] = str(related_object.pk)
            Notification.objects.create(**kwargs)
        except Exception as e:
            logger.warning(f"Failed to create notification: {e}")

    def send_email(self, to_email: str, subject: str, template: str,
                   context: dict, to_name: str = ''):
        """Queue an email via Celery."""
        from apps.notifications.tasks import send_email_task
        send_email_task.delay(
            to_email=to_email,
            to_name=to_name,
            subject=subject,
            template=template,
            context=context,
            company_id=str(self.company.pk) if self.company else None,
        )

    @staticmethod
    def generate_sequence_number(prefix: str, model_class, company_id) -> str:
        """Thread-safe sequence number generation."""
        with transaction.atomic():
            last = model_class.all_objects.select_for_update().filter(
                company_id=company_id,
                number__startswith=f"{prefix}-"
            ).order_by('-number').first()
            if last and last.number:
                try:
                    seq = int(last.number.split('-')[-1]) + 1
                except (ValueError, IndexError):
                    seq = 1
            else:
                seq = 1
            return f"{prefix}-{seq:05d}"
