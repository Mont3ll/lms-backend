def generate_sa_data(correct_answers=None, case_sensitive=False):
    """Helper to create the standard dict structure for a Short Answer question."""
    return {
        "correct_answers": correct_answers or [],
        "case_sensitive": case_sensitive,
    }


def validate_sa_data(data):
    """Validates the structure of type_specific_data for Short Answer questions."""
    correct_answers = data.get("correct_answers")
    if correct_answers is None:
        return False, "Missing 'correct_answers' field."
    if not isinstance(correct_answers, list):
        return False, "'correct_answers' must be a list of acceptable answers."
    if len(correct_answers) == 0:
        return False, "At least one correct answer must be provided."
    for answer in correct_answers:
        if not isinstance(answer, str) or not answer.strip():
            return False, "All correct answers must be non-empty strings."
    
    case_sensitive = data.get("case_sensitive", False)
    if not isinstance(case_sensitive, bool):
        return False, "'case_sensitive' must be a boolean."
    
    return True, ""


def grade_sa_answer(question_data, student_answer):
    """
    Grade a Short Answer question.
    
    Args:
        question_data: The type_specific_data from the question
        student_answer: The student's answer (string)
    
    Returns:
        Tuple of (is_correct, points_ratio, feedback)
        - is_correct: True if answer matches one of the correct answers
        - points_ratio: 1.0 for correct, 0.0 for incorrect
        - feedback: Explanation string
    """
    if not isinstance(student_answer, str):
        return False, 0.0, "Answer must be a text string."
    
    student_answer = student_answer.strip()
    if not student_answer:
        return False, 0.0, "No answer provided."
    
    correct_answers = question_data.get("correct_answers", [])
    case_sensitive = question_data.get("case_sensitive", False)
    
    # Normalize answers for comparison
    if case_sensitive:
        normalized_student = student_answer
        normalized_correct = [ans.strip() for ans in correct_answers]
    else:
        normalized_student = student_answer.lower()
        normalized_correct = [ans.strip().lower() for ans in correct_answers]
    
    if normalized_student in normalized_correct:
        return True, 1.0, "Correct!"
    else:
        # Provide feedback with acceptable answers (limited to first 3)
        shown_answers = correct_answers[:3]
        if len(correct_answers) > 3:
            answers_hint = f"Acceptable answers include: {', '.join(shown_answers)}, and more."
        else:
            answers_hint = f"Acceptable answers: {', '.join(shown_answers)}"
        return False, 0.0, f"Incorrect. {answers_hint}"
