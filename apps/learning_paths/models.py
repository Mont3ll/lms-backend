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


# =============================================================================
# Personalized Learning Path Models (AI-Generated)
# =============================================================================


class PersonalizedLearningPath(TimestampedModel):
    """
    AI-generated learning path tailored to an individual user's needs.
    
    Unlike curated LearningPaths which are shared across users, personalized
    paths are generated specifically for one user based on their skill gaps,
    goals, or remediation needs.
    """

    class GenerationType(models.TextChoices):
        SKILL_GAP = "SKILL_GAP", _("Skill Gap Based")
        REMEDIAL = "REMEDIAL", _("Remedial/Recovery")
        GOAL_BASED = "GOAL_BASED", _("Goal Based")
        ONBOARDING = "ONBOARDING", _("Onboarding")

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", _("Active")
        COMPLETED = "COMPLETED", _("Completed")
        EXPIRED = "EXPIRED", _("Expired")
        ARCHIVED = "ARCHIVED", _("Archived")

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='personalized_learning_paths'
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='personalized_learning_paths'
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    generation_type = models.CharField(
        max_length=20,
        choices=GenerationType.choices,
        db_index=True
    )
    target_skills = models.ManyToManyField(
        'skills.Skill',
        related_name='targeting_personalized_paths',
        blank=True,
        help_text="Skills this path aims to develop"
    )
    estimated_duration = models.PositiveIntegerField(
        help_text="Estimated duration in hours"
    )
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Path may become stale after this date"
    )
    generation_params = models.JSONField(
        default=dict,
        blank=True,
        help_text="Parameters used by the algorithm to generate this path"
    )

    class Meta:
        ordering = ['-generated_at']
        verbose_name = "Personalized Learning Path"
        verbose_name_plural = "Personalized Learning Paths"

    def __str__(self):
        return f"{self.title} - {self.user.email} ({self.generation_type})"

    @property
    def is_expired(self):
        """Check if the path has expired."""
        from django.utils import timezone
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @property
    def total_steps(self):
        """Return the total number of steps in this path."""
        return self.steps.count()

    @property
    def required_steps_count(self):
        """Return the count of required steps."""
        return self.steps.filter(is_required=True).count()


class PersonalizedPathStep(TimestampedModel):
    """
    A single step within a personalized learning path.
    
    Each step links to a specific Module and includes metadata about
    why this module was included in the user's personalized path.
    """

    path = models.ForeignKey(
        PersonalizedLearningPath,
        on_delete=models.CASCADE,
        related_name='steps'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='personalized_path_steps'
    )
    order = models.PositiveIntegerField(
        help_text="Order of this step within the path"
    )
    is_required = models.BooleanField(
        default=True,
        help_text="Is this step mandatory to complete the path?"
    )
    reason = models.TextField(
        blank=True,
        help_text="AI-generated explanation of why this module was included"
    )
    estimated_duration = models.PositiveIntegerField(
        help_text="Estimated duration in minutes"
    )
    target_skills = models.ManyToManyField(
        'skills.Skill',
        related_name='personalized_path_steps',
        blank=True,
        help_text="Specific skills this step addresses"
    )

    class Meta:
        ordering = ['path', 'order']
        unique_together = ('path', 'order')
        verbose_name = "Personalized Path Step"
        verbose_name_plural = "Personalized Path Steps"

    def __str__(self):
        return f"Step {self.order}: {self.module.title} (Path: {self.path.title})"


class PersonalizedPathProgress(TimestampedModel):
    """
    Track user progress through a personalized learning path.
    
    While PersonalizedLearningPath already has a user FK, this model
    allows tracking detailed progress state separately, similar to
    how LearningPathProgress works for curated paths.
    """

    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", _("Not Started")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")
        PAUSED = "PAUSED", _("Paused")
        ABANDONED = "ABANDONED", _("Abandoned")

    user = models.ForeignKey(
        'users.User',
        on_delete=models.CASCADE,
        related_name='personalized_path_progress'
    )
    path = models.ForeignKey(
        PersonalizedLearningPath,
        on_delete=models.CASCADE,
        related_name='progress_records'
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
    last_activity_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of last user activity on this path"
    )

    class Meta:
        unique_together = ('user', 'path')
        ordering = ['-updated_at']
        verbose_name = "Personalized Path Progress"
        verbose_name_plural = "Personalized Path Progress Records"

    def __str__(self):
        return f"{self.user.email} - {self.path.title} ({self.status})"

    @property
    def progress_percentage(self):
        """Calculate progress percentage based on completed steps."""
        total_steps = self.path.steps.count()
        if total_steps == 0:
            return 0
        # Count steps where the user has completed all content items in the module
        completed_count = 0
        for step in self.path.steps.all():
            if self._is_module_completed(step.module):
                completed_count += 1
        return (completed_count / total_steps) * 100

    def _is_module_completed(self, module):
        """
        Check if user has completed all content items in a module.
        
        A module is considered complete when all its content items
        have been marked as completed through the user's enrollment.
        """
        from apps.enrollments.models import LearnerProgress, Enrollment
        
        # Get content items in this module
        content_items = module.content_items.all()
        if not content_items.exists():
            # Module with no content is considered complete
            return True
        
        # Get user's enrollments for the module's course
        enrollments = Enrollment.objects.filter(
            user=self.user,
            course=module.course,
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        )
        
        if not enrollments.exists():
            return False
        
        # Check if all content items are completed in any enrollment
        for enrollment in enrollments:
            completed_items = LearnerProgress.objects.filter(
                enrollment=enrollment,
                content_item__in=content_items,
                status=LearnerProgress.Status.COMPLETED
            ).count()
            if completed_items == content_items.count():
                return True
        
        return False

    @property
    def current_step(self):
        """Get the current step the user should work on."""
        if self.current_step_order == 0:
            return self.path.steps.first()
        return self.path.steps.filter(order=self.current_step_order).first()

    @property
    def next_step(self):
        """Get the next step after the current one."""
        return self.path.steps.filter(order__gt=self.current_step_order).first()
