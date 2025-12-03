from django.contrib import admin

from .models import File, FileVersion, Folder


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "parent", "created_at")
    list_filter = ("tenant", "parent")
    search_fields = ("name", "tenant__name")
    list_select_related = ("tenant", "parent")


@admin.register(File)
class FileAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "tenant",
        "folder",
        "uploaded_by",
        "status",
        "mime_type",
        "file_size_display",
        "created_at",
    )
    list_filter = ("status", "mime_type", "tenant", "folder")
    search_fields = (
        "original_filename",
        "file",
        "tenant__name",
        "uploaded_by__email",
        "folder__name",
    )
    list_select_related = ("tenant", "folder", "uploaded_by")
    readonly_fields = (
        "file_size",
        "mime_type",
        "metadata",
        "scan_result",
        "scan_details",
        "scan_completed_at",
        "created_at",
        "updated_at",
        "id",
    )
    fields = (
        "tenant",
        "folder",
        "uploaded_by",
        "file",
        "original_filename",
        "status",
        "error_message",
        "file_size",
        "mime_type",
        "metadata",
        "scan_result",
        "scan_details",
        "scan_completed_at",
        "id",
        "created_at",
        "updated_at",
    )

    def file_size_display(self, obj):
        if obj.file_size is None:
            return "N/A"
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        elif obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        elif obj.file_size < 1024 * 1024 * 1024:
            return f"{obj.file_size / (1024 * 1024):.1f} MB"
        else:
            return f"{obj.file_size / (1024 * 1024 * 1024):.1f} GB"

    file_size_display.short_description = "Size"


@admin.register(FileVersion)
class FileVersionAdmin(admin.ModelAdmin):
    list_display = ("file_instance_name", "version_number", "user", "created_at")
    list_filter = ("file_instance__tenant", "user")
    search_fields = ("file_instance__original_filename", "user__email", "comment")
    list_select_related = ("file_instance", "user", "file_instance__tenant")
    readonly_fields = (
        "file_instance",
        "storage_path",
        "version_number",
        "user",
        "comment",
        "file_size",
        "mime_type",
        "created_at",
        "updated_at",
    )

    def file_instance_name(self, obj):
        return obj.file_instance.original_filename

    file_instance_name.short_description = "File"
    file_instance_name.admin_order_field = "file_instance__original_filename"
