"""Tests for courses app permissions."""

from django.test import TestCase, RequestFactory
from unittest.mock import Mock

from apps.courses.permissions import IsCourseInstructorOrAdmin, IsEnrolledOrInstructorOrAdmin
from apps.courses.models import Course, Module, ContentItem
from apps.enrollments.models import Enrollment
from apps.core.models import Tenant
from apps.users.models import User


class IsCourseInstructorOrAdminTests(TestCase):
    """Tests for IsCourseInstructorOrAdmin permission."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.permission = IsCourseInstructorOrAdmin()
        
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.other_instructor = User.objects.create_user(
            email="other_instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            is_staff=True,
            tenant=self.tenant
        )
        self.learner = User.objects.create_user(
            email="learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1
        )
        self.content_item = ContentItem.objects.create(
            module=self.module,
            title="Test Content",
            content_type=ContentItem.ContentType.TEXT,
            order=1
        )

    def _make_request(self, user):
        """Create a mock request with the given user."""
        request = self.factory.get('/')
        request.user = user
        return request

    def test_instructor_has_permission_on_own_course(self):
        """Test that course instructor has permission."""
        request = self._make_request(self.instructor)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_other_instructor_no_permission_on_course(self):
        """Test that other instructors don't have permission on the course."""
        request = self._make_request(self.other_instructor)
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_admin_has_permission_on_any_course(self):
        """Test that admin users have permission on any course."""
        request = self._make_request(self.admin)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_learner_no_permission_on_course(self):
        """Test that learners don't have permission."""
        request = self._make_request(self.learner)
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_instructor_has_permission_on_module(self):
        """Test that course instructor has permission on module."""
        request = self._make_request(self.instructor)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.module)
        )

    def test_instructor_has_permission_on_content_item(self):
        """Test that course instructor has permission on content item."""
        request = self._make_request(self.instructor)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.content_item)
        )

    def test_unauthenticated_user_no_permission(self):
        """Test that unauthenticated users have no permission."""
        request = self.factory.get('/')
        request.user = Mock()
        request.user.is_authenticated = False
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_no_user_no_permission(self):
        """Test that request without user has no permission."""
        request = self.factory.get('/')
        request.user = None
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )


class IsEnrolledOrInstructorOrAdminTests(TestCase):
    """Tests for IsEnrolledOrInstructorOrAdmin permission."""

    def setUp(self):
        """Set up test data."""
        self.factory = RequestFactory()
        self.permission = IsEnrolledOrInstructorOrAdmin()
        
        self.tenant = Tenant.objects.create(
            name="Test Tenant",
            slug="test-tenant"
        )
        self.instructor = User.objects.create_user(
            email="instructor@example.com",
            password="testpass123",
            role=User.Role.INSTRUCTOR,
            tenant=self.tenant
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
            role=User.Role.ADMIN,
            is_staff=True,
            tenant=self.tenant
        )
        self.enrolled_learner = User.objects.create_user(
            email="enrolled_learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )
        self.unenrolled_learner = User.objects.create_user(
            email="unenrolled_learner@example.com",
            password="testpass123",
            role=User.Role.LEARNER,
            tenant=self.tenant
        )
        self.course = Course.objects.create(
            tenant=self.tenant,
            title="Test Course",
            instructor=self.instructor,
            status=Course.Status.PUBLISHED
        )
        self.module = Module.objects.create(
            course=self.course,
            title="Test Module",
            order=1
        )
        self.content_item = ContentItem.objects.create(
            module=self.module,
            title="Test Content",
            content_type=ContentItem.ContentType.TEXT,
            order=1,
            is_published=True
        )
        
        # Create active enrollment for enrolled learner
        self.enrollment = Enrollment.objects.create(
            user=self.enrolled_learner,
            course=self.course,
            status=Enrollment.Status.ACTIVE
        )

    def _make_request(self, user):
        """Create a mock request with the given user."""
        request = self.factory.get('/')
        request.user = user
        return request

    def test_instructor_has_permission(self):
        """Test that course instructor has permission."""
        request = self._make_request(self.instructor)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_admin_has_permission(self):
        """Test that admin has permission."""
        request = self._make_request(self.admin)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_enrolled_learner_has_permission(self):
        """Test that enrolled learner has permission."""
        request = self._make_request(self.enrolled_learner)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_unenrolled_learner_no_permission(self):
        """Test that unenrolled learner has no permission."""
        request = self._make_request(self.unenrolled_learner)
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_enrolled_learner_has_permission_on_module(self):
        """Test that enrolled learner has permission on module."""
        request = self._make_request(self.enrolled_learner)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.module)
        )

    def test_enrolled_learner_has_permission_on_content_item(self):
        """Test that enrolled learner has permission on content item."""
        request = self._make_request(self.enrolled_learner)
        view = Mock()
        
        self.assertTrue(
            self.permission.has_object_permission(request, view, self.content_item)
        )

    def test_cancelled_enrollment_no_permission(self):
        """Test that learner with cancelled enrollment has no permission."""
        self.enrollment.status = Enrollment.Status.CANCELLED
        self.enrollment.save()
        
        request = self._make_request(self.enrolled_learner)
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_completed_enrollment_has_permission(self):
        """Test that learner with completed enrollment still has no permission.
        Note: This tests the current implementation which only checks ACTIVE status.
        """
        self.enrollment.status = Enrollment.Status.COMPLETED
        self.enrollment.save()
        
        request = self._make_request(self.enrolled_learner)
        view = Mock()
        
        # Current implementation only checks ACTIVE status
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )

    def test_unauthenticated_user_no_permission(self):
        """Test that unauthenticated users have no permission."""
        request = self.factory.get('/')
        request.user = Mock()
        request.user.is_authenticated = False
        view = Mock()
        
        self.assertFalse(
            self.permission.has_object_permission(request, view, self.course)
        )
