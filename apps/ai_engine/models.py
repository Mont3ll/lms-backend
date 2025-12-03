# Import the validators!
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

# Import other necessary models
from apps.common.models import TimestampedModel
from apps.core.models import Tenant
from apps.users.models import User

# Link generated content back to courses/assessments?
# from apps.courses.models import Course, ContentItem
# from apps.assessments.models import Assessment, Question


class ModelProvider(models.TextChoices):
    OPENAI = "OPENAI", _("OpenAI")
    ANTHROPIC = "ANTHROPIC", _("Anthropic")
    HUGGINGFACE = "HUGGINGFACE", _("Hugging Face")
    CUSTOM = "CUSTOM", _("Custom / Self-Hosted")
    # Add other providers


class ModelConfig(TimestampedModel):
    """Configuration for accessing an AI model provider and specific model."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ai_model_configs"
    )
    name = models.CharField(
        max_length=255, help_text="User-friendly name for this configuration"
    )
    provider = models.CharField(max_length=20, choices=ModelProvider.choices)
    model_id = models.CharField(
        max_length=255,
        help_text="Specific model identifier (e.g., gpt-4, claude-2, local/model-name)",
    )
    api_key = models.CharField(
        max_length=512,
        blank=True,
        help_text="API Key (store securely, consider Vault or similar)",
    )  # Encrypt this field
    base_url = models.URLField(
        max_length=512,
        blank=True,
        null=True,
        help_text="API Base URL (for custom/self-hosted models)",
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether this configuration can be used"
    )
    # Add other config like temperature defaults, max tokens, etc.
    default_params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Default parameters for API calls (e.g., temperature)",
    )

    def __str__(self):
        return f"{self.name} ({self.provider} - {self.model_id}) [{self.tenant.name}]"

    class Meta:
        unique_together = ("tenant", "name")
        ordering = ["tenant__name", "name"]
        verbose_name = _("AI Model Configuration")
        verbose_name_plural = _("AI Model Configurations")


class PromptTemplate(TimestampedModel):
    """Stores templates for generating prompts sent to AI models."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="prompt_templates"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    template_text = models.TextField(
        help_text="Prompt template text with placeholders (e.g., {input_text}, {topic})"
    )
    # Define expected variables/context for the template
    variables = models.JSONField(
        default=list,
        blank=True,
        help_text="List of variable names expected in the template",
    )
    # Link to default model config?
    default_model_config = models.ForeignKey(
        ModelConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def __str__(self):
        return f"{self.name} ({self.tenant.name})"

    class Meta:
        unique_together = ("tenant", "name")
        ordering = ["tenant__name", "name"]
        verbose_name = _("Prompt Template")
        verbose_name_plural = _("Prompt Templates")


class GenerationJob(TimestampedModel):
    """Tracks an asynchronous AI content generation job."""

    class JobStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        FAILED = "FAILED", _("Failed")
        CANCELLED = "CANCELLED", _("Cancelled")

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ai_generation_jobs"
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )  # User who initiated
    prompt_template = models.ForeignKey(
        PromptTemplate, on_delete=models.SET_NULL, null=True, blank=True
    )
    model_config_used = models.ForeignKey(
        ModelConfig, on_delete=models.SET_NULL, null=True, blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=JobStatus.choices,
        default=JobStatus.PENDING,
        db_index=True,
    )
    celery_task_id = models.CharField(
        max_length=255, null=True, blank=True, db_index=True
    )

    # Input data provided for the job
    input_prompt = models.TextField(
        blank=True, help_text="The final prompt sent to the model"
    )
    input_context = models.JSONField(
        default=dict, blank=True, help_text="Context variables used with the template"
    )
    generation_params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Specific parameters used for this generation call",
    )

    # Output data (link to GeneratedContent or store directly?)
    # Store error message if failed
    error_message = models.TextField(blank=True, null=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        template_name = (
            self.prompt_template.name if self.prompt_template else "Custom Prompt"
        )
        return f"Job {self.id} ({template_name}) - {self.status}"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("AI Generation Job")
        verbose_name_plural = _("AI Generation Jobs")


class GeneratedContent(TimestampedModel):
    """Stores content generated by an AI model."""

    job = models.OneToOneField(
        GenerationJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_content_output",
    )  # Link back to the job
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ai_generated_contents"
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )  # User associated (initiator or target)

    generated_text = models.TextField()
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Metadata about the generation (e.g., tokens used, cost)",
    )
    # Link to the LMS content where this was used (optional, use GenericForeignKey if needed)
    # content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    # object_id = models.UUIDField(null=True, blank=True, db_index=True)
    # related_object = GenericForeignKey('content_type', 'object_id')

    # Quality / Evaluation fields
    is_accepted = models.BooleanField(
        null=True, blank=True, help_text="Was the generated content accepted by a user?"
    )
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )  # e.g., 1-5 stars
    evaluation_feedback = models.TextField(blank=True)

    def __str__(self):
        return f"Generated Content {self.id} (Job: {self.job_id})"

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("AI Generated Content")
        verbose_name_plural = _("AI Generated Contents")
