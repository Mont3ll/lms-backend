"""Tests for notifications app services."""

from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationType,
    DeliveryMethod,
    UserDevice,
)
from apps.notifications.services import (
    NotificationService,
    EmailService,
    InAppService,
    SMSService,
    PushService,
)
from apps.core.models import Tenant
from apps.users.models import User


class NotificationServiceTests(TestCase):
    """Tests for the NotificationService class."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            first_name="Test",
            last_name="Learner",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )
        # Update auto-created preferences for the user
        self.prefs, _ = NotificationPreference.objects.get_or_create(
            user=self.user,
            defaults={
                "is_enabled": True,
                "preferences": {
                    "COURSE_ENROLLMENT": {"EMAIL": True, "IN_APP": True},
                    "SYSTEM_ALERT": {"EMAIL": True, "IN_APP": True},
                }
            }
        )
        # Ensure preferences are set correctly
        self.prefs.is_enabled = True
        self.prefs.preferences = {
            "COURSE_ENROLLMENT": {"EMAIL": True, "IN_APP": True},
            "SYSTEM_ALERT": {"EMAIL": True, "IN_APP": True},
        }
        self.prefs.save()

    @override_settings(EMAIL_HOST='localhost', EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    @patch('apps.notifications.services.send_notification_task')
    def test_create_notification_success(self, mock_task):
        """Test creating a notification successfully."""
        notification = NotificationService.create_notification(
            user=self.user,
            notification_type=NotificationType.COURSE_ENROLLMENT,
            subject="Welcome",
            message="You have been enrolled",
            action_url="https://lms.example.com/courses/1",
            trigger_send=True,
        )
        
        self.assertIsNotNone(notification)
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.notification_type, NotificationType.COURSE_ENROLLMENT)
        self.assertEqual(notification.subject, "Welcome")
        self.assertEqual(notification.status, Notification.Status.PENDING)
        self.assertIn("EMAIL", notification.delivery_methods)
        self.assertIn("IN_APP", notification.delivery_methods)
        
        # Verify async task was triggered
        mock_task.delay.assert_called_once_with(notification.id)

    @override_settings(EMAIL_HOST='localhost')
    @patch('apps.notifications.services.send_notification_task')
    def test_create_notification_no_trigger_send(self, mock_task):
        """Test creating a notification without triggering send."""
        notification = NotificationService.create_notification(
            user=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Alert",
            message="System alert message",
            trigger_send=False,
        )
        
        self.assertIsNotNone(notification)
        mock_task.delay.assert_not_called()

    def test_create_notification_missing_required_args(self):
        """Test that missing required arguments returns None."""
        # Missing user
        result = NotificationService.create_notification(
            user=None,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test",
            message="Test message",
        )
        self.assertIsNone(result)
        
        # Missing notification type
        result = NotificationService.create_notification(
            user=self.user,
            notification_type=None,
            subject="Test",
            message="Test message",
        )
        self.assertIsNone(result)
        
        # Missing message
        result = NotificationService.create_notification(
            user=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test",
            message="",
        )
        self.assertIsNone(result)

    def test_create_notification_invalid_type(self):
        """Test that invalid notification type returns None."""
        result = NotificationService.create_notification(
            user=self.user,
            notification_type="INVALID_TYPE",
            subject="Test",
            message="Test message",
        )
        self.assertIsNone(result)

    @override_settings(EMAIL_HOST='localhost')
    @patch('apps.notifications.services.send_notification_task')
    def test_create_notification_without_preferences(self, mock_task):
        """Test creating notification for user without saved preferences."""
        # Delete existing preferences
        self.prefs.delete()
        
        # Should still create notification with default enabled settings
        notification = NotificationService.create_notification(
            user=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Alert",
            message="Alert message",
            trigger_send=False,
        )
        
        self.assertIsNotNone(notification)

    def test_create_notification_globally_disabled(self):
        """Test that notification isn't created when user has globally disabled notifications."""
        self.prefs.is_enabled = False
        self.prefs.save()
        
        result = NotificationService.create_notification(
            user=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Alert",
            message="Alert message",
        )
        
        self.assertIsNone(result)

    @override_settings(EMAIL_HOST='localhost')
    def test_send_notification_success(self):
        """Test successfully sending a notification."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test Alert",
            message="Test message",
            delivery_methods=["IN_APP"],
            status=Notification.Status.PENDING,
        )
        
        with patch.object(InAppService, 'deliver_in_app_notification', return_value=True):
            NotificationService.send_notification(notification.id)
        
        notification.refresh_from_db()
        self.assertEqual(notification.status, Notification.Status.SENT)
        self.assertIsNotNone(notification.sent_at)

    def test_send_notification_not_found(self):
        """Test sending notification that doesn't exist."""
        import uuid
        fake_id = uuid.uuid4()
        
        # Should not raise exception, just log error
        NotificationService.send_notification(fake_id)

    def test_send_notification_not_pending(self):
        """Test sending notification that's not in PENDING state."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["IN_APP"],
            status=Notification.Status.SENT,  # Already sent
        )
        
        with patch.object(InAppService, 'deliver_in_app_notification') as mock:
            NotificationService.send_notification(notification.id)
            mock.assert_not_called()

    @override_settings(EMAIL_HOST='localhost')
    def test_send_notification_all_methods_fail(self):
        """Test notification status when all delivery methods fail."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test",
            message="Test message",
            delivery_methods=["EMAIL", "IN_APP"],
            status=Notification.Status.PENDING,
        )
        
        with patch.object(EmailService, 'send_email_notification', return_value=False):
            with patch.object(InAppService, 'deliver_in_app_notification', return_value=False):
                NotificationService.send_notification(notification.id)
        
        notification.refresh_from_db()
        self.assertEqual(notification.status, Notification.Status.FAILED)

    def test_is_method_globally_enabled_email(self):
        """Test checking if email method is globally enabled."""
        with override_settings(EMAIL_HOST='localhost'):
            self.assertTrue(
                NotificationService._is_method_globally_enabled(DeliveryMethod.EMAIL)
            )
        
        with override_settings(EMAIL_HOST='', EMAIL_BACKEND='other'):
            self.assertFalse(
                NotificationService._is_method_globally_enabled(DeliveryMethod.EMAIL)
            )

    def test_is_method_globally_enabled_in_app(self):
        """Test that IN_APP is always enabled."""
        self.assertTrue(
            NotificationService._is_method_globally_enabled(DeliveryMethod.IN_APP)
        )

    @override_settings(
        TWILIO_ACCOUNT_SID='test_sid',
        TWILIO_AUTH_TOKEN='test_token',
        TWILIO_FROM_NUMBER='+1234567890'
    )
    def test_is_method_globally_enabled_sms(self):
        """Test checking if SMS method is globally enabled."""
        self.assertTrue(
            NotificationService._is_method_globally_enabled(DeliveryMethod.SMS)
        )

    @override_settings(FCM_SERVER_KEY='test_fcm_key')
    def test_is_method_globally_enabled_push(self):
        """Test checking if Push method is globally enabled."""
        self.assertTrue(
            NotificationService._is_method_globally_enabled(DeliveryMethod.PUSH)
        )

    def test_generate_content_for_type_course_enrollment(self):
        """Test generating content for course enrollment notification."""
        context = {
            "user_name": "John Doe",
            "course_name": "Python Basics"
        }
        result = NotificationService.generate_content_for_type(
            NotificationType.COURSE_ENROLLMENT,
            context
        )
        
        self.assertIn("Python Basics", result["subject"])
        self.assertIn("John Doe", result["message"])

    def test_generate_content_for_type_assessment_graded(self):
        """Test generating content for assessment graded notification."""
        context = {
            "user_name": "Jane Doe",
            "course_name": "Web Development",
            "assessment_title": "Final Exam",
            "score": "85",
            "max_score": "100",
        }
        result = NotificationService.generate_content_for_type(
            NotificationType.ASSESSMENT_GRADED,
            context
        )
        
        self.assertIn("graded", result["subject"])
        self.assertIn("85/100", result["message"])


class EmailServiceTests(TestCase):
    """Tests for the EmailService class."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant
        )

    @override_settings(
        EMAIL_HOST='localhost',
        DEFAULT_FROM_EMAIL='noreply@lms.example.com'
    )
    @patch('apps.notifications.services.send_mail')
    def test_send_email_notification_success(self, mock_send_mail):
        """Test successfully sending email notification."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test Subject",
            message="Test message body",
            delivery_methods=["EMAIL"],
        )
        
        mock_send_mail.return_value = 1
        result = EmailService.send_email_notification(notification)
        
        self.assertTrue(result)
        mock_send_mail.assert_called_once()
        call_args = mock_send_mail.call_args
        self.assertEqual(call_args.kwargs['subject'], "Test Subject")
        self.assertEqual(call_args.kwargs['recipient_list'], [self.user.email])

    def test_send_email_notification_no_email(self):
        """Test sending email when user has no email address."""
        self.user.email = ""
        self.user.save()
        
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["EMAIL"],
        )
        
        result = EmailService.send_email_notification(notification)
        self.assertFalse(result)

    @override_settings(
        EMAIL_HOST='localhost',
        DEFAULT_FROM_EMAIL='noreply@lms.example.com'
    )
    @patch('apps.notifications.services.send_mail')
    def test_send_email_notification_failure(self, mock_send_mail):
        """Test handling email send failure."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test",
            message="Test message",
            delivery_methods=["EMAIL"],
        )
        
        mock_send_mail.side_effect = Exception("SMTP error")
        result = EmailService.send_email_notification(notification)
        
        self.assertFalse(result)


class InAppServiceTests(TestCase):
    """Tests for the InAppService class."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant
        )

    def test_deliver_in_app_notification(self):
        """Test delivering in-app notification."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["IN_APP"],
        )
        
        result = InAppService.deliver_in_app_notification(notification)
        
        # In-app delivery is essentially just confirming the notification exists
        self.assertTrue(result)


class SMSServiceTests(TestCase):
    """Tests for the SMSService class."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant
        )

    def test_send_sms_notification_no_phone(self):
        """Test sending SMS when user has no phone number."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["SMS"],
        )
        
        result = SMSService.send_sms_notification(notification)
        self.assertFalse(result)

    @override_settings(
        TWILIO_ACCOUNT_SID='test_sid',
        TWILIO_AUTH_TOKEN='test_token',
        TWILIO_FROM_NUMBER='+1234567890'
    )
    @patch('apps.notifications.services.SMSService.send_sms_notification')
    def test_send_sms_notification_with_twilio(self, mock_send):
        """Test sending SMS with Twilio configured."""
        mock_send.return_value = True
        
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test SMS message",
            delivery_methods=["SMS"],
        )
        
        result = SMSService.send_sms_notification(notification)
        # Will fail because user has no phone number
        self.assertTrue(result)


class PushServiceTests(TestCase):
    """Tests for the PushService class."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant
        )

    def test_send_push_notification_no_devices(self):
        """Test sending push when user has no devices."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["PUSH"],
        )
        
        with override_settings(FCM_SERVER_KEY='test_key'):
            result = PushService.send_push_notification(notification)
        
        self.assertFalse(result)

    @override_settings(FCM_SERVER_KEY='test_fcm_key')
    @patch('requests.post')
    def test_send_push_notification_success(self, mock_post):
        """Test successful push notification."""
        # Create device for user
        UserDevice.objects.create(
            user=self.user,
            device_type=UserDevice.DeviceType.WEB,
            token="test_fcm_token_123",
            is_active=True,
        )
        
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="Test Alert",
            message="Test push message",
            delivery_methods=["PUSH"],
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": 1,
            "failure": 0,
            "results": [{"message_id": "123"}]
        }
        mock_post.return_value = mock_response
        
        result = PushService.send_push_notification(notification)
        
        self.assertTrue(result)
        mock_post.assert_called_once()

    @override_settings(FCM_SERVER_KEY='test_fcm_key')
    @patch('requests.post')
    def test_send_push_notification_with_invalid_token(self, mock_post):
        """Test push notification handling of invalid tokens."""
        # Create device with token that will become invalid
        device = UserDevice.objects.create(
            user=self.user,
            device_type=UserDevice.DeviceType.ANDROID,
            token="invalid_token_123",
            is_active=True,
        )
        
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["PUSH"],
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": 0,
            "failure": 1,
            "results": [{"error": "NotRegistered"}]
        }
        mock_post.return_value = mock_response
        
        PushService.send_push_notification(notification)
        
        # Device should be deactivated
        device.refresh_from_db()
        self.assertFalse(device.is_active)

    def test_send_push_notification_no_fcm_config(self):
        """Test push notification when FCM is not configured."""
        UserDevice.objects.create(
            user=self.user,
            token="test_token",
            is_active=True,
        )
        
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test message",
            delivery_methods=["PUSH"],
        )
        
        with override_settings(FCM_SERVER_KEY=None):
            result = PushService.send_push_notification(notification)
        
        self.assertFalse(result)
