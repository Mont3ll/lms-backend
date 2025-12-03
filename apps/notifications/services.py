import logging
from typing import Any, Dict, List

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .models import (
    DeliveryMethod,
    Notification,
    NotificationPreference,
    NotificationType,
    User,
)
from .tasks import send_notification_task  # Celery task

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    pass


class NotificationService:
    """Service for creating and sending notifications."""

    @staticmethod
    def create_notification(
        user: User,
        notification_type: NotificationType | str,
        subject: str,
        message: str,
        action_url: str | None = None,
        # related_object=None, # Optional related object
        trigger_send: bool = True,
        preferred_methods: (
            List[DeliveryMethod | str] | None
        ) = None,  # Hint for preferred methods
    ) -> Notification | None:
        """Creates a Notification record and optionally triggers sending."""
        if not user or not notification_type or not message:
            logger.error(
                "Missing required arguments for create_notification (user, type, message)."
            )
            return None

        type_str = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else notification_type
        )
        if type_str not in NotificationType.values:
            logger.error(f"Invalid notification_type: {type_str}")
            return None

        # Get user preferences
        try:
            prefs = NotificationPreference.objects.get(user=user)
        except NotificationPreference.DoesNotExist:
            logger.warning(
                f"NotificationPreference not found for user {user.id}, using defaults."
            )
            prefs = NotificationPreference(
                user=user
            )  # Use default behaviour (defaults to enabled)

        # Determine target delivery methods based on preferences and availability
        target_methods = []
        possible_methods = preferred_methods or [
            m.value for m in DeliveryMethod
        ]  # Consider all if no preference hinted

        for method in possible_methods:
            method_enum = None
            try:
                method_enum = DeliveryMethod(method)
            except ValueError:
                logger.warning(f"Invalid delivery method specified: {method}")
                continue

            # Check if service for this method is configured/enabled globally (e.g., SMS keys set)
            if not NotificationService._is_method_globally_enabled(method_enum):
                continue

            # Check user preference
            if prefs.is_method_enabled_for_type(type_str, method_enum):
                target_methods.append(method_enum.value)

        if not target_methods:
            logger.info(
                f"No enabled delivery methods found for user {user.id}, type {type_str}. Notification not created."
            )
            return None  # Don't create notification if no way to send it

        # Create Notification record
        notification = Notification.objects.create(
            recipient=user,
            notification_type=type_str,
            subject=subject,
            message=message,  # This might be HTML for email, plain text for SMS/Push
            action_url=action_url,
            delivery_methods=target_methods,  # Store methods we intend to try
            status=Notification.Status.PENDING,
            # Add related_object fields if needed
        )
        logger.info(
            f"Created notification {notification.id} for user {user.id}, type {type_str}, methods: {target_methods}"
        )

        if trigger_send:
            # Trigger async task to handle actual sending
            send_notification_task.delay(notification.id)

        return notification

    @staticmethod
    def _is_method_globally_enabled(method: DeliveryMethod) -> bool:
        """Checks if a delivery method is configured in settings."""
        if method == DeliveryMethod.EMAIL:
            # Check if relevant EMAIL settings exist
            return bool(
                settings.EMAIL_HOST
                or settings.EMAIL_BACKEND
                == "django.core.mail.backends.console.EmailBackend"
            )
        elif method == DeliveryMethod.SMS:
            # Check for SMS provider keys/settings
            # return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN) # Example
            return False  # Placeholder
        elif method == DeliveryMethod.PUSH:
            # Check for Push notification service keys (FCM, APNS)
            return False  # Placeholder
        elif method == DeliveryMethod.IN_APP:
            return True  # In-app is usually just DB storage, enabled by default
        return False

    @staticmethod
    def send_notification(notification_id: uuid.UUID):
        """
        Attempts to send a notification via its configured delivery methods.
        Called by the Celery task.
        """
        try:
            notification = Notification.objects.select_related("recipient").get(
                pk=notification_id
            )
        except Notification.DoesNotExist:
            logger.error(f"Notification {notification_id} not found for sending.")
            return

        if notification.status != Notification.Status.PENDING:
            logger.warning(
                f"Notification {notification_id} not in PENDING state (status: {notification.status}). Skipping send."
            )
            return

        logger.info(
            f"Attempting to send notification {notification.id} via methods: {notification.delivery_methods}"
        )
        success = False
        errors = []

        for method_str in notification.delivery_methods:
            try:
                method = DeliveryMethod(method_str)
                sent = False
                if method == DeliveryMethod.EMAIL:
                    sent = EmailService.send_email_notification(notification)
                elif method == DeliveryMethod.IN_APP:
                    sent = InAppService.deliver_in_app_notification(notification)
                elif method == DeliveryMethod.SMS:
                    sent = SMSService.send_sms_notification(notification)
                elif method == DeliveryMethod.PUSH:
                    sent = PushService.send_push_notification(notification)

                if sent:
                    success = True
                    logger.info(
                        f"Notification {notification.id} sent successfully via {method.label}"
                    )
                    # Optionally stop sending via other methods if one succeeds? Or send all enabled? Send all for now.
                # else: implicitly failed if sent is False (logged within specific service)

            except Exception as e:
                error_msg = f"Error sending notification {notification.id} via {method_str}: {e}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)

        # Update notification status
        if success:
            notification.status = Notification.Status.SENT
            notification.sent_at = timezone.now()
            notification.fail_reason = None
        else:
            notification.status = Notification.Status.FAILED
            notification.fail_reason = (
                "\n".join(errors)
                if errors
                else "All delivery methods failed without specific error."
            )

        notification.save(update_fields=["status", "sent_at", "fail_reason"])

    # --- Helper methods to generate message content based on type ---
    # These could live elsewhere or be more sophisticated using templates

    @staticmethod
    def generate_content_for_type(
        notification_type: NotificationType | str, context: Dict[str, Any]
    ) -> Dict[str, str]:
        """Generates subject and message based on type and context data."""
        type_str = (
            notification_type.value
            if isinstance(notification_type, NotificationType)
            else notification_type
        )
        subject = (
            f"LMS Notification: {NotificationType(type_str).label}"  # Default subject
        )
        message = f"You have a new notification."  # Default message
        html_message = message  # Default HTML

        # Example context keys: 'user_name', 'course_name', 'assessment_title', 'due_date', 'issuer_name'
        user_name = context.get("user_name", "Learner")
        course_name = context.get("course_name", "the course")

        try:
            if type_str == NotificationType.COURSE_ENROLLMENT:
                subject = f"You are enrolled in {course_name}"
                message = f"Hi {user_name},\n\nYou have been successfully enrolled in the course: {course_name}.\n\nStart learning now!"
                # html_message = render_to_string('notifications/email/enrollment.html', context)
            elif type_str == NotificationType.COURSE_COMPLETION:
                subject = f"Congratulations on completing {course_name}!"
                message = f"Hi {user_name},\n\nWell done! You have successfully completed the course: {course_name}.\n\nYour certificate may be available shortly."
                # html_message = render_to_string(...)
            elif type_str == NotificationType.CERTIFICATE_ISSUED:
                subject = f"Your certificate for {course_name} is available"
                message = f"Hi {user_name},\n\nYour certificate for completing {course_name} has been issued and is now available."
                # html_message = render_to_string(...)
            # Add cases for other notification types...
        except Exception as e:
            logger.error(
                f"Error generating content for notification type {type_str}: {e}",
                exc_info=True,
            )
            # Use default content on error

        return {
            "subject": subject,
            "message": message,
            "html_message": html_message,
        }  # Return both plain and HTML?


class EmailService:
    """Handles sending email notifications."""

    @staticmethod
    def send_email_notification(notification: Notification) -> bool:
        """Sends the notification content via email."""
        recipient = notification.recipient
        if not recipient.email:
            logger.warning(
                f"Cannot send email for notification {notification.id}: Recipient {recipient.id} has no email address."
            )
            return False

        # Use generated subject/message or defaults
        subject = (
            notification.subject
            or f"LMS Notification ({notification.get_notification_type_display()})"
        )
        plain_message = notification.message
        # Assume message field might contain basic HTML, or generate specific HTML version
        html_message = (
            notification.message
        )  # Replace with rendered template if available

        try:
            # Use Django's send_mail function
            send_mail(
                subject=subject,
                message=plain_message,  # Plain text version
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient.email],
                html_message=html_message,  # HTML version (optional)
                fail_silently=False,  # Raise exception on failure
            )
            logger.info(
                f"Email sent successfully for notification {notification.id} to {recipient.email}"
            )
            return True
        except Exception as e:
            logger.error(
                f"Failed to send email for notification {notification.id} to {recipient.email}: {e}",
                exc_info=True,
            )
            return False


class InAppService:
    """Handles 'sending' in-app notifications (essentially ensures it's stored)."""

    @staticmethod
    def deliver_in_app_notification(notification: Notification) -> bool:
        """Marks the notification as ready for in-app display. Status will be PENDING until sent."""
        # The notification object is already created.
        # Frontend will fetch notifications with PENDING/SENT status for this user.
        # No specific action needed here unless complex real-time push (e.g., WebSockets) is used.
        logger.info(
            f"In-app notification {notification.id} ready for user {notification.recipient.id}"
        )
        return True  # Delivery is essentially just creation


class SMSService:
    """Handles sending SMS notifications. (Placeholder)"""

    @staticmethod
    def send_sms_notification(notification: Notification) -> bool:
        """Sends the notification message via SMS."""
        recipient = notification.recipient
        # Need user's phone number, likely stored in UserProfile
        phone_number = getattr(
            getattr(recipient, "profile", None), "phone_number", None
        )

        if not phone_number:
            logger.warning(
                f"Cannot send SMS for notification {notification.id}: Recipient {recipient.id} has no phone number."
            )
            return False

        # Truncate message if needed for SMS length limits
        sms_message = (
            (notification.message[:157] + "...")
            if len(notification.message) > 160
            else notification.message
        )

        # --- Integration with SMS Provider (e.g., Twilio) ---
        # try:
        #     from twilio.rest import Client
        #     client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        #     message = client.messages.create(
        #         body=sms_message,
        #         from_=settings.TWILIO_FROM_NUMBER,
        #         to=phone_number
        #     )
        #     logger.info(f"SMS sent successfully for notification {notification.id} to {phone_number} (SID: {message.sid})")
        #     return True
        # except Exception as e:
        #      logger.error(f"Failed to send SMS for notification {notification.id} to {phone_number}: {e}", exc_info=True)
        #      return False
        # ----------------------------------------------------
        logger.warning(
            f"SMS sending not implemented. Skipped for notification {notification.id}."
        )
        return False


class PushService:
    """Handles sending Push notifications. (Placeholder)"""

    @staticmethod
    def send_push_notification(notification: Notification) -> bool:
        """Sends a push notification to user's registered devices."""
        recipient = notification.recipient
        # Requires storing device tokens (e.g., FCM tokens) associated with the user
        # device_tokens = UserDevice.objects.filter(user=recipient, is_active=True).values_list('token', flat=True)
        device_tokens = []  # Placeholder

        if not device_tokens:
            logger.warning(
                f"Cannot send Push notification for {notification.id}: Recipient {recipient.id} has no active device tokens."
            )
            return False

        push_title = (
            notification.subject or notification.get_notification_type_display()
        )
        push_body = notification.message  # Truncate if needed
        push_data = {
            "notification_id": str(notification.id),
            "action_url": notification.action_url,
        }

        # --- Integration with Push Service (e.g., Firebase FCM, django-push-notifications) ---
        # try:
        #     from push_notifications.models import GCMDevice # Example library
        #     GCMDevice.objects.filter(registration_id__in=device_tokens).send_message(
        #         push_body,
        #         title=push_title,
        #         extra=push_data
        #     )
        #     logger.info(f"Push notification sent successfully for notification {notification.id} to {len(device_tokens)} devices.")
        #     return True
        # except Exception as e:
        #      logger.error(f"Failed to send Push notification for {notification.id}: {e}", exc_info=True)
        #      return False
        # --------------------------------------------------------------------------------------
        logger.warning(
            f"Push notification sending not implemented. Skipped for notification {notification.id}."
        )
        return False
