# paperless_saas/settings.py

from pathlib import Path
from decouple import config
from datetime import timedelta # Used for JWT configuration
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = ['*'] # Use specific domains in production


# ==============================================================================
# APPLICATION DEFINITION
# ==============================================================================

INSTALLED_APPS = [
    # Core Django Apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites', # <-- Required for Django Sites framework (used in email links)

    # 3rd Party/API/Tech Stack
    'rest_framework',
    'drf_yasg',              # For Swagger
    'django.contrib.postgres', # For JSONField, etc. (PostgreSQL features)
    'channels',              # For Chat (WebSockets)
    'corsheaders',           # For Cross-Origin Resource Sharing
    'rest_framework_simplejwt', # <-- Use JWT for modern stateless auth
    'django_filters',        # For API filtering

    # Custom Apps (Matching our defined structure)
    'core',                  # Foundation, Users, Orgs
    'documents',             # Document creation, PDF, Storage
    'projects',              # Project management, Expenses
    'chat',                  # Real-time messaging
    'workflow',  
     'editor', 
     'dashboard',       # Approval routing logic
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    
    # Custom Middleware for Multi-Tenancy (We'll implement this later)
    # 'core.middleware.OrganizationContextMiddleware', 
]

ROOT_URLCONF = 'paperless_saas.urls'
WSGI_APPLICATION = 'paperless_saas.wsgi.application'

# ==============================================================================
# TEMPLATES CONFIGURATION
# ==============================================================================
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # Optional: for custom templates
        'APP_DIRS': True,  # This is CRITICAL - allows Django to find admin templates
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',  # Required for admin
                'django.contrib.auth.context_processors.auth',  # Required for admin
                'django.contrib.messages.context_processors.messages',  # Required for admin
            ],
        },
    },
]

# ==============================================================================
# DATABASE CONFIGURATION (PostgreSQL)
# ==============================================================================
DATABASES = {
    'default': {
        'ENGINE': config('DATABASE_ENGINE', default='django.db.backends.postgresql'), # Explicit PostgreSQL default
        'NAME': config('DATABASE_NAME'),
        'USER': config('DATABASE_USER'),
        'PASSWORD': config('DATABASE_PASSWORD'),
        'HOST': config('DATABASE_HOST', default='localhost'),
        'PORT': config('DATABASE_PORT', default='5432', cast=int),
    }
}

# ==============================================================================
# PASSWORD VALIDATION
# ==============================================================================
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# ==============================================================================
# INTERNATIONALIZATION
# ==============================================================================
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ==============================================================================
# STATIC FILES (CSS, JavaScript, Images)
# ==============================================================================
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# ==============================================================================
# MEDIA FILES (User uploaded files)
# ==============================================================================
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Correct Custom User Model reference:
AUTH_USER_MODEL = 'core.CustomUser'
SITE_ID = 1 # Required by sites framework for accurate email domain links

# ==============================================================================
# EMAIL SETTINGS (SMTP for Real Email Delivery to Phone)
# ==============================================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # For Gmail delivery to phone
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='your-email@gmail.com')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='your-app-password')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='noreply@paperless-saas.com')

# ==============================================================================
# REST FRAMEWORK & JWT AUTHENTICATION
# ==============================================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # Use JWT as the standard for stateless API authentication
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        # Session auth is optional, good for the browsable API/Admin
        'rest_framework.authentication.SessionAuthentication', 
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 25,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
     # ADD THIS SECTION FOR THROTTLING:
    'DEFAULT_THROTTLE_RATES': {
        'user': '1000/day',
        'anon': '100/day',
        'message': '100/hour', 
        'chat_room': '50/hour', 
    }
}

# Simple JWT Configuration: CRITICAL for setting token lifetimes
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('JWT_ACCESS_MINUTES', default=600, cast=int)), 
    'REFRESH_TOKEN_LIFETIME': timedelta(days=config('JWT_REFRESH_DAYS', default=7, cast=int)),
    'ROTATE_REFRESH_TOKENS': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    
    # FIX: Allow tokens without "Bearer" prefix
    'AUTH_HEADER_TYPES': ('Bearer', ''),  # ← ADD EMPTY STRING HERE
    
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# ==============================================================================
# DRF YASG (Swagger) Settings
# ==============================================================================
SWAGGER_SETTINGS = {
    'SECURITY_DEFINITIONS': {
        # Define the security scheme to match JWT (Bearer scheme)
        'Bearer': { 
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            # Guide client to use "Bearer <token>" format
            'description': "JWT Authorization header using the **Bearer** scheme. Example: 'Bearer {token}'",
        }
    },
    'USE_SESSION_AUTH': False, # Disable session auth for Swagger/Redoc
}

# ==============================================================================
# CORS & CSRF SETTINGS (FIXED)
# ==============================================================================
CORS_ALLOW_ALL_ORIGINS = True  # Allow all during development
CORS_ALLOW_CREDENTIALS = True

# Explicitly allow your frontend origins
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# 🔥 CRITICAL FIX: Add CSRF trusted origins
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5174",
    "http://127.0.0.1:5174", 
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Session & Cookie settings for development
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript to read CSRF token

# For development - allow cookies from different ports
if DEBUG:
    SESSION_COOKIE_DOMAIN = None
    CSRF_COOKIE_DOMAIN = None
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False

# Allow specific headers
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-requested-with',
]

# Allow specific methods
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# ==============================================================================
# CHANNELS (WebSockets) Configuration - CHAT
# ==============================================================================
# ASGI is required for Channels (Chat)
ASGI_APPLICATION = 'paperless_saas.asgi.application' 

# Channel layers configuration
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer'
    }
}

# For production with Redis (uncomment when ready):
# CHANNEL_LAYERS = {
#     'default': {
#         'BACKEND': 'channels_redis.core.RedisChannelLayer',
#         'CONFIG': {
#             "hosts": [('127.0.0.1', 6379)],
#         },
#     },
# }

# ==============================================================================
# CHAT SPECIFIC SETTINGS
# ==============================================================================
# Maximum message length
CHAT_MESSAGE_MAX_LENGTH = 5000

# Rate limiting for chat messages (messages per minute)
CHAT_RATE_LIMIT = 30

# Online status timeout (seconds)
CHAT_ONLINE_TIMEOUT = 300

# File upload limits for chat
CHAT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
CHAT_ALLOWED_FILE_TYPES = [
    'image/jpeg', 'image/png', 'image/gif', 
    'application/pdf', 'text/plain',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
]

# ==============================================================================
# SECURITY SETTINGS (For Production)
# ==============================================================================
if not DEBUG:
    # Security settings for production
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    
    # Production CORS settings
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "https://yourproductiondomain.com",
        # Add your production frontend domains
    ]
    CSRF_TRUSTED_ORIGINS = [
        "https://yourproductiondomain.com",
        # Add your production frontend domains
    ]

# ==============================================================================
# LOGGING CONFIGURATION
# ==============================================================================
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
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'debug.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'chat': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# ==============================================================================
# CACHE CONFIGURATION (For production scaling)
# ==============================================================================
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# For production with Redis (uncomment when ready):
# CACHES = {
#     'default': {
#         'BACKEND': 'django_redis.cache.RedisCache',
#         'LOCATION': 'redis://127.0.0.1:6379/1',
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#         }
#     }
# }

# ==============================================================================
# EXTERNAL API CONFIGURATION
# ==============================================================================
HRIS_API_KEY = os.environ.get('HRIS_API_KEY', 'your-hris-api-key')
HRIS_BASE_URL = os.environ.get('HRIS_BASE_URL', 'https://api.hrsystem.com/v1')

