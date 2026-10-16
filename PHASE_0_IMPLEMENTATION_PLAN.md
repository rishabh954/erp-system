# Phase 0 Implementation Plan

## Completed in this pass

1. **Proxy and active-company IP restriction hardening**
   - Files: `core/middleware.py`, `apps/authentication/middleware.py`, `apps/authentication/api/views.py`.
   - Acceptance: untrusted `X-Forwarded-For` ignored; trusted direct proxy accepted; active company drives company restriction lookup.
   - Tests: `tests/test_production_hardening.py`, `tests/test_authentication_ip_restrictions.py`.
2. **Production configuration and readiness**
   - Files: `config/settings.py`, `apps/api/health.py`, `docker-compose.prod.yml`.
   - Acceptance: production must explicitly configure hosts and a non-default Redis password; readiness probes DB/cache without logging exception text; compose probes `/health/ready/` and requires explicit DB/Redis passwords.
   - Tests: `tests/test_settings_security.py`, `tests/test_health_checks.py`.
3. **CI integration services and failure visibility**
   - File: `.github/workflows/ci.yml`.
   - Acceptance: CI provides PostgreSQL and Redis, and deployment/security scan failures are not hidden behind `|| true`.
4. **Tenant relation regression and claims**
   - Files: `tests/test_api_tenant_relation_fields.py`, `README.md`.
   - Acceptance: a company A serializer relation rejects company B's customer; README no longer calls the system production-ready without qualification.

## Remaining release work

- Finish a full company-scoping call-chain review across all web views, DRF actions, service methods, management commands, tasks, imports/exports, and downloads. Add focused tests for every confirmed gap.
- Inventory every model invariant against current database data before adding constraints/indexes; then test reversible migrations and concurrent operations on PostgreSQL.
- Run full CI on PostgreSQL and Redis, including Celery worker task success/failure/retry/duplicate delivery and restart behavior.
- Exercise all required modules and detail/edit/delete routes with a company admin and least-privileged user.
- Complete an isolated full backup/restore drill covering database, uploaded media, users, global dependencies, and key/config handling; record elapsed times and set explicit RPO/RTO targets.

No new model migration was justified by the scoped work in this pass. Do not treat the remaining work as accepted or waived.
