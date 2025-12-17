import logging

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.courses.models import Course, Module
from apps.courses.serializers import (
    CourseSerializer,
    ModuleSerializer,
)

from .models import (
    LearningPath,
    LearningPathStep,
    LearningPathProgress,
    LearningPathStepProgress,
    PersonalizedLearningPath,
    PersonalizedPathStep,
    PersonalizedPathProgress,
)

logger = logging.getLogger(__name__)


# Valid content types for learning path steps
VALID_CONTENT_TYPES = {
    "course": ("courses", "course"),
    "module": ("courses", "module"),
}


class ContentTypeField(serializers.Field):
    """
    Custom field that accepts either:
    - An integer ContentType PK (e.g., 12)
    - A string model name (e.g., "course" or "module")
    
    Returns a ContentType instance on deserialization.
    """
    
    def to_representation(self, value):
        """Return the ContentType PK for serialization."""
        if value is None:
            return None
        return value.pk
    
    def to_internal_value(self, data):
        """Convert input to ContentType instance."""
        if data is None:
            raise serializers.ValidationError("This field is required.")
        
        # If it's an integer or numeric string, treat as PK
        if isinstance(data, int) or (isinstance(data, str) and data.isdigit()):
            pk = int(data)
            try:
                ct = ContentType.objects.get(pk=pk)
                # Validate it's an allowed content type
                if (ct.app_label, ct.model) not in VALID_CONTENT_TYPES.values():
                    raise serializers.ValidationError(
                        f"Content type '{ct.app_label}.{ct.model}' is not allowed. "
                        f"Allowed types: {list(VALID_CONTENT_TYPES.keys())}"
                    )
                return ct
            except ContentType.DoesNotExist:
                raise serializers.ValidationError(
                    f"No ContentType found with pk={pk}"
                )
        
        # If it's a string, look up by model name
        if isinstance(data, str):
            model_name = data.lower()
            if model_name not in VALID_CONTENT_TYPES:
                raise serializers.ValidationError(
                    f"Invalid content type '{data}'. "
                    f"Allowed types: {list(VALID_CONTENT_TYPES.keys())}"
                )
            
            app_label, model = VALID_CONTENT_TYPES[model_name]
            try:
                return ContentType.objects.get(app_label=app_label, model=model)
            except ContentType.DoesNotExist:
                raise serializers.ValidationError(
                    f"ContentType for '{app_label}.{model}' not found in database."
                )
        
        raise serializers.ValidationError(
            f"Invalid content_type_id format. Expected integer PK or string model name "
            f"({list(VALID_CONTENT_TYPES.keys())}), got {type(data).__name__}."
        )


class LearningPathStepSerializer(serializers.ModelSerializer):
    content_object = serializers.SerializerMethodField(read_only=True)
    content_type_name = serializers.CharField(
        source="content_type.model", read_only=True
    )
    # Custom field that accepts integer PK or string model name
    content_type_id = ContentTypeField(
        write_only=True,
        source="content_type",
    )
    object_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = LearningPathStep
        fields = (
            "id",
            "learning_path",
            "order",
            "is_required",
            "content_type_id",
            "object_id",  # Write-only fields
            "content_type_name",
            "content_object",  # Read-only representation
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "learning_path",
            "content_type_name",
            "content_object",
            "created_at",
            "updated_at",
        )

    def get_content_object(self, obj):
        """Serialize the related Course or Module object."""
        # Return a simplified representation or use full serializers? Use full for now.
        if isinstance(obj.content_object, Course):
            # Pass request context if needed by nested serializers
            context = {"request": self.context.get("request")}
            serializer = CourseSerializer(
                obj.content_object, context=context, read_only=True
            )  # Read only nested view
            return {"type": "course", "data": serializer.data}  # Add type indicator
        elif isinstance(obj.content_object, Module):
            context = {"request": self.context.get("request")}
            serializer = ModuleSerializer(
                obj.content_object, context=context, read_only=True
            )
            return {"type": "module", "data": serializer.data}
        return None

    def validate(self, attrs):
        """Validate that the object_id exists for the given content_type."""
        content_type = attrs.get(
            "content_type"
        )  # Get ContentType instance via source='content_type'
        object_id = attrs.get("object_id")
        learning_path = self.context["view"].get_object()  # Get path from view context
        path_tenant = learning_path.tenant

        if content_type and object_id:
            ModelClass = content_type.model_class()
            if not ModelClass:
                raise serializers.ValidationError(f"Invalid content type specified.")

            try:
                # Check existence and tenant match
                content_obj = ModelClass.objects.get(pk=object_id)
                obj_tenant = None
                if isinstance(content_obj, Course):
                    obj_tenant = content_obj.tenant
                elif isinstance(content_obj, Module):
                    obj_tenant = content_obj.course.tenant

                if obj_tenant != path_tenant:
                    raise serializers.ValidationError(
                        f"{content_type.model.capitalize()} belongs to a different tenant."
                    )

            except ModelClass.DoesNotExist:
                raise serializers.ValidationError(
                    f"No {content_type.model} found with ID {object_id}."
                )
            except AttributeError:
                # Handle cases where the content object doesn't have a tenant (shouldn't happen for Course/Module)
                logger.warning(
                    f"Could not verify tenant for {content_type.model} with ID {object_id}"
                )
                # Decide if this should be an error or allowed

        return attrs


class LearningPathSerializer(serializers.ModelSerializer):
    # Use read_only=True for nested steps in list/retrieve views
    # Step management happens via separate actions/endpoints
    steps = LearningPathStepSerializer(many=True, read_only=True)
    step_count = serializers.IntegerField(source="steps.count", read_only=True)
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # Add objectives, thumbnail_url etc.

    class Meta:
        model = LearningPath
        fields = (
            "id",
            "title",
            "slug",
            "description",
            "tenant",
            "tenant_name",
            "status",
            "status_display",
            "step_count",
            "steps",
            "created_at",
            "updated_at",  # Add other fields
        )
        read_only_fields = (
            "id",
            "slug",
            "tenant",
            "tenant_name",
            "step_count",
            "steps",
            "created_at",
            "updated_at",
            "status_display",
        )


# Serializer for managing steps order
class LearningPathStepOrderSerializer(serializers.Serializer):
    # List of LearningPathStep IDs in desired order
    steps = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        min_length=1,
    )


# Serializers for user progress
class LearningPathStepProgressSerializer(serializers.ModelSerializer):
    step_order = serializers.IntegerField(source='step.order', read_only=True)
    step_title = serializers.SerializerMethodField(read_only=True)
    learning_path_title = serializers.CharField(source='learning_path_progress.learning_path.title', read_only=True)
    content_type_name = serializers.CharField(source='step.content_type.model', read_only=True)
    
    class Meta:
        model = LearningPathStepProgress
        fields = (
            'id', 'user', 'learning_path_progress', 'step', 'step_order', 'step_title',
            'learning_path_title', 'content_type_name', 'status', 'started_at', 
            'completed_at', 'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'user', 'step_order', 'step_title', 'learning_path_title', 
            'content_type_name', 'created_at', 'updated_at'
        )
    
    def get_step_title(self, obj):
        """Get the title of the content object (course/module)."""
        if obj.step.content_object:
            return getattr(obj.step.content_object, 'title', str(obj.step.object_id))
        return str(obj.step.object_id)


class LearningPathProgressSerializer(serializers.ModelSerializer):
    learning_path_title = serializers.CharField(source='learning_path.title', read_only=True)
    learning_path_slug = serializers.CharField(source='learning_path.slug', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    progress_percentage = serializers.ReadOnlyField()
    current_step_info = serializers.SerializerMethodField(read_only=True)
    next_step_info = serializers.SerializerMethodField(read_only=True)
    step_progress = LearningPathStepProgressSerializer(many=True, read_only=True)
    total_steps = serializers.IntegerField(source='learning_path.steps.count', read_only=True)
    completed_step_ids = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = LearningPathProgress
        fields = (
            'id', 'user', 'user_email', 'learning_path', 'learning_path_title', 
            'learning_path_slug', 'status', 'started_at', 'completed_at', 'current_step_order',
            'progress_percentage', 'current_step_info', 'next_step_info', 'total_steps',
            'step_progress', 'completed_step_ids', 'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'user', 'user_email', 'learning_path_title', 'learning_path_slug',
            'progress_percentage', 'current_step_info', 'next_step_info', 'total_steps',
            'step_progress', 'completed_step_ids', 'created_at', 'updated_at'
        )
    
    def get_completed_step_ids(self, obj):
        """Get list of completed step IDs for easier frontend consumption."""
        return list(
            obj.step_progress.filter(
                status=LearningPathStepProgress.Status.COMPLETED
            ).values_list('step_id', flat=True).distinct()
        )
    
    def get_current_step_info(self, obj):
        """Get information about the current step."""
        current_step = obj.current_step
        if current_step and current_step.content_object:
            return {
                'id': current_step.id,
                'order': current_step.order,
                'title': getattr(current_step.content_object, 'title', str(current_step.object_id)),
                'content_type': current_step.content_type.model,
                'is_required': current_step.is_required,
            }
        return None
    
    def get_next_step_info(self, obj):
        """Get information about the next step."""
        next_step = obj.next_step
        if next_step and next_step.content_object:
            return {
                'id': next_step.id,
                'order': next_step.order,
                'title': getattr(next_step.content_object, 'title', str(next_step.object_id)),
                'content_type': next_step.content_type.model,
                'is_required': next_step.is_required,
            }
        return None


# =============================================================================
# Personalized Learning Path Serializers
# =============================================================================


class PersonalizedPathStepSerializer(serializers.ModelSerializer):
    """Serializer for steps within a personalized learning path."""
    module_title = serializers.CharField(source='module.title', read_only=True)
    module_slug = serializers.CharField(source='module.slug', read_only=True)
    course_title = serializers.CharField(source='module.course.title', read_only=True)
    target_skill_ids = serializers.PrimaryKeyRelatedField(
        queryset=Module.objects.none(),  # Will be set dynamically
        many=True,
        write_only=True,
        source='target_skills',
        required=False
    )
    target_skills_info = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = PersonalizedPathStep
        fields = (
            'id',
            'path',
            'module',
            'module_title',
            'module_slug',
            'course_title',
            'order',
            'is_required',
            'reason',
            'estimated_duration',
            'target_skill_ids',
            'target_skills_info',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'path',
            'module_title',
            'module_slug',
            'course_title',
            'target_skills_info',
            'created_at',
            'updated_at',
        )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamically set the queryset for target_skill_ids
        from apps.skills.models import Skill
        if 'target_skill_ids' in self.fields:
            self.fields['target_skill_ids'].child_relation.queryset = Skill.objects.filter(is_active=True)
    
    def get_target_skills_info(self, obj):
        """Return basic info about target skills."""
        return [
            {'id': str(skill.id), 'name': skill.name, 'slug': skill.slug}
            for skill in obj.target_skills.all()
        ]


class PersonalizedPathStepCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating personalized path steps (used by path generator)."""
    
    class Meta:
        model = PersonalizedPathStep
        fields = (
            'module',
            'order',
            'is_required',
            'reason',
            'estimated_duration',
        )


class PersonalizedLearningPathSerializer(serializers.ModelSerializer):
    """Serializer for personalized learning paths."""
    user_email = serializers.EmailField(source='user.email', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    generation_type_display = serializers.CharField(
        source='get_generation_type_display', read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    target_skill_ids = serializers.PrimaryKeyRelatedField(
        queryset=Module.objects.none(),  # Will be set dynamically
        many=True,
        write_only=True,
        source='target_skills',
        required=False
    )
    target_skills_info = serializers.SerializerMethodField(read_only=True)
    steps = PersonalizedPathStepSerializer(many=True, read_only=True)
    total_steps = serializers.ReadOnlyField()
    required_steps_count = serializers.ReadOnlyField()
    is_expired = serializers.ReadOnlyField()
    
    class Meta:
        model = PersonalizedLearningPath
        fields = (
            'id',
            'user',
            'user_email',
            'tenant',
            'tenant_name',
            'title',
            'description',
            'generation_type',
            'generation_type_display',
            'target_skill_ids',
            'target_skills_info',
            'estimated_duration',
            'status',
            'status_display',
            'generated_at',
            'expires_at',
            'generation_params',
            'total_steps',
            'required_steps_count',
            'is_expired',
            'steps',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'user',
            'user_email',
            'tenant',
            'tenant_name',
            'generation_type_display',
            'status_display',
            'target_skills_info',
            'generated_at',
            'total_steps',
            'required_steps_count',
            'is_expired',
            'steps',
            'created_at',
            'updated_at',
        )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamically set the queryset for target_skill_ids
        from apps.skills.models import Skill
        if 'target_skill_ids' in self.fields:
            self.fields['target_skill_ids'].child_relation.queryset = Skill.objects.filter(is_active=True)
    
    def get_target_skills_info(self, obj):
        """Return basic info about target skills."""
        return [
            {'id': str(skill.id), 'name': skill.name, 'slug': skill.slug}
            for skill in obj.target_skills.all()
        ]


class PersonalizedLearningPathListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing personalized paths."""
    generation_type_display = serializers.CharField(
        source='get_generation_type_display', read_only=True
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_steps = serializers.ReadOnlyField()
    is_expired = serializers.ReadOnlyField()
    
    class Meta:
        model = PersonalizedLearningPath
        fields = (
            'id',
            'title',
            'description',
            'generation_type',
            'generation_type_display',
            'estimated_duration',
            'status',
            'status_display',
            'generated_at',
            'expires_at',
            'total_steps',
            'is_expired',
        )


# =============================================================================
# Path Generation Request/Response Serializers
# =============================================================================


class GenerateSkillGapPathSerializer(serializers.Serializer):
    """Request serializer for skill-gap based path generation."""
    target_skills = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        help_text="List of skill UUIDs to target"
    )
    max_duration_hours = serializers.IntegerField(
        min_value=1,
        max_value=500,
        default=40,
        required=False,
        help_text="Maximum path duration in hours"
    )
    max_modules = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=20,
        required=False,
        help_text="Maximum number of modules in the path"
    )
    difficulty_preference = serializers.ChoiceField(
        choices=['BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'PROGRESSIVE', 'ANY'],
        default='ANY',
        required=False,
        help_text="Preferred difficulty level. Use PROGRESSIVE for gradual difficulty increase."
    )
    include_completed = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Include modules the user has already completed"
    )
    
    def validate_target_skills(self, value):
        """Validate that all skill UUIDs exist."""
        from apps.skills.models import Skill
        
        existing_skills = Skill.objects.filter(id__in=value, is_active=True)
        existing_ids = set(str(s.id) for s in existing_skills)
        provided_ids = set(str(v) for v in value)
        
        missing = provided_ids - existing_ids
        if missing:
            raise serializers.ValidationError(
                f"The following skill IDs do not exist or are inactive: {list(missing)}"
            )
        
        return value


class GenerateRemedialPathSerializer(serializers.Serializer):
    """Request serializer for remedial path generation after failed assessment."""
    assessment_attempt_id = serializers.UUIDField(
        help_text="UUID of the failed assessment attempt"
    )
    focus_weak_areas = serializers.BooleanField(
        default=True,
        required=False,
        help_text="Focus on areas where the user performed poorly"
    )
    max_modules = serializers.IntegerField(
        min_value=1,
        max_value=50,
        default=10,
        required=False,
        help_text="Maximum number of modules in the remedial path"
    )
    
    def validate_assessment_attempt_id(self, value):
        """Validate that the assessment attempt exists and is failed."""
        from apps.assessments.models import AssessmentAttempt
        
        try:
            attempt = AssessmentAttempt.objects.get(id=value)
        except AssessmentAttempt.DoesNotExist:
            raise serializers.ValidationError(
                f"Assessment attempt with ID {value} does not exist."
            )
        
        # Store the attempt for use in the view
        self._assessment_attempt = attempt
        return value


class GeneratePathPreviewSerializer(serializers.Serializer):
    """Request serializer for path preview (generates without saving)."""
    generation_type = serializers.ChoiceField(
        choices=['SKILL_GAP', 'REMEDIAL'],
        help_text="Type of path to preview"
    )
    # Skill gap params
    target_skills = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="List of skill UUIDs to target (for SKILL_GAP type)"
    )
    max_duration_hours = serializers.IntegerField(
        min_value=1,
        max_value=500,
        default=40,
        required=False,
        help_text="Maximum path duration in hours"
    )
    max_modules = serializers.IntegerField(
        min_value=1,
        max_value=100,
        default=20,
        required=False,
        help_text="Maximum number of modules in the path"
    )
    difficulty_preference = serializers.ChoiceField(
        choices=['BEGINNER', 'INTERMEDIATE', 'ADVANCED', 'PROGRESSIVE', 'ANY'],
        default='ANY',
        required=False,
        help_text="Preferred difficulty level. Use PROGRESSIVE for gradual difficulty increase."
    )
    include_completed = serializers.BooleanField(
        default=False,
        required=False,
        help_text="Include modules the user has already completed"
    )
    # Remedial params
    assessment_attempt_id = serializers.UUIDField(
        required=False,
        help_text="UUID of the failed assessment attempt (for REMEDIAL type)"
    )
    focus_weak_areas = serializers.BooleanField(
        default=True,
        required=False,
        help_text="Focus on areas where the user performed poorly (for REMEDIAL type)"
    )
    
    def validate(self, attrs):
        """Validate that required fields are present for the generation type."""
        gen_type = attrs.get('generation_type')
        
        if gen_type == 'SKILL_GAP':
            if not attrs.get('target_skills'):
                raise serializers.ValidationError({
                    'target_skills': 'This field is required for SKILL_GAP generation type.'
                })
            # Validate skill IDs exist
            from apps.skills.models import Skill
            target_skills = attrs.get('target_skills', [])
            existing_skills = Skill.objects.filter(id__in=target_skills, is_active=True)
            existing_ids = set(str(s.id) for s in existing_skills)
            provided_ids = set(str(v) for v in target_skills)
            missing = provided_ids - existing_ids
            if missing:
                raise serializers.ValidationError({
                    'target_skills': f"The following skill IDs do not exist or are inactive: {list(missing)}"
                })
                
        elif gen_type == 'REMEDIAL':
            if not attrs.get('assessment_attempt_id'):
                raise serializers.ValidationError({
                    'assessment_attempt_id': 'This field is required for REMEDIAL generation type.'
                })
            # Validate assessment attempt exists
            from apps.assessments.models import AssessmentAttempt
            attempt_id = attrs.get('assessment_attempt_id')
            try:
                AssessmentAttempt.objects.get(id=attempt_id)
            except AssessmentAttempt.DoesNotExist:
                raise serializers.ValidationError({
                    'assessment_attempt_id': f"Assessment attempt with ID {attempt_id} does not exist."
                })
        
        return attrs


class PathPreviewStepSerializer(serializers.Serializer):
    """Serializer for steps in a path preview (not persisted)."""
    module_id = serializers.UUIDField()
    module_title = serializers.CharField()
    module_slug = serializers.CharField()
    course_title = serializers.CharField()
    order = serializers.IntegerField()
    is_required = serializers.BooleanField()
    reason = serializers.CharField()
    estimated_duration = serializers.IntegerField(help_text="Duration in minutes")
    skills_addressed = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of skills this module addresses"
    )


class PathPreviewResponseSerializer(serializers.Serializer):
    """Response serializer for path preview."""
    title = serializers.CharField()
    description = serializers.CharField()
    generation_type = serializers.CharField()
    estimated_duration = serializers.IntegerField(help_text="Total duration in minutes")
    total_steps = serializers.IntegerField()
    steps = PathPreviewStepSerializer(many=True)
    target_skills = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of target skills"
    )
    generation_params = serializers.DictField()


class PersonalizedPathProgressSerializer(serializers.ModelSerializer):
    """Serializer for tracking progress through personalized paths."""
    path_title = serializers.CharField(source='path.title', read_only=True)
    path_generation_type = serializers.CharField(source='path.generation_type', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    progress_percentage = serializers.ReadOnlyField()
    current_step_info = serializers.SerializerMethodField(read_only=True)
    next_step_info = serializers.SerializerMethodField(read_only=True)
    total_steps = serializers.IntegerField(source='path.total_steps', read_only=True)
    
    class Meta:
        model = PersonalizedPathProgress
        fields = (
            'id',
            'user',
            'user_email',
            'path',
            'path_title',
            'path_generation_type',
            'status',
            'status_display',
            'started_at',
            'completed_at',
            'current_step_order',
            'last_activity_at',
            'progress_percentage',
            'current_step_info',
            'next_step_info',
            'total_steps',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'user',
            'user_email',
            'path_title',
            'path_generation_type',
            'status_display',
            'progress_percentage',
            'current_step_info',
            'next_step_info',
            'total_steps',
            'created_at',
            'updated_at',
        )
    
    def get_current_step_info(self, obj):
        """Get information about the current step."""
        current_step = obj.current_step
        if current_step:
            return {
                'id': str(current_step.id),
                'order': current_step.order,
                'module_id': str(current_step.module.id),
                'module_title': current_step.module.title,
                'is_required': current_step.is_required,
                'estimated_duration': current_step.estimated_duration,
            }
        return None
    
    def get_next_step_info(self, obj):
        """Get information about the next step."""
        next_step = obj.next_step
        if next_step:
            return {
                'id': str(next_step.id),
                'order': next_step.order,
                'module_id': str(next_step.module.id),
                'module_title': next_step.module.title,
                'is_required': next_step.is_required,
                'estimated_duration': next_step.estimated_duration,
            }
        return None
