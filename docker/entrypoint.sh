#!/bin/bash
set -e

echo "=============================="
echo "  EnterpriseERP Starting Up   "
echo "=============================="

# Wait for database
echo "Waiting for PostgreSQL..."
until nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
  echo "  DB not ready, sleeping 2s..."
  sleep 2
done
echo "PostgreSQL is up!"

# Wait for Redis
echo "Waiting for Redis..."
until nc -z redis "${REDIS_PORT:-6379}"; do
  echo "  Redis not ready, sleeping 2s..."
  sleep 2
done
echo "Redis is up!"

if [ "$1" = "gunicorn" ]; then
  echo "Running database migrations..."
  python manage.py migrate --noinput

  echo "Collecting static files..."
  python manage.py collectstatic --noinput

  echo "Compiling translation messages..."
  python manage.py compilemessages --ignore=.tox 2>/dev/null || true

  # Create superuser if not exists
  if [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    python manage.py shell << EOF
from apps.authentication.models import User
if not User.objects.filter(email='$DJANGO_SUPERUSER_EMAIL').exists():
    User.objects.create_superuser(
        email='$DJANGO_SUPERUSER_EMAIL',
        password='$DJANGO_SUPERUSER_PASSWORD',
        first_name='Super',
        last_name='Admin',
    )
    print('Superuser created: $DJANGO_SUPERUSER_EMAIL')
else:
    print('Superuser already exists')
EOF
  fi

  # Load initial data if requested
  if [ "$LOAD_FIXTURES" = "true" ]; then
    echo "Loading fixtures..."
    python manage.py loaddata fixtures/initial_data.json 2>/dev/null || true
  fi

  echo "Starting Gunicorn..."
  exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-4}" \
    --worker-class "${GUNICORN_WORKER_CLASS:-sync}" \
    --worker-connections "${GUNICORN_CONNECTIONS:-1000}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --keepalive "${GUNICORN_KEEPALIVE:-5}" \
    --max-requests "${GUNICORN_MAX_REQUESTS:-1000}" \
    --max-requests-jitter 50 \
    --access-logfile - \
    --error-logfile - \
    --log-level "${GUNICORN_LOG_LEVEL:-info}" \
    --capture-output \
    --enable-stdio-inheritance

elif [ "$1" = "celery" ]; then
  echo "Starting Celery worker..."
  exec celery -A config.celery worker \
    -l "${CELERY_LOG_LEVEL:-info}" \
    -c "${CELERY_CONCURRENCY:-4}" \
    --max-tasks-per-child=1000

elif [ "$1" = "celery-beat" ]; then
  echo "Starting Celery Beat..."
  exec celery -A config.celery beat \
    -l "${CELERY_LOG_LEVEL:-info}" \
    --scheduler django_celery_beat.schedulers:DatabaseScheduler

else
  exec "$@"
fi
