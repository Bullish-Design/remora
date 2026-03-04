"""Deep merge utilities for configuration dicts."""

from __future__ import annotations

from typing import Any


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override values win."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_dicts(*dicts: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple dicts left-to-right using deep_merge."""
    if not dicts:
        return {}
    result = dicts[0].copy()
    for d in dicts[1:]:
        result = deep_merge(result, d)
    return result
