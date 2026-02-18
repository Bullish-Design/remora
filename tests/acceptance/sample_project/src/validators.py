"""Validation utilities."""

from typing import Optional


def is_valid_url(url: str) -> bool:
    """Check if URL is valid."""
    return url.startswith(("http://", "https://"))


def validate_username(username):
    # Missing type hints and docstring
    if not username:
        return False
    if len(username) < 3:
        return False
    return username.isalnum()


def sanitize_filename(filename):
    # Missing type hints and docstring
    # E231: missing whitespace after comma
    invalid_chars = ["<", ">", ":", '"', "/", "\\", "|", "?", "*"]
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename


def is_valid_date(date_string):
    # Missing type hints and docstring
    from datetime import datetime

    try:
        datetime.strptime(date_string, "%Y-%m-%d")
        return True
    except ValueError:
        return False
