"""Tests for Enrollments services."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone

from apps.core.models import Tenant
from apps.courses.models import ContentItem, Course, Module
from apps.enrollments.models import (
    Certificate,
    Enrollment,
    GroupEnrollment,
    LearnerProgress,
)
from apps.enrollments.services import (
    CertificateService,
    EnrollmentError,
    EnrollmentService,
    ProgressTrackerService,
)
from apps.users.models import LearnerGroup, User


class EnrollmentServiceEnrollUserTests(TestCase):
    """Tests for EnrollmentService.enroll_user."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.other_tenant = Tenant.objects.create(name="Other Tenant", slug="other-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.other_tenant_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.other_tenant,
        )
        self.superuser = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )

    def test_enroll_user_creates_new_enrollment(self):
        """Test that enrolling a user creates a new enrollment record."""
        enrollment, created = EnrollmentService.enroll_user(self.learner, self.course)
        
        self.assertTrue(created)
        self.assertEqual(enrollment.user, self.learner)
        self.assertEqual(enrollment.course, self.course)
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)

    def test_enroll_user_with_custom_status(self):
        """Test enrolling a user with a custom status."""
        enrollment, created = EnrollmentService.enroll_user(
            self.learner, self.course, status=Enrollment.Status.PENDING
        )
        
        self.assertTrue(created)
        self.assertEqual(enrollment.status, Enrollment.Status.PENDING)

    def test_enroll_user_returns_existing_enrollment(self):
        """Test that enrolling an already enrolled user returns the existing enrollment."""
        enrollment1, created1 = EnrollmentService.enroll_user(self.learner, self.course)
        enrollment2, created2 = EnrollmentService.enroll_user(self.learner, self.course)
        
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(enrollment1.id, enrollment2.id)

    def test_enroll_user_reactivates_cancelled_enrollment(self):
        """Test that enrolling a user with a cancelled enrollment reactivates it."""
        # Create a cancelled enrollment
        enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.CANCELLED,
        )
        
        reactivated, created = EnrollmentService.enroll_user(self.learner, self.course)
        
        self.assertFalse(created)
        self.assertEqual(reactivated.id, enrollment.id)
        self.assertEqual(reactivated.status, Enrollment.Status.ACTIVE)

    def test_enroll_user_resets_completion_on_reactivation(self):
        """Test that reactivating an enrollment resets completion data."""
        enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        
        reactivated, created = EnrollmentService.enroll_user(self.learner, self.course)
        
        self.assertIsNone(reactivated.completed_at)
        self.assertIsNone(reactivated.expires_at)

    def test_enroll_user_raises_error_for_tenant_mismatch(self):
        """Test that enrolling a user from a different tenant raises an error."""
        with self.assertRaises(EnrollmentError) as ctx:
            EnrollmentService.enroll_user(self.other_tenant_user, self.course)
        
        self.assertIn("different tenants", str(ctx.exception))

    def test_enroll_superuser_bypasses_tenant_check(self):
        """Test that a superuser can be enrolled regardless of tenant."""
        # Create a course in a different tenant
        other_course = Course.objects.create(
            tenant=self.other_tenant,
            title="Other Course",
            instructor=self.instructor,
        )
        
        enrollment, created = EnrollmentService.enroll_user(self.superuser, other_course)
        
        self.assertTrue(created)
        self.assertEqual(enrollment.user, self.superuser)

    def test_enroll_user_raises_error_for_none_user(self):
        """Test that enrolling with None user raises an error."""
        with self.assertRaises(ValueError) as ctx:
            EnrollmentService.enroll_user(None, self.course)
        
        self.assertIn("must be provided", str(ctx.exception))

    def test_enroll_user_raises_error_for_none_course(self):
        """Test that enrolling with None course raises an error."""
        with self.assertRaises(ValueError) as ctx:
            EnrollmentService.enroll_user(self.learner, None)
        
        self.assertIn("must be provided", str(ctx.exception))

    @patch("apps.enrollments.services.NotificationService.notify_enrollment_creation")
    def test_enroll_user_triggers_notification(self, mock_notify):
        """Test that creating a new enrollment triggers a notification."""
        enrollment, created = EnrollmentService.enroll_user(self.learner, self.course)
        
        self.assertTrue(created)
        mock_notify.assert_called_once_with(enrollment)


class EnrollmentServiceEnrollGroupTests(TestCase):
    """Tests for EnrollmentService.enroll_group."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.other_tenant = Tenant.objects.create(name="Other Tenant", slug="other-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner1 = User.objects.create_user(
            email="learner1@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        self.learner2 = User.objects.create_user(
            email="learner2@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        self.inactive_learner = User.objects.create_user(
            email="inactive@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.SUSPENDED,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.group = LearnerGroup.objects.create(
            name="Test Group",
            tenant=self.tenant,
        )
        self.group.members.add(self.learner1, self.learner2, self.inactive_learner)

    def test_enroll_group_creates_group_enrollment(self):
        """Test that enrolling a group creates a GroupEnrollment record."""
        group_enrollment = EnrollmentService.enroll_group(self.group, self.course)
        
        self.assertIsNotNone(group_enrollment)
        self.assertEqual(group_enrollment.group, self.group)
        self.assertEqual(group_enrollment.course, self.course)

    def test_enroll_group_creates_individual_enrollments(self):
        """Test that enrolling a group creates enrollments for active members."""
        EnrollmentService.enroll_group(self.group, self.course)
        
        # Should create enrollments for active members only
        self.assertTrue(
            Enrollment.objects.filter(user=self.learner1, course=self.course).exists()
        )
        self.assertTrue(
            Enrollment.objects.filter(user=self.learner2, course=self.course).exists()
        )
        # Inactive user should not be enrolled
        self.assertFalse(
            Enrollment.objects.filter(user=self.inactive_learner, course=self.course).exists()
        )

    def test_enroll_group_is_idempotent(self):
        """Test that enrolling the same group twice doesn't create duplicates."""
        EnrollmentService.enroll_group(self.group, self.course)
        EnrollmentService.enroll_group(self.group, self.course)
        
        self.assertEqual(
            GroupEnrollment.objects.filter(group=self.group, course=self.course).count(),
            1
        )
        self.assertEqual(
            Enrollment.objects.filter(course=self.course).count(),
            2  # Only active members
        )

    def test_enroll_group_raises_error_for_tenant_mismatch(self):
        """Test that enrolling a group from a different tenant raises an error."""
        other_group = LearnerGroup.objects.create(
            name="Other Group",
            tenant=self.other_tenant,
        )
        
        with self.assertRaises(EnrollmentError) as ctx:
            EnrollmentService.enroll_group(other_group, self.course)
        
        self.assertIn("different tenants", str(ctx.exception))

    def test_enroll_group_raises_error_for_none_group(self):
        """Test that enrolling with None group raises an error."""
        with self.assertRaises(ValueError):
            EnrollmentService.enroll_group(None, self.course)

    def test_enroll_group_raises_error_for_none_course(self):
        """Test that enrolling with None course raises an error."""
        with self.assertRaises(ValueError):
            EnrollmentService.enroll_group(self.group, None)


class EnrollmentServiceSyncGroupEnrollmentTests(TestCase):
    """Tests for EnrollmentService.sync_group_enrollment."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner1 = User.objects.create_user(
            email="learner1@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        self.learner2 = User.objects.create_user(
            email="learner2@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.group = LearnerGroup.objects.create(
            name="Test Group",
            tenant=self.tenant,
        )
        self.group.members.add(self.learner1)

    def test_sync_adds_new_member_enrollments(self):
        """Test that syncing adds enrollments for new group members."""
        # Create group enrollment without members
        group_enrollment = GroupEnrollment.objects.create(
            group=self.group,
            course=self.course,
        )
        
        # Add a new member
        self.group.members.add(self.learner2)
        
        EnrollmentService.sync_group_enrollment(group_enrollment)
        
        self.assertTrue(
            Enrollment.objects.filter(user=self.learner2, course=self.course).exists()
        )

    def test_sync_reactivates_cancelled_enrollments(self):
        """Test that syncing reactivates previously cancelled enrollments."""
        # First, create a cancelled enrollment (before group enrollment exists)
        enrollment = Enrollment.objects.create(
            user=self.learner1,
            course=self.course,
            status=Enrollment.Status.CANCELLED,
        )
        
        group_enrollment = GroupEnrollment.objects.create(
            group=self.group,
            course=self.course,
        )
        
        EnrollmentService.sync_group_enrollment(group_enrollment)
        
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)

    def test_sync_cancels_suspended_member_enrollments(self):
        """Test that syncing cancels enrollments for suspended members still in the group."""
        # Add learner2 to group first
        self.group.members.add(self.learner2)
        
        group_enrollment = GroupEnrollment.objects.create(
            group=self.group,
            course=self.course,
        )
        
        # First sync creates enrollments for active members
        EnrollmentService.sync_group_enrollment(group_enrollment)
        
        # Verify enrollment was created for learner2
        self.assertTrue(
            Enrollment.objects.filter(user=self.learner2, course=self.course).exists()
        )
        
        # Suspend learner2 (still in group but not active)
        self.learner2.status = User.Status.SUSPENDED
        self.learner2.save()
        
        # Sync again - should cancel suspended user's enrollment
        EnrollmentService.sync_group_enrollment(group_enrollment)
        
        enrollment = Enrollment.objects.get(user=self.learner2, course=self.course)
        self.assertEqual(enrollment.status, Enrollment.Status.CANCELLED)


class EnrollmentServiceBulkEnrollUsersTests(TestCase):
    """Tests for EnrollmentService.bulk_enroll_users."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        self.other_tenant = Tenant.objects.create(name="Other Tenant", slug="other-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner1 = User.objects.create_user(
            email="learner1@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        self.learner2 = User.objects.create_user(
            email="learner2@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.ACTIVE,
        )
        self.inactive_user = User.objects.create_user(
            email="inactive@example.com",
            password="testpass123",
            tenant=self.tenant,
            status=User.Status.SUSPENDED,
        )
        self.other_tenant_user = User.objects.create_user(
            email="other@example.com",
            password="testpass123",
            tenant=self.other_tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )

    def test_bulk_enroll_creates_enrollments(self):
        """Test that bulk enrollment creates enrollments for valid users."""
        user_ids = [self.learner1.id, self.learner2.id]
        
        created_count, errors = EnrollmentService.bulk_enroll_users(
            user_ids, self.course.id, self.tenant
        )
        
        self.assertEqual(created_count, 2)
        self.assertEqual(len(errors), 0)
        self.assertTrue(
            Enrollment.objects.filter(user=self.learner1, course=self.course).exists()
        )
        self.assertTrue(
            Enrollment.objects.filter(user=self.learner2, course=self.course).exists()
        )

    def test_bulk_enroll_skips_already_enrolled_users(self):
        """Test that bulk enrollment skips already enrolled users."""
        Enrollment.objects.create(
            user=self.learner1,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        
        user_ids = [self.learner1.id, self.learner2.id]
        created_count, errors = EnrollmentService.bulk_enroll_users(
            user_ids, self.course.id, self.tenant
        )
        
        self.assertEqual(created_count, 1)
        self.assertEqual(len(errors), 0)

    def test_bulk_enroll_reports_invalid_user_ids(self):
        """Test that bulk enrollment reports invalid user IDs."""
        invalid_id = uuid4()
        user_ids = [self.learner1.id, invalid_id]
        
        created_count, errors = EnrollmentService.bulk_enroll_users(
            user_ids, self.course.id, self.tenant
        )
        
        self.assertEqual(created_count, 1)
        self.assertEqual(len(errors), 1)
        self.assertIn(str(invalid_id), errors[0])

    def test_bulk_enroll_rejects_inactive_users(self):
        """Test that bulk enrollment rejects inactive users."""
        user_ids = [self.learner1.id, self.inactive_user.id]
        
        created_count, errors = EnrollmentService.bulk_enroll_users(
            user_ids, self.course.id, self.tenant
        )
        
        self.assertEqual(created_count, 1)
        self.assertEqual(len(errors), 1)
        self.assertIn(str(self.inactive_user.id), errors[0])

    def test_bulk_enroll_rejects_other_tenant_users(self):
        """Test that bulk enrollment rejects users from other tenants."""
        user_ids = [self.learner1.id, self.other_tenant_user.id]
        
        created_count, errors = EnrollmentService.bulk_enroll_users(
            user_ids, self.course.id, self.tenant
        )
        
        self.assertEqual(created_count, 1)
        self.assertEqual(len(errors), 1)

    def test_bulk_enroll_returns_error_for_invalid_course(self):
        """Test that bulk enrollment returns error for invalid course ID."""
        invalid_course_id = uuid4()
        user_ids = [self.learner1.id]
        
        created_count, errors = EnrollmentService.bulk_enroll_users(
            user_ids, invalid_course_id, self.tenant
        )
        
        self.assertEqual(created_count, 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0])


class EnrollmentServiceAccessCheckTests(TestCase):
    """Tests for EnrollmentService.has_active_enrollment and get_enrollment."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )

    def test_has_active_enrollment_returns_true_for_active(self):
        """Test that has_active_enrollment returns True for active enrollment."""
        Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        
        result = EnrollmentService.has_active_enrollment(self.learner, self.course)
        
        self.assertTrue(result)

    def test_has_active_enrollment_returns_true_for_completed(self):
        """Test that has_active_enrollment returns True for completed enrollment."""
        Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.COMPLETED,
        )
        
        result = EnrollmentService.has_active_enrollment(self.learner, self.course)
        
        self.assertTrue(result)

    def test_has_active_enrollment_returns_false_for_cancelled(self):
        """Test that has_active_enrollment returns False for cancelled enrollment."""
        Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.CANCELLED,
        )
        
        result = EnrollmentService.has_active_enrollment(self.learner, self.course)
        
        self.assertFalse(result)

    def test_has_active_enrollment_returns_false_for_no_enrollment(self):
        """Test that has_active_enrollment returns False when not enrolled."""
        result = EnrollmentService.has_active_enrollment(self.learner, self.course)
        
        self.assertFalse(result)

    def test_has_active_enrollment_returns_false_for_none_user(self):
        """Test that has_active_enrollment returns False for None user."""
        result = EnrollmentService.has_active_enrollment(None, self.course)
        
        self.assertFalse(result)

    def test_get_enrollment_returns_enrollment_for_active(self):
        """Test that get_enrollment returns enrollment for active status."""
        enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        
        result = EnrollmentService.get_enrollment(self.learner, self.course)
        
        self.assertEqual(result, enrollment)

    def test_get_enrollment_returns_none_for_cancelled(self):
        """Test that get_enrollment returns None for cancelled enrollment."""
        Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.CANCELLED,
        )
        
        result = EnrollmentService.get_enrollment(self.learner, self.course)
        
        self.assertIsNone(result)


class ProgressTrackerServiceUpdateContentProgressTests(TestCase):
    """Tests for ProgressTrackerService.update_content_progress."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.module = Module.objects.create(
            course=self.course,
            title="Introduction",
            order=1,
        )
        
        self.content_item = ContentItem.objects.create(
            module=self.module,
            title="Welcome Video",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
            is_published=True,
            is_required=True,
        )
        
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )

    def test_update_progress_creates_new_record(self):
        """Test that updating progress creates a new LearnerProgress record."""
        progress, updated = ProgressTrackerService.update_content_progress(
            self.enrollment,
            self.content_item,
            LearnerProgress.Status.IN_PROGRESS,
        )
        
        self.assertTrue(updated)
        self.assertEqual(progress.status, LearnerProgress.Status.IN_PROGRESS)
        self.assertIsNotNone(progress.started_at)

    def test_update_progress_marks_completed(self):
        """Test that updating progress to completed sets completed_at."""
        progress, updated = ProgressTrackerService.update_content_progress(
            self.enrollment,
            self.content_item,
            LearnerProgress.Status.COMPLETED,
        )
        
        self.assertTrue(updated)
        self.assertEqual(progress.status, LearnerProgress.Status.COMPLETED)
        self.assertIsNotNone(progress.completed_at)
        self.assertIsNotNone(progress.started_at)

    def test_update_progress_with_details(self):
        """Test that updating progress with details stores them."""
        details = {"last_position_seconds": 120.5, "total_duration_seconds": 300}
        
        progress, updated = ProgressTrackerService.update_content_progress(
            self.enrollment,
            self.content_item,
            LearnerProgress.Status.IN_PROGRESS,
            details=details,
        )
        
        self.assertTrue(updated)
        self.assertEqual(progress.progress_details["last_position_seconds"], 120.5)
        self.assertEqual(progress.progress_details["total_duration_seconds"], 300)

    def test_update_progress_can_reset_to_not_started(self):
        """Test that progress can be reset to NOT_STARTED."""
        # First mark as completed
        ProgressTrackerService.update_content_progress(
            self.enrollment,
            self.content_item,
            LearnerProgress.Status.COMPLETED,
        )
        
        # Then reset
        progress, updated = ProgressTrackerService.update_content_progress(
            self.enrollment,
            self.content_item,
            LearnerProgress.Status.NOT_STARTED,
        )
        
        self.assertTrue(updated)
        self.assertEqual(progress.status, LearnerProgress.Status.NOT_STARTED)
        self.assertIsNone(progress.started_at)
        self.assertIsNone(progress.completed_at)

    def test_update_progress_raises_error_for_wrong_course(self):
        """Test that updating progress for a different course raises an error."""
        other_course = Course.objects.create(
            tenant=self.tenant,
            title="Other Course",
            instructor=self.instructor,
        )
        other_module = Module.objects.create(
            course=other_course,
            title="Other Module",
            order=1,
        )
        other_content = ContentItem.objects.create(
            module=other_module,
            title="Other Content",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
        )
        
        with self.assertRaises(ValueError) as ctx:
            ProgressTrackerService.update_content_progress(
                self.enrollment,
                other_content,
                LearnerProgress.Status.COMPLETED,
            )
        
        self.assertIn("does not belong", str(ctx.exception))

    def test_update_progress_raises_error_for_none_enrollment(self):
        """Test that updating progress with None enrollment raises an error."""
        with self.assertRaises(ValueError):
            ProgressTrackerService.update_content_progress(
                None,
                self.content_item,
                LearnerProgress.Status.COMPLETED,
            )


class ProgressTrackerServiceCourseCompletionTests(TestCase):
    """Tests for ProgressTrackerService.check_and_update_course_completion."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.module = Module.objects.create(
            course=self.course,
            title="Introduction",
            order=1,
        )
        
        self.content1 = ContentItem.objects.create(
            module=self.module,
            title="Video 1",
            content_type=ContentItem.ContentType.VIDEO,
            order=1,
            is_published=True,
            is_required=True,
        )
        self.content2 = ContentItem.objects.create(
            module=self.module,
            title="Video 2",
            content_type=ContentItem.ContentType.VIDEO,
            order=2,
            is_published=True,
            is_required=True,
        )
        
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )

    def test_completion_check_marks_course_complete_when_all_done(self):
        """Test that completing all content marks the course as complete."""
        # Complete all content items
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=self.content1,
            status=LearnerProgress.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=self.content2,
            status=LearnerProgress.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        
        is_complete = ProgressTrackerService.check_and_update_course_completion(
            self.enrollment
        )
        
        self.enrollment.refresh_from_db()
        self.assertTrue(is_complete)
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)
        self.assertEqual(self.enrollment.progress, 100)

    def test_completion_check_updates_progress_percentage(self):
        """Test that completion check updates progress percentage."""
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=self.content1,
            status=LearnerProgress.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        
        ProgressTrackerService.check_and_update_course_completion(self.enrollment)
        
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.progress, 50)
        self.assertEqual(self.enrollment.status, Enrollment.Status.ACTIVE)

    def test_completion_check_ignores_optional_content(self):
        """Test that completion check ignores non-required content."""
        # Make content2 optional
        self.content2.is_required = False
        self.content2.save()
        
        # Complete only required content
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=self.content1,
            status=LearnerProgress.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        
        is_complete = ProgressTrackerService.check_and_update_course_completion(
            self.enrollment
        )
        
        self.enrollment.refresh_from_db()
        self.assertTrue(is_complete)
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)

    def test_completion_check_ignores_unpublished_content(self):
        """Test that completion check ignores unpublished content."""
        self.content2.is_published = False
        self.content2.save()
        
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=self.content1,
            status=LearnerProgress.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        
        is_complete = ProgressTrackerService.check_and_update_course_completion(
            self.enrollment
        )
        
        self.enrollment.refresh_from_db()
        self.assertTrue(is_complete)

    def test_empty_course_is_considered_complete(self):
        """Test that a course with no content is considered complete."""
        # Remove all content
        ContentItem.objects.all().delete()
        
        is_complete = ProgressTrackerService.check_and_update_course_completion(
            self.enrollment
        )
        
        self.enrollment.refresh_from_db()
        self.assertTrue(is_complete)
        self.assertEqual(self.enrollment.status, Enrollment.Status.COMPLETED)

    def test_completion_reverts_if_content_added_after_completion(self):
        """Test that adding required content after completion reverts status."""
        # Mark enrollment as completed
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.completed_at = timezone.now()
        self.enrollment.progress = 100
        self.enrollment.save()
        
        # Complete only one content item
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=self.content1,
            status=LearnerProgress.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        
        # Check completion - should revert because content2 is not complete
        is_complete = ProgressTrackerService.check_and_update_course_completion(
            self.enrollment
        )
        
        self.enrollment.refresh_from_db()
        self.assertFalse(is_complete)
        self.assertEqual(self.enrollment.status, Enrollment.Status.ACTIVE)
        self.assertIsNone(self.enrollment.completed_at)


class ProgressTrackerServiceCalculateProgressTests(TestCase):
    """Tests for ProgressTrackerService.calculate_course_progress_percentage."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.module = Module.objects.create(
            course=self.course,
            title="Introduction",
            order=1,
        )
        
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )

    def test_calculate_progress_for_empty_course(self):
        """Test progress calculation for a course with no content."""
        percentage = ProgressTrackerService.calculate_course_progress_percentage(
            self.enrollment
        )
        
        self.assertEqual(percentage, 0)

    def test_calculate_progress_rounds_correctly(self):
        """Test that progress percentage rounds correctly."""
        # Create 3 content items
        for i in range(3):
            ContentItem.objects.create(
                module=self.module,
                title=f"Content {i}",
                content_type=ContentItem.ContentType.VIDEO,
                order=i,
                is_published=True,
                is_required=True,
            )
        
        content_items = list(ContentItem.objects.all())
        
        # Complete 1 of 3 (33.33%)
        LearnerProgress.objects.create(
            enrollment=self.enrollment,
            content_item=content_items[0],
            status=LearnerProgress.Status.COMPLETED,
        )
        
        percentage = ProgressTrackerService.calculate_course_progress_percentage(
            self.enrollment
        )
        
        self.assertEqual(percentage, 33)  # Should round 33.33 to 33

    def test_calculate_progress_100_for_completed_enrollment_with_no_content(self):
        """Test that completed enrollment with no content returns 100%."""
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        percentage = ProgressTrackerService.calculate_course_progress_percentage(
            self.enrollment
        )
        
        self.assertEqual(percentage, 100)


class CertificateServiceTests(TestCase):
    """Tests for CertificateService."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Tenant", slug="test-tenant")
        
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            tenant=self.tenant,
        )
        
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Python Basics",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED,
        )
        
        self.enrollment = Enrollment.objects.create(
            user=self.learner,
            course=self.course,
            status=Enrollment.Status.COMPLETED,
            completed_at=timezone.now(),
        )

    @patch("apps.enrollments.services.NotificationService.notify_certificate_issued")
    def test_generate_certificate_creates_certificate(self, mock_notify):
        """Test that generating a certificate creates a Certificate record."""
        certificate = CertificateService.generate_certificate_for_enrollment(
            self.enrollment
        )
        
        self.assertIsNotNone(certificate)
        self.assertEqual(certificate.enrollment, self.enrollment)
        self.assertEqual(certificate.user, self.learner)
        self.assertEqual(certificate.course, self.course)
        self.assertEqual(certificate.status, Certificate.Status.ISSUED)
        self.assertIsNotNone(certificate.verification_code)

    def test_generate_certificate_returns_none_for_non_completed(self):
        """Test that generating a certificate for non-completed enrollment returns None."""
        self.enrollment.status = Enrollment.Status.ACTIVE
        self.enrollment.save()
        
        certificate = CertificateService.generate_certificate_for_enrollment(
            self.enrollment
        )
        
        self.assertIsNone(certificate)

    @patch("apps.enrollments.services.NotificationService.notify_certificate_issued")
    def test_generate_certificate_is_idempotent(self, mock_notify):
        """Test that generating a certificate twice returns the same certificate."""
        cert1 = CertificateService.generate_certificate_for_enrollment(self.enrollment)
        cert2 = CertificateService.generate_certificate_for_enrollment(self.enrollment)
        
        self.assertEqual(cert1.id, cert2.id)
        self.assertEqual(Certificate.objects.count(), 1)

    @patch("apps.enrollments.services.NotificationService.notify_certificate_issued")
    def test_generate_certificate_triggers_notification(self, mock_notify):
        """Test that generating a new certificate triggers a notification."""
        certificate = CertificateService.generate_certificate_for_enrollment(
            self.enrollment
        )
        
        mock_notify.assert_called_once_with(certificate)

    @patch("apps.enrollments.services.NotificationService.notify_certificate_issued")
    def test_verify_certificate_returns_certificate(self, mock_notify):
        """Test that verifying a certificate returns the certificate."""
        certificate = CertificateService.generate_certificate_for_enrollment(
            self.enrollment
        )
        
        result = CertificateService.verify_certificate(certificate.verification_code)
        
        self.assertEqual(result, certificate)

    def test_verify_certificate_returns_none_for_invalid_code(self):
        """Test that verifying an invalid code returns None."""
        result = CertificateService.verify_certificate(uuid4())
        
        self.assertIsNone(result)
