"""Configuration file loading utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from configlib.schema import validate


def load_config(path: str | Path) -> dict[str, Any]:
    """Load and parse a configuration file."""
    path = Path(path)
    fmt = detect_format(path)
    raw = path.read_text(encoding="utf-8")

    if fmt == "json":
        data = json.loads(raw)
    elif fmt == "yaml":
        data = load_yaml(raw)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    validate(data)
    return data


def detect_format(path: str | Path) -> str:
    """Detect config file format from extension."""
    suffix = Path(path).suffix.lower()
    mapping = {".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml"}
    fmt = mapping.get(suffix)
    if fmt is None:
        raise ValueError(f"Unknown config format: {suffix}")
    return fmt


def load_yaml(raw: str) -> dict[str, Any]:
    """Parse YAML content string into a dict."""
    # Simplified: real impl would use PyYAML
    import yaml

    return yaml.safe_load(raw)
