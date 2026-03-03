"""Utility functions for data validation."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ValidationResult:
    """Result of a validation operation."""

    is_valid: bool
    errors: list[str]
    warnings: list[str]


def create_range_validator(
    min_value: float | None = None,
    max_value: float | None = None,
) -> Callable[[Any], bool]:
    """Create a validator that checks if a value is within range.

    Args:
        min_value: Minimum allowed value (inclusive)
        max_value: Maximum allowed value (inclusive)

    Returns:
        A validator function that returns True if value is in range

    Example:
        validator = create_range_validator(0, 100)
        validator(DataRecord(id="1", name="test", value=50))  # True
        validator(DataRecord(id="2", name="test", value=150)) # False
    """

    def validator(record) -> bool:
        value = record.value
        if min_value is not None and value < min_value:
            return False
        if max_value is not None and value > max_value:
            return False
        return True

    return validator


def create_name_pattern_validator(pattern: str) -> Callable[[Any], bool]:
    """Create a validator that checks if name matches a pattern.

    Args:
        pattern: Regex pattern to match against record name

    Returns:
        A validator function
    """
    import re

    compiled = re.compile(pattern)

    def validator(record) -> bool:
        return bool(compiled.match(record.name))

    return validator


def validate_batch(
    records: list[Any],
    validators: list[Callable[[Any], bool]],
) -> ValidationResult:
    """Validate a batch of records against multiple validators.

    Args:
        records: List of records to validate
        validators: List of validator functions

    Returns:
        ValidationResult with overall status and any errors
    """
    errors = []
    warnings = []

    for i, record in enumerate(records):
        for validator in validators:
            try:
                if not validator(record):
                    errors.append(f"Record {i}: validation failed")
            except Exception as e:
                warnings.append(f"Record {i}: validator error - {e}")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
