from rest_framework import permissions

# Import permissions from common, users, courses if needed or redefine here


class CanAttemptAssessment(permissions.BasePermission):
    """
    Checks if a user can start a new attempt for an assessment.
    (Combines enrollment, max attempts, due date checks - better in view logic).
    Placeholder - actual checks are complex and done in the start view.
    """

    def has_object_permission(self, request, view, obj):
        # Object 'obj' here is the Assessment
        user = request.user
        if not user or not user.is_authenticated or user.role != user.Role.LEARNER:
            return False
        # Basic check: is assessment published?
        if not obj.is_published:
            return False
        # More complex checks (enrollment, attempts, due date) are in the StartAssessmentAttemptView
        return True  # View performs the detailed checks


class CanSubmitAttempt(permissions.BasePermission):
    """Checks if a user owns the attempt and it's in progress."""

    def has_object_permission(self, request, view, obj):
        # Object 'obj' here is the AssessmentAttempt
        user = request.user
        return (
            user
            and user.is_authenticated
            and obj.user == user
            and obj.status == obj.AttemptStatus.IN_PROGRESS
        )


# Use permissions like IsInstructorOrAdmin, IsCourseInstructorOrAdmin from other apps for managing assessments/questions.
