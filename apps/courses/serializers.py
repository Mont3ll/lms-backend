from rest_framework import serializers

from apps.users.serializers import UserSerializer  # For instructor info
from apps.files.models import File

from .models import ContentItem, ContentVersion, Course, Module


# --- Nested File Serializer for ContentItem ---


class ContentItemFileSerializer(serializers.ModelSerializer):
    """Lightweight serializer for file data in ContentItem responses."""
    file_url = serializers.URLField(read_only=True)

    class Meta:
        model = File
        fields = (
            "id",
            "original_filename",
            "file_url",
            "file_size",
            "mime_type",
            "status",
        )
        read_only_fields = fields


# --- Content Item Serializers ---


class ContentVersionSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = ContentVersion
        fields = (
            "id",
            "version_number",
            "user",
            "comment",
            "created_at",
            "content_type",
            "text_content",
            "external_url",
            "metadata",
        )  # Add file/assessment snapshots if needed
        read_only_fields = fields  # Versions are read-only snapshots


class ContentItemSerializer(serializers.ModelSerializer):
    content_type_display = serializers.CharField(
        source="get_content_type_display", read_only=True
    )
    # Nested file serializer for read operations
    file = ContentItemFileSerializer(read_only=True)
    # Write-only field for assigning file by ID
    file_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = ContentItem
        fields = (
            "id",
            "title",
            "module",
            "order",
            "content_type",
            "content_type_display",
            "text_content",
            "external_url",
            "file",
            "file_id",
            "metadata",
            "is_published",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "module",
            "created_at",
            "updated_at",
            "content_type_display",
        )  # Module set via Module endpoint
        extra_kwargs = {
            "text_content": {"required": False, "allow_null": True},
            "external_url": {"required": False, "allow_null": True},
            "metadata": {"required": False},
            # Make fields required based on content_type in validation if needed
        }

    def validate_file_id(self, value):
        """Ensure file exists and belongs to the same tenant."""
        if value:
            request = self.context.get("request")
            if request and hasattr(request, "tenant"):
                if not File.objects.filter(id=value, tenant=request.tenant).exists():
                    raise serializers.ValidationError(
                        "File not found or doesn't belong to this tenant."
                    )
        return value

    def validate(self, attrs):
        # Add validation logic based on content_type
        content_type = attrs.get(
            "content_type", getattr(self.instance, "content_type", None)
        )
        if content_type == ContentItem.ContentType.TEXT and not attrs.get(
            "text_content"
        ):
            # raise serializers.ValidationError({"text_content": "Text content is required for TEXT type."})
            pass  # Allow saving empty text content initially
        elif content_type == ContentItem.ContentType.URL and not attrs.get(
            "external_url"
        ):
            raise serializers.ValidationError(
                {"external_url": "External URL is required for URL type."}
            )
        # Validate file is provided for file-based content types
        file_types = [
            ContentItem.ContentType.DOCUMENT,
            ContentItem.ContentType.IMAGE,
            ContentItem.ContentType.VIDEO,
            ContentItem.ContentType.AUDIO,
            ContentItem.ContentType.H5P,
            ContentItem.ContentType.SCORM,
        ]
        if content_type in file_types:
            file_id = attrs.get("file_id")
            has_existing_file = self.instance and self.instance.file_id
            # Only require file on create, not update (unless explicitly clearing it)
            if not file_id and not has_existing_file and not self.instance:
                # For new items with file-based content types, file_id is recommended
                pass  # Allow creation without file initially for flexibility
        return attrs

    def create(self, validated_data):
        file_id = validated_data.pop("file_id", None)
        if file_id:
            validated_data["file_id"] = file_id
        return super().create(validated_data)

    def update(self, instance, validated_data):
        file_id = validated_data.pop("file_id", None)
        if file_id is not None:  # Allow explicitly setting to null
            instance.file_id = file_id
        return super().update(instance, validated_data)


# --- Module Serializers ---


class ModuleSerializer(serializers.ModelSerializer):
    # Nested listing of content items (read-only in module list/detail)
    content_items = ContentItemSerializer(many=True, read_only=True)

    class Meta:
        model = Module
        fields = (
            "id",
            "title",
            "description",
            "course",
            "order",
            "content_items",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "course",
            "content_items",
            "created_at",
            "updated_at",
        )  # Course is set via Course endpoint


# --- Course Serializers ---


class CourseSerializer(serializers.ModelSerializer):
    # Nested listing of modules (read-only in course list/detail)
    modules = ModuleSerializer(many=True, read_only=True)
    instructor = UserSerializer(read_only=True)  # Display instructor details
    instructor_id = serializers.UUIDField(
        write_only=True, required=False, allow_null=True
    )  # For setting instructor on create/update
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    difficulty_level_display = serializers.CharField(source="get_difficulty_level_display", read_only=True)
    enrollment_count = serializers.SerializerMethodField()  # Add enrollment count
    is_enrolled = serializers.SerializerMethodField()  # Add enrollment status for current user
    enrollment_id = serializers.SerializerMethodField()  # Add enrollment ID for current user
    progress_percentage = serializers.SerializerMethodField()  # Add progress percentage for current user
    # Add thumbnail URL when File model is integrated
    # thumbnail_url = serializers.URLField(source='thumbnail.file_url', read_only=True, allow_null=True)

    class Meta:
        model = Course
        fields = (
            "id",
            "title",
            "slug",
            "description",
            "category",
            "difficulty_level",
            "difficulty_level_display",
            "estimated_duration",
            "price",
            "is_free",
            "learning_objectives",
            "thumbnail",
            "tenant",
            "tenant_name",
            "instructor",
            "instructor_id",
            "status",
            "status_display",
            "tags",
            "modules",
            "enrollment_count",  # Add to fields
            "is_enrolled",  # Add enrollment status for current user
            "enrollment_id",  # Add enrollment ID for current user
            "progress_percentage",  # Add progress percentage for current user
            "created_at",
            "updated_at",  # Add 'thumbnail_url'
        )
        read_only_fields = (
            "id",
            "slug",
            "tenant",
            "tenant_name",
            "modules",
            "enrollment_count",  # Make it read-only
            "is_enrolled",  # Make it read-only
            "enrollment_id",  # Make it read-only
            "progress_percentage",  # Make it read-only
            "created_at",
            "updated_at",
            "status_display",
            "difficulty_level_display",
        )

    def create(self, validated_data):
        # Tenant should be set by the viewset based on request context
        tenant = self.context["request"].tenant
        if not tenant:
            raise serializers.ValidationError(
                "Tenant context is required to create a course."
            )
        validated_data["tenant"] = tenant

        # Assign instructor if instructor_id is provided
        instructor_id = validated_data.pop("instructor_id", None)
        if instructor_id:
            # Add validation: ensure instructor belongs to the same tenant and has correct role
            validated_data["instructor_id"] = instructor_id

        course = Course.objects.create(**validated_data)
        return course

    def update(self, instance, validated_data):
        # Handle instructor update if instructor_id is provided
        instructor_id = validated_data.pop("instructor_id", None)
        if instructor_id:
            # Add validation: ensure instructor belongs to the same tenant and has correct role
            instance.instructor_id = instructor_id
        # Prevent changing tenant
        validated_data.pop("tenant", None)
        instance = super().update(instance, validated_data)
        return instance

    def get_enrollment_count(self, obj):
        """Calculate the number of active enrollments for this course."""
        return obj.enrollments.filter(status='ACTIVE').count()

    def get_is_enrolled(self, obj):
        """Check if the current user is enrolled in this course."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        
        from apps.enrollments.models import Enrollment
        return Enrollment.objects.filter(
            course=obj, 
            user=request.user, 
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).exists()

    def get_enrollment_id(self, obj):
        """Get the enrollment ID for the current user if enrolled."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        
        from apps.enrollments.models import Enrollment
        try:
            enrollment = Enrollment.objects.get(
                course=obj, 
                user=request.user, 
                status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
            )
            return str(enrollment.id)  # Convert UUID to string for JSON serialization
        except Enrollment.DoesNotExist:
            return None

    def get_progress_percentage(self, obj):
        """Get the progress percentage for the current user if enrolled."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        
        from apps.enrollments.models import Enrollment
        try:
            enrollment = Enrollment.objects.get(
                course=obj, 
                user=request.user, 
                status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
            )
            return enrollment.progress
        except Enrollment.DoesNotExist:
            return None
