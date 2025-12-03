from django.contrib import admin

from .models import Certificate, Enrollment, GroupEnrollment, LearnerProgress


class LearnerProgressInline(admin.TabularInline):
    model = LearnerProgress
    extra = 0
    readonly_fields = (
        "content_item",
        "status",
        "started_at",
        "completed_at",
        "progress_details",
    )
    can_delete = False
    show_change_link = True


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "course",
        "status",
        "enrolled_at",
        "completed_at",
        "expires_at",
    )
    list_filter = ("status", "course__tenant", "course")
    search_fields = ("user__email", "course__title")
    list_select_related = ("user", "course", "course__tenant")
    readonly_fields = ("enrolled_at", "completed_at")  # Status managed by services
    inlines = [LearnerProgressInline]


@admin.register(GroupEnrollment)
class GroupEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("group", "course", "enrolled_at")
    list_filter = ("group__tenant", "course")
    search_fields = ("group__name", "course__title")
    list_select_related = ("group", "course", "group__tenant")
    readonly_fields = ("enrolled_at",)


@admin.register(LearnerProgress)
class LearnerProgressAdmin(admin.ModelAdmin):
    list_display = (
        "user_email",
        "content_item_title",
        "course_title",
        "status",
        "completed_at",
    )
    list_filter = (
        "status",
        "enrollment__course__tenant",
        "enrollment__course",
        "content_item__content_type",
    )
    search_fields = (
        "enrollment__user__email",
        "content_item__title",
        "enrollment__course__title",
    )
    list_select_related = ("enrollment__user", "enrollment__course", "content_item")
    readonly_fields = (
        "enrollment",
        "content_item",
        "started_at",
        "completed_at",
        "progress_details",
    )  # Progress managed by system

    def user_email(self, obj):
        return obj.enrollment.user.email

    user_email.admin_order_field = "enrollment__user__email"

    def content_item_title(self, obj):
        return obj.content_item.title

    content_item_title.admin_order_field = "content_item__title"

    def course_title(self, obj):
        return obj.enrollment.course.title

    course_title.admin_order_field = "enrollment__course__title"


@admin.register(Certificate)
class CertificateAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "issued_at", "verification_code")
    list_filter = ("course__tenant", "course")
    search_fields = ("user__email", "course__title", "verification_code")
    list_select_related = ("user", "course", "enrollment", "course__tenant")
    readonly_fields = (
        "enrollment",
        "user",
        "course",
        "issued_at",
        "verification_code",
    )  # Certificates are immutable once issued
