from .base import *

# Development specific settings
DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Use console email backend for development
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Use local file storage for development (override base S3 settings)
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# Disable CORS restrictions for easier local development (use with caution)
# CORS_ALLOW_ALL_ORIGINS = True

# Optional: Django Debug Toolbar settings
# INSTALLED_APPS += ['debug_toolbar']
# MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']
# INTERNAL_IPS = ['127.0.0.1']

# Make Celery tasks run synchronously in development for easier debugging (optional)
# CELERY_TASK_ALWAYS_EAGER = True
# CELERY_TASK_EAGER_PROPAGATES = True

print("LOADED DEVELOPMENT SETTINGS")
