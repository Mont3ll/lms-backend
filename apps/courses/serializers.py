from rest_framework import serializers

from apps.users.serializers import UserSerializer  # For instructor info
from apps.files.models import File

from .models import ContentItem, ContentVersion, Course, CoursePrerequisite, Module, ModulePrerequisite


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


# --- Prerequisite Serializers ---


class ModulePrerequisiteSerializer(serializers.ModelSerializer):
    """Serializer for module prerequisite relationships."""
    prerequisite_module_title = serializers.CharField(
        source='prerequisite_module.title', read_only=True
    )
    prerequisite_module_order = serializers.IntegerField(
        source='prerequisite_module.order', read_only=True
    )
    prerequisite_type_display = serializers.CharField(
        source='get_prerequisite_type_display', read_only=True
    )

    class Meta:
        model = ModulePrerequisite
        fields = (
            "id",
            "module",
            "prerequisite_module",
            "prerequisite_module_title",
            "prerequisite_module_order",
            "prerequisite_type",
            "prerequisite_type_display",
            "minimum_score",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "module",
            "prerequisite_module_title",
            "prerequisite_module_order",
            "prerequisite_type_display",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        """Validate the prerequisite relationship."""
        module = attrs.get('module') or (self.instance.module if self.instance else None)
        prereq_module = attrs.get('prerequisite_module') or (
            self.instance.prerequisite_module if self.instance else None
        )
        
        if module and prereq_module:
            # Check self-reference
            if module.id == prereq_module.id:
                raise serializers.ValidationError(
                    {"prerequisite_module": "A module cannot be its own prerequisite."}
                )
            
            # Check same course or valid cross-course prerequisite
            if module.course_id != prereq_module.course_id:
                # Verify prerequisite course relationship exists
                if not CoursePrerequisite.objects.filter(
                    course=module.course,
                    prerequisite_course=prereq_module.course
                ).exists():
                    raise serializers.ValidationError({
                        "prerequisite_module": "Prerequisite module must be from the same course or from a prerequisite course."
                    })
        
        # Validate minimum_score if provided
        minimum_score = attrs.get('minimum_score')
        if minimum_score is not None and (minimum_score < 0 or minimum_score > 100):
            raise serializers.ValidationError({
                "minimum_score": "Minimum score must be between 0 and 100."
            })
        
        return attrs


class CoursePrerequisiteSerializer(serializers.ModelSerializer):
    """Serializer for course prerequisite relationships."""
    prerequisite_course_title = serializers.CharField(
        source='prerequisite_course.title', read_only=True
    )
    prerequisite_course_slug = serializers.CharField(
        source='prerequisite_course.slug', read_only=True
    )
    prerequisite_type_display = serializers.CharField(
        source='get_prerequisite_type_display', read_only=True
    )

    class Meta:
        model = CoursePrerequisite
        fields = (
            "id",
            "course",
            "prerequisite_course",
            "prerequisite_course_title",
            "prerequisite_course_slug",
            "prerequisite_type",
            "prerequisite_type_display",
            "minimum_completion_percentage",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "course",
            "prerequisite_course_title",
            "prerequisite_course_slug",
            "prerequisite_type_display",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        """Validate the prerequisite relationship."""
        course = attrs.get('course') or (self.instance.course if self.instance else None)
        prereq_course = attrs.get('prerequisite_course') or (
            self.instance.prerequisite_course if self.instance else None
        )
        
        if course and prereq_course:
            # Check self-reference
            if course.id == prereq_course.id:
                raise serializers.ValidationError(
                    {"prerequisite_course": "A course cannot be its own prerequisite."}
                )
            
            # Check same tenant
            if course.tenant_id != prereq_course.tenant_id:
                raise serializers.ValidationError({
                    "prerequisite_course": "Prerequisite course must belong to the same tenant."
                })
            
            # Check for circular dependencies
            if self._creates_circular_dependency(course, prereq_course):
                raise serializers.ValidationError({
                    "prerequisite_course": "Adding this prerequisite would create a circular dependency."
                })
        
        # Validate minimum_completion_percentage
        min_completion = attrs.get('minimum_completion_percentage')
        if min_completion is not None and (min_completion < 0 or min_completion > 100):
            raise serializers.ValidationError({
                "minimum_completion_percentage": "Minimum completion percentage must be between 0 and 100."
            })
        
        return attrs

    def _creates_circular_dependency(self, course, prereq_course):
        """Check if adding this prerequisite creates a circular dependency."""
        visited = set()
        
        def has_cycle(current_course_id, target_id):
            if current_course_id == target_id:
                return True
            if current_course_id in visited:
                return False
            visited.add(current_course_id)
            
            prereqs = CoursePrerequisite.objects.filter(
                course_id=current_course_id
            ).values_list('prerequisite_course_id', flat=True)
            
            for prereq_id in prereqs:
                if has_cycle(prereq_id, target_id):
                    return True
            return False
        
        return has_cycle(prereq_course.id, course.id)


class ModulePrerequisiteListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing prerequisites in module responses."""
    title = serializers.CharField(source='prerequisite_module.title', read_only=True)
    order = serializers.IntegerField(source='prerequisite_module.order', read_only=True)
    prerequisite_type_display = serializers.CharField(
        source='get_prerequisite_type_display', read_only=True
    )

    class Meta:
        model = ModulePrerequisite
        fields = (
            "id",
            "prerequisite_module",
            "title",
            "order",
            "prerequisite_type",
            "prerequisite_type_display",
            "minimum_score",
        )
        read_only_fields = fields


class CoursePrerequisiteListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing prerequisites in course responses."""
    title = serializers.CharField(source='prerequisite_course.title', read_only=True)
    slug = serializers.CharField(source='prerequisite_course.slug', read_only=True)
    prerequisite_type_display = serializers.CharField(
        source='get_prerequisite_type_display', read_only=True
    )

    class Meta:
        model = CoursePrerequisite
        fields = (
            "id",
            "prerequisite_course",
            "title",
            "slug",
            "prerequisite_type",
            "prerequisite_type_display",
            "minimum_completion_percentage",
        )
        read_only_fields = fields


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
            "is_required",
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
    # Nested listing of prerequisites (read-only)
    prerequisites_list = ModulePrerequisiteListSerializer(
        source='prerequisites', many=True, read_only=True
    )
    # For checking if user has met prerequisites
    prerequisites_met = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = (
            "id",
            "title",
            "description",
            "course",
            "order",
            "content_items",
            "prerequisites_list",
            "prerequisites_met",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "course",
            "content_items",
            "prerequisites_list",
            "prerequisites_met",
            "created_at",
            "updated_at",
        )  # Course is set via Course endpoint

    def get_prerequisites_met(self, obj):
        """Check if the current user has met all required prerequisites."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        
        is_met, unmet = obj.are_prerequisites_met(request.user, check_type='REQUIRED')
        if is_met:
            return {"met": True, "unmet_count": 0, "unmet_modules": []}
        
        return {
            "met": False,
            "unmet_count": len(unmet),
            "unmet_modules": [
                {
                    "id": str(item['module'].id),
                    "title": item['module'].title,
                    "reason": item['reason']
                }
                for item in unmet
            ]
        }


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
    # Nested listing of prerequisites (read-only)
    prerequisites_list = CoursePrerequisiteListSerializer(
        source='prerequisites', many=True, read_only=True
    )
    # For checking if user has met prerequisites
    prerequisites_met = serializers.SerializerMethodField()
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
            "prerequisites_list",
            "prerequisites_met",
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
            "prerequisites_list",
            "prerequisites_met",
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
        """Calculate the number of active enrollments for this course.
        
        Uses the _enrollment_count annotation from the viewset queryset if available,
        otherwise falls back to a database query.
        """
        # Use annotation if available (set by CourseViewSet.get_queryset)
        if hasattr(obj, '_enrollment_count'):
            return obj._enrollment_count
        # Fallback for when annotation is not present (e.g., single object retrieval)
        from apps.enrollments.models import Enrollment
        return obj.enrollments.filter(status=Enrollment.Status.ACTIVE).count()

    def get_is_enrolled(self, obj):
        """Check if the current user is enrolled in this course.
        
        Uses the _is_enrolled annotation from the viewset queryset if available,
        otherwise falls back to a database query.
        """
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False
        
        # Use annotation if available (set by CourseViewSet.get_queryset)
        if hasattr(obj, '_is_enrolled'):
            return obj._is_enrolled
        
        # Fallback for when annotation is not present
        from apps.enrollments.models import Enrollment
        return Enrollment.objects.filter(
            course=obj, 
            user=request.user, 
            status__in=[Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED]
        ).exists()

    def get_enrollment_id(self, obj):
        """Get the enrollment ID for the current user if enrolled.
        
        Uses the _enrollment_id annotation from the viewset queryset if available,
        otherwise falls back to a database query.
        """
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        
        # Use annotation if available (set by CourseViewSet.get_queryset)
        if hasattr(obj, '_enrollment_id'):
            enrollment_id = obj._enrollment_id
            return str(enrollment_id) if enrollment_id else None
        
        # Fallback for when annotation is not present
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
        """Get the progress percentage for the current user if enrolled.
        
        Uses the _progress_percentage annotation from the viewset queryset if available,
        otherwise falls back to a database query.
        """
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        
        # Use annotation if available (set by CourseViewSet.get_queryset)
        if hasattr(obj, '_progress_percentage'):
            return obj._progress_percentage
        
        # Fallback for when annotation is not present
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

    def get_prerequisites_met(self, obj):
        """Check if the current user has met all required prerequisites for this course."""
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return None
        
        is_met, unmet = obj.are_prerequisites_met(request.user, check_type='REQUIRED')
        if is_met:
            return {"met": True, "unmet_count": 0, "unmet_courses": []}
        
        return {
            "met": False,
            "unmet_count": len(unmet),
            "unmet_courses": [
                {
                    "id": str(item['course'].id),
                    "title": item['course'].title,
                    "slug": item['course'].slug,
                    "reason": item['reason'],
                    "current_progress": item.get('current_progress'),
                    "required_completion": item.get('required_completion')
                }
                for item in unmet
            ]
        }
