"""Configuration schema validation."""

from __future__ import annotations

from typing import Any


class SchemaError(Exception):
    """Raised when config data fails validation."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"Schema error in '{field}': {message}")


def validate(data: dict[str, Any], required_fields: list[str] | None = None) -> None:
    """Validate configuration data against basic rules."""
    if not isinstance(data, dict):
        raise SchemaError("root", "Config must be a dict")

    required = required_fields or []
    for field in required:
        if field not in data:
            raise SchemaError(field, "Required field missing")
