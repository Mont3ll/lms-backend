import logging

from celery import shared_task

from .services import ScanningService, TransformationService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)  # Example retry logic
def scan_file_task(self, file_id):
    """Celery task to trigger file scanning."""
    logger.info(f"Celery task: Starting scan for file {file_id}")
    try:
        ScanningService.scan_file(file_id)
    except Exception as e:
        logger.error(f"Celery task: Error scanning file {file_id}: {e}", exc_info=True)
        # Retry task if it fails (e.g., scanner service temporarily down)
        self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def transform_file_task(self, file_id):
    """Celery task to trigger file transformations."""
    logger.info(f"Celery task: Starting transformation for file {file_id}")
    try:
        TransformationService.transform_file(file_id)
    except Exception as e:
        logger.error(
            f"Celery task: Error transforming file {file_id}: {e}", exc_info=True
        )
        self.retry(exc=e)
