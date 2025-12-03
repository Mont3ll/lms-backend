from django.contrib import admin

from .models import ContentItem, ContentVersion, Course, Module


class ModuleInline(admin.StackedInline):  # Or TabularInline
    model = Module
    extra = 1
    ordering = ("order",)
    fields = ("title", "description", "order")  # Customize fields shown inline


class ContentItemInline(admin.StackedInline):  # Or TabularInline
    model = ContentItem
    extra = 1
    ordering = ("order",)
    fields = ("title", "content_type", "order", "is_published")  # Customize fields
    # Add fields relevant to content data based on type (might require custom admin logic)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
        "tenant",
        "instructor",
        "status",
        "module_count",
        "created_at",
    )
    list_filter = ("status", "tenant", "instructor")
    search_fields = (
        "title",
        "slug",
        "description",
        "tenant__name",
        "instructor__email",
    )
    prepopulated_fields = {"slug": ("title",)}
    list_select_related = ("tenant", "instructor")
    inlines = [ModuleInline]
    # Add fieldsets for better organization
    fieldsets = (
        (None, {"fields": ("tenant", "title", "slug", "instructor", "status")}),
        ("Details", {"fields": ("description", "tags")}),  # 'thumbnail'
    )

    def module_count(self, obj):
        return obj.modules.count()

    module_count.short_description = "Modules"


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order", "content_item_count", "created_at")
    list_filter = ("course__tenant", "course")
    search_fields = ("title", "description", "course__title")
    list_select_related = ("course", "course__tenant")  # Optimize queries
    inlines = [ContentItemInline]
    ordering = ("course__title", "order")

    def content_item_count(self, obj):
        return obj.content_items.count()

    content_item_count.short_description = "Content Items"


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "module",
        "course_title",
        "content_type",
        "order",
        "is_published",
        "created_at",
    )
    list_filter = (
        "content_type",
        "is_published",
        "module__course__tenant",
        "module__course",
    )
    search_fields = ("title", "module__title", "module__course__title")
    list_select_related = (
        "module",
        "module__course",
        "module__course__tenant",
    )  # Optimize
    ordering = ("module__course__title", "module__order", "order")
    # Customize form based on content_type (requires more advanced admin config)
    fieldsets = (
        (
            None,
            {"fields": ("module", "title", "content_type", "order", "is_published")},
        ),
        (
            "Content Data",
            {"fields": ("text_content", "external_url", "metadata")},
        ),  # 'file', 'assessment'
    )

    def course_title(self, obj):
        return obj.module.course.title

    course_title.short_description = "Course"
    course_title.admin_order_field = "module__course__title"


@admin.register(ContentVersion)
class ContentVersionAdmin(admin.ModelAdmin):
    list_display = ("content_item_title", "version_number", "user", "created_at")
    list_filter = ("content_item__module__course__tenant", "user")
    search_fields = ("content_item__title", "comment", "user__email")
    list_select_related = ("content_item", "user")
    readonly_fields = (
        "content_item",
        "user",
        "version_number",
        "created_at",
        "updated_at",
        "content_type",
        "text_content",
        "external_url",
        "metadata",
    )  # Make versions read-only in admin

    def content_item_title(self, obj):
        return obj.content_item.title

    content_item_title.short_description = "Content Item"
    content_item_title.admin_order_field = "content_item__title"
