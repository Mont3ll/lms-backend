from rest_framework import permissions

# Reuse permissions from other apps or define specific ones if needed.
# Example:
# class IsLearningPathEditor(permissions.BasePermission):
#     """ Check if user is admin or created the learning path """
#     def has_object_permission(self, request, view, obj):
#         # obj is LearningPath instance
#         user = request.user
#         if not user or not user.is_authenticated: return False
#         # Check if creator? Need 'created_by' field on LearningPath model.
#         # return user.is_staff or obj.created_by == user
#         return user.is_staff # Simplified
