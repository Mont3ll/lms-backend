def generate_tf_data(correct_answer=True):
    """Helper to create the standard dict structure for a True/False question."""
    return {
        "correct_answer": correct_answer,
    }


def validate_tf_data(data):
    """Validates the structure of type_specific_data for True/False questions."""
    correct_answer = data.get("correct_answer")
    if correct_answer is None:
        return False, "Missing 'correct_answer' field."
    if not isinstance(correct_answer, bool):
        return False, "'correct_answer' must be a boolean (true or false)."
    return True, ""


def grade_tf_answer(question_data, student_answer):
    """
    Grade a True/False question.
    
    Args:
        question_data: The type_specific_data from the question
        student_answer: The student's answer (boolean or string 'true'/'false')
    
    Returns:
        Tuple of (is_correct, points_ratio, feedback)
        - is_correct: True if answer is correct, False otherwise
        - points_ratio: 1.0 for correct, 0.0 for incorrect
        - feedback: Explanation string
    """
    correct_answer = question_data.get("correct_answer")
    
    # Normalize student answer to boolean
    if isinstance(student_answer, str):
        student_answer = student_answer.lower() == "true"
    elif not isinstance(student_answer, bool):
        return False, 0.0, "Invalid answer format. Please answer True or False."
    
    is_correct = student_answer == correct_answer
    
    if is_correct:
        return True, 1.0, "Correct!"
    else:
        expected = "True" if correct_answer else "False"
        return False, 0.0, f"Incorrect. The correct answer is {expected}."
