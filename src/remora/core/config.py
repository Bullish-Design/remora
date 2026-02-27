"""Configuration loading and validation.

Remora uses two configuration levels:
1. remora.yaml - Project-level config (loaded once at startup)
2. bundle.yaml - Per-agent config (structured-agents v0.3 format)
"""

from __future__ import annotations

import os
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from remora.core.errors import ConfigError

logger = logging.getLogger(__name__)


class ErrorPolicy(Enum):
    """How to handle agent failures in graph execution."""

    STOP_GRAPH = "stop_graph"
    SKIP_DOWNSTREAM = "skip_downstream"
    CONTINUE = "continue"


# ============================================================================
# Configuration Sections
# ============================================================================


@dataclass(frozen=True, slots=True)
class DiscoveryConfig:
    """Discovery configuration."""

    paths: tuple[str, ...] = ("src/",)
    languages: tuple[str, ...] | None = None
    max_workers: int = 4


@dataclass(frozen=True, slots=True)
class BundleConfig:
    """Agent bundle configuration."""

    path: str = "agents/"
    mapping: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """Graph execution configuration."""

    max_concurrency: int = 4
    error_policy: ErrorPolicy = ErrorPolicy.SKIP_DOWNSTREAM
    timeout: float = 300.0
    max_turns: int = 8
    truncation_limit: int = 1024


@dataclass(frozen=True, slots=True)
class IndexerConfig:
    """Indexer daemon configuration."""

    watch_paths: tuple[str, ...] = ("src/",)
    store_path: str = ".remora/index"


@dataclass(frozen=True, slots=True)
class DashboardConfig:
    """Dashboard server configuration."""

    host: str = "0.0.0.0"
    port: int = 8420


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Cairn workspace configuration."""

    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Default model configuration."""

    base_url: str = "http://localhost:8000/v1"
    default_model: str = "Qwen/Qwen3-4B"
    api_key: str = ""


# ============================================================================
# Main Configuration
# ============================================================================


@dataclass(frozen=True, slots=True)
class RemoraConfig:
    """Complete Remora configuration.

    Frozen dataclass - immutable after creation.
    Loaded once at startup, passed explicitly to components.
    """

    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    bundles: BundleConfig = field(default_factory=BundleConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    indexer: IndexerConfig = field(default_factory=IndexerConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    model: ModelConfig = field(default_factory=ModelConfig)


# ============================================================================
# Loading
# ============================================================================


def load_config(path: Path | str | None = None) -> RemoraConfig:
    """Load configuration from YAML file.

    Args:
        path: Path to remora.yaml. If None, searches current directory
              and parent directories.

    Returns:
        Frozen RemoraConfig instance

    Raises:
        ConfigError: If config file is invalid
    """
    if path is None:
        path = _find_config_file()

    config_path = Path(path)

    if not config_path.exists():
        logger.info("No config file found, using defaults")
        return RemoraConfig()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML in {config_path}: {e}")

    data = _apply_env_overrides(data)

    try:
        return _build_config(data)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"Invalid configuration: {e}")


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


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to config.

    Environment variables use REMORA_ prefix:
    - REMORA_MODEL_BASE_URL -> model.base_url
    - REMORA_MODEL_API_KEY -> model.api_key
    - REMORA_MODEL_DEFAULT -> model.default_model
    - REMORA_EXECUTION_MAX_CONCURRENCY -> execution.max_concurrency
    - REMORA_EXECUTION_TIMEOUT -> execution.timeout
    - REMORA_DASHBOARD_PORT -> dashboard.port
    - REMORA_WORKSPACE_BASE_PATH -> workspace.base_path
    """
    env_mappings = {
        "REMORA_MODEL_BASE_URL": ("model", "base_url"),
        "REMORA_MODEL_API_KEY": ("model", "api_key"),
        "REMORA_MODEL_DEFAULT": ("model", "default_model"),
        "REMORA_EXECUTION_MAX_CONCURRENCY": ("execution", "max_concurrency"),
        "REMORA_EXECUTION_TIMEOUT": ("execution", "timeout"),
        "REMORA_DASHBOARD_PORT": ("dashboard", "port"),
        "REMORA_WORKSPACE_BASE_PATH": ("workspace", "base_path"),
    }

    for env_var, (section, key) in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            if section not in data:
                data[section] = {}
            if key in ("max_concurrency", "port", "timeout"):
                value = int(value) if "." not in value else float(value)
            data[section][key] = value

    return data


def _build_config(data: dict[str, Any]) -> RemoraConfig:
    """Build RemoraConfig from dictionary data."""

    def get_section(name: str, cls: type) -> Any:
        section_data = data.get(name, {})
        for key, value in list(section_data.items()):
            if isinstance(value, list):
                section_data[key] = tuple(value)
        if name == "execution" and "error_policy" in section_data:
            section_data["error_policy"] = ErrorPolicy(section_data["error_policy"])
        return cls(**section_data)

    return RemoraConfig(
        discovery=get_section("discovery", DiscoveryConfig),
        bundles=get_section("bundles", BundleConfig),
        execution=get_section("execution", ExecutionConfig),
        indexer=get_section("indexer", IndexerConfig),
        dashboard=get_section("dashboard", DashboardConfig),
        workspace=get_section("workspace", WorkspaceConfig),
        model=get_section("model", ModelConfig),
    )


def serialize_config(config: RemoraConfig) -> dict[str, Any]:
    """Serialize the configuration to a dictionary."""

    def normalize(value: Any) -> Any:
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    def section_to_dict(section: Any) -> dict[str, Any]:
        data = asdict(section)
        if isinstance(section, ExecutionConfig):
            data["error_policy"] = section.error_policy.value
        return normalize(data)

    return {
        "discovery": section_to_dict(config.discovery),
        "bundles": section_to_dict(config.bundles),
        "execution": section_to_dict(config.execution),
        "indexer": section_to_dict(config.indexer),
        "dashboard": section_to_dict(config.dashboard),
        "workspace": section_to_dict(config.workspace),
        "model": section_to_dict(config.model),
    }


__all__ = [
    "ConfigError",
    "ErrorPolicy",
    "RemoraConfig",
    "DiscoveryConfig",
    "BundleConfig",
    "ExecutionConfig",
    "IndexerConfig",
    "DashboardConfig",
    "WorkspaceConfig",
    "ModelConfig",
    "load_config",
    "serialize_config",
]
