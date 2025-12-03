import logging
import uuid

from celery import shared_task

# from .services import ContentGeneratorService # Causes circular import

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="ai_engine.trigger_ai_generation")
def trigger_ai_generation_task(self, job_id: uuid.UUID):
    """
    Celery task that calls the service method to execute AI generation.
    """
    logger.info(f"Celery task received: Execute AI generation for job {job_id}")
    # Import service here to avoid circular dependency at module level
    from .services import ContentGeneratorService

    try:
        ContentGeneratorService.execute_generation(job_id)
    except Exception as e:
        logger.error(f"Celery task failed for job {job_id}: {e}", exc_info=True)
        # Depending on the error, you might want to retry the task
        # self.retry(exc=e, countdown=60) # Example: retry after 60 seconds
