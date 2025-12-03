from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.core.models import Tenant
from apps.courses.models import Course, Module  # Need Course/Module models defined


class LearningPath(TimestampedModel):
    """Represents a curated sequence of learning items (Courses or Modules)."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PUBLISHED = "PUBLISHED", _("Published")
        ARCHIVED = "ARCHIVED", _("Archived")

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="learning_paths"
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier for the learning path URL",
    )
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    # Add fields like target audience, estimated duration, learning objectives, thumbnail etc.
    # objectives = models.JSONField(default=list, blank=True)
    # thumbnail = models.ForeignKey('files.File', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f"{self.title} ({self.tenant.name})"

    def save(self, *args, **kwargs):
        from apps.common.utils import generate_unique_slug

        if not self.slug:
            # Assuming globally unique slug for paths
            self.slug = generate_unique_slug(self, source_field="title")
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["tenant__name", "title"]
        # If slug is unique per tenant:
        # unique_together = ('tenant', 'slug')


class LearningPathStep(TimestampedModel):
    """Represents a single step within a Learning Path, linking to a Course or Module."""

    learning_path = models.ForeignKey(
        LearningPath, related_name="steps", on_delete=models.CASCADE
    )
    order = models.PositiveIntegerField(
        default=0, help_text="Order of this step within the path"
    )

    # Generic relation to link to either a Course or a Module
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to=models.Q(app_label="courses", model="course")
        | models.Q(app_label="courses", model="module"),
    )
    object_id = models.UUIDField(db_index=True)
    content_object = GenericForeignKey(
        "content_type", "object_id"
    )  # The actual Course or Module instance

    # Optional settings for the step
    is_required = models.BooleanField(
        default=True, help_text="Is this step mandatory to complete the path?"
    )
    # Add due date specific to this step in the path?

    def __str__(self):
        item_name = getattr(self.content_object, "title", str(self.object_id))
        return f"Step {self.order}: {item_name} (Path: {self.learning_path.title})"

    class Meta:
        ordering = ["learning_path", "order"]
        unique_together = (
            "learning_path",
            "order",
        )  # Ensure unique order within a path


class LearningPathProgress(TimestampedModel):
    """Track user progress through learning paths."""
    
    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", _("Not Started")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        PAUSED = "PAUSED", _("Paused")
    
    user = models.ForeignKey(
        'users.User', 
        on_delete=models.CASCADE, 
        related_name='learning_path_user_progress'
    )
    learning_path = models.ForeignKey(
        LearningPath, 
        on_delete=models.CASCADE, 
        related_name='user_progress'
    )
    status = models.CharField(
        max_length=15, 
        choices=Status.choices, 
        default=Status.NOT_STARTED,
        db_index=True
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    current_step_order = models.PositiveIntegerField(
        default=0,
        help_text="Order of the current step (0 means not started)"
    )
    
    class Meta:
        unique_together = ('user', 'learning_path')
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.user.email} - {self.learning_path.title} ({self.status})"
    
    @property
    def progress_percentage(self):
        """Calculate progress percentage based on completed steps."""
        total_steps = self.learning_path.steps.count()
        if total_steps == 0:
            return 0
        completed_steps = self.step_progress.filter(
            status=LearningPathStepProgress.Status.COMPLETED
        ).count()
        return (completed_steps / total_steps) * 100
    
    @property
    def current_step(self):
        """Get the current step the user should work on."""
        if self.current_step_order == 0:
            return self.learning_path.steps.first()
        return self.learning_path.steps.filter(order__gt=self.current_step_order).first()
    
    @property
    def next_step(self):
        """Get the next step after the current one."""
        if self.current_step_order == 0:
            return self.learning_path.steps.filter(order__gt=0).first()
        return self.learning_path.steps.filter(order__gt=self.current_step_order).first()


class LearningPathStepProgress(TimestampedModel):
    """Track user progress for individual learning path steps."""
    
    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", _("Not Started")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        SKIPPED = "SKIPPED", _("Skipped")
    
    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='learning_path_step_user_progress'
    )
    learning_path_progress = models.ForeignKey(
        LearningPathProgress,
        on_delete=models.CASCADE,
        related_name='step_progress'
    )
    step = models.ForeignKey(
        LearningPathStep,
        on_delete=models.CASCADE,
        related_name='user_progress'
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.NOT_STARTED,
        db_index=True
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        unique_together = ('user', 'step')
        ordering = ['step__order']
    
    def __str__(self):
        return f"{self.user.email} - Step {self.step.order} ({self.status})"
#     completed_at = models.DateTimeField(null=True, blank=True)
#
#     class Meta:
#         unique_together = ('user', 'learning_path')
#         ordering = ['learning_path', 'user']
