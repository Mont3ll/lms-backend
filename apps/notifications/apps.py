from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"

    def ready(self):
        # Import signals here to ensure models are loaded first
        try:
            import apps.notifications.signals  # noqa F401
        except ImportError:
            pass
