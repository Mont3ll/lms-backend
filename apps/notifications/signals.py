# lms/backend/apps/notifications/signals.py
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.users.models import User  # Import User from the correct app

from .models import (
    DeliveryMethod,  # Import models needed by the signal
    NotificationPreference,
    NotificationType,
)

logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_user_notification_preferences_signal(sender, instance, created, **kwargs):
    """
    Create NotificationPreference for a new User.
    """
    if created:
        # Check if preferences already exist (e.g., due to concurrent requests or tests)
        if not NotificationPreference.objects.filter(user=instance).exists():
            # Initialize with default preferences based on NotificationType choices
            default_prefs = {}
            # Example: Enable EMAIL and IN_APP by default for most types
            enabled_methods = [DeliveryMethod.EMAIL.value, DeliveryMethod.IN_APP.value]
            for type_choice in NotificationType:
                prefs_for_type = {method: True for method in enabled_methods}
                # Disable SMS/Push by default unless configured/opted-in later
                prefs_for_type[DeliveryMethod.SMS.value] = False
                prefs_for_type[DeliveryMethod.PUSH.value] = False
                default_prefs[type_choice.value] = prefs_for_type

            try:
                NotificationPreference.objects.create(
                    user=instance, preferences=default_prefs
                )
                logger.info(
                    f"Created default notification preferences for new user {instance.id}"
                )
            except Exception as e:
                # Log error if preference creation fails, but don't block user creation
                logger.error(
                    f"Failed to create notification preferences for user {instance.id}: {e}",
                    exc_info=True,
                )
        else:
            logger.info(
                f"Notification preferences already exist for user {instance.id}, skipping creation."
            )
