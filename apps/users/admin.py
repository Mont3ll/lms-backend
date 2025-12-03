from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import GroupMembership, LearnerGroup, User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fk_name = "user"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # Use email as the primary identifier in admin
    list_display = (
        "email",
        "first_name",
        "last_name",
        "role",
        "status",
        "tenant",
        "is_staff",
        "is_active",
        "last_login",
    )
    list_filter = (
        "role",
        "status",
        "is_staff",
        "is_superuser",
        "is_active",
        "groups",
        "tenant",
    )
    search_fields = ("email", "first_name", "last_name", "tenant__name")
    ordering = ("email",)

    # Define fieldsets for the admin form
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "tenant")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("LMS Specific", {"fields": ("role", "status")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        # ('SSO/LTI Info', {'fields': ('lti_user_id', 'sso_provider', 'sso_subject_id'), 'classes': ('collapse',)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password",
                    "password2",
                    "first_name",
                    "last_name",
                    "tenant",
                    "role",
                    "status",
                ),
            },
        ),
    )

    # Use the custom User model's manager
    model = User
    # No username field
    readonly_fields = ("last_login", "date_joined")
    # Inline the profile model
    inlines = (UserProfileInline,)

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super().get_inline_instances(request, obj)


class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 1
    autocomplete_fields = ["user"]  # Assumes user search is enabled


@admin.register(LearnerGroup)
class LearnerGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "member_count", "created_at")
    list_filter = ("tenant",)
    search_fields = ("name", "description", "tenant__name")
    inlines = [GroupMembershipInline]
    list_select_related = ("tenant",)

    def member_count(self, obj):
        return obj.members.count()

    member_count.short_description = "Members"


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "group", "date_joined")
    list_filter = ("group__tenant", "group")
    search_fields = ("user__email", "group__name")
    autocomplete_fields = ["user", "group"]  # Assumes search fields are set up
