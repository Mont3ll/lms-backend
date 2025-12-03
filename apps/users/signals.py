from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, UserProfile


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """
    Create or update the user profile when a User object is saved.
    """
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # Ensure profile exists and save it (in case related fields were updated indirectly)
        # This might be redundant if profile isn't expected to change via User save
        try:
            instance.profile.save()
        except UserProfile.DoesNotExist:
            UserProfile.objects.create(user=instance)  # Create if missing
