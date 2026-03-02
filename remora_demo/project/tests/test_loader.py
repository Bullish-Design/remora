"""Tests for configlib.loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from configlib.loader import detect_format, load_config, load_yaml


def test_load_yaml(tmp_path: Path) -> None:
    """Test loading a YAML configuration file."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("database:\n  host: localhost\n  port: 5432\n")
    result = load_config(config_file)
    assert result["database"]["host"] == "localhost"
    assert result["database"]["port"] == 5432


def test_load_json(tmp_path: Path) -> None:
    """Test loading a JSON configuration file."""
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"api_key": "test123", "debug": True}))
    result = load_config(config_file)
    assert result["api_key"] == "test123"


def test_detect_format() -> None:
    """Test format detection from file extensions."""
    assert detect_format("config.yaml") == "yaml"
    assert detect_format("config.yml") == "yaml"
    assert detect_format("config.json") == "json"
    with pytest.raises(ValueError, match="Unknown"):
        detect_format("config.txt")
