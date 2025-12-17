import uuid  # Make sure uuid is imported if used in model defaults

from django.core.validators import (  # If used elsewhere in this file
    MaxValueValidator,
    MinValueValidator,
)
from django.db import models
from django.utils import timezone  # Import timezone if used in defaults
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.users.models import User

# from apps.core.models import Tenant # Link notifications to tenant?
# from django.contrib.contenttypes.fields import GenericForeignKey # If using related_object
# from django.contrib.contenttypes.models import ContentType # If using related_object


# --- Enums ---
class NotificationType(models.TextChoices):
    COURSE_ENROLLMENT = "COURSE_ENROLLMENT", _("Course Enrollment")
    COURSE_COMPLETION = "COURSE_COMPLETION", _("Course Completion")
    ASSESSMENT_SUBMISSION = "ASSESSMENT_SUBMISSION", _("Assessment Submission")
    ASSESSMENT_GRADED = "ASSESSMENT_GRADED", _("Assessment Graded")
    CERTIFICATE_ISSUED = "CERTIFICATE_ISSUED", _("Certificate Issued")
    DEADLINE_REMINDER = "DEADLINE_REMINDER", _("Deadline Reminder")
    NEW_CONTENT_AVAILABLE = "NEW_CONTENT_AVAILABLE", _("New Content Available")
    ANNOUNCEMENT = "ANNOUNCEMENT", _("Announcement")
    SYSTEM_ALERT = "SYSTEM_ALERT", _("System Alert")
    # Add more specific types


class DeliveryMethod(models.TextChoices):
    EMAIL = "EMAIL", _("Email")
    IN_APP = "IN_APP", _("In-App")  # Requires frontend implementation
    PUSH = "PUSH", _("Push Notification")  # Requires mobile app/service worker setup
    SMS = "SMS", _("SMS")  # Requires SMS gateway integration
    # Add others like Webhook?


# --- Models ---
class Notification(TimestampedModel):
    """Represents a notification sent or scheduled to be sent to a user."""

    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        SENT = "SENT", _("Sent")
        FAILED = "FAILED", _("Failed")
        READ = "READ", _("Read")  # Applicable mainly for IN_APP
        DISMISSED = "DISMISSED", _("Dismissed")  # Applicable mainly for IN_APP

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    # tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='notifications') # Optional tenant link
    notification_type = models.CharField(
        max_length=50, choices=NotificationType.choices
    )
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    subject = models.CharField(
        max_length=255, blank=True
    )  # Subject line (mainly for email)
    message = models.TextField(help_text="The main content of the notification.")
    # Optional: Link to related object (Course, Assessment, Enrollment etc.) using GenericForeignKey
    # content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    # object_id = models.UUIDField(null=True, blank=True, db_index=True)
    # related_object = GenericForeignKey('content_type', 'object_id')

    # Optional: URL to redirect user to when clicking notification
    action_url = models.URLField(max_length=2048, blank=True, null=True)

    # Delivery details
    delivery_methods = models.JSONField(
        default=list, help_text="List of methods attempted (e.g., ['EMAIL', 'IN_APP'])"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)  # For IN_APP
    fail_reason = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Notification for {self.recipient.email} ({self.get_notification_type_display()})"

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "status"], name="notif_recipient_status_idx"
            ),
            models.Index(fields=["created_at"]),
        ]


class NotificationPreference(TimestampedModel):
    """Stores user preferences for receiving different types of notifications via different methods."""

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="notification_preferences"
    )
    preferences = models.JSONField(default=dict, blank=True)
    is_enabled = models.BooleanField(
        default=True, help_text="Globally enable/disable notifications for this user"
    )

    def __str__(self):
        return f"Preferences for {self.user.email}"

    def is_method_enabled_for_type(
        self, notification_type: NotificationType | str, method: DeliveryMethod | str
    ) -> bool:
        """Checks if a specific delivery method is enabled for a notification type."""
        if not self.is_enabled:
            return False

        type_str = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else notification_type
        )
        method_str = method.value if isinstance(method, DeliveryMethod) else method

        type_prefs = self.preferences.get(type_str, {})
        # Default to ENABLED if not explicitly set in preferences
        return type_prefs.get(method_str, True)


#
# --- REMOVED Signal Handler Functions from models.py ---
# The functions create_user_notification_preferences and potentially save_user_profile (if you had it)
# should be moved to signals.py
#


class UserDevice(TimestampedModel):
    """Stores device tokens for push notifications (FCM, APNS)."""

    class DeviceType(models.TextChoices):
        ANDROID = "ANDROID", _("Android")
        IOS = "IOS", _("iOS")
        WEB = "WEB", _("Web Browser")

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="devices"
    )
    device_type = models.CharField(
        max_length=10, choices=DeviceType.choices, default=DeviceType.WEB
    )
    token = models.TextField(
        help_text="FCM registration token or APNS device token"
    )
    device_name = models.CharField(
        max_length=255, blank=True, help_text="User-friendly device name (e.g., 'Chrome on MacOS')"
    )
    is_active = models.BooleanField(
        default=True, help_text="Set to False when token becomes invalid"
    )
    last_used_at = models.DateTimeField(
        null=True, blank=True, help_text="Last time this device received a notification"
    )

    def __str__(self):
        return f"{self.user.email}'s {self.get_device_type_display()} device"

    class Meta:
        ordering = ["-created_at"]
        # Ensure unique token per user (a token should only belong to one user)
        unique_together = ("user", "token")


class Announcement(TimestampedModel):
    """
    Represents an admin announcement that can be sent to multiple users.
    Can target all users in a tenant, enrolled users in a course, etc.
    """
    
    class TargetType(models.TextChoices):
        ALL_TENANT = "ALL_TENANT", _("All Users in Tenant")
        COURSE_ENROLLED = "COURSE_ENROLLED", _("Course Enrolled Users")
        SPECIFIC_USERS = "SPECIFIC_USERS", _("Specific Users")
    
    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        SCHEDULED = "SCHEDULED", _("Scheduled")
        SENT = "SENT", _("Sent")
        CANCELLED = "CANCELLED", _("Cancelled")
    
    # From apps.core.models import Tenant if needed
    tenant = models.ForeignKey(
        'core.Tenant', on_delete=models.CASCADE, related_name='announcements'
    )
    author = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='authored_announcements'
    )
    
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    target_type = models.CharField(
        max_length=20, choices=TargetType.choices, default=TargetType.ALL_TENANT
    )
    # For COURSE_ENROLLED target type - store course ID
    target_course = models.ForeignKey(
        'courses.Course', on_delete=models.SET_NULL, 
        null=True, blank=True, related_name='announcements'
    )
    # For SPECIFIC_USERS target type - store list of user IDs as JSON
    target_user_ids = models.JSONField(
        default=list, blank=True, 
        help_text="List of user UUIDs for SPECIFIC_USERS target type"
    )
    
    status = models.CharField(
        max_length=15, choices=Status.choices, default=Status.DRAFT
    )
    scheduled_at = models.DateTimeField(
        null=True, blank=True, help_text="Scheduled time to send announcement"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    recipients_count = models.PositiveIntegerField(
        default=0, help_text="Number of notifications created from this announcement"
    )
    
    def __str__(self):
        return f"Announcement: {self.title} ({self.get_status_display()})"
    
    class Meta:
        ordering = ["-created_at"]
