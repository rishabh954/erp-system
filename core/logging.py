import contextvars
import logging

# Define context variables to hold request data
_user_id = contextvars.ContextVar("user_id", default=None)
_company_id = contextvars.ContextVar("company_id", default=None)
_request_path = contextvars.ContextVar("request_path", default=None)
_client_ip = contextvars.ContextVar("client_ip", default=None)

def set_logging_context(user_id=None, company_id=None, request_path=None, client_ip=None):
    if user_id:
        _user_id.set(user_id)
    if company_id:
        _company_id.set(company_id)
    if request_path:
        _request_path.set(request_path)
    if client_ip:
        _client_ip.set(client_ip)

def clear_logging_context():
    _user_id.set(None)
    _company_id.set(None)
    _request_path.set(None)
    _client_ip.set(None)


class RequestContextLogFilter(logging.Filter):
    """
    Injects contextual information from contextvars into the log record.
    """
    def filter(self, record):
        record.user_id = _user_id.get() or "-"
        record.company_id = _company_id.get() or "-"
        record.request_path = _request_path.get() or "-"
        record.client_ip = _client_ip.get() or "-"
        return True
