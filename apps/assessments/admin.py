from django.contrib import admin

from .models import Assessment, AssessmentAttempt, Question


class QuestionInline(admin.StackedInline):  # Or TabularInline
    model = Question
    extra = 1
    ordering = ("order",)
    fields = (
        "order",
        "question_type",
        "question_text",
        "points",
        "type_specific_data",
        "feedback",
    )
    # Consider using django-jsoneditor for easier editing of type_specific_data
    # or custom widgets based on question_type


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "course",
        "assessment_type",
        "grading_type",
        "is_published",
        "due_date",
        "total_points_display",
        "question_count",
    )
    list_filter = (
        "assessment_type",
        "grading_type",
        "is_published",
        "course__tenant",
        "course",
    )
    search_fields = ("title", "description", "course__title")
    list_select_related = ("course", "course__tenant")
    inlines = [QuestionInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "course",
                    "title",
                    "description",
                    "assessment_type",
                    "grading_type",
                    "is_published",
                )
            },
        ),
        (
            "Settings",
            {
                "fields": (
                    "due_date",
                    "time_limit_minutes",
                    "max_attempts",
                    "pass_mark_percentage",
                    "show_results_immediately",
                    "shuffle_questions",
                )
            },
        ),
    )

    def question_count(self, obj):
        return obj.questions.count()

    question_count.short_description = "Questions"

    def total_points_display(self, obj):
        return obj.total_points

    total_points_display.short_description = "Total Points"


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "assessment", "order", "points")
    list_filter = ("question_type", "assessment__course__tenant", "assessment")
    search_fields = ("question_text", "assessment__title")
    list_select_related = ("assessment", "assessment__course")
    # Customize form based on question_type using fieldsets or custom forms if needed
    fields = (
        "assessment",
        "order",
        "question_type",
        "question_text",
        "points",
        "type_specific_data",
        "feedback",
    )


@admin.register(AssessmentAttempt)
class AssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "assessment",
        "status",
        "start_time",
        "end_time",
        "score",
        "is_passed",
    )
    list_filter = ("status", "is_passed", "assessment__course__tenant", "assessment")
    search_fields = ("user__email", "assessment__title")
    list_select_related = ("assessment", "user", "graded_by", "assessment__course")
    readonly_fields = (
        "start_time",
        "end_time",
        "answers",
        "score",
        "max_score",
        "is_passed",
        "graded_at",
        "graded_by",
    )  # Make results read-only for basic admin
    # Add actions for re-grading or manual grading trigger if needed
    fieldsets = (
        (None, {"fields": ("assessment", "user", "status")}),
        ("Timing", {"fields": ("start_time", "end_time")}),
        # ('Submitted Answers', {'fields': ('answers',), 'classes': ('collapse',)}), # Show raw answers if needed
        (
            "Grading",
            {
                "fields": (
                    "score",
                    "max_score",
                    "is_passed",
                    "feedback",
                    "graded_by",
                    "graded_at",
                )
            },
        ),
    )
