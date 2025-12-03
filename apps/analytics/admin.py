from django.contrib import admin

from .models import Dashboard, Event, Report


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "user_email", "tenant_name", "created_at")
    list_filter = ("event_type", "tenant", "created_at")
    search_fields = (
        "event_type",
        "user__email",
        "tenant__name",
        "context_data",
    )  # Searching JSON might be limited/slow
    list_select_related = ("user", "tenant")
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "tenant",
        "user",
        "event_type",
        "context_data",
        "session_id",
        "ip_address",
    )
    date_hierarchy = "created_at"

    def user_email(self, obj):
        return obj.user.email if obj.user else "N/A"

    user_email.short_description = "User"
    user_email.admin_order_field = "user__email"

    def tenant_name(self, obj):
        return obj.tenant.name if obj.tenant else "System"

    tenant_name.short_description = "Tenant"
    tenant_name.admin_order_field = "tenant__name"


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "tenant", "description_snippet")
    list_filter = ("tenant",)
    search_fields = ("name", "slug", "description", "tenant__name")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("tenant",)
    # Use django-jsoneditor or similar for config field

    def description_snippet(self, obj):
        return (
            obj.description[:50] + "..."
            if obj.description and len(obj.description) > 50
            else obj.description
        )

    description_snippet.short_description = "Description"


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "tenant", "description_snippet")
    list_filter = ("tenant",)
    search_fields = ("name", "slug", "description", "tenant__name")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("tenant",)
    # Use django-jsoneditor or similar for layout_config field

    def description_snippet(self, obj):
        return (
            obj.description[:50] + "..."
            if obj.description and len(obj.description) > 50
            else obj.description
        )

    description_snippet.short_description = "Description"
