# Phase 0 Deployment Guide

## Required production configuration

Set these values in the deployment environment or a protected environment file; never commit real credentials:

- `DEBUG=False`
- `SECRET_KEY`: unique high-entropy secret
- `ALLOWED_HOSTS`: explicit comma-separated hostnames
- `DB_ENGINE=django.db.backends.postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT`
- `REDIS_PASSWORD`: unique secret, not a default/common value
- `REDIS_URL` and `CELERY_BROKER_URL`, pointing to the protected Redis service
- `CSRF_TRUSTED_ORIGINS`: HTTPS origins for the public site
- `TRUSTED_PROXY_IPS`: direct IP addresses of the reverse proxies that are allowed to set `X-Forwarded-For`
- `PRIVATE_BACKUP_ROOT`: private, non-web-served persistent storage

The production Compose file now refuses missing database and Redis passwords. Configure `DB_PASSWORD` and `REDIS_PASSWORD` before running Compose. Do not expose database or Redis ports beyond the host/network that needs them.

## Start and verify

1. Back up the database and private media before release.
2. Build and start PostgreSQL and Redis; wait for their health checks.
3. Apply schema migrations once using the release image: `python manage.py migrate --noinput`.
4. Collect static files, then start the web service, Celery worker, and Celery beat.
5. Check `/health/live/` for process liveness and `/health/ready/` for database/cache readiness. Readiness does not assert that a Celery worker is alive.
6. Verify the worker separately with an operational task/monitor. Redis availability alone is not a worker-health signal.
7. Run the release smoke tests and review logs for migration, task, and backup failures.

CI is configured for PostgreSQL 16 and Redis 7. Local SQLite success is not a substitute for the CI run. Do not issue a production certification until the PostgreSQL suite and Celery/Redis operational checks are green.

## Rollback

1. Stop web and worker processes so they cannot write during rollback.
2. Restore the pre-deployment database and uploaded files into an isolated location first and verify them.
3. Roll back the application image. Reverse a migration only when that migration is explicitly reversible and the rollback has been rehearsed; otherwise restore the matching database snapshot.
4. Restart services and verify readiness, authentication, tenant boundaries, and representative financial/inventory workflows.

This repository does not establish an RPO/RTO guarantee. Set and test those targets with the deployment owner.
