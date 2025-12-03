from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from .models import LearningPath, LearningPathStep  # , LearningPathProgress


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


# @admin.register(LearningPathProgress)
# class LearningPathProgressAdmin(admin.ModelAdmin):
#     list_display = ('user', 'learning_path', 'status', 'started_at', 'completed_at')
#     list_filter = ('status', 'learning_path__tenant', 'learning_path')
#     search_fields = ('user__email', 'learning_path__title')
#     readonly_fields = ('user', 'learning_path', 'completed_steps', 'started_at', 'completed_at')
#     list_select_related = ('user', 'learning_path', 'learning_path__tenant')
