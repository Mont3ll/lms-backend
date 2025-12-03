from rest_framework import serializers

from apps.courses.serializers import ContentItemSerializer, CourseSerializer
from apps.users.serializers import LearnerGroupSerializer, UserSerializer

from .models import Certificate, Enrollment, GroupEnrollment, LearnerProgress


class EnrollmentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)  # Display user details
    course = CourseSerializer(read_only=True)  # Display course details
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # Add progress percentage calculation?
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Enrollment
        fields = (
            "id",
            "user",
            "course",
            "enrolled_at",
            "status",
            "status_display",
            "completed_at",
            "expires_at",
            "progress_percentage",
            "created_at",
        )
        read_only_fields = fields  # Enrollments usually managed via services/actions

    def get_progress_percentage(self, obj):
        # Calculate completion percentage based on LearnerProgress items
        from .services import ProgressTrackerService

        return ProgressTrackerService.calculate_course_progress_percentage(obj)


class EnrollmentCreateSerializer(serializers.Serializer):
    """Serializer for manually creating a single enrollment (e.g., by admin)."""

    user_id = serializers.UUIDField(required=True)
    course_id = serializers.UUIDField(required=True)
    status = serializers.ChoiceField(
        choices=Enrollment.Status.choices,
        required=False,
        default=Enrollment.Status.ACTIVE,
    )

    # Add validation if needed (e.g., check if user/course exist and belong to tenant)


class GroupEnrollmentSerializer(serializers.ModelSerializer):
    group = LearnerGroupSerializer(read_only=True)
    course = CourseSerializer(read_only=True)

    class Meta:
        model = GroupEnrollment
        fields = ("id", "group", "course", "enrolled_at")
        read_only_fields = fields


class GroupEnrollmentCreateSerializer(serializers.Serializer):
    """Serializer for enrolling a group in a course."""

    group_id = serializers.UUIDField(required=True)
    course_id = serializers.UUIDField(required=True)


class LearnerProgressSerializer(serializers.ModelSerializer):
    enrollment_id = serializers.UUIDField(source="enrollment.id", read_only=True)
    user_id = serializers.UUIDField(source="enrollment.user.id", read_only=True)
    content_item = ContentItemSerializer(read_only=True)  # Display content item details
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = LearnerProgress
        fields = (
            "id",
            "enrollment_id",
            "user_id",
            "content_item",
            "status",
            "status_display",
            "progress_details",
            "started_at",
            "completed_at",
            "updated_at",
        )
        read_only_fields = fields  # Progress updated via specific actions/services


class LearnerProgressUpdateSerializer(serializers.Serializer):
    """Serializer for updating progress (e.g., marking as complete, saving video position)."""

    status = serializers.ChoiceField(
        choices=LearnerProgress.Status.choices, required=False
    )
    progress_details = serializers.JSONField(required=False)


class CertificateSerializer(serializers.ModelSerializer):
    """Serializer for Certificate model."""
    course_title = serializers.CharField(source='course.title', read_only=True)
    course_id = serializers.UUIDField(source='course.id', read_only=True)
    user_id = serializers.UUIDField(source='user.id', read_only=True)
    issued_date = serializers.DateTimeField(source='issued_at', read_only=True)
    expiry_date = serializers.DateTimeField(source='expires_at', read_only=True)

    class Meta:
        model = Certificate
        fields = (
            'id',
            'course_id',
            'course_title',
            'user_id',
            'status',
            'issued_date',
            'expiry_date',
            'file_url',
            'description',
            'verification_code',
        )
        read_only_fields = fields
