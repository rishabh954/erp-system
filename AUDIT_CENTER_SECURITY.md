# Audit Center Security Notes

- Sensitive values are redacted centrally via `AuditRedactionService`.
- Request and correlation IDs are generated via context vars rather than global mutable dictionaries.
- Audit records are append-oriented and should not be writable through ordinary CRUD views.
- The hash chain is a tamper-evidence control, not a cryptographic guarantee against privileged database administrators.
