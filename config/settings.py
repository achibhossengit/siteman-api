from datetime import timedelta
from pathlib import Path
import sys
import dj_database_url
from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())
CORS_ALLOW_CREDENTIALS = config('CORS_ALLOW_CREDENTIALS', default=True, cast=bool)

# Django admin path (env-driven). Prefer a non-default slug in production.
_ADMIN_URL = config('ADMIN_URL', default='backoffice').strip().strip('/')
if not _ADMIN_URL:
    raise ImproperlyConfigured("ADMIN_URL must be a non-empty URL path segment.")
ADMIN_URL = f'{_ADMIN_URL}/'


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_standardized_errors',
    'drf_spectacular',
    'django_filters',
    'anymail',

    # Local
    'core',
    'company',
    'sites',
    'labours',
    'accounts',
    'subscription',
    'activity',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
DATABASES = {
    'default': dj_database_url.parse(
        config('DATABASE_URL'),
        conn_max_age=config('DB_CONN_MAX_AGE', default=60, cast=int),
        conn_health_checks=True,
    )
}


CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://localhost:6379/0'),
    }
}


AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization & localization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Dhaka'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# User/labour photos: local disk in DEBUG; Cloudflare R2 when DEBUG is False.
# Tests always use the local backend so they never hit the bucket.
TESTING = len(sys.argv) > 1 and sys.argv[1] == 'test'
R2_ACCESS_KEY_ID = config('R2_ACCESS_KEY_ID', default='')
R2_SECRET_ACCESS_KEY = config('R2_SECRET_ACCESS_KEY', default='')
R2_BUCKET_NAME = config('R2_BUCKET_NAME', default='')
R2_ENDPOINT_URL = config('R2_ENDPOINT_URL', default='')
R2_CUSTOM_DOMAIN = (
    config('R2_CUSTOM_DOMAIN', default='')
    .strip()
    .removeprefix('https://')
    .removeprefix('http://')
    .strip('/')
)

def _r2_configured():
    return all(
        [
            R2_ACCESS_KEY_ID,
            R2_SECRET_ACCESS_KEY,
            R2_BUCKET_NAME,
            R2_ENDPOINT_URL,
            R2_CUSTOM_DOMAIN,
        ]
    )


# Default: R2 in production (DEBUG=False). Set USE_R2_STORAGE=True to try R2 locally.
_use_r2_override = config('USE_R2_STORAGE', default='')
if _use_r2_override != '':
    USE_R2_STORAGE = (not TESTING) and config('USE_R2_STORAGE', cast=bool)
else:
    USE_R2_STORAGE = (not TESTING) and (not DEBUG)

if USE_R2_STORAGE and not _r2_configured():
    raise ImproperlyConfigured(
        'Production media uses Cloudflare R2. Set R2_ACCESS_KEY_ID, '
        'R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME, R2_ENDPOINT_URL, and '
        'R2_CUSTOM_DOMAIN (public hostname, e.g. pub-xxx.r2.dev).'
    )

STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}
if USE_R2_STORAGE:
    STORAGES['default'] = {
        'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        'OPTIONS': {
            'access_key': R2_ACCESS_KEY_ID,
            'secret_key': R2_SECRET_ACCESS_KEY,
            'bucket_name': R2_BUCKET_NAME,
            'endpoint_url': R2_ENDPOINT_URL,
            'region_name': 'auto',
            'custom_domain': R2_CUSTOM_DOMAIN,
            'default_acl': None,
            'querystring_auth': False,
            'file_overwrite': False,
            'addressing_style': 'path',
            'signature_version': 's3v4',
        },
    }
else:
    STORAGES['default'] = {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    }


# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# RestFramework settings
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
        'core.permissions.DjangoModelPermissionsWithView',
        'core.permissions.ActiveSubscriptionOrReadOnly',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
    ),
    'EXCEPTION_HANDLER': 'drf_standardized_errors.handler.exception_handler',
    'DEFAULT_SCHEMA_CLASS': 'drf_standardized_errors.openapi.AutoSchema',
    'DEFAULT_VERSIONING_CLASS': 'rest_framework.versioning.URLPathVersioning',
    'DEFAULT_VERSION': 'v1',
    'ALLOWED_VERSIONS': ('v1',),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.ScopedRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'register': config('REGISTER_THROTTLE_RATE', default='20/h'),
        'login': config('LOGIN_THROTTLE_RATE', default='3/min'),
        'password_reset': config('PASSWORD_RESET_THROTTLE_RATE', default='20/h'),
        # generous per-user backstop for every endpoint (anon requests key by IP)
        'user': config('USER_THROTTLE_RATE', default='100/min'),
    },
}


# drf-spectacular (OpenAPI schema + swagger/redoc docs)
SPECTACULAR_SETTINGS = {
    'TITLE': 'SiteMan API',
    'DESCRIPTION': 'Construction-site management API: auth, company, sites, labour, ledgers.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SCHEMA_PATH_PREFIX': r'/api/v[0-9]+',
    # drf_standardized_errors error-response schemas
    'ENUM_NAME_OVERRIDES': {
        'ValidationErrorEnum': 'drf_standardized_errors.openapi_serializers.ValidationErrorEnum.choices',
        'ClientErrorEnum': 'drf_standardized_errors.openapi_serializers.ClientErrorEnum.choices',
        'ServerErrorEnum': 'drf_standardized_errors.openapi_serializers.ServerErrorEnum.choices',
        'ErrorCode401Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode401Enum.choices',
        'ErrorCode403Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode403Enum.choices',
        'ErrorCode404Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode404Enum.choices',
        'ErrorCode405Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode405Enum.choices',
        'ErrorCode406Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode406Enum.choices',
        'ErrorCode415Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode415Enum.choices',
        'ErrorCode429Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode429Enum.choices',
        'ErrorCode500Enum': 'drf_standardized_errors.openapi_serializers.ErrorCode500Enum.choices',
    },
    # replaces drf-spectacular's default enum hook (patched copy that skips
    # the dynamically generated per-endpoint error serializers)
    'POSTPROCESSING_HOOKS': [
        'drf_standardized_errors.openapi_hooks.postprocess_schema_enums',
    ],
}


# Simple JWT settings
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=config("ACCESS_TOKEN_LIFE_MINUTES", cast=int, default=10)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=config("REFRESH_TOKEN_LIFE_DAYS", cast=int, default=7)
    ),
    "ROTATE_REFRESH_TOKENS": True, # never need to login again. ones login life par.
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "USER_AUTHENTICATION_RULE": "accounts.authentication.jwt_user_authentication_rule", # checked on new token creation by TokenObtainPairView and TokenRefreshView
}


# Auth refresh cookie
# Cross-origin frontends (e.g. Netlify → Railway) need SameSite=None + Secure=True.
REFRESH_TOKEN_COOKIE_NAME = 'refresh_token'
REFRESH_TOKEN_COOKIE_SECURE = config('REFRESH_TOKEN_COOKIE_SECURE', default='True', cast=bool)
REFRESH_TOKEN_COOKIE_SAMESITE = config('REFRESH_TOKEN_COOKIE_SAMESITE', default='None')
REFRESH_TOKEN_COOKIE_PATH = '/api/v1/auth/token'


# OTP / notification delivery
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='anymail.backends.resend.EmailBackend',
)
ANYMAIL = {
    'RESEND_API_KEY': config('RESEND_API_KEY', default=''),
}
DEFAULT_FROM_EMAIL = config(
    'DEFAULT_FROM_EMAIL',
    default='SiteMan <siteman@achibhossen.me>',
)

OTP_LENGTH = config('OTP_LENGTH', default=6, cast=int)
OTP_AGE = config('OTP_AGE', default=300, cast=int)
OTP_TICKET_TTL = config('OTP_TICKET_TTL', default=3600, cast=int)
OTP_RESEND_COOLDOWN = config('OTP_RESEND_COOLDOWN', default=60, cast=int)
OTP_MAX_RESENDS = config('OTP_MAX_RESENDS', default=5, cast=int)
OTP_MAX_ATTEMPTS = config('OTP_MAX_ATTEMPTS', default=5, cast=int)

# Public self-serve registration (company signup). Off for MVP.
REGISTRATION_ENABLED = config('REGISTRATION_ENABLED', default=True, cast=bool)


# Activity log retention (purged by ``purge_activity_logs`` management command)
ACTIVITY_LOG_RETENTION_DAYS = config(
    "ACTIVITY_LOG_RETENTION_DAYS", default=180, cast=int
)


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'siteman': {
            'handlers': ['console'],
            'level': config('SITEMAN_LOG_LEVEL', default='ERROR'),
            'propagate': False,
        },
        'siteman.notifications': {
            'handlers': ['console'],
            'level': config('NOTIFICATIONS_LOG_LEVEL', default='DEBUG'),
            'propagate': False,
        },
    },
}