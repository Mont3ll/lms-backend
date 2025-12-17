from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.utils.html import format_html

from .models import (
    LearningPath,
    LearningPathStep,
    LearningPathProgress,
    LearningPathStepProgress,
    PersonalizedLearningPath,
    PersonalizedPathStep,
    PersonalizedPathProgress,
)


class LearningPathStepInline(
    admin.TabularInline
):  # Cannot use GenericTabularInline easily if editing generic FK directly
    model = LearningPathStep
    fk_name = "learning_path"
    extra = 1
    ordering = ("order",)
    # Need custom form or widget to select Course/Module easily for content_object
    fields = (
        "order",
        "content_type",
        "object_id",
        "is_required",
    )  # Manually enter content_type ID and object_id UUID
    # Consider using django-grappelli or similar for better generic relation handling in admin,
    # or a custom ModelAdmin form.


@admin.register(LearningPath)
class LearningPathAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "tenant", "status", "step_count", "created_at")
    list_filter = ("status", "tenant")
    search_fields = ("title", "slug", "description", "tenant__name")
    prepopulated_fields = {"slug": ("title",)}
    list_select_related = ("tenant",)
    inlines = [LearningPathStepInline]
    fieldsets = (
        (None, {"fields": ("tenant", "title", "slug", "status")}),
        ("Details", {"fields": ("description",)}),  # 'objectives', 'thumbnail'
    )

    def step_count(self, obj):
        return obj.steps.count()

    step_count.short_description = "Steps"


@admin.register(LearningPathStep)
class LearningPathStepAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "learning_path",
        "order",
        "content_type",
        "object_id",
        "is_required",
    )
    list_filter = (
        "learning_path__tenant",
        "learning_path",
        "content_type",
        "is_required",
    )
    search_fields = (
        "learning_path__title",
        "object_id",
    )  # Search by UUID might not be user friendly
    list_select_related = ("learning_path", "learning_path__tenant", "content_type")
    ordering = ("learning_path__title", "order")
    # Customize form for better selection of content_object
    fields = ("learning_path", "order", "content_type", "object_id", "is_required")


# =============================================================================
# Learning Path Progress Admin
# =============================================================================


class LearningPathStepProgressInline(admin.TabularInline):
    model = LearningPathStepProgress
    fk_name = "learning_path_progress"
    extra = 0
    ordering = ("step__order",)
    fields = ("step", "status", "started_at", "completed_at")
    readonly_fields = ("step", "started_at", "completed_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LearningPathProgress)
class LearningPathProgressAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "learning_path",
        "status",
        "progress_display",
        "current_step_order",
        "started_at",
        "completed_at",
    )
    list_filter = ("status", "learning_path__tenant", "learning_path")
    search_fields = ("user__email", "learning_path__title")
    readonly_fields = (
        "user",
        "learning_path",
        "started_at",
        "completed_at",
        "progress_display",
    )
    list_select_related = ("user", "learning_path", "learning_path__tenant")
    inlines = [LearningPathStepProgressInline]
    fieldsets = (
        (None, {"fields": ("user", "learning_path")}),
        (
            "Progress",
            {"fields": ("status", "current_step_order", "progress_display")},
        ),
        ("Timestamps", {"fields": ("started_at", "completed_at")}),
    )

    def progress_display(self, obj):
        percentage = obj.progress_percentage
        return format_html(
            '<div style="width:100px;background:#ddd;border-radius:4px;">'
            '<div style="width:{}px;background:#4CAF50;height:20px;border-radius:4px;"></div>'
            '</div> {:.0f}%',
            percentage,
            percentage,
        )

    progress_display.short_description = "Progress"


@admin.register(LearningPathStepProgress)
class LearningPathStepProgressAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "learning_path_progress",
        "step",
        "status",
        "started_at",
        "completed_at",
    )
    list_filter = (
        "status",
        "learning_path_progress__learning_path__tenant",
        "learning_path_progress__learning_path",
    )
    search_fields = (
        "user__email",
        "learning_path_progress__learning_path__title",
    )
    list_select_related = (
        "user",
        "learning_path_progress",
        "learning_path_progress__learning_path",
        "step",
    )
    readonly_fields = ("user", "learning_path_progress", "step", "started_at", "completed_at")
    ordering = ("learning_path_progress", "step__order")


# =============================================================================
# Personalized Learning Path Admin
# =============================================================================


class PersonalizedPathStepInline(admin.TabularInline):
    model = PersonalizedPathStep
    fk_name = "path"
    extra = 0
    ordering = ("order",)
    fields = ("order", "module", "is_required", "estimated_duration", "reason")
    readonly_fields = ("reason",)
    autocomplete_fields = ("module",)


@admin.register(PersonalizedLearningPath)
class PersonalizedLearningPathAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "user",
        "tenant",
        "generation_type",
        "status",
        "step_count",
        "estimated_duration",
        "generated_at",
        "expires_at",
    )
    list_filter = ("status", "generation_type", "tenant")
    search_fields = ("title", "user__email", "description", "tenant__name")
    list_select_related = ("user", "tenant")
    autocomplete_fields = ("user", "tenant")
    filter_horizontal = ("target_skills",)
    inlines = [PersonalizedPathStepInline]
    readonly_fields = ("generated_at", "generation_params_display")
    fieldsets = (
        (None, {"fields": ("user", "tenant", "title", "description")}),
        (
            "Generation Details",
            {"fields": ("generation_type", "target_skills", "generation_params_display")},
        ),
        (
            "Status & Duration",
            {"fields": ("status", "estimated_duration", "expires_at")},
        ),
        ("Metadata", {"fields": ("generated_at",), "classes": ("collapse",)}),
    )

    def step_count(self, obj):
        return obj.steps.count()

    step_count.short_description = "Steps"

    def generation_params_display(self, obj):
        import json
        return format_html(
            '<pre style="max-width:500px;overflow:auto;">{}</pre>',
            json.dumps(obj.generation_params, indent=2),
        )

    generation_params_display.short_description = "Generation Parameters"


@admin.register(PersonalizedPathStep)
class PersonalizedPathStepAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "path",
        "module",
        "order",
        "is_required",
        "estimated_duration",
    )
    list_filter = (
        "is_required",
        "path__tenant",
        "path__generation_type",
        "path",
    )
    search_fields = (
        "path__title",
        "path__user__email",
        "module__title",
        "reason",
    )
    list_select_related = ("path", "path__user", "path__tenant", "module")
    autocomplete_fields = ("path", "module")
    filter_horizontal = ("target_skills",)
    ordering = ("path", "order")
    fieldsets = (
        (None, {"fields": ("path", "module", "order")}),
        ("Settings", {"fields": ("is_required", "estimated_duration")}),
        ("Skills & Reasoning", {"fields": ("target_skills", "reason")}),
    )


@admin.register(PersonalizedPathProgress)
class PersonalizedPathProgressAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "path",
        "status",
        "progress_display",
        "current_step_order",
        "started_at",
        "completed_at",
        "last_activity_at",
    )
    list_filter = ("status", "path__tenant", "path__generation_type")
    search_fields = ("user__email", "path__title")
    list_select_related = ("user", "path", "path__tenant")
    autocomplete_fields = ("user", "path")
    readonly_fields = (
        "user",
        "path",
        "started_at",
        "completed_at",
        "last_activity_at",
        "progress_display",
    )
    fieldsets = (
        (None, {"fields": ("user", "path")}),
        (
            "Progress",
            {"fields": ("status", "current_step_order", "progress_display")},
        ),
        (
            "Timestamps",
            {"fields": ("started_at", "completed_at", "last_activity_at")},
        ),
    )

    def progress_display(self, obj):
        percentage = obj.progress_percentage
        return format_html(
            '<div style="width:100px;background:#ddd;border-radius:4px;">'
            '<div style="width:{}px;background:#4CAF50;height:20px;border-radius:4px;"></div>'
            '</div> {:.0f}%',
            percentage,
            percentage,
        )

    progress_display.short_description = "Progress"
