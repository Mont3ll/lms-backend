import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.core.models import Tenant
from apps.users.models import User
from apps.files.models import File


class Course(TimestampedModel):
    """Represents a course in the LMS."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PUBLISHED = "PUBLISHED", _("Published")
        ARCHIVED = "ARCHIVED", _("Archived")

    class DifficultyLevel(models.TextChoices):
        BEGINNER = "beginner", _("Beginner")
        INTERMEDIATE = "intermediate", _("Intermediate")
        ADVANCED = "advanced", _("Advanced")

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="courses")
    title = models.CharField(max_length=255)
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Unique identifier for the course URL",
    )
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True, help_text="Course category")
    difficulty_level = models.CharField(
        max_length=20, 
        choices=DifficultyLevel.choices, 
        default=DifficultyLevel.BEGINNER,
        help_text="Course difficulty level"
    )
    estimated_duration = models.PositiveIntegerField(
        default=1, 
        help_text="Estimated duration in hours"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        help_text="Course price (0 for free courses)"
    )
    is_free = models.BooleanField(default=True, help_text="Whether the course is free")
    learning_objectives = models.JSONField(
        default=list, 
        blank=True, 
        help_text="List of learning objectives"
    )
    thumbnail = models.URLField(
        max_length=2048, 
        blank=True, 
        null=True, 
        help_text="Course thumbnail URL"
    )
    instructor = models.ForeignKey(
        User,
        related_name="courses_authored",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"role__in": [User.Role.INSTRUCTOR, User.Role.ADMIN]},
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    tags = models.JSONField(
        default=list, blank=True, help_text="List of tags for categorization"
    )
    # Add fields like category, estimated duration, prerequisites, thumbnail etc.
    # thumbnail = models.ForeignKey(File, on_delete=models.SET_NULL, null=True, blank=True, related_name='+') # Link to File model

    def __str__(self):
        return f"{self.title} ({self.tenant.name})"

    def save(self, *args, **kwargs):
        from apps.common.utils import generate_unique_slug

        if not self.slug:
            # Slug should be unique across all tenants if using subdomains/paths like /courses/my-slug/
            # If using tenant subdomains, slug only needs to be unique per tenant.
            # This implementation assumes globally unique slug. Adjust if needed.
            self.slug = generate_unique_slug(self, source_field="title")
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["title"]
        # If slug is unique per tenant:
        # unique_together = ('tenant', 'slug')


class Module(TimestampedModel):
    """Represents a module or section within a Course."""

    course = models.ForeignKey(Course, related_name="modules", on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(
        default=0, help_text="Order of the module within the course"
    )

    def __str__(self):
        return f"{self.title} (Course: {self.course.title})"

    class Meta:
        ordering = ["course", "order", "title"]
        # Ensure order is unique per course if strict ordering is required without gaps
        # unique_together = ('course', 'order')


class ContentItem(TimestampedModel):
    """Represents a piece of learning content within a Module."""

    class ContentType(models.TextChoices):
        # Basic Types
        TEXT = "TEXT", _("Text")  # Simple markdown/HTML content stored directly
        DOCUMENT = "DOCUMENT", _(
            "Document"
        )  # PDF, DOCX, PPTX etc. (linked to File model)
        IMAGE = "IMAGE", _("Image")  # JPG, PNG, GIF etc. (linked to File model)
        VIDEO = "VIDEO", _(
            "Video"
        )  # MP4, WEBM etc. or external link (e.g., YouTube, Vimeo)
        AUDIO = "AUDIO", _("Audio")  # MP3, OGG etc. (linked to File model)
        URL = "URL", _("External URL")  # Link to an external resource

        # Interactive Types (Placeholders - require more complex handling/rendering)
        H5P = "H5P", _("H5P Content")  # Link to H5P file or platform
        SCORM = "SCORM", _(
            "SCORM Package"
        )  # Link to SCORM file (requires SCORM player)
        QUIZ = "QUIZ", _("Quiz / Assessment")  # Link to an Assessment model instance
        # Add other types like simulations, coding exercises, discussions etc.

    module = models.ForeignKey(
        Module, related_name="content_items", on_delete=models.CASCADE
    )
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=20, choices=ContentType.choices)
    order = models.PositiveIntegerField(
        default=0, help_text="Order of the content within the module"
    )

    # --- Content Data ---
    # Store content based on type. Use only one of the following.

    # 1. For TEXT type:
    text_content = models.TextField(
        blank=True, null=True, help_text="Markdown or HTML content"
    )

    # 2. For URL type or external video/audio:
    external_url = models.URLField(
        max_length=2048, blank=True, null=True, help_text="URL for external content"
    )

    # 3. For DOCUMENT, IMAGE, VIDEO, AUDIO, H5P, SCORM types (link to File model):
    file = models.ForeignKey(
        'files.File',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='content_items',
        help_text="Associated file for document, media, or package types"
    )

    # 4. For QUIZ type (link to Assessment model):
    # Need to define Assessment model in assessments app first
    # assessment = models.ForeignKey(
    #     'assessments.Assessment',
    #     on_delete=models.SET_NULL, # Keep content item if assessment deleted?
    #     null=True, blank=True,
    #     related_name='content_items',
    #     help_text="Associated assessment for quiz types"
    # )

    # Additional metadata (optional)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Type-specific metadata (e.g., video duration, quiz settings)",
    )
    is_published = models.BooleanField(
        default=False, db_index=True
    )  # Allow draft content items

    def __str__(self):
        return f"{self.title} ({self.get_content_type_display()})"

    class Meta:
        ordering = ["module", "order", "title"]
        # Ensure order is unique per module if strict ordering is required
        # unique_together = ('module', 'order')


class ContentVersion(TimestampedModel):
    """Tracks versions of a ContentItem."""

    content_item = models.ForeignKey(
        ContentItem, related_name="versions", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created this version",
    )
    version_number = models.PositiveIntegerField(default=1)
    comment = models.TextField(
        blank=True, help_text="Optional comment about changes in this version"
    )

    # Store snapshot of the content data at the time of versioning
    # This duplicates data but ensures historical accuracy
    content_type = models.CharField(
        max_length=20, choices=ContentItem.ContentType.choices
    )
    text_content = models.TextField(blank=True, null=True)
    external_url = models.URLField(max_length=2048, blank=True, null=True)
    # file_version = models.ForeignKey( # Link to specific FileVersion if using File versions
    #     'files.FileVersion',
    #     on_delete=models.SET_NULL, null=True, blank=True
    # )
    # assessment_snapshot = models.JSONField(default=dict, blank=True) # Snapshot of linked assessment?
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.content_item.title} - v{self.version_number}"

    class Meta:
        ordering = ["content_item", "-version_number"]
        unique_together = ("content_item", "version_number")
