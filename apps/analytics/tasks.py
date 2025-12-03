import logging

from celery import shared_task

# from .services import DataProcessorService # Avoid circular import

logger = logging.getLogger(__name__)


@shared_task(name="analytics.process_daily_events")
def process_daily_events_task():
    """
    Celery task to trigger daily (or periodic) aggregation/processing of analytics data.
    """
    logger.info("Celery task received: Process daily analytics events/metrics")
    from .services import DataProcessorService

    try:
        DataProcessorService.process_events_task()
    except Exception as e:
        logger.error(
            f"Celery task failed during daily analytics processing: {e}", exc_info=True
        )
        # Decide if retry is appropriate for aggregation tasks
