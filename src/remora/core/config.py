"""Configuration loading and validation.

Remora uses two configuration levels:
1. remora.yaml - Project-level config (loaded once at startup)
2. bundle.yaml - Per-agent config (structured-agents v0.3 format)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from remora.utils import PathLike, normalize_path

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


@dataclass(slots=True)
class Config:
    """Flat Remora configuration for swarm-only mode."""

    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    discovery_languages: tuple[str, ...] | None = None
    discovery_max_workers: int = 4

    bundle_root: str = "agents"
    bundle_mapping: dict[str, str] = field(default_factory=dict)

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

    workspace_ignore_patterns: tuple[str, ...] = DEFAULT_IGNORE_PATTERNS
    workspace_ignore_dotfiles: bool = True

    nvim_enabled: bool = False
    nvim_socket: str = ".remora/nvim.sock"


def load_config(path: PathLike | None = None) -> Config:
    """Load configuration from YAML file."""
    if path is None:
        path = _find_config_file()

    config_path = normalize_path(path)

    if not config_path.exists():
        logger.info("No config file found, using defaults")
        return Config()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        from remora.core.errors import ConfigError

        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    return _build_config(data)


def _find_config_file() -> Path:
    """Search for remora.yaml in current and parent directories."""
    current = Path.cwd()

    for directory in [current] + list(current.parents):
        config_path = directory / "remora.yaml"
        if config_path.exists():
            return config_path
        if (directory / "pyproject.toml").exists():
            break

    return current / "remora.yaml"


def _build_config(data: dict[str, Any]) -> Config:
    """Build Config from dictionary data."""
    if "discovery_paths" in data and isinstance(data["discovery_paths"], list):
        data["discovery_paths"] = tuple(data["discovery_paths"])
    if "discovery_languages" in data and isinstance(data["discovery_languages"], list):
        data["discovery_languages"] = tuple(data["discovery_languages"])
    if "workspace_ignore_patterns" in data and isinstance(data["workspace_ignore_patterns"], list):
        data["workspace_ignore_patterns"] = tuple(data["workspace_ignore_patterns"])
    return Config(**data)


def serialize_config(config: Config) -> dict[str, Any]:
    """Serialize the configuration to a dictionary."""

    def normalize(value: Any) -> Any:
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    data = {
        "project_path": config.project_path,
        "discovery_paths": normalize(config.discovery_paths),
        "discovery_languages": normalize(config.discovery_languages),
        "discovery_max_workers": config.discovery_max_workers,
        "bundle_root": config.bundle_root,
        "bundle_mapping": normalize(config.bundle_mapping),
        "model_base_url": config.model_base_url,
        "model_default": config.model_default,
        "model_api_key": config.model_api_key,
        "swarm_root": config.swarm_root,
        "swarm_id": config.swarm_id,
        "max_concurrency": config.max_concurrency,
        "max_turns": config.max_turns,
        "truncation_limit": config.truncation_limit,
        "timeout_s": config.timeout_s,
        "max_trigger_depth": config.max_trigger_depth,
        "trigger_cooldown_ms": config.trigger_cooldown_ms,
        "workspace_ignore_patterns": normalize(config.workspace_ignore_patterns),
        "workspace_ignore_dotfiles": config.workspace_ignore_dotfiles,
        "nvim_enabled": config.nvim_enabled,
        "nvim_socket": config.nvim_socket,
    }
    return data


from remora.core.errors import ConfigError


__all__ = [
    "Config",
    "ConfigError",
    "load_config",
    "serialize_config",
]
