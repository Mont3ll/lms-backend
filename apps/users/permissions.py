from rest_framework import permissions

from apps.users.models import (
    User,
)  # Avoid circular import if possible by checking roles directly


def is_admin_user(user) -> bool:
    """
    Check if user has admin privileges.
    
    Admin privileges are granted to users who:
    - Are superusers (is_superuser=True)
    - Have the ADMIN role (role=ADMIN)
    - Have Django staff status (is_staff=True) for backwards compatibility
    
    Args:
        user: The user to check
        
    Returns:
        bool: True if user has admin privileges, False otherwise
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return (
        user.is_superuser
        or user.role == User.Role.ADMIN
        or user.is_staff
    )


def is_tenant_admin(user, tenant) -> bool:
    """
    Check if user is an admin for a specific tenant.
    
    Args:
        user: The user to check
        tenant: The tenant to check admin status for
        
    Returns:
        bool: True if user is a tenant admin, False otherwise
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    if user.is_superuser:
        return True
    if not tenant:
        return False
    return (user.role == User.Role.ADMIN or user.is_staff) and user.tenant == tenant


class IsAdminOrTenantAdmin(permissions.BasePermission):
    """
    Allows access only to superusers or tenant admins.
    Tenant admins are users with role=ADMIN who belong to the request's tenant.
    Assumes TenantMiddleware sets request.tenant.
    """

    def has_permission(self, request, view):
        user = request.user
        tenant = getattr(request, "tenant", None)
        return is_tenant_admin(user, tenant)


class IsInstructorOrAdmin(permissions.BasePermission):
    """Allows access only to Admins or Instructors."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return (
            is_admin_user(user)
            or user.role == User.Role.INSTRUCTOR
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
        return obj == user or is_admin_user(user)


class IsAdmin(permissions.BasePermission):
    """
    Allows access only to users with admin privileges.
    
    This is a drop-in replacement for DRF's IsAdminUser that also checks
    the custom role field for ADMIN role, not just is_staff.
    
    Use this permission class instead of permissions.IsAdminUser in views
    that should be accessible to users with role=ADMIN.
    """

    def has_permission(self, request, view):
        return is_admin_user(request.user)
