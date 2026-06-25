"""
Core Service Layer
Base Service, Repository Pattern, Business Logic Utilities
Following SOLID principles and clean architecture
"""

from typing import TypeVar, Generic, Optional, List, Dict, Any, Type
from django.db import models, transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
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
    def generate_sequence_number(prefix: str, model_class, company_id, field_name='number') -> str:
        """Thread-safe sequence number generation."""
        doc_type_map = {
            'Quotation': 'quotation',
            'SalesOrder': 'sales_order',
            'Invoice': 'invoice',
            'CreditNote': 'credit_note',
            'PurchaseRequest': 'purchase_request',
            'PurchaseOrder': 'purchase_order',
            'Bill': 'bill',
            'DeliveryOrder': 'receipt',
            'Payment': 'payment',
            'JournalEntry': 'journal_entry',
            'Lead': 'lead',
            'Employee': 'employee',
            'Payslip': 'payslip',
            'LeaveRequest': 'leave_request',
            'ExpenseClaim': 'expense_claim',
            'ManufacturingOrder': 'mfg_order',
            'Asset': 'asset',
            'Ticket': 'helpdesk_ticket',
        }
        
        doc_type = doc_type_map.get(model_class.__name__)
        
        with transaction.atomic():
            if doc_type and company_id:
                try:
                    from apps.administration.models import NumberSeries
                    series = NumberSeries.objects.get(company_id=company_id, doc_type=doc_type, is_active=True)
                    return series.get_next_number()
                except Exception:
                    pass  # Fall back to legacy generation
            
            # We don't filter by company_id because 'number' is globally unique=True in SequenceMixin
            filter_kwargs = {f"{field_name}__startswith": f"{prefix}-"}
            last = model_class.all_objects.select_for_update().filter(**filter_kwargs).order_by('-created_at').first()
            
            if last and getattr(last, field_name):
                try:
                    # Sort issue: -number string sorting breaks when moving from 9 to 10
                    # So we ordered by -created_at instead.
                    # Wait, if we order by created_at, what if someone imports old records?
                    # Let's extract all numbers and find the max integer.
                    all_numbers = model_class.all_objects.select_for_update().filter(**filter_kwargs).values_list(field_name, flat=True)
                    
                    max_seq = 0
                    for num in all_numbers:
                        try:
                            seq_val = int(num.split('-')[-1])
                            if seq_val > max_seq:
                                max_seq = seq_val
                        except (ValueError, IndexError, AttributeError):
                            pass
                    seq = max_seq + 1
                except Exception:
                    seq = 1
            else:
                seq = 1
            return f"{prefix}-{seq:05d}"


# ─── Pagination ───────────────────────────────────────────────────────────────

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 200

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'page_size': self.get_page_size(self.request),
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        })

    def get_paginated_response_schema(self, schema):
        return {
            'type': 'object',
            'properties': {
                'count': {'type': 'integer'},
                'total_pages': {'type': 'integer'},
                'current_page': {'type': 'integer'},
                'next': {'type': 'string', 'nullable': True},
                'previous': {'type': 'string', 'nullable': True},
                'results': schema,
            }
        }


# ─── Custom Exception Handler ─────────────────────────────────────────────────

from rest_framework.views import exception_handler
from rest_framework import status


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        error_payload = {
            'success': False,
            'error': {
                'code': response.status_code,
                'message': '',
                'details': response.data,
            }
        }

        if isinstance(exc, ValidationError):
            error_payload['error']['message'] = 'Validation failed'
        elif isinstance(exc, PermissionDenied):
            error_payload['error']['message'] = 'Permission denied'
        elif response.status_code == 404:
            error_payload['error']['message'] = 'Resource not found'
        elif response.status_code == 401:
            error_payload['error']['message'] = 'Authentication required'
        else:
            error_payload['error']['message'] = 'An error occurred'

        response.data = error_payload

    return response


# ─── Middleware ───────────────────────────────────────────────────────────────

class AuditLogMiddleware:
    """Captures user IP and user-agent for audit logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    @staticmethod
    def get_client_ip(request) -> str:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '')


class TenantMiddleware:
    """Injects current company into request based on user's primary_company."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.company = None
        if request.user.is_authenticated:
            request.company = request.user.primary_company
        return self.get_response(request)


class ActiveUserMiddleware:
    """Updates user's last_active timestamp on each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from apps.authentication.models import User
            User.objects.filter(pk=request.user.pk).update(last_active=timezone.now())
        return self.get_response(request)


# ─── Context Processors ───────────────────────────────────────────────────────

def company_context(request):
    return {
        'current_company': getattr(request, 'company', None),
    }


def notification_context(request):
    if not request.user.is_authenticated:
        return {'unread_notification_count': 0}
    from apps.notifications.models import Notification
    count = Notification.objects.filter(
        recipient=request.user, is_read=False
    ).count()
    return {'unread_notification_count': count}


def theme_context(request):
    theme = 'light'
    if request.user.is_authenticated:
        theme = getattr(request.user, 'theme', 'light')
    return {'user_theme': theme}
