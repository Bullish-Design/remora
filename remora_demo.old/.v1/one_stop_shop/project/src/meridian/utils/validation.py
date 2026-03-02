"""Validation helpers for Meridian."""

from __future__ import annotations


def clamp(value: float, lower: float, upper: float) -> float:
    """Clamp a value into a closed interval."""
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def require_positive(value: float, field_name: str) -> float:
    """Ensure a value is positive."""
    if value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


__all__ = ["clamp", "require_positive"]
