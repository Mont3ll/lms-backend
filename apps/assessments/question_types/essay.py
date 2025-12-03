def generate_essay_data(max_words=None, min_words=None):
    """Helper to create the standard dict structure for an Essay question."""
    return {
        "max_words": max_words,
        "min_words": min_words,
        "requires_manual_grading": True,
        "allow_file_upload": False,
        "accepted_file_types": []
    }


def validate_essay_data(data):
    """Validates the structure of type_specific_data for Essay questions."""
    max_words = data.get("max_words")
    if max_words is not None and (not isinstance(max_words, int) or max_words <= 0):
        return False, "'max_words' must be a positive integer or null."
    
    min_words = data.get("min_words")
    if min_words is not None and (not isinstance(min_words, int) or min_words < 0):
        return False, "'min_words' must be a non-negative integer or null."
    
    if max_words and min_words and min_words > max_words:
        return False, "'min_words' cannot be greater than 'max_words'."
    
    allow_file_upload = data.get("allow_file_upload", False)
    if not isinstance(allow_file_upload, bool):
        return False, "'allow_file_upload' must be a boolean."
    
    accepted_file_types = data.get("accepted_file_types", [])
    if not isinstance(accepted_file_types, list):
        return False, "'accepted_file_types' must be a list."
    
    return True, ""


def grade_essay_answer(question_data, student_answer):
    """Grade an Essay question - returns ungraded status for manual review."""
    if not isinstance(student_answer, (str, dict)):
        return False, 0, "Answer must be a string or contain file information."
    
    # Basic validation
    if isinstance(student_answer, str):
        answer_text = student_answer.strip()
        word_count = len(answer_text.split()) if answer_text else 0
        
        min_words = question_data.get("min_words")
        max_words = question_data.get("max_words")
        
        if min_words and word_count < min_words:
            return False, 0, f"Answer must be at least {min_words} words. Current: {word_count}"
        
        if max_words and word_count > max_words:
            return False, 0, f"Answer must not exceed {max_words} words. Current: {word_count}"
    
    # Essay questions require manual grading
    return None, None, "Requires manual grading"