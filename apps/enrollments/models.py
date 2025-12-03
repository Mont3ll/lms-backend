import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.courses.models import (  # Module progress tracked via ContentItem
    ContentItem,
    Course,
)
from apps.users.models import LearnerGroup, User

# from apps.learning_paths.models import LearningPath # For path enrollments if needed


class Enrollment(TimestampedModel):
    """Manages a User's enrollment in a Course."""

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")  # E.g., waiting for approval or payment
        ACTIVE = "ACTIVE", _("Active")
        COMPLETED = "COMPLETED", _("Completed")
        CANCELLED = "CANCELLED", _("Cancelled")  # User dropped or admin removed
        EXPIRED = "EXPIRED", _("Expired")  # If enrollment has time limit

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="enrollments")
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="enrollments"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    progress = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Course completion percentage",
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(
        null=True, blank=True, help_text="Optional date when enrollment access expires"
    )
    # enrolled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+') # User who performed enrollment action

    def __str__(self):
        return f"{self.user.email} enrolled in {self.course.title}"

    def mark_as_completed(self):
        """Sets the completion status and timestamp."""
        if self.status != self.Status.COMPLETED:
            self.status = self.Status.COMPLETED
            self.completed_at = timezone.now()
            self.progress = 100
            self.save(update_fields=["status", "completed_at", "progress", "updated_at"])
            # Trigger certificate generation, notifications etc. via signals or services
            from .services import (  # Avoid circular import if possible
                CertificateService,
                NotificationService,
            )

            CertificateService.generate_certificate_for_enrollment(self)
            NotificationService.notify_course_completion(self)
            
            # Sync with learning path progress
            try:
                from apps.learning_paths.services import LearningPathService
                LearningPathService.sync_course_completion_with_learning_paths(self)
            except ImportError:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("Learning paths app not available for synchronization")

    class Meta:
        unique_together = ("user", "course")  # User can only enroll once in a course
        ordering = ["user__email", "course__title"]


class GroupEnrollment(TimestampedModel):
    """Manages enrollment of a LearnerGroup in a Course."""

    group = models.ForeignKey(
        LearnerGroup, on_delete=models.CASCADE, related_name="course_enrollments"
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="group_enrollments"
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)
    # enrolled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f"Group '{self.group.name}' enrolled in '{self.course.title}'"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            # Trigger creation of individual Enrollment records for group members
            from .services import EnrollmentService  # Avoid circular import

            EnrollmentService.sync_group_enrollment(self)

    # Consider how updates to group membership affect individual enrollments (handled in service/signals)

    class Meta:
        unique_together = ("group", "course")
        ordering = ["group__name", "course__title"]


class LearnerProgress(TimestampedModel):
    """Tracks a User's progress on a specific ContentItem within an Enrollment."""

    class Status(models.TextChoices):
        NOT_STARTED = "NOT_STARTED", _("Not Started")
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        COMPLETED = "COMPLETED", _("Completed")

    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="progress_items"
    )
    content_item = models.ForeignKey(
        ContentItem, on_delete=models.CASCADE, related_name="+"
    )  # '+' avoids reverse relation clutter on ContentItem
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.NOT_STARTED, db_index=True
    )
    # Store progress details specific to content type
    # VIDEO: {'last_position_seconds': 120.5, 'total_duration_seconds': 300}
    # ASSESSMENT: {'attempt_id': 'uuid', 'score': 85.5, 'passed': True}
    # SCORM/H5P: Requires specific data structure based on standard (e.g., cmi5 data)
    # DOCUMENT/IMAGE: Simply 'completed' status might suffice
    progress_details = models.JSONField(
        default=dict, blank=True, help_text="Type-specific progress data"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Progress: {self.enrollment.user.email} on {self.content_item.title}"

    def mark_as_viewed(self):
        """Mark as started if not already started/completed."""
        if self.status == self.Status.NOT_STARTED:
            self.status = self.Status.IN_PROGRESS
            self.started_at = timezone.now()
            self.save(update_fields=["status", "started_at"])

    def mark_as_completed(self, details: dict = None):
        """Mark content item as completed."""
        if self.status != self.Status.COMPLETED:
            self.status = self.Status.COMPLETED
            self.completed_at = timezone.now()
            if not self.started_at:  # Ensure started_at is set if completing directly
                self.started_at = self.completed_at
            if details:
                self.progress_details.update(details)  # Merge details
            self.save(
                update_fields=[
                    "status",
                    "completed_at",
                    "started_at",
                    "progress_details",
                ]
            )
            # Trigger course completion check
            from .services import ProgressTrackerService  # Avoid circular import

            ProgressTrackerService.check_and_update_course_completion(self.enrollment)

    class Meta:
        unique_together = ("enrollment", "content_item")
        ordering = ["enrollment", "content_item__module__order", "content_item__order"]


class Certificate(TimestampedModel):
    """Represents a certificate issued for a completed Enrollment."""

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        ISSUED = "ISSUED", _("Issued")
        REVOKED = "REVOKED", _("Revoked")

    enrollment = models.OneToOneField(
        Enrollment, on_delete=models.CASCADE, related_name="certificate"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="certificates"
    )  # Denormalized for easy lookup
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="certificates"
    )  # Denormalized
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ISSUED, db_index=True
    )
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional expiry date")
    file_url = models.URLField(blank=True, null=True, help_text="URL to the certificate PDF")
    description = models.TextField(blank=True, help_text="Optional certificate description")
    # Store certificate as a file, or generate on-the-fly? Store file ref.
    # certificate_file = models.ForeignKey('files.File', on_delete=models.PROTECT, related_name='+')
    verification_code = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        help_text="Unique code for verification",
    )
    # Optional: snapshot of grade/completion details if needed on cert
    # grade_snapshot = models.CharField(max_length=10, blank=True)

    def __str__(self):
        return f"Certificate for {self.user.email} - {self.course.title}"

    # Add property for verification URL
    # @property
    # def verification_url(self):
    #     from django.urls import reverse
    #     return settings.SITE_URL + reverse('certificate-verify', kwargs={'code': self.verification_code})

    class Meta:
        ordering = ["-issued_at", "user__email"]
