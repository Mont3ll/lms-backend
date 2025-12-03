from django.apps import AppConfig


class EnrollmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.enrollments"
    verbose_name = "Enrollments and Progress"

    def ready(self):
        import apps.enrollments.signals  # Import signals if you have any
