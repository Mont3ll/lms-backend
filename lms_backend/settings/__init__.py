import os

# Default to development settings unless DJANGO_SETTINGS_MODULE is set otherwise
# or an environment variable indicates production
SETTINGS_ENV = os.getenv("DJANGO_SETTINGS_ENV", "development")

if SETTINGS_ENV == "production":
    from .production import *
else:
    from .development import *
