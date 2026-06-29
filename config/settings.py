"""
Enterprise ERP System - Production Settings
Django 5+ | PostgreSQL | Redis | Celery
"""

import os
from pathlib import Path
from datetime import timedelta

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
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

if not DEBUG:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("SECRET_KEY environment variable must be set when DEBUG is False")
else:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'change-me-in-production-use-50+-chars')
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

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
    'core.middleware.ActiveUserMiddleware',
    'apps.authentication.middleware.SecurityMiddleware',
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
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'erp_db'),
        'USER': os.environ.get('DB_USER', 'erp_user'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'erp_password'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
        'CONN_MAX_AGE': 600,
    }
}

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
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
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
        'All endpoints are company-scoped — data is automatically filtered to your organisation.'
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
CELERY_BEAT_SCHEDULE = {
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


# ─── Email ────────────────────────────────────────────────────────────────────
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
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
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ─── Security Headers ─────────────────────────────────────────────────────────
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

CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', 'http://localhost').split(',')

# ─── CORS ─────────────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
CORS_ALLOW_CREDENTIALS = True

# ─── Logging ─────────────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
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
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {'handlers': ['console', 'file'], 'level': 'WARNING', 'propagate': False},
        'apps': {'handlers': ['console', 'file'], 'level': 'DEBUG', 'propagate': False},
        'core': {'handlers': ['console', 'file'], 'level': 'DEBUG', 'propagate': False},
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

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

import sys
if 'test' in sys.argv or 'pytest' in sys.modules:
    DATABASES['default'] = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}
