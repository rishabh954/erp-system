from rest_framework.views import exception_handler
from rest_framework import status
from django.core.exceptions import ValidationError, PermissionDenied

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
