from rest_framework import permissions


class IsAdminUserOrReadOnly(permissions.BasePermission):
    """
    Allows read-only access to any user, but write access only to admin users.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_staff


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object or admins to edit it.
    Assumes the object has a 'user' or 'owner' attribute.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Write permissions are only allowed to the owner of the object or an admin.
        # Check for 'user' attribute first, then 'owner'
        owner_field = None
        if hasattr(obj, "user"):
            owner_field = obj.user
        elif hasattr(obj, "owner"):
            owner_field = obj.owner

        return (owner_field == request.user) or (request.user and request.user.is_staff)


# Add more granular permissions as needed, e.g., IsInstructor, IsCourseMember
