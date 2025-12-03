from django.contrib import admin

from .models import Notification, NotificationPreference


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "recipient",
        "notification_type",
        "status",
        "subject_snippet",
        "created_at",
        "sent_at",
    )
    list_filter = (
        "status",
        "notification_type",
        "recipient__tenant",
    )  # Add tenant filter if model linked
    search_fields = ("recipient__email", "subject", "message")
    list_select_related = ("recipient",)  # 'recipient__tenant'
    readonly_fields = (
        "created_at",
        "updated_at",
        "sent_at",
        "read_at",
        "fail_reason",
        "delivery_methods",
    )
    # Add action to retry sending failed notifications?

    def subject_snippet(self, obj):
        return (
            obj.subject[:50] + "..."
            if obj.subject and len(obj.subject) > 50
            else obj.subject
        )

    subject_snippet.short_description = "Subject"


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "is_enabled", "updated_at")
    search_fields = ("user__email",)
    list_select_related = ("user",)
    # Use django-jsoneditor or similar for better editing of the preferences JSON field
