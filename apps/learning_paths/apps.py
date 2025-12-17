from django.apps import AppConfig


class LearningPathsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.learning_paths"
    verbose_name = "Learning Paths"

    def ready(self):
        """Import signal handlers when the app is ready."""
        import apps.learning_paths.signals  # noqa: F401
