from rest_framework import serializers

from .models import GeneratedContent, GenerationJob, ModelConfig, PromptTemplate


class ModelConfigSerializer(serializers.ModelSerializer):
    # Exclude api_key from responses by default
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = ModelConfig
        fields = (
            "id",
            "name",
            "tenant",
            "provider",
            "model_id",
            "api_key",
            "base_url",
            "is_active",
            "default_params",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant",
            "created_at",
            "updated_at",
        )  # Tenant set by context


class PromptTemplateSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.name", read_only=True)
    default_model_config_name = serializers.CharField(
        source="default_model_config.name", read_only=True, allow_null=True
    )

    class Meta:
        model = PromptTemplate
        fields = (
            "id",
            "name",
            "description",
            "template_text",
            "variables",
            "tenant",
            "tenant_name",
            "default_model_config",
            "default_model_config_name",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant",
            "tenant_name",
            "default_model_config_name",
            "created_at",
            "updated_at",
        )


class GenerationJobSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    user_email = serializers.EmailField(
        source="user.email", read_only=True, allow_null=True
    )
    prompt_template_name = serializers.CharField(
        source="prompt_template.name", read_only=True, allow_null=True
    )
    model_name = serializers.CharField(
        source="model_config_used.name", read_only=True, allow_null=True
    )

    class Meta:
        model = GenerationJob
        fields = (
            "id",
            "status",
            "status_display",
            "tenant",
            "user",
            "user_email",
            "prompt_template",
            "prompt_template_name",
            "model_config_used",
            "model_name",
            "celery_task_id",
            "input_context",
            "generation_params",  # Input prompt might be too large
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "status",
            "status_display",
            "tenant",
            "user",
            "user_email",
            "prompt_template_name",
            "model_name",
            "celery_task_id",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
        )
        # Input fields are writable via specific creation endpoint


class GeneratedContentSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(
        source="user.email", read_only=True, allow_null=True
    )

    class Meta:
        model = GeneratedContent
        fields = (
            "id",
            "job",
            "tenant",
            "user",
            "user_email",
            "generated_text",
            "metadata",
            "is_accepted",
            "rating",
            "evaluation_feedback",
            "created_at",
        )
        read_only_fields = (
            "id",
            "job",
            "tenant",
            "user",
            "user_email",
            "generated_text",
            "metadata",
            "created_at",
        )
        # Allow updates only for evaluation fields


class GenerateContentSerializer(serializers.Serializer):
    """Serializer for initiating a content generation job."""

    prompt_template_id = serializers.UUIDField(required=False, allow_null=True)
    model_config_id = serializers.UUIDField(
        required=False, allow_null=True
    )  # Optional: override template default
    input_context = serializers.JSONField(
        required=True, help_text="Dictionary of variables for the prompt template"
    )
    generation_params = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Override model parameters (e.g., temperature)",
    )
    # Allow raw prompt input?
    # custom_prompt = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        # Ensure either template or custom prompt is provided?
        if not attrs.get("prompt_template_id"):  # and not attrs.get('custom_prompt'):
            raise serializers.ValidationError(
                "Either prompt_template_id or custom_prompt must be provided."
            )
        return attrs
