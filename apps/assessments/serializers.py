import re

from rest_framework import serializers

from apps.users.serializers import UserSerializer  # For user/graded_by info

from .models import Assessment, AssessmentAttempt, Question

# from apps.courses.serializers import CourseSerializer # If needed for nested course info


class QuestionSkillSerializer(serializers.Serializer):
    """Lightweight serializer for skills embedded in question responses."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    slug = serializers.CharField()
    category = serializers.CharField()
    weight = serializers.IntegerField()
    proficiency_required = serializers.CharField()


class QuestionSerializer(serializers.ModelSerializer):
    question_type_display = serializers.CharField(
        source="get_question_type_display", read_only=True
    )
    skills = serializers.SerializerMethodField()

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
            "skills",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "assessment",
            "created_at",
            "updated_at",
            "question_type_display",
            "skills",
        )

    def get_skills(self, obj):
        """Get skills associated with this question via AssessmentSkillMapping."""
        from apps.skills.models import AssessmentSkillMapping
        
        mappings = AssessmentSkillMapping.objects.filter(
            question=obj
        ).select_related('skill')
        
        return [
            {
                'id': str(mapping.skill.id),
                'name': mapping.skill.name,
                'slug': mapping.skill.slug,
                'category': mapping.skill.category,
                'weight': mapping.weight,
                'proficiency_required': mapping.proficiency_required,
            }
            for mapping in mappings
        ]
        # Type-specific data might need custom validation based on question_type

    def validate_type_specific_data(self, data):
        """
        Validate type_specific_data JSON field based on question type.
        
        Expected schemas per question type:
        - MC/TF: {'options': [{'id': 'uuid', 'text': 'Option A', 'is_correct': True}, ...], 'allow_multiple': False}
        - SA: {'correct_answers': ['answer1', 'answer2'], 'case_sensitive': False}
        - MT: {'prompts': [{'id': 'p1', 'text': 'Prompt 1'}], 'matches': [{'id': 'm1', 'text': 'Match 1'}], 'correct_pairs': [{'prompt_id': 'p1', 'match_id': 'm1'}]}
        - ES: {} (no specific data required)
        - CODE: {} or {'language': 'python'}
        - FB: {'text': 'The capital of France is [blank1].', 'blanks': {'blank1': {'correct': ['Paris']}}}
        """
        q_type = self.initial_data.get("question_type")
        
        if q_type == Question.QuestionType.MULTIPLE_CHOICE:
            self._validate_multiple_choice(data)
        elif q_type == Question.QuestionType.TRUE_FALSE:
            self._validate_true_false(data)
        elif q_type == Question.QuestionType.SHORT_ANSWER:
            self._validate_short_answer(data)
        elif q_type == Question.QuestionType.ESSAY:
            self._validate_essay(data)
        elif q_type == Question.QuestionType.CODE:
            self._validate_code(data)
        elif q_type == Question.QuestionType.MATCHING:
            self._validate_matching(data)
        elif q_type == Question.QuestionType.FILL_BLANKS:
            self._validate_fill_blanks(data)
        
        return data

    def _validate_multiple_choice(self, data):
        """Validate Multiple Choice question data."""
        options = data.get("options")
        if not isinstance(options, list):
            raise serializers.ValidationError(
                "MC questions require a list of 'options'."
            )
        if len(options) < 2:
            raise serializers.ValidationError(
                "MC questions require at least 2 options."
            )
        
        for i, opt in enumerate(options):
            if not isinstance(opt, dict):
                raise serializers.ValidationError(
                    f"Option {i + 1} must be an object."
                )
            if not opt.get("text"):
                raise serializers.ValidationError(
                    f"Option {i + 1} must have a 'text' field."
                )
            if "is_correct" not in opt:
                raise serializers.ValidationError(
                    f"Option {i + 1} must have an 'is_correct' field."
                )
        
        has_correct = any(opt.get("is_correct") for opt in options)
        if not has_correct:
            raise serializers.ValidationError(
                "MC questions must have at least one correct option."
            )

    def _validate_true_false(self, data):
        """Validate True/False question data."""
        options = data.get("options")
        if not isinstance(options, list):
            raise serializers.ValidationError(
                "TF questions require a list of 'options'."
            )
        if len(options) != 2:
            raise serializers.ValidationError(
                "TF questions must have exactly 2 options (True and False)."
            )
        
        has_correct = any(opt.get("is_correct") for opt in options)
        if not has_correct:
            raise serializers.ValidationError(
                "TF questions must have exactly one correct option."
            )
        
        correct_count = sum(1 for opt in options if opt.get("is_correct"))
        if correct_count != 1:
            raise serializers.ValidationError(
                "TF questions must have exactly one correct option."
            )

    def _validate_short_answer(self, data):
        """Validate Short Answer question data."""
        correct_answers = data.get("correct_answers")
        if not isinstance(correct_answers, list):
            raise serializers.ValidationError(
                "SA questions require a list of 'correct_answers'."
            )
        if len(correct_answers) == 0:
            raise serializers.ValidationError(
                "SA questions require at least one correct answer."
            )
        for i, answer in enumerate(correct_answers):
            if not isinstance(answer, str) or not answer.strip():
                raise serializers.ValidationError(
                    f"Correct answer {i + 1} must be a non-empty string."
                )

    def _validate_essay(self, data):
        """Validate Essay question data. Essays have no specific data requirements."""
        # Essays are manually graded and don't require specific data
        pass

    def _validate_code(self, data):
        """Validate Code question data."""
        # Code questions may optionally specify a language
        language = data.get("language")
        if language is not None and not isinstance(language, str):
            raise serializers.ValidationError(
                "CODE questions 'language' field must be a string if provided."
            )

    def _validate_matching(self, data):
        """Validate Matching question data."""
        prompts = data.get("prompts")
        matches = data.get("matches")
        correct_pairs = data.get("correct_pairs")
        
        if not isinstance(prompts, list):
            raise serializers.ValidationError(
                "MT questions require a list of 'prompts'."
            )
        if not isinstance(matches, list):
            raise serializers.ValidationError(
                "MT questions require a list of 'matches'."
            )
        if not isinstance(correct_pairs, list):
            raise serializers.ValidationError(
                "MT questions require a list of 'correct_pairs'."
            )
        
        if len(prompts) < 2:
            raise serializers.ValidationError(
                "MT questions require at least 2 prompts."
            )
        if len(matches) < 2:
            raise serializers.ValidationError(
                "MT questions require at least 2 matches."
            )
        
        # Validate prompts structure
        prompt_ids = set()
        for i, prompt in enumerate(prompts):
            if not isinstance(prompt, dict):
                raise serializers.ValidationError(
                    f"Prompt {i + 1} must be an object."
                )
            if not prompt.get("id"):
                raise serializers.ValidationError(
                    f"Prompt {i + 1} must have an 'id' field."
                )
            if not prompt.get("text"):
                raise serializers.ValidationError(
                    f"Prompt {i + 1} must have a 'text' field."
                )
            prompt_ids.add(prompt["id"])
        
        # Validate matches structure
        match_ids = set()
        for i, match in enumerate(matches):
            if not isinstance(match, dict):
                raise serializers.ValidationError(
                    f"Match {i + 1} must be an object."
                )
            if not match.get("id"):
                raise serializers.ValidationError(
                    f"Match {i + 1} must have an 'id' field."
                )
            if not match.get("text"):
                raise serializers.ValidationError(
                    f"Match {i + 1} must have a 'text' field."
                )
            match_ids.add(match["id"])
        
        # Validate correct_pairs reference valid prompts and matches
        if len(correct_pairs) == 0:
            raise serializers.ValidationError(
                "MT questions require at least one correct pair."
            )
        
        for i, pair in enumerate(correct_pairs):
            if not isinstance(pair, dict):
                raise serializers.ValidationError(
                    f"Correct pair {i + 1} must be an object."
                )
            if pair.get("prompt_id") not in prompt_ids:
                raise serializers.ValidationError(
                    f"Correct pair {i + 1} references invalid prompt_id."
                )
            if pair.get("match_id") not in match_ids:
                raise serializers.ValidationError(
                    f"Correct pair {i + 1} references invalid match_id."
                )

    def _validate_fill_blanks(self, data):
        """Validate Fill in the Blanks question data."""
        text = data.get("text")
        blanks = data.get("blanks")
        
        if not isinstance(text, str) or not text.strip():
            raise serializers.ValidationError(
                "FB questions require a 'text' field with the question text."
            )
        if not isinstance(blanks, dict):
            raise serializers.ValidationError(
                "FB questions require a 'blanks' object mapping blank IDs to correct answers."
            )
        if len(blanks) == 0:
            raise serializers.ValidationError(
                "FB questions require at least one blank."
            )
        
        # Check that blanks referenced in text exist in blanks dict
        blank_refs = re.findall(r'\[([^\]]+)\]', text)
        if len(blank_refs) == 0:
            raise serializers.ValidationError(
                "FB questions text must contain at least one blank reference in [blank_id] format."
            )
        
        for blank_ref in blank_refs:
            if blank_ref not in blanks:
                raise serializers.ValidationError(
                    f"Blank reference '[{blank_ref}]' in text has no corresponding entry in 'blanks' object."
                )
        
        # Validate each blank has correct answers
        for blank_id, blank_data in blanks.items():
            if not isinstance(blank_data, dict):
                raise serializers.ValidationError(
                    f"Blank '{blank_id}' data must be an object."
                )
            correct = blank_data.get("correct")
            if not isinstance(correct, list) or len(correct) == 0:
                raise serializers.ValidationError(
                    f"Blank '{blank_id}' must have a 'correct' list with at least one answer."
                )
            for i, answer in enumerate(correct):
                if not isinstance(answer, str) or not answer.strip():
                    raise serializers.ValidationError(
                        f"Blank '{blank_id}' correct answer {i + 1} must be a non-empty string."
                    )


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
    course_slug = serializers.CharField(source="course.slug", read_only=True)
    total_points = serializers.IntegerField(
        read_only=True
    )  # Include calculated total points
    attempts_count = serializers.SerializerMethodField()
    
    # User-specific attempt summary fields
    user_attempts_count = serializers.SerializerMethodField()
    user_best_score = serializers.SerializerMethodField()
    user_best_percentage = serializers.SerializerMethodField()
    user_has_passed = serializers.SerializerMethodField()
    user_latest_attempt_status = serializers.SerializerMethodField()
    user_attempts_remaining = serializers.SerializerMethodField()

    def get_attempts_count(self, obj):
        """Get the total number of attempts for this assessment"""
        return obj.attempts.count()

    def _get_user_attempts(self, obj):
        """Helper to get current user's attempts for this assessment"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return AssessmentAttempt.objects.none()
        return obj.attempts.filter(user=request.user)

    def get_user_attempts_count(self, obj):
        """Get number of attempts by the current user"""
        return self._get_user_attempts(obj).count()

    def get_user_best_score(self, obj):
        """Get the best score achieved by the current user"""
        attempts = self._get_user_attempts(obj).filter(
            status__in=[AssessmentAttempt.AttemptStatus.SUBMITTED, AssessmentAttempt.AttemptStatus.GRADED],
            score__isnull=False
        )
        if not attempts.exists():
            return None
        return float(attempts.order_by('-score').first().score)

    def get_user_best_percentage(self, obj):
        """Get the best percentage score achieved by the current user"""
        attempts = self._get_user_attempts(obj).filter(
            status__in=[AssessmentAttempt.AttemptStatus.SUBMITTED, AssessmentAttempt.AttemptStatus.GRADED],
            score__isnull=False,
            max_score__isnull=False
        ).exclude(max_score=0)
        if not attempts.exists():
            return None
        best = attempts.order_by('-score').first()
        return round((float(best.score) / float(best.max_score)) * 100, 1)

    def get_user_has_passed(self, obj):
        """Check if the current user has passed this assessment"""
        return self._get_user_attempts(obj).filter(is_passed=True).exists()

    def get_user_latest_attempt_status(self, obj):
        """Get the status of the user's most recent attempt"""
        latest = self._get_user_attempts(obj).order_by('-start_time').first()
        if not latest:
            return None
        return latest.status

    def get_user_attempts_remaining(self, obj):
        """Get remaining attempts for the current user"""
        user_count = self._get_user_attempts(obj).exclude(
            status=AssessmentAttempt.AttemptStatus.IN_PROGRESS
        ).count()
        return max(0, obj.max_attempts - user_count)

    class Meta:
        model = Assessment
        fields = (
            "id",
            "course",
            "course_title",
            "course_slug",
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
            "user_attempts_count",
            "user_best_score",
            "user_best_percentage",
            "user_has_passed",
            "user_latest_attempt_status",
            "user_attempts_remaining",
            "questions",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "course_title",
            "course_slug",
            "total_points",
            "attempts_count",
            "user_attempts_count",
            "user_best_score",
            "user_best_percentage",
            "user_has_passed",
            "user_latest_attempt_status",
            "user_attempts_remaining",
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
    attempt_id = serializers.UUIDField(source='id', read_only=True)  # Alias for frontend compatibility
    time_limit_minutes = serializers.IntegerField(source='assessment.time_limit_minutes', read_only=True)

    class Meta:
        model = AssessmentAttempt
        fields = (
            "id",
            "attempt_id",
            "assessment",
            "start_time",
            "time_limit_minutes",
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


class ManualGradeSerializer(serializers.Serializer):
    """Serializer for manual grading of assessment attempts."""

    score = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=True,
        help_text="Total score for the attempt",
    )
    feedback = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Overall feedback for the learner",
    )
    question_scores = serializers.JSONField(
        required=False,
        help_text="Optional per-question scores: {'question_id': score}",
    )

    def validate_score(self, value):
        if value < 0:
            raise serializers.ValidationError("Score cannot be negative.")
        return value

    def validate_question_scores(self, value):
        if value is not None and not isinstance(value, dict):
            raise serializers.ValidationError(
                "question_scores must be a dictionary mapping question IDs to scores."
            )
        if value:
            for q_id, q_score in value.items():
                if not isinstance(q_score, (int, float)):
                    raise serializers.ValidationError(
                        f"Score for question {q_id} must be a number."
                    )
                if q_score < 0:
                    raise serializers.ValidationError(
                        f"Score for question {q_id} cannot be negative."
                    )
        return value

    def validate(self, attrs):
        """Validate that score doesn't exceed max_score if attempt is available."""
        attempt = self.context.get("attempt")
        if attempt and attempt.max_score:
            if attrs["score"] > attempt.max_score:
                raise serializers.ValidationError(
                    {
                        "score": f"Score cannot exceed maximum score of {attempt.max_score}."
                    }
                )
        return attrs
