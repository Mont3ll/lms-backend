import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimestampedModel
from apps.courses.models import Course, Module  # Link assessments to courses/modules
from apps.users.models import User


class Assessment(TimestampedModel):
    """Represents an assessment (quiz, exam, assignment) within a course."""

    class AssessmentType(models.TextChoices):
        QUIZ = "QUIZ", _("Quiz")
        EXAM = "EXAM", _("Exam")
        ASSIGNMENT = "ASSIGNMENT", _("Assignment")  # E.g., essay or file submission

    class GradingType(models.TextChoices):
        AUTO = "AUTO", _("Automatic")  # Graded automatically based on answers
        MANUAL = "MANUAL", _("Manual")  # Requires instructor grading
        HYBRID = "HYBRID", _("Hybrid")  # Mix of auto and manual questions

    # Link to Course or Module (choose one or allow both?)
    # Linking to Course allows standalone assessments for the course.
    # Linking to Module integrates it within the course flow via ContentItem.
    course = models.ForeignKey(
        Course, related_name="assessments", on_delete=models.CASCADE
    )
    # module = models.ForeignKey(Module, related_name='assessments', on_delete=models.CASCADE, null=True, blank=True) # Optional module link

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    assessment_type = models.CharField(
        max_length=20, choices=AssessmentType.choices, default=AssessmentType.QUIZ
    )
    grading_type = models.CharField(
        max_length=10, choices=GradingType.choices, default=GradingType.AUTO
    )

    # Settings
    due_date = models.DateTimeField(null=True, blank=True, db_index=True)
    time_limit_minutes = models.PositiveIntegerField(
        null=True, blank=True, help_text="Time limit in minutes. Blank for no limit."
    )
    max_attempts = models.PositiveIntegerField(
        default=1, help_text="Maximum number of attempts allowed. 0 for unlimited."
    )
    pass_mark_percentage = models.PositiveIntegerField(
        default=50,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Minimum percentage score required to pass.",
    )
    show_results_immediately = models.BooleanField(
        default=True, help_text="Show score/feedback immediately after submission"
    )
    shuffle_questions = models.BooleanField(
        default=False, help_text="Randomize question order for each attempt"
    )
    is_published = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.title} ({self.course.title})"

    @property
    def total_points(self):
        """Calculates the total possible points for the assessment."""
        return sum(q.points for q in self.questions.all() if q.points)

    class Meta:
        ordering = ["course", "title"]


class Question(TimestampedModel):
    """Represents a question within an Assessment."""

    class QuestionType(models.TextChoices):
        MULTIPLE_CHOICE = "MC", _(
            "Multiple Choice"
        )  # Single or multiple correct answers
        TRUE_FALSE = "TF", _("True/False")
        SHORT_ANSWER = "SA", _(
            "Short Answer"
        )  # Auto-gradable simple text match (use with caution)
        ESSAY = "ES", _("Essay")  # Manually graded
        CODE = "CODE", _("Code Submission")  # Manually graded or external auto-grader
        MATCHING = "MT", _("Matching")  # Manually or potentially auto-graded
        FILL_BLANKS = "FB", _("Fill in the Blanks")
        # Add more types as needed: Ordering, File Upload

    assessment = models.ForeignKey(
        Assessment, related_name="questions", on_delete=models.CASCADE
    )
    question_text = models.TextField()
    question_type = models.CharField(max_length=10, choices=QuestionType.choices)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Order of the question within the assessment (if not shuffled)",
    )
    points = models.PositiveIntegerField(
        default=1, help_text="Points awarded for a correct answer"
    )

    # Data for specific question types stored in JSON
    # Example structure:
    # MC/TF: {'options': [{'id': 'uuid', 'text': 'Option A', 'is_correct': True}, ...], 'allow_multiple': False}
    # SA: {'correct_answers': ['answer1', 'answer2'], 'case_sensitive': False}
    # MT: {'prompts': [{'id': 'p1', 'text': 'Prompt 1'}], 'matches': [{'id': 'm1', 'text': 'Match 1'}], 'correct_pairs': [{'prompt_id': 'p1', 'match_id': 'm1'}]}
    # ES/CODE: {} or {'language': 'python'} for CODE
    # FB: {'text': 'The capital of France is [blank1]. Paris is known for the [blank2].', 'blanks': {'blank1': {'correct': ['Paris']}, 'blank2': {'correct': ['Eiffel Tower']}}}
    type_specific_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Data specific to the question type (options, answers, etc.)",
    )

    feedback = models.TextField(
        blank=True, help_text="General feedback displayed after answering (optional)"
    )

    def __str__(self):
        return f"{self.question_type}: {self.question_text[:50]}... (Assessment: {self.assessment.title})"

    class Meta:
        ordering = ["assessment", "order"]


class AssessmentAttempt(TimestampedModel):
    """Records a user's attempt at an Assessment."""

    class AttemptStatus(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", _("In Progress")
        SUBMITTED = "SUBMITTED", _("Submitted")
        GRADED = "GRADED", _("Graded")

    assessment = models.ForeignKey(
        Assessment, related_name="attempts", on_delete=models.CASCADE
    )
    user = models.ForeignKey(
        User, related_name="assessment_attempts", on_delete=models.CASCADE
    )
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=AttemptStatus.choices,
        default=AttemptStatus.IN_PROGRESS,
        db_index=True,
    )

    # Store raw answers submitted by the user
    # Structure: { 'question_id_uuid': answer_data, ... }
    # answer_data format depends on question type:
    # MC/TF: ['selected_option_id_uuid'] or ['opt1_uuid', 'opt2_uuid'] for multiple correct
    # SA/ES/CODE/FB: 'user submitted text' or {'blank1': 'text1', 'blank2': 'text2'} for FB
    # MT: [{'prompt_id': 'p1', 'selected_match_id': 'm1'}, ...]
    answers = models.JSONField(default=dict, blank=True)

    # Grading results
    score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Calculated score for the attempt",
    )
    max_score = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total possible points at time of attempt"
    )
    is_passed = models.BooleanField(
        null=True, blank=True, help_text="Whether the attempt met the pass mark"
    )
    graded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )  # User who manually graded
    graded_at = models.DateTimeField(null=True, blank=True)
    feedback = models.TextField(
        blank=True, help_text="Overall feedback for the attempt (from instructor)"
    )

    def __str__(self):
        return f"Attempt by {self.user.email} on {self.assessment.title} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"

    def calculate_duration(self):
        """Calculates the duration of the attempt in seconds."""
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        elif self.status == self.AttemptStatus.IN_PROGRESS:
            # Calculate time elapsed so far
            return (timezone.now() - self.start_time).total_seconds()
        return None

    def submit(self, submitted_answers: dict):
        """Marks the attempt as submitted and saves answers."""
        if self.status == self.AttemptStatus.IN_PROGRESS:
            self.answers = submitted_answers
            self.end_time = timezone.now()
            self.status = self.AttemptStatus.SUBMITTED
            # Calculate max score at time of submission
            self.max_score = self.assessment.total_points
            self.save()
            # Trigger auto-grading if applicable
            from .services import GradingService  # Avoid circular import

            GradingService.grade_attempt(self)
            return True
        return False  # Already submitted or graded

    class Meta:
        ordering = ["assessment", "user", "-start_time"]
        # Potentially add constraint for number of attempts per user per assessment
