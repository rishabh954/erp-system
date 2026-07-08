from django.core.exceptions import PermissionDenied, ValidationError
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        error_payload = {
            "success": False,
            "error": {
                "code": response.status_code,
                "message": "",
                "details": response.data,
            },
        }

        if isinstance(exc, ValidationError):
            error_payload["error"]["message"] = "Validation failed"
        elif isinstance(exc, PermissionDenied):
            error_payload["error"]["message"] = "Permission denied"
        elif response.status_code == 404:
            error_payload["error"]["message"] = "Resource not found"
        elif response.status_code == 401:
            error_payload["error"]["message"] = "Authentication required"
        else:
            error_payload["error"]["message"] = "An error occurred"

        response.data = error_payload

    return response


class ERPException(Exception):
    """Base exception for all custom ERP errors."""
    def __init__(self, message="An error occurred in the ERP system."):
        self.message = message
        super().__init__(self.message)


class BusinessLogicError(ERPException):
    """Raised when a business rule is violated."""
    pass


class InsufficientStockError(BusinessLogicError):
    """Raised when there is not enough stock for a requested operation."""
    pass


class InvalidStateError(BusinessLogicError):
    """Raised when an entity is in an invalid state for the requested operation."""
    pass


class MultiTenantError(ERPException):
    """Raised when an operation attempts to breach tenant boundaries."""
    pass
