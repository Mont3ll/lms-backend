import os

from .base import *

# Production specific settings
DEBUG = False

SECRET_KEY = os.getenv("SECRET_KEY")  # MUST be set in environment
if not SECRET_KEY:
    raise ValueError("No SECRET_KEY set for production environment")

ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "").split(",")  # MUST be set in environment
if not ALLOWED_HOSTS:
    raise ValueError("No ALLOWED_HOSTS set for production environment")


# Security enhancements
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = True  # Ensure HTTPS
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)  # If behind a proxy like Nginx/ELB

# Configure database from DATABASE_URL environment variable
# Already handled in base.py using dj_database_url

# Configure Cache from CACHE_URL environment variable
# Already handled in base.py

# CORS Headers - Ensure specific origins are listed
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
if not CORS_ALLOWED_ORIGINS:
    raise ValueError("No CORS_ALLOWED_ORIGINS set for production environment")
# CORS_ALLOW_ALL_ORIGINS = False # Ensure this is False


# Static files - Whitenoise is configured in base.py
# Ensure STATIC_ROOT is set correctly (done in base.py)


# Media files - Ensure S3 or equivalent is configured correctly
# Configuration should be done via environment variables in base.py


# Email - Ensure production email settings are configured via environment variables
# Configuration should be done via environment variables in base.py


# Logging - Configure production logging (e.g., file handlers, external services like Sentry)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {  # Still log to console (e.g., for container logs)
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        # Add file handler example:
        # 'file': {
        #     'level': 'INFO',
        #     'class': 'logging.handlers.RotatingFileHandler',
        #     'filename': '/var/log/django/app.log', # Ensure this path exists and is writable
        #     'maxBytes': 1024*1024*5, # 5 MB
        #     'backupCount': 5,
        #     'formatter': 'verbose',
        # },
        # Add mail_admins handler example:
        # 'mail_admins': {
        #     'level': 'ERROR',
        #     'class': 'django.utils.log.AdminEmailHandler',
        # }
    },
    "root": {
        "handlers": ["console"],  # Add 'file', 'mail_admins' as needed
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],  # Add 'file', 'mail_admins' as needed
            "level": "INFO",  # Less verbose than DEBUG
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],  # Add 'file' as needed
            "level": "INFO",
            "propagate": False,
        },
        # Configure loggers for your apps if needed
    },
}


# DRF Spectacular - Hide schema in production unless explicitly needed
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,  # Inherit from base
    "SERVE_INCLUDE_SCHEMA": False,
}

print("LOADED PRODUCTION SETTINGS")
