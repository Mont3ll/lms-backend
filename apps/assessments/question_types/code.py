def generate_code_data(language="python", max_file_size_mb=5, allow_multiple_files=False):
    """Helper to create the standard dict structure for a Code Submission question."""
    return {
        "language": language,
        "max_file_size_mb": max_file_size_mb,
        "allow_multiple_files": allow_multiple_files,
        "accepted_file_extensions": [".py", ".js", ".java", ".cpp", ".c", ".txt"],
        "requires_manual_grading": True,
        "enable_syntax_highlighting": True,
        "template_code": "",
        "test_cases": []  # For future auto-grading implementation
    }


def validate_code_data(data):
    """Validates the structure of type_specific_data for Code Submission questions."""
    language = data.get("language", "python")
    if not isinstance(language, str):
        return False, "'language' must be a string."
    
    max_file_size_mb = data.get("max_file_size_mb", 5)
    if not isinstance(max_file_size_mb, (int, float)) or max_file_size_mb <= 0:
        return False, "'max_file_size_mb' must be a positive number."
    
    allow_multiple_files = data.get("allow_multiple_files", False)
    if not isinstance(allow_multiple_files, bool):
        return False, "'allow_multiple_files' must be a boolean."
    
    accepted_file_extensions = data.get("accepted_file_extensions", [])
    if not isinstance(accepted_file_extensions, list):
        return False, "'accepted_file_extensions' must be a list."
    
    template_code = data.get("template_code", "")
    if not isinstance(template_code, str):
        return False, "'template_code' must be a string."
    
    test_cases = data.get("test_cases", [])
    if not isinstance(test_cases, list):
        return False, "'test_cases' must be a list."
    
    return True, ""


def grade_code_answer(question_data, student_answer):
    """Grade a Code Submission question - returns ungraded status for manual review."""
    if not isinstance(student_answer, (str, dict)):
        return False, 0, "Answer must be a string (code) or contain file information."
    
    # Basic validation
    if isinstance(student_answer, str):
        code = student_answer.strip()
        if not code:
            return False, 0, "Code submission cannot be empty."
        
        max_file_size_mb = question_data.get("max_file_size_mb", 5)
        # Rough estimate: 1 character ≈ 1 byte
        size_mb = len(code.encode('utf-8')) / (1024 * 1024)
        if size_mb > max_file_size_mb:
            return False, 0, f"Code submission exceeds maximum size of {max_file_size_mb}MB."
    
    # Code questions require manual grading (unless auto-grader is implemented)
    return None, None, "Requires manual grading"