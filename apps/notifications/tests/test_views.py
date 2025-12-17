"""
Tests for notification views and API endpoints.
"""
import uuid
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.core.models import Tenant
from apps.courses.models import Course
from apps.enrollments.models import Enrollment
from apps.notifications.models import (
    Notification,
    NotificationPreference,
    NotificationType,
    UserDevice,
    Announcement,
)


class NotificationViewSetTestCase(TestCase):
    """Tests for NotificationViewSet API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant",
        )
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        # Create notifications for the user
        self.notification1 = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.NEW_CONTENT_AVAILABLE,
            subject="Course Updated",
            message="Your course has been updated.",
            status=Notification.Status.SENT,
        )
        self.notification2 = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.DEADLINE_REMINDER,
            subject="Assignment Due",
            message="Your assignment is due soon.",
            status=Notification.Status.PENDING,
        )
        self.notification_dismissed = Notification.objects.create(
            recipient=self.user,
            notification_type=NotificationType.SYSTEM_ALERT,
            subject="System Notice",
            message="System maintenance.",
            status=Notification.Status.DISMISSED,
        )
        # Notification for another user (should not be visible)
        self.other_notification = Notification.objects.create(
            recipient=self.other_user,
            notification_type=NotificationType.COURSE_ENROLLMENT,
            subject="Enrollment Confirmed",
            message="You have been enrolled.",
            status=Notification.Status.SENT,
        )

    def test_list_notifications_unauthenticated(self):
        """Test that unauthenticated users cannot list notifications."""
        url = reverse("notifications:notification-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_notifications_authenticated(self):
        """Test that authenticated users can list their notifications."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see own notifications (excluding dismissed by default)
        self.assertEqual(len(response.data["results"]), 2)
        notification_ids = [n["id"] for n in response.data["results"]]
        self.assertIn(str(self.notification1.id), notification_ids)
        self.assertIn(str(self.notification2.id), notification_ids)
        self.assertNotIn(str(self.notification_dismissed.id), notification_ids)
        self.assertNotIn(str(self.other_notification.id), notification_ids)

    def test_list_notifications_filter_by_status(self):
        """Test filtering notifications by status."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-list")
        
        # Filter by PENDING
        response = self.client.get(url, {"status": "PENDING"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.notification2.id))
        
        # Filter by SENT
        response = self.client.get(url, {"status": "SENT"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.notification1.id))

    def test_list_notifications_filter_by_dismissed(self):
        """Test that dismissed notifications can be included with status filter."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-list")
        
        response = self.client.get(url, {"status": "DISMISSED"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.notification_dismissed.id))

    def test_retrieve_notification(self):
        """Test retrieving a single notification."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-detail", kwargs={"pk": self.notification1.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], str(self.notification1.id))
        self.assertEqual(response.data["subject"], "Course Updated")

    def test_retrieve_other_user_notification_forbidden(self):
        """Test that users cannot retrieve other users' notifications."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-detail", kwargs={"pk": self.other_notification.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_mark_read(self):
        """Test marking a notification as read."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-mark-read", kwargs={"pk": self.notification1.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.notification1.refresh_from_db()
        self.assertEqual(self.notification1.status, Notification.Status.READ)
        self.assertIsNotNone(self.notification1.read_at)

    def test_mark_read_already_read(self):
        """Test marking an already read notification as read (idempotent)."""
        self.notification1.status = Notification.Status.READ
        self.notification1.read_at = timezone.now()
        self.notification1.save()
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-mark-read", kwargs={"pk": self.notification1.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.notification1.refresh_from_db()
        self.assertEqual(self.notification1.status, Notification.Status.READ)

    def test_mark_all_read(self):
        """Test marking all notifications as read."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-mark-all-read")
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("updated_count", response.data)
        self.assertEqual(response.data["updated_count"], 2)  # SENT and PENDING
        
        self.notification1.refresh_from_db()
        self.notification2.refresh_from_db()
        self.assertEqual(self.notification1.status, Notification.Status.READ)
        self.assertEqual(self.notification2.status, Notification.Status.READ)

    def test_dismiss(self):
        """Test dismissing a notification."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-dismiss", kwargs={"pk": self.notification1.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.notification1.refresh_from_db()
        self.assertEqual(self.notification1.status, Notification.Status.DISMISSED)

    def test_dismiss_sets_read_at_if_unread(self):
        """Test that dismissing an unread notification sets read_at."""
        self.assertIsNone(self.notification1.read_at)
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-dismiss", kwargs={"pk": self.notification1.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.notification1.refresh_from_db()
        self.assertIsNotNone(self.notification1.read_at)


class NotificationPreferenceViewTestCase(TestCase):
    """Tests for NotificationPreferenceView API endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant-prefs",
        )
        self.user = User.objects.create_user(
            email="prefuser@example.com",
            password="testpass123",
            tenant=self.tenant,
        )

    def test_get_preferences_unauthenticated(self):
        """Test that unauthenticated users cannot get preferences."""
        url = reverse("notifications:notification-preferences")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_preferences_creates_default(self):
        """Test that getting preferences creates default if not exists."""
        # Delete any auto-created preferences from user creation signal
        NotificationPreference.objects.filter(user=self.user).delete()
        self.assertFalse(NotificationPreference.objects.filter(user=self.user).exists())
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-preferences")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(NotificationPreference.objects.filter(user=self.user).exists())
        self.assertTrue(response.data["is_enabled"])

    def test_get_existing_preferences(self):
        """Test retrieving existing preferences."""
        # Update existing preferences (auto-created by signal)
        prefs = NotificationPreference.objects.get(user=self.user)
        prefs.is_enabled = False
        prefs.preferences = {
            NotificationType.NEW_CONTENT_AVAILABLE: {"EMAIL": True, "IN_APP": False}
        }
        prefs.save()
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-preferences")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_enabled"])
        self.assertIn(NotificationType.NEW_CONTENT_AVAILABLE, response.data["preferences"])

    def test_update_preferences_put(self):
        """Test updating preferences with PUT."""
        # Use existing preferences (auto-created by signal)
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-preferences")
        
        data = {
            "is_enabled": False,
            "preferences": {
                NotificationType.DEADLINE_REMINDER: {"EMAIL": False, "IN_APP": True}
            },
        }
        response = self.client.put(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prefs = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(prefs.is_enabled)
        self.assertEqual(
            prefs.preferences[NotificationType.DEADLINE_REMINDER]["EMAIL"], False
        )

    def test_update_preferences_patch(self):
        """Test partial update of preferences with PATCH."""
        # Use existing preferences (auto-created by signal)
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-preferences")
        
        data = {"is_enabled": False}
        response = self.client.patch(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prefs = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(prefs.is_enabled)

    def test_update_preferences_invalid_type(self):
        """Test validation error for invalid notification type."""
        # Use existing preferences (auto-created by signal)
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-preferences")
        
        data = {
            "preferences": {
                "INVALID_TYPE": {"EMAIL": True}
            },
        }
        response = self.client.put(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_preferences_invalid_method(self):
        """Test validation error for invalid delivery method."""
        # Use existing preferences (auto-created by signal)
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:notification-preferences")
        
        data = {
            "preferences": {
                NotificationType.NEW_CONTENT_AVAILABLE: {"INVALID_METHOD": True}
            },
        }
        response = self.client.put(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserDeviceViewSetTestCase(TestCase):
    """Tests for UserDeviceViewSet API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant-devices",
        )
        self.user = User.objects.create_user(
            email="deviceuser@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.other_user = User.objects.create_user(
            email="otherdevice@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.device = UserDevice.objects.create(
            user=self.user,
            device_type=UserDevice.DeviceType.WEB,
            token="test-token-123",
            device_name="Test Browser",
        )
        self.other_device = UserDevice.objects.create(
            user=self.other_user,
            device_type=UserDevice.DeviceType.ANDROID,
            token="other-token-456",
        )

    def test_list_devices_unauthenticated(self):
        """Test that unauthenticated users cannot list devices."""
        url = reverse("notifications:device-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_devices_authenticated(self):
        """Test that authenticated users can list their devices."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(self.device.id))

    def test_create_device(self):
        """Test registering a new device."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-list")
        
        data = {
            "device_type": UserDevice.DeviceType.IOS,
            "token": "new-ios-token-789",
            "device_name": "iPhone 15",
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            UserDevice.objects.filter(user=self.user, token="new-ios-token-789").exists()
        )

    def test_create_device_existing_token_updates(self):
        """Test that creating with existing token updates the device."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-list")
        
        data = {
            "device_type": UserDevice.DeviceType.ANDROID,
            "token": "test-token-123",  # Same token as existing device
            "device_name": "Updated Device Name",
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Should update existing, not create new
        self.assertEqual(UserDevice.objects.filter(user=self.user).count(), 1)
        self.device.refresh_from_db()
        self.assertEqual(self.device.device_name, "Updated Device Name")
        self.assertEqual(self.device.device_type, UserDevice.DeviceType.ANDROID)

    def test_create_device_empty_token_rejected(self):
        """Test that empty token is rejected."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-list")
        
        data = {
            "device_type": UserDevice.DeviceType.WEB,
            "token": "   ",
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_deactivate_device(self):
        """Test deactivating a device."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-deactivate", kwargs={"pk": self.device.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_active)

    def test_activate_device(self):
        """Test reactivating a device."""
        self.device.is_active = False
        self.device.save()
        
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-activate", kwargs={"pk": self.device.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_active)

    def test_delete_device(self):
        """Test deleting a device."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-detail", kwargs={"pk": self.device.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(UserDevice.objects.filter(id=self.device.id).exists())

    def test_cannot_access_other_user_device(self):
        """Test that users cannot access other users' devices."""
        self.client.force_authenticate(user=self.user)
        url = reverse("notifications:device-detail", kwargs={"pk": self.other_device.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AnnouncementViewSetTestCase(TestCase):
    """Tests for AnnouncementViewSet API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant-announce",
        )
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
            tenant=self.tenant,
        )
        self.regular_user = User.objects.create_user(
            email="regular@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.target_user1 = User.objects.create_user(
            email="target1@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.target_user2 = User.objects.create_user(
            email="target2@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            title="Test Course",
            tenant=self.tenant,
            instructor=self.admin_user,
        )
        
        # Create enrollment for target users
        Enrollment.objects.create(
            user=self.target_user1,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        Enrollment.objects.create(
            user=self.target_user2,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        
        self.announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin_user,
            title="Test Announcement",
            message="This is a test announcement.",
            target_type=Announcement.TargetType.ALL_TENANT,
            status=Announcement.Status.DRAFT,
        )

    def test_list_announcements_unauthenticated(self):
        """Test that unauthenticated users cannot list announcements."""
        url = reverse("notifications:announcement-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_announcements_non_admin(self):
        """Test that non-admin users cannot list announcements."""
        self.client.force_authenticate(user=self.regular_user)
        url = reverse("notifications:announcement-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_announcements_admin(self):
        """Test that admin users can list announcements."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-list")
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_create_announcement(self):
        """Test creating a new announcement."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-list")
        
        data = {
            "title": "New Announcement",
            "message": "This is a new announcement.",
            "target_type": Announcement.TargetType.ALL_TENANT,
            "tenant": str(self.tenant.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "New Announcement")
        self.assertEqual(str(response.data["author"]), str(self.admin_user.id))

    def test_create_announcement_course_enrolled_without_course(self):
        """Test that COURSE_ENROLLED target type requires a course."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-list")
        
        data = {
            "title": "Course Announcement",
            "message": "This is a course announcement.",
            "target_type": Announcement.TargetType.COURSE_ENROLLED,
            "tenant": str(self.tenant.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("target_course", response.data)

    def test_create_announcement_specific_users_without_ids(self):
        """Test that SPECIFIC_USERS target type requires user IDs."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-list")
        
        data = {
            "title": "Targeted Announcement",
            "message": "This is for specific users.",
            "target_type": Announcement.TargetType.SPECIFIC_USERS,
            "tenant": str(self.tenant.id),
        }
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("target_user_ids", response.data)

    def test_send_announcement_all_tenant(self):
        """Test sending an announcement to all tenant users."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-send", kwargs={"pk": self.announcement.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.announcement.refresh_from_db()
        self.assertEqual(self.announcement.status, Announcement.Status.SENT)
        self.assertIsNotNone(self.announcement.sent_at)
        self.assertGreater(self.announcement.recipients_count, 0)
        
        # Check notifications were created
        notification_count = Notification.objects.filter(
            notification_type=NotificationType.ANNOUNCEMENT,
            subject=self.announcement.title,
        ).count()
        self.assertEqual(notification_count, self.announcement.recipients_count)

    def test_send_announcement_course_enrolled(self):
        """Test sending an announcement to course-enrolled users."""
        course_announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin_user,
            title="Course Announcement",
            message="This is for enrolled students.",
            target_type=Announcement.TargetType.COURSE_ENROLLED,
            target_course=self.course,
            status=Announcement.Status.DRAFT,
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-send", kwargs={"pk": course_announcement.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        course_announcement.refresh_from_db()
        self.assertEqual(course_announcement.status, Announcement.Status.SENT)
        self.assertEqual(course_announcement.recipients_count, 2)  # target_user1 and target_user2

    def test_send_announcement_specific_users(self):
        """Test sending an announcement to specific users."""
        specific_announcement = Announcement.objects.create(
            tenant=self.tenant,
            author=self.admin_user,
            title="Specific Announcement",
            message="This is for specific users.",
            target_type=Announcement.TargetType.SPECIFIC_USERS,
            target_user_ids=[str(self.target_user1.id)],
            status=Announcement.Status.DRAFT,
        )
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-send", kwargs={"pk": specific_announcement.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        specific_announcement.refresh_from_db()
        self.assertEqual(specific_announcement.recipients_count, 1)

    def test_send_announcement_already_sent(self):
        """Test that already sent announcements cannot be sent again."""
        self.announcement.status = Announcement.Status.SENT
        self.announcement.save()
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-send", kwargs={"pk": self.announcement.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_cancel_announcement(self):
        """Test cancelling an announcement."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-cancel", kwargs={"pk": self.announcement.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.announcement.refresh_from_db()
        self.assertEqual(self.announcement.status, Announcement.Status.CANCELLED)

    def test_cancel_sent_announcement(self):
        """Test that sent announcements cannot be cancelled."""
        self.announcement.status = Announcement.Status.SENT
        self.announcement.save()
        
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-cancel", kwargs={"pk": self.announcement.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("error", response.data)

    def test_update_announcement(self):
        """Test updating an announcement."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-detail", kwargs={"pk": self.announcement.id})
        
        data = {
            "title": "Updated Title",
            "message": "Updated message content.",
            "target_type": Announcement.TargetType.ALL_TENANT,
            "tenant": str(self.tenant.id),
        }
        response = self.client.put(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.announcement.refresh_from_db()
        self.assertEqual(self.announcement.title, "Updated Title")

    def test_delete_announcement(self):
        """Test deleting an announcement."""
        self.client.force_authenticate(user=self.admin_user)
        url = reverse("notifications:announcement-detail", kwargs={"pk": self.announcement.id})
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Announcement.objects.filter(id=self.announcement.id).exists())
