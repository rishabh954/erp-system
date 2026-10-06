# Enterprise Audit Center Audit

This repository already contained two legacy audit patterns:

- `apps.administration.models.AuditLog`
- `apps.authentication.models.ActivityLog`

The older signal layer in `apps/administration/signals.py` also used a process-wide mutable dictionary (`_PRE_SAVE_STATE`) to track old values before model save. That pattern is unsafe across concurrent workers, Celery tasks, and request contexts. The new implementation replaces that with context-local state and a centralized audit model.

## What the new implementation provides

- A central `AuditEvent` model in `apps/administration/models.py`
- A request-scoped audit context via `core.logging` and `core.middleware`
- A central `AuditService` and `AuditRedactionService`
- Hash-chain metadata for tamper evidence
- Backward compatibility with the older `AuditLog`/`ActivityLog` models

## Security boundary

The hash chain is an integrity aid, not a cryptographically immutable ledger. It prevents incidental tampering inside the application layer, but it does not protect against a database administrator or privileged operator changing records directly at the storage layer.
