import importlib
import logging
import uuid

import requests
from django.conf import settings
from django.utils import timezone

from .models import (
    GeneratedContent,
    GenerationJob,
    ModelConfig,
    PromptTemplate,
    Tenant,
    User,
)
from .tasks import trigger_ai_generation_task  # Celery task

logger = logging.getLogger(__name__)


class AIAdapterError(Exception):
    pass


class AIAdapterFactory:
    """Factory to get the correct adapter based on provider type."""

    _adapter_cache = {}

    @classmethod
    def get_adapter(cls, provider_name: str):
        if provider_name in cls._adapter_cache:
            return cls._adapter_cache[provider_name]

        adapter_module_path = f"apps.ai_engine.adapters.{provider_name.lower()}_adapter"
        adapter_class_name = f"{provider_name.capitalize()}Adapter"

        try:
            module = importlib.import_module(adapter_module_path)
            adapter_class = getattr(module, adapter_class_name)
            cls._adapter_cache[provider_name] = adapter_class
            return adapter_class
        except (ImportError, AttributeError) as e:
            logger.error(
                f"Could not load AI adapter for provider '{provider_name}': {e}"
            )
            raise AIAdapterError(
                f"Adapter for provider '{provider_name}' not found or invalid."
            ) from e


class ContentGeneratorService:
    """Service for managing AI content generation jobs."""

    @staticmethod
    def start_generation_job(
        *,
        tenant: Tenant,
        user: User,
        prompt_template: PromptTemplate | None = None,
        model_config: ModelConfig | None = None,
        input_context: dict,
        generation_params: dict | None = None,
        custom_prompt: str | None = None,  # Allow direct prompt? Needs careful handling
    ) -> GenerationJob:
        """Creates a GenerationJob record and triggers the async Celery task."""

        if not tenant or not user:
            raise ValueError("Tenant and User are required.")
        if not prompt_template and not custom_prompt:
            raise ValueError(
                "Either prompt_template or custom_prompt must be provided."
            )
        if prompt_template and custom_prompt:
            raise ValueError(
                "Provide either prompt_template or custom_prompt, not both."
            )

        final_model_config = model_config or (
            prompt_template.default_model_config if prompt_template else None
        )
        if not final_model_config:
            raise ValueError(
                "AI Model Configuration must be specified directly or via prompt template default."
            )
        if not final_model_config.is_active:
            raise ValueError(
                f"Model Configuration '{final_model_config.name}' is not active."
            )

        # Prepare the prompt
        if prompt_template:
            try:
                final_prompt = prompt_template.template_text.format(**input_context)
            except KeyError as e:
                raise ValueError(
                    f"Missing variable '{e}' in input_context for template '{prompt_template.name}'."
                )
        else:
            # Security risk: Ensure custom prompts are handled safely (e.g., no injection)
            final_prompt = custom_prompt or ""  # Should have been validated earlier

        # Merge generation parameters
        final_params = final_model_config.default_params.copy()
        if generation_params:
            final_params.update(generation_params)

        # Create the job record
        job = GenerationJob.objects.create(
            tenant=tenant,
            user=user,
            prompt_template=prompt_template,
            model_config_used=final_model_config,
            status=GenerationJob.JobStatus.PENDING,
            input_prompt=final_prompt,  # Store the rendered prompt
            input_context=input_context,
            generation_params=final_params,
        )
        logger.info(f"Created AI Generation Job {job.id} by user {user.id}")

        # Trigger Celery task
        task = trigger_ai_generation_task.delay(job.id)
        job.celery_task_id = task.id
        job.save(update_fields=["celery_task_id"])
        logger.info(f"Dispatched Celery task {task.id} for job {job.id}")

        return job

    @staticmethod
    def execute_generation(job_id: uuid.UUID):
        """
        Executes the actual AI generation call. Called by the Celery task.
        """
        try:
            job = GenerationJob.objects.select_related(
                "model_config_used", "tenant", "user"
            ).get(pk=job_id)
        except GenerationJob.DoesNotExist:
            logger.error(f"Generation Job {job_id} not found for execution.")
            return

        if job.status != GenerationJob.JobStatus.PENDING:
            logger.warning(
                f"Generation Job {job_id} is not in PENDING state (status: {job.status}). Skipping execution."
            )
            return

        job.status = GenerationJob.JobStatus.IN_PROGRESS
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
        logger.info(f"Executing AI Generation Job {job.id}...")

        model_config = job.model_config_used
        if not model_config:
            job.status = GenerationJob.JobStatus.FAILED
            job.error_message = "Model configuration missing for job execution."
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at"])
            logger.error(job.error_message)
            return

        try:
            # Get the appropriate adapter
            AdapterClass = AIAdapterFactory.get_adapter(model_config.provider)
            adapter_instance = AdapterClass(config=model_config)

            # Make the API call
            generated_text, metadata = adapter_instance.generate(
                prompt=job.input_prompt, params=job.generation_params
            )

            # Save the result
            GeneratedContent.objects.create(
                job=job,
                tenant=job.tenant,
                user=job.user,  # User who initiated
                generated_text=generated_text,
                metadata=metadata,
            )

            # Mark job as completed
            job.status = GenerationJob.JobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "completed_at"])
            logger.info(f"Successfully completed AI Generation Job {job.id}")

        except Exception as e:
            logger.error(
                f"Error executing AI Generation Job {job.id}: {e}", exc_info=True
            )
            job.status = GenerationJob.JobStatus.FAILED
            job.error_message = f"Generation failed: {e}"
            job.completed_at = timezone.now()
            job.save(update_fields=["status", "error_message", "completed_at"])


class PersonalizationService:
    """Service for content personalization using AI/ML. (Placeholder)"""

    @staticmethod
    def recommend_content(user: User, context: dict):
        logger.warning("PersonalizationService.recommend_content not implemented.")
        return []


class NLPProcessorService:
    """Service for NLP tasks like text analysis, keyword extraction. (Placeholder)"""

    @staticmethod
    def analyze_text(text: str):
        logger.warning("NLPProcessorService.analyze_text not implemented.")
        return {"keywords": [], "summary": ""}


class EvaluationService:
    """Service for evaluating the quality of generated content. (Placeholder)"""

    @staticmethod
    def evaluate_content(content: GeneratedContent):
        logger.warning("EvaluationService.evaluate_content not implemented.")
        # Could involve heuristics, user feedback analysis, or even AI-based evaluation
        return {"quality_score": None, "issues": []}
