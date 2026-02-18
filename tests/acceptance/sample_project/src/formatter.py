"""String formatting utilities with defects."""


def truncate_string(text, max_length=50):
    # Missing type hints and docstring
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."


def slugify(text):
    # Missing type hints and docstring
    # E225: missing whitespace around operator
    return text.lower().replace(" ", "-").replace("_", "-")


def normalize_whitespace(text):
    """Normalize whitespace in text."""
    # Has docstring
    import re

    return re.sub(r"\s+", " ", text).strip()


def format_phone_number(number):
    # Missing type hints and docstring
    # W292: no newline at end of file (will be added by lint)
    digits = "".join(c for c in number if c.isdigit())
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number
