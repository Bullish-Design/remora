"""Configuration for AST Summary demo."""

from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel

DEFAULT_CONFIG_FILENAME = "ast_summary.yaml"


class DemoConfig(BaseModel):
    """Configuration for the AST Summary demo."""

    base_url: str = "http://remora-server:8000/v1"
    api_key: str = "EMPTY"
    timeout: int = 120
    model: str = "Qwen/Qwen3-4B-Instruct-2507-FP8" #"google/functiongemma-270m-it"
    max_concurrency: int = 10
    cache_dir: Path = Path(".cache/ast_summary")
    event_file: Path = Path(".ast_summary_events.jsonl")


def load_demo_config(config_path: Path | None = None) -> DemoConfig:
    """Load demo configuration from file or defaults."""
    if config_path is None:
        default_path = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if default_path.exists():
            config_path = default_path

    if config_path and config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return DemoConfig(**data)

    return DemoConfig()
