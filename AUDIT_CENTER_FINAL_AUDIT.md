# Enterprise Audit Center Final Audit

## Scope

This patch introduces a central audit pipeline to replace the unsafe global state pattern while preserving compatibility with the older audit log tables.

## Files created

- `apps/administration/services/__init__.py`
- `apps/administration/services/audit.py`
- `apps/administration/migrations/0005_auditevent.py`
- `tests/test_audit_center.py`
- `AUDIT_CENTER_AUDIT.md`

## Files modified

- `apps/administration/models.py`
- `apps/administration/signals.py`
- `core/logging.py`
- `core/middleware.py`
- `config/settings.py`

## Added capability

- Central `AuditEvent` model
- `AuditService.record*` methods
- `AuditRedactionService` redaction
- `AuditIntegrityService` hash-chain utilities
- Request-scoped context with `X-Request-ID` and `X-Correlation-ID`
- Context-local pre-save state for change tracking

## Remaining caveat

The broader project test suite still depends on the repository’s database configuration being set consistently (PostgreSQL by default versus SQLite dev fallback), and legacy fixtures in the repo are not currently isolated from a persistent SQLite database state.
