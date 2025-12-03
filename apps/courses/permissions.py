from rest_framework import permissions

from apps.users.models import User

# from apps.enrollments.models import Enrollment # Import when defined


class IsCourseInstructorOrAdmin(permissions.BasePermission):
    """
    Allows access only to the instructor listed on the course or an admin user.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Determine the course object, works for Course, Module, ContentItem, Question viewsets
        course = None
        if hasattr(obj, "course"):  # Module object
            course = obj.course
        elif hasattr(obj, "module") and hasattr(
            obj.module, "course"
        ):  # ContentItem object
            course = obj.module.course
        elif hasattr(obj, "assessment") and hasattr(
            obj.assessment, "course"
        ):  # Question object
            course = obj.assessment.course
        elif isinstance(
            obj, User
        ):  # Should compare against obj itself if checking a User object
            pass  # Handle user object checks if needed separately
        else:  # Assume obj is a Course
            course = obj

        if not course:  # Or if obj is User
            # Fallback or specific logic needed if checking permissions on non-course related objects
            # Or simply check if the user is staff/admin in this context
            return user.is_staff

        # Check if user is instructor or admin (staff)
        is_instructor = course.instructor == user
        is_admin = (
            user.is_staff
        )  # Or check for specific Admin role: user.role == User.Role.ADMIN

        return is_instructor or is_admin


class IsEnrolledOrInstructorOrAdmin(permissions.BasePermission):
    """
    Allows access if the user is enrolled in the course, is the instructor, or is an admin.
    Used for accessing published course content.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # Determine the course object
        course = None
        if hasattr(obj, "course"):
            course = obj.course
        elif hasattr(obj, "module") and hasattr(obj.module, "course"):
            course = obj.module.course
        else:
            course = obj

        if not course:
            return user.is_staff  # Fallback for non-course objects

        # Check if admin or instructor
        if user.is_staff or (course.instructor == user):
            return True

        # Check if enrolled (Requires Enrollment model)
        # try:
        #     return Enrollment.objects.filter(user=user, course=course, is_active=True).exists()
        # except ImportError:
        #      # Handle case where Enrollment model isn't available yet or app not installed
        #      return False
        return False  # Placeholder until Enrollment model is integrated
