from django.contrib.contenttypes.models import ContentType
from django.db import models  # <<<--- IMPORT 'models' HERE
from django.shortcuts import get_object_or_404  # Useful for validation
from rest_framework import serializers

from apps.courses.models import Course, Module
from apps.courses.serializers import (  # Use existing course/module serializers
    CourseSerializer,
    ModuleSerializer,
)

from .models import LearningPath, LearningPathStep, LearningPathProgress, LearningPathStepProgress


class LearningPathStepSerializer(serializers.ModelSerializer):
    content_object = serializers.SerializerMethodField(read_only=True)
    content_type_name = serializers.CharField(
        source="content_type.model", read_only=True
    )
    # Writable fields for linking content object during creation/update
    content_type_id = serializers.PrimaryKeyRelatedField(
        queryset=ContentType.objects.filter(
            # Now 'models.Q' will be recognized
            models.Q(app_label="courses", model="course")
            | models.Q(app_label="courses", model="module")
        ),
        write_only=True,
        source="content_type",  # Use source to map correctly to model field
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
    
    class Meta:
        model = LearningPathProgress
        fields = (
            'id', 'user', 'user_email', 'learning_path', 'learning_path_title', 
            'learning_path_slug', 'status', 'started_at', 'completed_at', 'current_step_order',
            'progress_percentage', 'current_step_info', 'next_step_info', 'total_steps',
            'step_progress', 'created_at', 'updated_at'
        )
        read_only_fields = (
            'id', 'user', 'user_email', 'learning_path_title', 'learning_path_slug',
            'progress_percentage', 'current_step_info', 'next_step_info', 'total_steps',
            'step_progress', 'created_at', 'updated_at'
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
