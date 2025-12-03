from rest_framework import serializers

from apps.users.serializers import UserSerializer  # For user/graded_by info

from .models import Assessment, AssessmentAttempt, Question

# from apps.courses.serializers import CourseSerializer # If needed for nested course info


class QuestionSerializer(serializers.ModelSerializer):
    question_type_display = serializers.CharField(
        source="get_question_type_display", read_only=True
    )

    class Meta:
        model = Question
        fields = (
            "id",
            "assessment",
            "order",
            "question_type",
            "question_type_display",
            "question_text",
            "points",
            "type_specific_data",
            "feedback",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "assessment",
            "created_at",
            "updated_at",
            "question_type_display",
        )
        # Type-specific data might need custom validation based on question_type

    # Example validation (needs refinement based on actual JSON structure)
    def validate_type_specific_data(self, data):
        q_type = self.initial_data.get("question_type")  # Get type from incoming data
        # Add validation rules based on q_type
        if q_type == Question.QuestionType.MULTIPLE_CHOICE:
            if not isinstance(data.get("options"), list):
                raise serializers.ValidationError(
                    "MC questions require a list of 'options'."
                )
            has_correct = any(opt.get("is_correct") for opt in data["options"])
            if not has_correct:
                raise serializers.ValidationError(
                    "MC questions must have at least one correct option."
                )
        # Add more validation for other types...
        return data


class AssessmentSerializer(serializers.ModelSerializer):
    # Nested questions for read operations (e.g., when starting an attempt)
    questions = QuestionSerializer(many=True, read_only=True)
    assessment_type_display = serializers.CharField(
        source="get_assessment_type_display", read_only=True
    )
    grading_type_display = serializers.CharField(
        source="get_grading_type_display", read_only=True
    )
    course_title = serializers.CharField(source="course.title", read_only=True)
    total_points = serializers.IntegerField(
        read_only=True
    )  # Include calculated total points
    attempts_count = serializers.SerializerMethodField()

    def get_attempts_count(self, obj):
        """Get the total number of attempts for this assessment"""
        return obj.attempts.count()

    class Meta:
        model = Assessment
        fields = (
            "id",
            "course",
            "course_title",
            "title",
            "description",
            "assessment_type",
            "assessment_type_display",
            "grading_type",
            "grading_type_display",
            "due_date",
            "time_limit_minutes",
            "max_attempts",
            "pass_mark_percentage",
            "show_results_immediately",
            "shuffle_questions",
            "is_published",
            "total_points",
            "attempts_count",
            "questions",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "course_title",
            "total_points",
            "attempts_count",
            "questions",
            "created_at",
            "updated_at",
            "assessment_type_display",
            "grading_type_display",
        )


# --- Assessment Attempt Serializers ---


class AssessmentAttemptSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    assessment_title = serializers.CharField(source="assessment.title", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    graded_by_email = serializers.EmailField(
        source="graded_by.email", read_only=True, allow_null=True
    )

    class Meta:
        model = AssessmentAttempt
        fields = (
            "id",
            "assessment",
            "assessment_title",
            "user",
            "start_time",
            "end_time",
            "status",
            "status_display",
            "answers",
            "score",
            "max_score",
            "is_passed",
            "graded_by_email",
            "graded_at",
            "feedback",
            "created_at",
        )
        read_only_fields = (
            "id",
            "assessment",
            "assessment_title",
            "user",
            "start_time",
            "end_time",
            "status",
            "status_display",
            "score",
            "max_score",
            "is_passed",
            "graded_by_email",
            "graded_at",
            "created_at",
        )
        # Answers field is writable only via a specific submission endpoint/action


class AssessmentAttemptStartSerializer(serializers.ModelSerializer):
    """Serializer for response when starting an attempt"""

    assessment = AssessmentSerializer(read_only=True)  # Include full assessment details

    class Meta:
        model = AssessmentAttempt
        fields = (
            "id",
            "assessment",
            "start_time",
            "status",
        )  # Only return essential info


class AssessmentAttemptSubmitSerializer(serializers.Serializer):
    """Serializer for submitting answers"""

    answers = serializers.JSONField(
        required=True
    )  # Expects {'question_id': answer_data}

    def validate_answers(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "Answers must be a dictionary mapping question IDs to answer data."
            )
        # Add more specific validation based on question types if needed
        return value

    def save(self, attempt: AssessmentAttempt, **kwargs):
        """Submits the attempt"""
        submitted = attempt.submit(self.validated_data["answers"])
        if not submitted:
            raise serializers.ValidationError(
                "Attempt could not be submitted (e.g., already submitted or invalid status)."
            )
        return attempt
