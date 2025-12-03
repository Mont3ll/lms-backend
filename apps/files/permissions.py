from rest_framework import permissions

# Permissions usually defined in common or specific apps like users/courses
# e.g., IsAdminOrTenantAdmin from users app can be reused here.

# Example: Check if user owns the file (if ownership concept is added)
# class IsFileOwnerOrAdmin(permissions.BasePermission):
#     def has_object_permission(self, request, view, obj):
#         user = request.user
#         if not user or not user.is_authenticated:
#             return False
#         # Assumes File model has an 'owner' or 'uploaded_by' field
#         return obj.uploaded_by == user or user.is_staff
