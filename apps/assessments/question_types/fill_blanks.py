import re


def generate_fill_blanks_data(text_with_blanks="", case_sensitive=False):
    """Helper to create the standard dict structure for a Fill in the Blanks question."""
    return {
        "text_with_blanks": text_with_blanks,
        "blanks": [],  # Will be populated when text is parsed
        "case_sensitive": case_sensitive,
        "allow_partial_credit": True,
        "blank_placeholder": "___"
    }


def parse_blanks_from_text(text_with_blanks):
    """Parse blanks from text using [answer] syntax."""
    # Find all blanks in format [answer] or [answer1|answer2] for multiple correct answers
    blank_pattern = r'\[([^\]]+)\]'
    matches = re.finditer(blank_pattern, text_with_blanks)
    
    blanks = []
    for i, match in enumerate(matches):
        answers_text = match.group(1)
        # Split by | for multiple correct answers
        correct_answers = [ans.strip() for ans in answers_text.split('|')]
        
        blanks.append({
            "id": f"blank_{i+1}",
            "position": i,
            "correct_answers": correct_answers,
            "start_index": match.start(),
            "end_index": match.end()
        })
    
    return blanks


def validate_fill_blanks_data(data):
    """Validates the structure of type_specific_data for Fill in the Blanks questions."""
    text_with_blanks = data.get("text_with_blanks", "")
    if not isinstance(text_with_blanks, str) or not text_with_blanks.strip():
        return False, "'text_with_blanks' must be a non-empty string."
    
    # Check if text contains at least one blank
    if '[' not in text_with_blanks or ']' not in text_with_blanks:
        return False, "Text must contain at least one blank in format [answer]."
    
    # Try to parse blanks to validate format
    try:
        blanks = parse_blanks_from_text(text_with_blanks)
        if not blanks:
            return False, "No valid blanks found in text. Use format [answer] or [answer1|answer2]."
    except Exception as e:
        return False, f"Error parsing blanks: {str(e)}"
    
    case_sensitive = data.get("case_sensitive", False)
    if not isinstance(case_sensitive, bool):
        return False, "'case_sensitive' must be a boolean."
    
    allow_partial_credit = data.get("allow_partial_credit", True)
    if not isinstance(allow_partial_credit, bool):
        return False, "'allow_partial_credit' must be a boolean."
    
    return True, ""


def grade_fill_blanks_answer(question_data, student_answer):
    """Grade a Fill in the Blanks question."""
    if not isinstance(student_answer, (list, dict)):
        return False, 0, "Answer must be a list of answers or a dictionary mapping blank IDs to answers."
    
    text_with_blanks = question_data.get("text_with_blanks", "")
    case_sensitive = question_data.get("case_sensitive", False)
    allow_partial_credit = question_data.get("allow_partial_credit", True)
    
    # Parse blanks from the text
    blanks = parse_blanks_from_text(text_with_blanks)
    
    if not blanks:
        return False, 0, "No blanks found in the question text."
    
    # Convert student answer to consistent format
    if isinstance(student_answer, list):
        if len(student_answer) != len(blanks):
            return False, 0, f"Expected {len(blanks)} answers, got {len(student_answer)}."
        student_answers = {f"blank_{i+1}": ans for i, ans in enumerate(student_answer)}
    else:
        student_answers = student_answer
    
    correct_count = 0
    total_blanks = len(blanks)
    
    for blank in blanks:
        blank_id = blank["id"]
        student_ans = student_answers.get(blank_id, "").strip()
        
        if not student_ans:
            continue  # Empty answer is incorrect
        
        # Check against all correct answers for this blank
        correct_answers = blank["correct_answers"]
        is_correct = False
        
        for correct_ans in correct_answers:
            compare_student = student_ans if case_sensitive else student_ans.lower()
            compare_correct = correct_ans if case_sensitive else correct_ans.lower()
            
            if compare_student == compare_correct:
                is_correct = True
                break
        
        if is_correct:
            correct_count += 1
    
    if allow_partial_credit:
        score = correct_count / total_blanks if total_blanks > 0 else 0
        is_correct = score >= 0.5  # 50% threshold for "correct"
    else:
        is_correct = correct_count == total_blanks
        score = 1 if is_correct else 0
    
    return is_correct, score, ""


def render_text_for_display(text_with_blanks, blank_placeholder="___"):
    """Convert text with [answers] to display format with blanks."""
    # Replace all [answer] patterns with blank placeholder
    blank_pattern = r'\[([^\]]+)\]'
    display_text = re.sub(blank_pattern, blank_placeholder, text_with_blanks)
    return display_text