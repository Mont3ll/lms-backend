import uuid


def generate_mc_option(text, is_correct=False):
    """Helper to create the standard dict structure for an MC option."""
    return {"id": str(uuid.uuid4()), "text": text, "is_correct": is_correct}


def validate_mc_data(data):
    """Validates the structure of type_specific_data for MC questions."""
    if not isinstance(data.get("options"), list):
        return False, "Missing or invalid 'options' list."
    if not any(opt.get("is_correct") for opt in data["options"]):
        return False, "At least one option must be marked as correct."
    for option in data["options"]:
        if not isinstance(option.get("text"), str) or not option.get("text"):
            return False, f"Invalid or missing text for option ID {option.get('id')}."
        if not isinstance(option.get("is_correct"), bool):
            return (
                False,
                f"Missing or invalid boolean 'is_correct' for option ID {option.get('id')}.",
            )
    return True, ""


# Add functions for rendering, specific grading variations etc.
