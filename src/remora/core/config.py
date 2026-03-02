"""Configuration loading and validation.

Remora uses two configuration levels:
1. remora.yaml - Project-level config (loaded once at startup)
2. bundle.yaml - Per-agent config (structured-agents v0.3 format)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from remora.utils import PathLike, normalize_path
from remora.core.errors import ConfigError

logger = logging.getLogger(__name__)


DEFAULT_IGNORE_PATTERNS: tuple[str, ...] = (
    ".agentfs",
    ".git",
    ".jj",
    ".mypy_cache",
    ".pytest_cache",
    ".remora",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
)


class Config(BaseSettings):
    """Flat Remora configuration for swarm-only mode."""

    model_config = SettingsConfigDict(env_prefix="REMORA_")

    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None
    discovery_max_workers: int = 4

    bundle_root: str = "agents"
    bundle_mapping: dict[str, str] = Field(default_factory=dict)
    bundle_mapping_tools: dict[str, str] = Field(default_factory=dict)

    model_base_url: str = "http://localhost:8000/v1"
    model_default: str = "Qwen/Qwen3-4B"
    model_api_key: str = ""

    swarm_root: str = ".remora"
    swarm_id: str = "swarm"
    max_concurrency: int = 4
    max_turns: int = 8
    truncation_limit: int = 1024
    timeout_s: float = 300.0
    max_trigger_depth: int = 5
    trigger_cooldown_ms: int = 1000
    chat_history_limit: int = 5

    workspace_ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
    workspace_ignore_dotfiles: bool = True

    nvim_enabled: bool = False
    nvim_socket: str = ".remora/nvim.sock"


def load_config(path: PathLike | None = None) -> Config:
    """Load configuration from YAML file."""
    if path is None:
        path = _find_config_file()

    if path is None:
        logger.info("No config file found, using defaults")
        return Config()

    config_path = normalize_path(path)

    if not config_path.exists():
        logger.info("No config file found, using defaults")
        return Config()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    return _build_config(data)


def _find_config_file() -> Path | None:
    """Search for remora.yaml in current and parent directories.

    Returns None if no config file is found.
    """
    current = Path.cwd()

    for directory in [current] + list(current.parents):
        config_path = directory / "remora.yaml"
        if config_path.exists():
            return config_path
        if (directory / "pyproject.toml").exists():
            break

    return None


def _build_config(data: dict[str, Any]) -> Config:
    """Build Config from dictionary data.

    Pydantic handles list-to-tuple coercion automatically.
    """
    return Config(**data)


def serialize_config(config: Config) -> dict[str, Any]:
    """Serialize the configuration to a dictionary.

    Uses mode='json' so tuples become lists (YAML/JSON compatible).
    """
    return config.model_dump(mode="json")


__all__ = [
    "Config",
    "ConfigError",
    "load_config",
    "serialize_config",
]
