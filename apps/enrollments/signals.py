"""
Signal handlers to sync individual enrollments when group membership changes.

Since LearnerGroup uses an explicit through model (GroupMembership), we use
post_save and post_delete signals on GroupMembership instead of m2m_changed.
"""
import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.users.models import GroupMembership

from .services import EnrollmentService

logger = logging.getLogger(__name__)


@receiver(post_save, sender=GroupMembership)
def sync_enrollments_on_member_added(sender, instance, created, **kwargs):
    """
    When a user is added to a group, sync their individual enrollments
    for all courses the group is enrolled in.
    """
    if not created:
        return  # Only process new memberships

    group = instance.group
    group_enrollments = group.course_enrollments.all()

    if not group_enrollments.exists():
        return

    logger.info(
        f"User {instance.user_id} added to group '{group.name}', "
        f"syncing {group_enrollments.count()} course enrollment(s)..."
    )

    for group_enrollment in group_enrollments:
        try:
            EnrollmentService.sync_group_enrollment(group_enrollment)
        except Exception as e:
            logger.error(
                f"Failed to sync group enrollment {group_enrollment.id} "
                f"after adding user {instance.user_id}: {e}"
            )


@receiver(post_delete, sender=GroupMembership)
def handle_member_removed(sender, instance, **kwargs):
    """
    When a user is removed from a group, sync enrollments.

    Note: This triggers a full sync which handles the removal appropriately.
    The sync_group_enrollment method will handle marking enrollments as
    appropriate based on the updated group membership.
    """
    group = instance.group
    group_enrollments = group.course_enrollments.all()

    if not group_enrollments.exists():
        return

    logger.info(
        f"User {instance.user_id} removed from group '{group.name}', "
        f"syncing {group_enrollments.count()} course enrollment(s)..."
    )

    for group_enrollment in group_enrollments:
        try:
            EnrollmentService.sync_group_enrollment(group_enrollment)
        except Exception as e:
            logger.error(
                f"Failed to sync group enrollment {group_enrollment.id} "
                f"after removing user {instance.user_id}: {e}"
            )
