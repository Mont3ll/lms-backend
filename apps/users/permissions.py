from rest_framework import permissions

from apps.users.models import (
    User,
)  # Avoid circular import if possible by checking roles directly


class IsAdminOrTenantAdmin(permissions.BasePermission):
    """
    Allows access only to superusers or staff users associated with the current request's tenant.
    Assumes TenantMiddleware sets request.tenant.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        if user.is_superuser:
            return True

        # Check if the user is staff and belongs to the tenant associated with the request
        tenant = getattr(request, "tenant", None)
        if user.is_staff and tenant and user.tenant == tenant:
            return True

        return False


class IsInstructorOrAdmin(permissions.BasePermission):
    """Allows access only to Admins or Instructors."""

    def has_permission(self, request, view):
        user = request.user
        return (
            user
            and user.is_authenticated
            and (
                user.role == User.Role.ADMIN
                or user.role == User.Role.INSTRUCTOR
                or user.is_staff
            )
        )


class IsLearner(permissions.BasePermission):
    """Allows access only to Learners."""

    def has_permission(self, request, view):
        user = request.user
        return user and user.is_authenticated and user.role == User.Role.LEARNER


class IsSelfOrAdmin(permissions.BasePermission):
    """Allows access only to the user themselves or an admin."""

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False

        # obj is the User instance being accessed
        return obj == user or user.is_staff  # Or check for Admin role specifically
