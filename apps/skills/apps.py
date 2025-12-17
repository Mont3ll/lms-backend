from django.apps import AppConfig


class SkillsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.skills'
    verbose_name = 'Skills Management'

    def ready(self):
        """Import signal handlers when the app is ready."""
        import apps.skills.signals  # noqa: F401
