"""
Enterprise ERP System - Production Settings
Django 5+ | PostgreSQL | Redis | Celery
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file if it exists
dotenv_path = BASE_DIR / '.env'
if dotenv_path.exists():
    with open(dotenv_path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip('\'"')
                os.environ.setdefault(key, val)

# ─── Security ────────────────────────────────────────────────────────────────
# Detect test runs (pytest or manage.py test).
# Use multiple reliable signals: sys.modules, sys.argv, and common pytest env vars.
TESTING = False
try:
    if 'pytest' in ' '.join(sys.argv):
        TESTING = True
except Exception:
    pass

if not TESTING:
    # check loaded modules
    TESTING = any(name.startswith('pytest') for name in list(sys.modules.keys()))

if not TESTING:
    # environment variables set by pytest/test runners
    TESTING = bool(os.environ.get('PYTEST_CURRENT_TEST')) or bool(os.environ.get('DJANGO_TESTING'))

# Respect explicit DEBUG env var; otherwise enable DEBUG during tests to avoid
# running production-only checks in the test environment.
if 'DEBUG' in os.environ:
    DEBUG = os.environ.get('DEBUG') == 'True'
else:
    DEBUG = bool(TESTING)

if not DEBUG and not TESTING:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY or SECRET_KEY == 'change-me-in-production-use-50+-chars' or SECRET_KEY == 'your-very-long-random-secret-key-50-chars-minimum-change-me':  # noqa: E501
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("SECRET_KEY environment variable must be set securely when DEBUG is False")  # noqa: E501
else:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production-use-50+-chars')
# Parse ALLOWED_HOSTS from env; require explicit hosts in production
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

if not DEBUG and not TESTING:
    if not ALLOWED_HOSTS:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            "ALLOWED_HOSTS must be set (comma-separated) when DEBUG is False"
        )

# ─── Applications ─────────────────────────────────────────────────────────────
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'celery',
    'django_celery_beat',
    'django_celery_results',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'two_factor',
    'storages',
]

LOCAL_APPS = [
    'core',
    'apps.authentication',
    'apps.company',
    'apps.hrms',
    'apps.crm',
    'apps.sales',
    'apps.purchase',
    'apps.inventory',
    'apps.accounting',
    'apps.projects',
    'apps.assets',
    'apps.helpdesk',
    'apps.documents',
    'apps.notifications',
    'apps.workflow',
    'apps.dashboard',
    'apps.manufacturing',
    'apps.api',
    'apps.portals',
    'apps.administration',
    'apps.analytics',
    'apps.pos',
    'apps.ai',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.AuditLogMiddleware',
    'core.middleware.TenantMiddleware',
    'core.middleware.RequestLoggingMiddleware',
    'core.middleware.ActiveUserMiddleware',
    'apps.authentication.middleware.SecurityMiddleware',
    'apps.company.middleware.TimezoneMiddleware',
]

if not DEBUG:
    # ─── Production Security Settings ──────────────────────────────────────
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

    if os.environ.get('USE_X_FORWARDED_PROTO', 'True') == 'True':
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    if os.environ.get('SECURE_SSL_REDIRECT', 'True') == 'True':
        SECURE_SSL_REDIRECT = True
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True
        SECURE_HSTS_SECONDS = 31536000  # 1 year
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

ROOT_URLCONF = 'config.urls'

# ─── Templates ────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.administration.context_processors.active_apps',
                'core.context_processors.company_context',
                'core.context_processors.notification_context',
                'core.context_processors.theme_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ─── Database ─────────────────────────────────────────────────────────────────
DB_ENGINE = os.environ.get('DB_ENGINE', 'django.db.backends.postgresql')
DATABASES = {
    'default': {
        'ENGINE': DB_ENGINE,
        'NAME': os.environ.get('DB_NAME', 'erp_db'),
        'USER': os.environ.get('DB_USER', 'erp_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'erp_password'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        } if DB_ENGINE == 'django.db.backends.postgresql' else {},
        'CONN_MAX_AGE': 600 if DB_ENGINE == 'django.db.backends.postgresql' else 0,
    }
}

# Guard: refuse to start in production with a default/weak DB password.
if not DEBUG and not TESTING and DB_ENGINE != 'django.db.backends.sqlite3':
    _db_password = os.environ.get('DB_PASSWORD', '')
    if not _db_password or _db_password in ('erp_password', 'postgres', 'password', 'secret'):
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            "DB_PASSWORD must be set to a strong, unique value in production. "
            "Do not use the default 'erp_password' or other well-known weak values."
        )

# ─── Cache (Redis) ────────────────────────────────────────────────────────────
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Auto-detect if Redis is available locally in DEBUG mode
use_redis = True
if DEBUG:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.05)
    if s.connect_ex(('127.0.0.1', 6379)) != 0:
        use_redis = False
    s.close()

if use_redis:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'COMPRESSOR': 'django_redis.compressors.zlib.ZlibCompressor',
            },
            'KEY_PREFIX': 'erp',
            'TIMEOUT': 300,
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
else:
    # Fallback to local memory cache and database sessions if Redis is not running
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'erp-local-mem-cache',
        }
    }
    SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 86400  # 24 hours
# SESSION_COOKIE_SECURE handled dynamically above
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# ─── Auth & Password ──────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'authentication.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},  # noqa: E501
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},  # noqa: E501
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/auth/login/'

# ─── JWT Configuration ─────────────────────────────────────────────────────────
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ─── REST Framework ────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PAGINATION_CLASS': 'core.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ] if not DEBUG else [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
    },
    'EXCEPTION_HANDLER': 'core.exceptions.custom_exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# ─── drf-spectacular (OpenAPI 3.0) ────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    'TITLE': 'ERP System API',
    'DESCRIPTION': (
        'Production-grade REST API for the ERP System. '
        'Authenticate via JWT Bearer token. '
        'All endpoints are company-scoped — data is automatically filtered to your organisation.'  # noqa: E501
    ),
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'CONTACT': {'name': 'ERP Support'},
    'LICENSE': {'name': 'Proprietary'},
    'TAGS': [
        {'name': 'Auth', 'description': 'JWT token management'},
        {'name': 'CRM', 'description': 'Leads and Customers'},
        {'name': 'Sales', 'description': 'Quotations, Orders, Invoices'},
        {'name': 'Purchase', 'description': 'Vendors, POs, Bills'},
        {'name': 'Inventory', 'description': 'Products and Warehouses'},
        {'name': 'HRMS', 'description': 'Employees and Leave'},
        {'name': 'Manufacturing', 'description': 'BOMs and Manufacturing Orders'},
    ],
    'COMPONENT_SPLIT_REQUEST': True,
    'SORT_OPERATIONS': False,
}

# ─── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_ENABLE_UTC = True
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_ALWAYS_EAGER = not use_redis
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# ─── AI / LLM Settings ──────────────────────────────────────────────────────
OPENAI_API_KEY   = os.environ.get('OPENAI_API_KEY', '')
GEMINI_API_KEY   = os.environ.get('GEMINI_API_KEY', '')
OPENAI_MODEL     = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
AI_TEMPERATURE   = float(os.environ.get('AI_TEMPERATURE', '0.3'))
AI_MAX_TOKENS    = int(os.environ.get('AI_MAX_TOKENS', '2048'))
AI_ENABLED       = bool(OPENAI_API_KEY or GEMINI_API_KEY)

# Workflow escalation + reminder periodic tasks
# NOTE: All beat tasks are defined here. config/celery.py previously also set
# app.conf.beat_schedule which was overwritten by this dict when
# app.config_from_object ran. Both sets of tasks are now merged here so nothing
# is silently dropped.
CELERY_BEAT_SCHEDULE = {
    # ── Operational tasks (previously in celery.py) ───────────────────────
    # Daily: Check overdue invoices and send reminders
    'check-overdue-invoices': {
        'task': 'apps.sales.tasks.check_overdue_invoices',
        'schedule': 28800,  # 08:00 UTC daily (crontab not serialisable without celery import)
    },
    # Daily: Process attendance auto-marking
    'auto-mark-attendance': {
        'task': 'apps.hrms.tasks.auto_mark_attendance',
        'schedule': 86340,  # 23:59 UTC daily
    },
    # Daily: Send low stock alerts
    'low-stock-alerts': {
        'task': 'apps.inventory.tasks.send_low_stock_alerts',
        'schedule': 32400,  # 09:00 UTC daily
    },
    # Daily: Update exchange rates
    'update-exchange-rates': {
        'task': 'apps.company.tasks.update_exchange_rates',
        'schedule': 1800,   # 00:30 UTC daily
    },
    # Weekly: Generate depreciation entries (Monday 02:00 UTC)
    'process-depreciation': {
        'task': 'apps.assets.tasks.process_depreciation',
        'schedule': 604800,  # weekly
    },
    # Every 30 min: Check SLA breaches for helpdesk tickets
    'check-sla-breaches': {
        'task': 'apps.helpdesk.tasks.check_sla_breaches',
        'schedule': 1800,
    },
    # Hourly: Clean up expired sessions
    'cleanup-sessions': {
        'task': 'apps.authentication.tasks.cleanup_expired_sessions',
        'schedule': 3600,
    },
    # Daily: Cleanup old audit logs
    'cleanup-audit-logs': {
        'task': 'apps.authentication.tasks.cleanup_old_audit_logs',
        'schedule': 10800,  # 03:00 UTC
    },
    # Daily: Clean up expired password reset / email tokens
    'cleanup-expired-tokens': {
        'task': 'apps.authentication.tasks.cleanup_expired_tokens',
        'schedule': 14400,  # 04:00 UTC
    },
    # ── Workflow / Analytics tasks ────────────────────────────────────────
    'workflow-check-escalations': {
        'task': 'workflow.check_escalations',
        'schedule': 1800,  # every 30 minutes
    },
    'workflow-send-pending-reminders': {
        'task': 'workflow.send_pending_reminders',
        'schedule': 86400,  # daily
    },
    'run-scheduled-reports': {
        'task': 'analytics.run_scheduled_reports_daily',
        'schedule': 3600,  # hourly check
    },
}

# WhatsApp / Twilio (optional — set these in .env to enable WhatsApp notifications)
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN  = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', '')  # e.g. +14155238886

# ─── Third-Party Integration Credentials ──────────────────────────────────────
# All credentials are read from environment variables — never hard-coded.
# Set the relevant variables in your .env file or deployment secrets manager.
#
# Razorpay (payment links)
#   RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxx
#   RAZORPAY_KEY_SECRET=<secret>
RAZORPAY_KEY_ID     = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')

# Shiprocket (logistics / shipment tracking)
#   SHIPROCKET_EMAIL=you@yourstore.com
#   SHIPROCKET_PASSWORD=<password>
SHIPROCKET_EMAIL    = os.environ.get('SHIPROCKET_EMAIL', '')
SHIPROCKET_PASSWORD = os.environ.get('SHIPROCKET_PASSWORD', '')

# Twilio SMS
#   TWILIO_ACCOUNT_SID=AC<your-twilio-account-sid>
#   TWILIO_AUTH_TOKEN=<token>
#   TWILIO_SMS_FROM=+15005550006
TWILIO_SMS_FROM = os.environ.get('TWILIO_SMS_FROM', '')

# WhatsApp Business Cloud API (Meta)
#   WHATSAPP_ACCESS_TOKEN=<long-lived token>
#   WHATSAPP_PHONE_NUMBER_ID=<phone number ID from Meta Business Manager>
WHATSAPP_ACCESS_TOKEN    = os.environ.get('WHATSAPP_ACCESS_TOKEN', '')
WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '')

# Stripe (optional payment gateway)
#   STRIPE_SECRET_KEY=sk_test_xxxx
#   STRIPE_PUBLISHABLE_KEY=pk_test_xxxx
STRIPE_SECRET_KEY      = os.environ.get('STRIPE_SECRET_KEY', '')
STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')

# Google Service Account (Drive / Calendar integrations)
# Option A: path to a JSON key file on the server filesystem (never commit this file)
#   GOOGLE_CREDENTIALS_PATH=/run/secrets/google_credentials.json
# Option B: inline JSON as an env var (useful for container deployments)
#   GOOGLE_CREDENTIALS_JSON={"type":"service_account",...}
# The GoogleDriveService in apps/administration/services/integrations.py reads
# config/google_credentials.json by default.  Override via GOOGLE_CREDENTIALS_PATH.
GOOGLE_CREDENTIALS_PATH = os.environ.get(
    'GOOGLE_CREDENTIALS_PATH',
    str(BASE_DIR / 'config' / 'google_credentials.json'),
)
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON', '')


# ─── Email ────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')  # noqa: E501
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@erp.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# ─── Internationalization ─────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = os.environ.get('TIME_ZONE', 'UTC')
USE_I18N = False
USE_TZ = True

# ─── Static & Media ────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
if 'pytest' in sys.modules or 'test' in sys.argv:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
else:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── Security Headers ─────────────────────────────────────────────────────────
SECURE_REFERRER_POLICY = 'same-origin'

if not DEBUG:
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = 'DENY'
else:
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_HSTS_SECONDS = 0

def _parse_origins(env_val, default):
    return [o.strip() for o in os.environ.get(env_val, default).split(',') if o.strip()]

CSRF_TRUSTED_ORIGINS = _parse_origins('CSRF_TRUSTED_ORIGINS', 'http://localhost')

if not DEBUG and not TESTING:
    # In production require explicit HTTPS origins
    for origin in CSRF_TRUSTED_ORIGINS:
        if not origin.lower().startswith('https://'):
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured('All CSRF_TRUSTED_ORIGINS must use https in production')

CSRF_COOKIE_HTTPONLY = not DEBUG

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
CORS_ALLOW_CREDENTIALS = True

# ─── Trusted Reverse Proxy IPs ────────────────────────────────────────────────
# Set this to a comma-separated list of your load balancer / reverse proxy IP
# addresses so that X-Forwarded-For is only trusted when the direct TCP
# connection originates from a known proxy.
#
# Example .env entry:
#   TRUSTED_PROXY_IPS=10.0.0.1,10.0.0.2
#
# Leave unset (empty string) to fall back to the legacy behaviour of trusting
# any X-Forwarded-For header — only acceptable if the app is always behind
# a proxy and REMOTE_ADDR is always the proxy IP.
_raw_trusted_proxies = os.environ.get('TRUSTED_PROXY_IPS', '')
TRUSTED_PROXY_IPS = (
    {ip.strip() for ip in _raw_trusted_proxies.split(',') if ip.strip()}
    or None  # None means "trust all" (legacy / single-proxy setups)
)

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'context_filter': {
            '()': 'core.logging.RequestContextLogFilter',
        },
    },
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} [User:{user_id} Comp:{company_id} IP:{client_ip} Path:{request_path}] {module} {process:d} {thread:d} {message}',  # noqa: E501
            'style': '{',
        },
        'simple': {
            'format': '{levelname} [User:{user_id} Comp:{company_id}] {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs/erp.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 5,
            'formatter': 'verbose',
            'filters': ['context_filter'],
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'filters': ['context_filter'],
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {'handlers': ['console', 'file'], 'level': 'WARNING', 'propagate': False},  # noqa: E501
        'apps': {'handlers': ['console', 'file'], 'level': 'DEBUG', 'propagate': False},
        'core': {'handlers': ['console', 'file'], 'level': 'DEBUG', 'propagate': False},
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ─── Rate Limiting ────────────────────────────────────────────────────────────
RATELIMIT_USE_CACHE = 'default'

# ─── ERP Custom Settings ──────────────────────────────────────────────────────
ERP_SETTINGS = {
    'COMPANY_NAME': os.environ.get('COMPANY_NAME', 'EnterpriseERP'),
    'MAX_COMPANIES': int(os.environ.get('MAX_COMPANIES', 10)),
    'DEFAULT_CURRENCY': os.environ.get('DEFAULT_CURRENCY', 'USD'),
    'FISCAL_YEAR_START': os.environ.get('FISCAL_YEAR_START', '01-01'),
    'INVOICE_PREFIX': os.environ.get('INVOICE_PREFIX', 'INV'),
    'PO_PREFIX': os.environ.get('PO_PREFIX', 'PO'),
    'SO_PREFIX': os.environ.get('SO_PREFIX', 'SO'),
    'PAYSLIP_PREFIX': os.environ.get('PAYSLIP_PREFIX', 'PAY'),
    'ENABLE_2FA': os.environ.get('ENABLE_2FA', 'True') == 'True',
    'AUDIT_LOG_RETENTION_DAYS': int(os.environ.get('AUDIT_LOG_RETENTION_DAYS', 365)),
    'LOW_STOCK_THRESHOLD': int(os.environ.get('LOW_STOCK_THRESHOLD', 10)),
}

import os  # noqa: E402
import sys  # noqa: E402

# Use a local SQLite database when requested or during pytest runs.
db_host = os.environ.get('DB_HOST')
db_engine = os.environ.get('DB_ENGINE', 'django.db.backends.postgresql')

if db_host == 'sqlite' or db_engine in {'django.db.backends.sqlite3', 'sqlite3'}:
    DATABASES['default'] = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}
elif ('test' in sys.argv or 'pytest' in sys.modules) and (not db_host or db_host == 'sqlite'):
    DATABASES['default'] = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}
