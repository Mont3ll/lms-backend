import logging
import uuid
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

# from .services import NotificationService # Avoid circular import

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="notifications.send_notification",
    max_retries=3,
    default_retry_delay=60 * 5,
)  # Retry after 5 mins
def send_notification_task(self, notification_id: uuid.UUID):
    """
    Celery task that calls the service method to send a notification.
    """
    logger.info(f"Celery task received: Send notification {notification_id}")
    # Import service here to avoid circular dependency at module level
    from .services import NotificationService

    try:
        NotificationService.send_notification(notification_id)
    except Exception as e:
        logger.error(
            f"Celery task failed for notification {notification_id}: {e}", exc_info=True
        )
        # Retry if potentially recoverable error
        self.retry(exc=e)


@shared_task(name="notifications.send_deadline_reminders")
def send_deadline_reminders_task():
    """
    Celery task to send deadline reminders for assessments due within 24 hours.
    Should be scheduled to run periodically (e.g., every hour or every few hours).
    """
    logger.info("Celery task received: Send deadline reminders")
    
    # Import models and services here to avoid circular dependency
    from apps.assessments.models import Assessment
    from apps.enrollments.models import Enrollment
    from apps.notifications.models import Notification, NotificationType
    from .services import NotificationService
    
    try:
        now = timezone.now()
        # Find assessments with deadlines in the next 24 hours
        reminder_window_start = now
        reminder_window_end = now + timedelta(hours=24)
        
        upcoming_assessments = Assessment.objects.filter(
            is_published=True,
            due_date__gte=reminder_window_start,
            due_date__lte=reminder_window_end,
        ).select_related('course', 'course__tenant')
        
        notifications_created = 0
        
        for assessment in upcoming_assessments:
            # Get all enrolled learners for this course
            enrolled_users = Enrollment.objects.filter(
                course=assessment.course,
                status__in=[Enrollment.Status.ACTIVE],
            ).select_related('user')
            
            for enrollment in enrolled_users:
                user = enrollment.user
                
                # Check if we already sent a reminder for this assessment to this user
                # (within the last 24 hours to avoid duplicate reminders)
                existing_reminder = Notification.objects.filter(
                    user=user,
                    notification_type=NotificationType.DEADLINE_REMINDER,
                    content_type__model='assessment',
                    object_id=assessment.id,
                    created_at__gte=now - timedelta(hours=24),
                ).exists()
                
                if existing_reminder:
                    continue
                
                # Calculate time until deadline for the message
                time_until_due = assessment.due_date - now
                hours_until_due = int(time_until_due.total_seconds() / 3600)
                
                if hours_until_due <= 1:
                    time_str = "in less than an hour"
                else:
                    time_str = f"in {hours_until_due} hours"
                
                try:
                    NotificationService.create_notification(
                        user=user,
                        notification_type=NotificationType.DEADLINE_REMINDER,
                        title=f"Deadline Reminder: {assessment.title}",
                        message=f"'{assessment.title}' in '{assessment.course.title}' is due {time_str}.",
                        related_object=assessment,
                        tenant=assessment.course.tenant,
                    )
                    notifications_created += 1
                except Exception as e:
                    logger.error(f"Failed to create deadline reminder for user {user.id}, assessment {assessment.id}: {e}")
        
        logger.info(f"Deadline reminders task completed. Created {notifications_created} notifications.")
        return notifications_created
        
    except Exception as e:
        logger.error(f"Celery task failed during deadline reminders: {e}", exc_info=True)
        raise
