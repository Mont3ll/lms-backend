import logging
import uuid

from celery import shared_task

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
