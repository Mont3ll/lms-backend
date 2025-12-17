"""Tests for notifications app models."""

from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone

from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationType,
    DeliveryMethod,
    UserDevice,
    Announcement,
)
from apps.core.models import Tenant
from apps.courses.models import Course
from apps.users.models import User


class NotificationModelTests(TestCase):
    """Tests for the Notification model."""

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

    def test_notification_creation(self):
        """Test basic notification creation."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.COURSE_ENROLLMENT,
            subject="Welcome to Python Basics",
            message="You have been enrolled in Python Basics course.",
            delivery_methods=["EMAIL", "IN_APP"],
        )
        
        self.assertEqual(notification.recipient, self.user)
        self.assertEqual(notification.notification_type, NotificationType.COURSE_ENROLLMENT)
        self.assertEqual(notification.subject, "Welcome to Python Basics")
        self.assertEqual(notification.status, Notification.Status.PENDING)
        self.assertIsNotNone(notification.id)
        self.assertIsNotNone(notification.created_at)

    def test_notification_status_choices(self):
        """Test notification status transitions."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test notification",
        )
        
        # Default status is PENDING
        self.assertEqual(notification.status, Notification.Status.PENDING)
        
        # Can change to SENT
        notification.status = Notification.Status.SENT
        notification.sent_at = timezone.now()
        notification.save()
        notification.refresh_from_db()
        self.assertEqual(notification.status, Notification.Status.SENT)
        
        # Can change to READ
        notification.status = Notification.Status.READ
        notification.read_at = timezone.now()
        notification.save()
        notification.refresh_from_db()
        self.assertEqual(notification.status, Notification.Status.READ)
        
        # Can change to DISMISSED
        notification.status = Notification.Status.DISMISSED
        notification.save()
        notification.refresh_from_db()
        self.assertEqual(notification.status, Notification.Status.DISMISSED)

    def test_notification_type_choices(self):
        """Test all notification types."""
        notification_types = [
            NotificationType.COURSE_ENROLLMENT,
            NotificationType.COURSE_COMPLETION,
            NotificationType.ASSESSMENT_SUBMISSION,
            NotificationType.ASSESSMENT_GRADED,
            NotificationType.CERTIFICATE_ISSUED,
            NotificationType.DEADLINE_REMINDER,
            NotificationType.NEW_CONTENT_AVAILABLE,
            NotificationType.ANNOUNCEMENT,
            NotificationType.SYSTEM_ALERT,
        ]
        
        for nt in notification_types:
            notification = Notification.objects.create(
                recipient=self.user,
                notification_type=nt,
                message=f"Test notification for {nt}",
            )
            self.assertEqual(notification.notification_type, nt)

    def test_notification_with_action_url(self):
        """Test notification with action URL."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.COURSE_ENROLLMENT,
            message="You're enrolled!",
            action_url="https://lms.example.com/courses/python-basics",
        )
        
        self.assertEqual(
            notification.action_url,
            "https://lms.example.com/courses/python-basics"
        )

    def test_notification_delivery_methods_json(self):
        """Test delivery methods JSON field."""
        methods = ["EMAIL", "IN_APP", "PUSH"]
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.ANNOUNCEMENT,
            message="Important announcement",
            delivery_methods=methods,
        )
        
        self.assertEqual(notification.delivery_methods, methods)
        self.assertIn("EMAIL", notification.delivery_methods)
        self.assertIn("IN_APP", notification.delivery_methods)
        self.assertIn("PUSH", notification.delivery_methods)

    def test_notification_str_representation(self):
        """Test notification string representation."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.COURSE_ENROLLMENT,
            message="Test message",
        )
        
        self.assertIn(self.user.email, str(notification))
        self.assertIn("Course Enrollment", str(notification))

    def test_notification_ordering(self):
        """Test notifications are ordered by created_at descending."""
        notification1 = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="First notification",
        )
        notification2 = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Second notification",
        )
        notification3 = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Third notification",
        )
        
        # Default ordering should be newest first
        notifications = list(Notification.objects.filter(recipient=self.user))
        self.assertEqual(notifications[0], notification3)
        self.assertEqual(notifications[1], notification2)
        self.assertEqual(notifications[2], notification1)

    def test_notification_cascade_delete(self):
        """Test that notifications are deleted when user is deleted."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test notification",
        )
        notification_id = notification.id
        
        self.user.delete()
        
        self.assertFalse(Notification.objects.filter(id=notification_id).exists())

    def test_notification_fail_reason(self):
        """Test storing failure reason for failed notifications."""
        notification = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            message="Test notification",
            status=Notification.Status.FAILED,
            fail_reason="SMTP server connection failed",
        )
        
        self.assertEqual(notification.status, Notification.Status.FAILED)
        self.assertEqual(notification.fail_reason, "SMTP server connection failed")


class NotificationPreferenceModelTests(TestCase):
    """Tests for the NotificationPreference model."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )
        # Delete auto-created preferences to allow manual creation in tests
        NotificationPreference.objects.filter(user=self.user).delete()

    def test_notification_preference_creation(self):
        """Test creating notification preferences."""
        prefs = NotificationPreference.objects.create(
            user=self.user,
            is_enabled=True,
            preferences={
                "COURSE_ENROLLMENT": {"EMAIL": True, "IN_APP": True},
                "ASSESSMENT_GRADED": {"EMAIL": True, "IN_APP": True, "PUSH": False},
            }
        )
        
        self.assertEqual(prefs.user, self.user)
        self.assertTrue(prefs.is_enabled)
        self.assertIn("COURSE_ENROLLMENT", prefs.preferences)
        self.assertIn("ASSESSMENT_GRADED", prefs.preferences)

    def test_notification_preference_one_to_one(self):
        """Test that user can only have one preference record."""
        NotificationPreference.objects.create(
            user=self.user,
            is_enabled=True,
        )
        
        with self.assertRaises(IntegrityError):
            NotificationPreference.objects.create(
                user=self.user,
                is_enabled=False,
            )

    def test_notification_preference_default_values(self):
        """Test default values for notification preferences."""
        prefs = NotificationPreference.objects.create(user=self.user)
        
        self.assertTrue(prefs.is_enabled)
        self.assertEqual(prefs.preferences, {})

    def test_is_method_enabled_for_type_enabled(self):
        """Test is_method_enabled_for_type returns True when enabled."""
        prefs = NotificationPreference.objects.create(
            user=self.user,
            is_enabled=True,
            preferences={
                "COURSE_ENROLLMENT": {"EMAIL": True, "IN_APP": True},
            }
        )
        
        self.assertTrue(
            prefs.is_method_enabled_for_type(
                NotificationType.COURSE_ENROLLMENT,
                DeliveryMethod.EMAIL
            )
        )
        self.assertTrue(
            prefs.is_method_enabled_for_type(
                "COURSE_ENROLLMENT",  # Test with string
                "IN_APP"  # Test with string
            )
        )

    def test_is_method_enabled_for_type_disabled(self):
        """Test is_method_enabled_for_type returns False when disabled."""
        prefs = NotificationPreference.objects.create(
            user=self.user,
            is_enabled=True,
            preferences={
                "COURSE_ENROLLMENT": {"EMAIL": False, "IN_APP": True},
            }
        )
        
        self.assertFalse(
            prefs.is_method_enabled_for_type(
                NotificationType.COURSE_ENROLLMENT,
                DeliveryMethod.EMAIL
            )
        )

    def test_is_method_enabled_for_type_globally_disabled(self):
        """Test is_method_enabled_for_type returns False when globally disabled."""
        prefs = NotificationPreference.objects.create(
            user=self.user,
            is_enabled=False,  # Globally disabled
            preferences={
                "COURSE_ENROLLMENT": {"EMAIL": True, "IN_APP": True},
            }
        )
        
        # Should return False even though type/method is enabled in preferences
        self.assertFalse(
            prefs.is_method_enabled_for_type(
                NotificationType.COURSE_ENROLLMENT,
                DeliveryMethod.EMAIL
            )
        )

    def test_is_method_enabled_for_type_default_enabled(self):
        """Test is_method_enabled_for_type defaults to True if not set."""
        prefs = NotificationPreference.objects.create(
            user=self.user,
            is_enabled=True,
            preferences={}  # Empty preferences
        )
        
        # Should default to True for any type/method not explicitly set
        self.assertTrue(
            prefs.is_method_enabled_for_type(
                NotificationType.COURSE_ENROLLMENT,
                DeliveryMethod.EMAIL
            )
        )

    def test_notification_preference_str_representation(self):
        """Test preference string representation."""
        prefs = NotificationPreference.objects.create(user=self.user)
        
        self.assertIn(self.user.email, str(prefs))


class UserDeviceModelTests(TestCase):
    """Tests for the UserDevice model."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.user = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )

    def test_user_device_creation(self):
        """Test creating a user device."""
        device = UserDevice.objects.create(
            user=self.user,
            device_type=UserDevice.DeviceType.WEB,
            token="fcm_token_123abc",
            device_name="Chrome on MacOS",
        )
        
        self.assertEqual(device.user, self.user)
        self.assertEqual(device.device_type, UserDevice.DeviceType.WEB)
        self.assertEqual(device.token, "fcm_token_123abc")
        self.assertEqual(device.device_name, "Chrome on MacOS")
        self.assertTrue(device.is_active)

    def test_user_device_types(self):
        """Test all device types."""
        device_types = [
            (UserDevice.DeviceType.ANDROID, "Android"),
            (UserDevice.DeviceType.IOS, "iOS"),
            (UserDevice.DeviceType.WEB, "Web Browser"),
        ]
        
        for device_type, display_name in device_types:
            device = UserDevice.objects.create(
                user=self.user,
                device_type=device_type,
                token=f"token_{device_type}",
            )
            self.assertEqual(device.device_type, device_type)
            self.assertEqual(device.get_device_type_display(), display_name)

    def test_user_device_unique_token_per_user(self):
        """Test that token must be unique per user."""
        UserDevice.objects.create(
            user=self.user,
            device_type=UserDevice.DeviceType.WEB,
            token="unique_token_123",
        )
        
        with self.assertRaises(IntegrityError):
            UserDevice.objects.create(
                user=self.user,
                device_type=UserDevice.DeviceType.ANDROID,
                token="unique_token_123",  # Same token
            )

    def test_user_device_same_token_different_users(self):
        """Test that same token can exist for different users (edge case)."""
        user2 = User.objects.create_user(
            email="learner2@example.com",
            password="testpass123",
            tenant=self.tenant
        )
        
        UserDevice.objects.create(
            user=self.user,
            token="shared_token_123",
        )
        
        # Should succeed for different user
        device2 = UserDevice.objects.create(
            user=user2,
            token="shared_token_123",
        )
        self.assertEqual(device2.token, "shared_token_123")

    def test_user_device_deactivation(self):
        """Test deactivating a device."""
        device = UserDevice.objects.create(
            user=self.user,
            token="token_123",
            is_active=True,
        )
        
        device.is_active = False
        device.save()
        device.refresh_from_db()
        
        self.assertFalse(device.is_active)

    def test_user_device_last_used_at(self):
        """Test updating last_used_at timestamp."""
        device = UserDevice.objects.create(
            user=self.user,
            token="token_123",
        )
        
        self.assertIsNone(device.last_used_at)
        
        device.last_used_at = timezone.now()
        device.save()
        device.refresh_from_db()
        
        self.assertIsNotNone(device.last_used_at)

    def test_user_device_str_representation(self):
        """Test device string representation."""
        device = UserDevice.objects.create(
            user=self.user,
            device_type=UserDevice.DeviceType.IOS,
            token="token_123",
        )
        
        self.assertIn(self.user.email, str(device))
        self.assertIn("iOS", str(device))

    def test_user_device_ordering(self):
        """Test devices are ordered by created_at descending."""
        device1 = UserDevice.objects.create(
            user=self.user,
            token="token_1",
        )
        device2 = UserDevice.objects.create(
            user=self.user,
            token="token_2",
        )
        device3 = UserDevice.objects.create(
            user=self.user,
            token="token_3",
        )
        
        devices = list(UserDevice.objects.filter(user=self.user))
        self.assertEqual(devices[0], device3)
        self.assertEqual(devices[1], device2)
        self.assertEqual(devices[2], device1)


class AnnouncementModelTests(TestCase):
    """Tests for the Announcement model."""

    def setUp(self):
        """Set up test data."""
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            tenant=self.tenant,
            is_staff=True,
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor
        )

    def test_announcement_creation(self):
        """Test basic announcement creation."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="System Maintenance",
            message="The system will be down for maintenance on Saturday.",
            target_type=Announcement.TargetType.ALL_TENANT,
        )
        
        self.assertEqual(announcement.tenant, self.tenant)
        self.assertEqual(announcement.author, self.admin)
        self.assertEqual(announcement.title, "System Maintenance")
        self.assertEqual(announcement.status, Announcement.Status.DRAFT)
        self.assertEqual(announcement.target_type, Announcement.TargetType.ALL_TENANT)

    def test_announcement_status_choices(self):
        """Test announcement status transitions."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Test Announcement",
            message="Test message",
        )
        
        # Default status is DRAFT
        self.assertEqual(announcement.status, Announcement.Status.DRAFT)
        
        # Can change to SCHEDULED
        announcement.status = Announcement.Status.SCHEDULED
        announcement.scheduled_at = timezone.now()
        announcement.save()
        announcement.refresh_from_db()
        self.assertEqual(announcement.status, Announcement.Status.SCHEDULED)
        
        # Can change to SENT
        announcement.status = Announcement.Status.SENT
        announcement.sent_at = timezone.now()
        announcement.save()
        announcement.refresh_from_db()
        self.assertEqual(announcement.status, Announcement.Status.SENT)

    def test_announcement_target_type_all_tenant(self):
        """Test announcement targeting all tenant users."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="All Users Announcement",
            message="This is for everyone",
            target_type=Announcement.TargetType.ALL_TENANT,
        )
        
        self.assertEqual(announcement.target_type, Announcement.TargetType.ALL_TENANT)
        self.assertIsNone(announcement.target_course)
        self.assertEqual(announcement.target_user_ids, [])

    def test_announcement_target_type_course_enrolled(self):
        """Test announcement targeting course enrolled users."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Course Announcement",
            message="Important update for enrolled students",
            target_type=Announcement.TargetType.COURSE_ENROLLED,
            target_course=self.course,
        )
        
        self.assertEqual(announcement.target_type, Announcement.TargetType.COURSE_ENROLLED)
        self.assertEqual(announcement.target_course, self.course)

    def test_announcement_target_type_specific_users(self):
        """Test announcement targeting specific users."""
        user_ids = [str(self.admin.id), str(self.instructor.id)]
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Specific Users Announcement",
            message="This is for specific people",
            target_type=Announcement.TargetType.SPECIFIC_USERS,
            target_user_ids=user_ids,
        )
        
        self.assertEqual(announcement.target_type, Announcement.TargetType.SPECIFIC_USERS)
        self.assertEqual(announcement.target_user_ids, user_ids)

    def test_announcement_recipients_count(self):
        """Test tracking recipients count."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Test Announcement",
            message="Test message",
            recipients_count=50,
        )
        
        self.assertEqual(announcement.recipients_count, 50)

    def test_announcement_str_representation(self):
        """Test announcement string representation."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="System Update",
            message="Important system update",
        )
        
        self.assertIn("System Update", str(announcement))
        self.assertIn("Draft", str(announcement))

    def test_announcement_ordering(self):
        """Test announcements are ordered by created_at descending."""
        announcement1 = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="First",
            message="First",
        )
        announcement2 = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Second",
            message="Second",
        )
        announcement3 = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Third",
            message="Third",
        )
        
        announcements = list(Announcement.objects.filter(tenant=self.tenant))
        self.assertEqual(announcements[0], announcement3)
        self.assertEqual(announcements[1], announcement2)
        self.assertEqual(announcements[2], announcement1)

    def test_announcement_cancelled_status(self):
        """Test cancelling an announcement."""
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin,
            title="Cancelled Announcement",
            message="This will be cancelled",
            status=Announcement.Status.SCHEDULED,
        )
        
        announcement.status = Announcement.Status.CANCELLED
        announcement.save()
        announcement.refresh_from_db()
        
        self.assertEqual(announcement.status, Announcement.Status.CANCELLED)

    def test_announcement_author_set_null(self):
        """Test that announcement author is set to NULL when user is deleted."""
        admin2 = User.objects.create_user(
            email="admin2@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            tenant=self.tenant,
        )
        announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=admin2,
            title="Test Announcement",
            message="Test",
        )
        
        admin2.delete()
        announcement.refresh_from_db()
        
        self.assertIsNone(announcement.author)
