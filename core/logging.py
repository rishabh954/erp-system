import contextvars
import logging

# Define context variables to hold request data
_user_id = contextvars.ContextVar("user_id", default=None)
_company_id = contextvars.ContextVar("company_id", default=None)
_request_path = contextvars.ContextVar("request_path", default=None)
_client_ip = contextvars.ContextVar("client_ip", default=None)
_request_id = contextvars.ContextVar("request_id", default=None)
_correlation_id = contextvars.ContextVar("correlation_id", default=None)
_session_id = contextvars.ContextVar("session_id", default=None)
_user_agent = contextvars.ContextVar("user_agent", default=None)
_method = contextvars.ContextVar("http_method", default=None)


def set_logging_context(user_id=None, company_id=None, request_path=None, client_ip=None,
                       request_id=None, correlation_id=None, session_id=None,
                       user_agent=None, http_method=None):
    if user_id is not None:
        _user_id.set(user_id)
    if company_id is not None:
        _company_id.set(company_id)
    if request_path is not None:
        _request_path.set(request_path)
    if client_ip is not None:
        _client_ip.set(client_ip)
    if request_id is not None:
        _request_id.set(request_id)
    if correlation_id is not None:
        _correlation_id.set(correlation_id)
    if session_id is not None:
        _session_id.set(session_id)
    if user_agent is not None:
        _user_agent.set(user_agent)
    if http_method is not None:
        _method.set(http_method)


def clear_logging_context():
    _user_id.set(None)
    _company_id.set(None)
    _request_path.set(None)
    _client_ip.set(None)
    _request_id.set(None)
    _correlation_id.set(None)
    _session_id.set(None)
    _user_agent.set(None)
    _method.set(None)


class RequestContextLogFilter(logging.Filter):
    """
    Injects contextual information from contextvars into the log record.
    """
    def filter(self, record):
        record.user_id = _user_id.get() or "-"
        record.company_id = _company_id.get() or "-"
        record.request_path = _request_path.get() or "-"
        record.client_ip = _client_ip.get() or "-"
        record.request_id = _request_id.get() or "-"
        record.correlation_id = _correlation_id.get() or "-"
        record.session_id = _session_id.get() or "-"
        record.user_agent = _user_agent.get() or "-"
        record.http_method = _method.get() or "-"
        return True
