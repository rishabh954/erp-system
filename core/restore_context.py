"""Execution context flag used to suppress side effects during tenant restore."""

from contextlib import contextmanager
from contextvars import ContextVar

_RESTORING = ContextVar("erp_restoring", default=False)


def is_restoring():
    return _RESTORING.get()


@contextmanager
def restoring():
    token = _RESTORING.set(True)
    try:
        yield
    finally:
        _RESTORING.reset(token)
