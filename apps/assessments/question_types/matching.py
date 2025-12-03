import uuid


def generate_matching_data(pairs=None):
    """Helper to create the standard dict structure for a Matching question."""
    if pairs is None:
        pairs = [
            {"id": str(uuid.uuid4()), "left_item": "", "right_item": ""},
            {"id": str(uuid.uuid4()), "left_item": "", "right_item": ""}
        ]
    
    return {
        "pairs": pairs,
        "shuffle_items": True,
        "allow_partial_credit": True,
        "max_matches_per_item": 1  # 1-to-1 matching by default
    }


def validate_matching_data(data):
    """Validates the structure of type_specific_data for Matching questions."""
    pairs = data.get("pairs", [])
    if not isinstance(pairs, list) or len(pairs) < 2:
        return False, "'pairs' must be a list with at least 2 items."
    
    for i, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            return False, f"Pair {i+1} must be a dictionary."
        
        if not isinstance(pair.get("left_item"), str) or not pair.get("left_item"):
            return False, f"Pair {i+1} must have a non-empty 'left_item' string."
        
        if not isinstance(pair.get("right_item"), str) or not pair.get("right_item"):
            return False, f"Pair {i+1} must have a non-empty 'right_item' string."
        
        if "id" not in pair:
            return False, f"Pair {i+1} must have an 'id' field."
    
    shuffle_items = data.get("shuffle_items", True)
    if not isinstance(shuffle_items, bool):
        return False, "'shuffle_items' must be a boolean."
    
    allow_partial_credit = data.get("allow_partial_credit", True)
    if not isinstance(allow_partial_credit, bool):
        return False, "'allow_partial_credit' must be a boolean."
    
    max_matches_per_item = data.get("max_matches_per_item", 1)
    if not isinstance(max_matches_per_item, int) or max_matches_per_item < 1:
        return False, "'max_matches_per_item' must be a positive integer."
    
    return True, ""


def grade_matching_answer(question_data, student_answer):
    """Grade a Matching question."""
    if not isinstance(student_answer, dict):
        return False, 0, "Answer must be a dictionary mapping left items to right items."
    
    pairs = question_data.get("pairs", [])
    allow_partial_credit = question_data.get("allow_partial_credit", True)
    
    if not pairs:
        return False, 0, "No matching pairs defined for this question."
    
    # Create correct mapping
    correct_mapping = {pair["left_item"]: pair["right_item"] for pair in pairs}
    
    total_pairs = len(pairs)
    correct_matches = 0
    
    # Check each student answer
    for left_item, right_item in student_answer.items():
        if left_item in correct_mapping and correct_mapping[left_item] == right_item:
            correct_matches += 1
    
    if allow_partial_credit:
        score = correct_matches / total_pairs if total_pairs > 0 else 0
        is_correct = score >= 0.5  # 50% threshold for "correct"
    else:
        is_correct = correct_matches == total_pairs
        score = 1 if is_correct else 0
    
    return is_correct, score, ""