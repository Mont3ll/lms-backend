from django.contrib import admin

from .models import GeneratedContent, GenerationJob, ModelConfig, PromptTemplate


@admin.register(ModelConfig)
class ModelConfigAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "provider", "model_id", "is_active")
    list_filter = ("provider", "is_active", "tenant")
    search_fields = ("name", "model_id", "tenant__name")
    # Consider hiding api_key or using a custom widget/field for better security


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "description_snippet", "default_model_config")
    list_filter = ("tenant", "default_model_config")
    search_fields = ("name", "template_text", "description", "tenant__name")
    list_select_related = ("tenant", "default_model_config")

    def description_snippet(self, obj):
        return (
            obj.description[:50] + "..."
            if obj.description and len(obj.description) > 50
            else obj.description
        )

    description_snippet.short_description = "Description"


@admin.register(GenerationJob)
class GenerationJobAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "prompt_template",
        "model_config_used",
        "user",
        "status",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "tenant", "model_config_used", "prompt_template", "user")
    search_fields = ("id", "user__email", "prompt_template__name", "celery_task_id")
    list_select_related = ("tenant", "user", "prompt_template", "model_config_used")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "input_prompt",
        "input_context",
        "generation_params",
        "error_message",
        "celery_task_id",
    )
    # Add action to retry failed jobs?


@admin.register(GeneratedContent)
class GeneratedContentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "user",
        "job_id_display",
        "created_at",
        "is_accepted",
        "rating",
    )
    list_filter = ("tenant", "user", "is_accepted", "rating")
    search_fields = ("id", "generated_text", "user__email", "job__id")
    list_select_related = ("tenant", "user", "job")
    readonly_fields = (
        "id",
        "job",
        "tenant",
        "user",
        "generated_text",
        "metadata",
        "created_at",
        "updated_at",
    )  # Make generated content immutable?
    fields = (
        "job",
        "tenant",
        "user",
        "generated_text",
        "metadata",
        "is_accepted",
        "rating",
        "evaluation_feedback",
        "created_at",
        "updated_at",
    )

    def job_id_display(self, obj):
        return obj.job_id

    job_id_display.short_description = "Job ID"
