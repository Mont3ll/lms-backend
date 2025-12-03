import logging
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from .models import AssessmentAttempt, Question

logger = logging.getLogger(__name__)


class GradingServiceError(Exception):
    pass


class GradingService:
    """Handles the logic for grading assessment attempts."""

    @classmethod
    def grade_attempt(cls, attempt: AssessmentAttempt):
        """
        Grades a submitted assessment attempt.
        Handles auto-gradable questions. Sets status to GRADED if fully auto-graded,
        or leaves as SUBMITTED if manual grading is required.
        """
        if attempt.status != AssessmentAttempt.AttemptStatus.SUBMITTED:
            logger.warning(
                f"Attempt {attempt.id} cannot be graded in status {attempt.status}"
            )
            return

        assessment = attempt.assessment
        questions = Question.objects.filter(assessment=assessment)
        submitted_answers = attempt.answers or {}

        total_score = Decimal(0)
        max_score = Decimal(
            assessment.total_points or 0
        )  # Use points at time of attempt? Or current? Using current for now.
        requires_manual_grading = False

        if assessment.grading_type == assessment.GradingType.MANUAL:
            requires_manual_grading = True
        else:  # AUTO or HYBRID
            for question in questions:
                question_id_str = str(question.id)
                user_answer = submitted_answers.get(question_id_str)
                question_score = Decimal(0)

                try:
                    if question.question_type in [
                        Question.QuestionType.ESSAY,
                        Question.QuestionType.CODE,
                    ]:
                        requires_manual_grading = True
                        # Store placeholder or skip score calculation for manual parts
                        continue  # Skip auto-grading for manual types

                    elif (
                        user_answer is not None
                    ):  # Only grade if an answer was provided
                        # --- Auto-Grading Logic ---
                        if (
                            question.question_type
                            == Question.QuestionType.MULTIPLE_CHOICE
                        ):
                            question_score = cls._grade_multiple_choice(
                                question, user_answer
                            )
                        elif question.question_type == Question.QuestionType.TRUE_FALSE:
                            question_score = cls._grade_true_false(
                                question, user_answer
                            )
                        elif (
                            question.question_type == Question.QuestionType.SHORT_ANSWER
                        ):
                            question_score = cls._grade_short_answer(
                                question, user_answer
                            )
                        elif question.question_type == Question.QuestionType.MATCHING:
                            question_score = cls._grade_matching(question, user_answer)
                        elif (
                            question.question_type == Question.QuestionType.FILL_BLANKS
                        ):
                            question_score = cls._grade_fill_blanks(
                                question, user_answer
                            )
                        # Add logic for other auto-gradable types

                        total_score += question_score

                except Exception as e:
                    logger.error(
                        f"Error auto-grading question {question.id} for attempt {attempt.id}: {e}",
                        exc_info=True,
                    )
                    # Decide how to handle grading errors - mark as needing manual review? Assign 0?
                    requires_manual_grading = True  # Mark for review if error occurs

        attempt.score = total_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        attempt.max_score = int(max_score)  # Store as integer

        # Determine pass status
        if max_score > 0 and assessment.pass_mark_percentage is not None:
            pass_mark = (
                Decimal(assessment.pass_mark_percentage) / Decimal(100)
            ) * max_score
            attempt.is_passed = attempt.score >= pass_mark
        else:
            attempt.is_passed = None  # Cannot determine pass status

        if (
            not requires_manual_grading
            or assessment.grading_type == assessment.GradingType.AUTO
        ):
            attempt.status = AssessmentAttempt.AttemptStatus.GRADED
            attempt.graded_at = timezone.now()
            # graded_by could be null for auto-grading or a system user
            logger.info(
                f"Attempt {attempt.id} auto-graded. Score: {attempt.score}/{attempt.max_score}"
            )
        else:
            # Remains SUBMITTED, needs manual intervention
            logger.info(
                f"Attempt {attempt.id} requires manual grading. Auto-score part: {attempt.score}"
            )

        attempt.save()

    # --- Private Helper Methods for Auto-Grading ---

    @staticmethod
    def _get_correct_options(question: Question) -> set:
        """Gets the set of correct option IDs for MC/TF questions."""
        options = question.type_specific_data.get("options", [])
        return {opt.get("id") for opt in options if opt.get("is_correct")}

    @classmethod
    def _grade_multiple_choice(cls, question: Question, user_answer) -> Decimal:
        correct_option_ids = cls._get_correct_options(question)
        allow_multiple = question.type_specific_data.get("allow_multiple", False)
        points = Decimal(question.points)

        if not isinstance(user_answer, list):
            user_answer = [user_answer]  # Ensure list for consistency
        user_selected_ids = set(user_answer)

        if allow_multiple:
            # Simple exact match scoring for multiple answers (could implement partial credit)
            is_correct = user_selected_ids == correct_option_ids
        else:
            # Single choice
            is_correct = (
                len(user_selected_ids) == 1
                and list(user_selected_ids)[0] in correct_option_ids
            )

        return points if is_correct else Decimal(0)

    @classmethod
    def _grade_true_false(cls, question: Question, user_answer) -> Decimal:
        # Assumes TF stores options like MC, or stores correct answer directly
        # Example: type_specific_data = {'correct_answer': True}
        # Example: user_answer could be True, False, 'true', 'false', or option ID
        correct_answer = question.type_specific_data.get("correct_answer")
        if correct_answer is None:  # Try options format
            correct_option_ids = cls._get_correct_options(question)
            # Need a mapping from option ID to True/False value based on option text or stored value
            # This structure needs standardization. Assume simple True/False for now.
            logger.warning(
                f"Cannot grade TF question {question.id} without clear correct answer structure."
            )
            return Decimal(0)

        # Normalize user answer
        if isinstance(user_answer, str):
            user_answer_bool = user_answer.lower() == "true"
        elif isinstance(user_answer, list):  # Came from option selection potentially
            # Need logic to map selected option ID back to True/False
            logger.warning(
                f"Cannot grade TF question {question.id} from option ID list yet."
            )
            return Decimal(0)
        else:
            user_answer_bool = bool(user_answer)

        return (
            Decimal(question.points)
            if user_answer_bool == correct_answer
            else Decimal(0)
        )

    @staticmethod
    def _grade_short_answer(question: Question, user_answer) -> Decimal:
        if not isinstance(user_answer, str):
            return Decimal(0)

        correct_answers = question.type_specific_data.get("correct_answers", [])
        case_sensitive = question.type_specific_data.get("case_sensitive", False)
        points = Decimal(question.points)

        processed_user_answer = user_answer.strip()
        if not case_sensitive:
            processed_user_answer = processed_user_answer.lower()

        for correct in correct_answers:
            processed_correct = correct.strip()
            if not case_sensitive:
                processed_correct = processed_correct.lower()
            if processed_user_answer == processed_correct:
                return points
        return Decimal(0)

    @staticmethod
    def _grade_matching(question: Question, user_answer) -> Decimal:
        # Requires 'correct_pairs': [{'prompt_id': 'p1', 'match_id': 'm1'}, ...] in type_specific_data
        # Requires user_answer: [{'prompt_id': 'p1', 'selected_match_id': 'm1'}, ...]
        correct_pairs_map = {
            p["prompt_id"]: p["match_id"]
            for p in question.type_specific_data.get("correct_pairs", [])
        }
        if not correct_pairs_map or not isinstance(user_answer, list):
            return Decimal(0)

        points_per_match = (
            Decimal(question.points) / Decimal(len(correct_pairs_map))
            if correct_pairs_map
            else Decimal(0)
        )
        earned_score = Decimal(0)

        user_answers_map = {
            ua.get("prompt_id"): ua.get("selected_match_id") for ua in user_answer
        }

        for prompt_id, correct_match_id in correct_pairs_map.items():
            if user_answers_map.get(prompt_id) == correct_match_id:
                earned_score += points_per_match

        # Round final score for the question? Or let total round? Rounding here.
        return earned_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _grade_fill_blanks(question: Question, user_answer) -> Decimal:
        # Requires type_specific_data: {'blanks': {'blank1': {'correct': ['ans1', 'ans2']}, ...}}
        # Requires user_answer: {'blank1': 'user_text1', 'blank2': 'user_text2'}
        blanks_data = question.type_specific_data.get("blanks", {})
        if not blanks_data or not isinstance(user_answer, dict):
            return Decimal(0)

        points_per_blank = (
            Decimal(question.points) / Decimal(len(blanks_data))
            if blanks_data
            else Decimal(0)
        )
        earned_score = Decimal(0)
        case_sensitive = question.type_specific_data.get(
            "case_sensitive", False
        )  # Global or per-blank? Assume global.

        for blank_id, blank_info in blanks_data.items():
            user_text = user_answer.get(blank_id, "").strip()
            correct_options = blank_info.get("correct", [])

            if not case_sensitive:
                user_text = user_text.lower()

            is_correct_blank = False
            for correct in correct_options:
                processed_correct = correct.strip()
                if not case_sensitive:
                    processed_correct = processed_correct.lower()
                if user_text == processed_correct:
                    is_correct_blank = True
                    break
            if is_correct_blank:
                earned_score += points_per_blank

        return earned_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
