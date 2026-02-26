"""src/remora/config.py

Two-level configuration system:
- remora.yaml: Project-level config (loaded once at startup)
- bundle.yaml: Per-agent config (structured-agents v0.3 format)

Configuration precedence (highest to lowest):
1. Environment variables (REMORA_* prefix)
2. YAML file (remora.yaml)
3. Code defaults
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """Configuration error."""

    code = "CONFIG_ERROR"


LANGUAGES: dict[str, str] = {
    ".py": "tree_sitter_python",
    ".pyi": "tree_sitter_python",
    ".toml": "tree_sitter_toml",
    ".md": "tree_sitter_markdown",
}


@dataclass(frozen=True)
class DiscoveryConfig:
    """Configuration for code discovery."""

    paths: list[str] = field(default_factory=lambda: ["src/"])
    languages: list[str] = field(default_factory=lambda: ["python", "markdown"])


@dataclass(frozen=True)
class BundleConfig:
    """Configuration for agent bundles."""

    path: str = "agents"
    mapping: dict[str, str] = field(
        default_factory=lambda: {
            "function": "lint",
            "class": "docstring",
            "file": "test",
        }
    )


@dataclass(frozen=True)
class ExecutionConfig:
    """Configuration for graph execution."""

    max_concurrency: int = 4
    error_policy: str = "skip_downstream"
    timeout: int = 300


@dataclass(frozen=True)
class IndexerConfig:
    """Configuration for the indexer daemon."""

    watch_paths: list[str] = field(default_factory=lambda: ["src/"])
    store_path: str = ".remora/index"


@dataclass(frozen=True)
class DashboardConfig:
    """Configuration for the web dashboard."""

    host: str = "0.0.0.0"
    port: int = 8420


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for Cairn workspaces."""

    base_path: str = ".remora/workspaces"
    cleanup_after: str = "1h"


@dataclass(frozen=True)
class ModelConfig:
    """Configuration for the LLM model."""

    base_url: str = "http://localhost:8000/v1"
    default_model: str = "Qwen/Qwen3-4B"


@dataclass(frozen=True)
class RemoraConfig:
    """Root configuration object. Immutable after load."""

    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    bundles: BundleConfig = field(default_factory=BundleConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    indexer: IndexerConfig = field(default_factory=IndexerConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    model: ModelConfig = field(default_factory=ModelConfig)


def load_config(config_path: Path | None = None) -> RemoraConfig:
    """Load configuration from YAML file.

    Loads remora.yaml from the current directory if no path is specified.
    Environment variables override file config (e.g., REMORA_MODEL_BASE_URL).

    Args:
        config_path: Path to remora.yaml. Defaults to ./remora.yaml

    Returns:
        Frozen RemoraConfig instance

    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config file is invalid
    """
    if config_path is None:
        config_path = Path.cwd() / "remora.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in config file: {e}") from e

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise ValueError("Config file must define a mapping.")

    data = _apply_env_overrides(data)

    return _build_config(data)


def serialize_config(config: RemoraConfig) -> dict[str, Any]:
    """Serialize config to a dictionary.

    Args:
        config: RemoraConfig instance

    Returns:
        Dictionary representation of config
    """
    return {
        "discovery": {
            "paths": list(config.discovery.paths),
            "languages": list(config.discovery.languages),
        },
        "bundles": {
            "path": config.bundles.path,
            "mapping": dict(config.bundles.mapping),
        },
        "execution": {
            "max_concurrency": config.execution.max_concurrency,
            "timeout": config.execution.timeout,
        },
        "indexer": {
            "enabled": config.indexer.enabled,
        },
        "dashboard": {
            "enabled": config.dashboard.enabled,
            "host": config.dashboard.host,
            "port": config.dashboard.port,
        },
        "workspace": {
            "path": str(config.workspace.path),
        },
        "model": {
            "base_url": config.model.base_url,
            "api_key": config.model.api_key,
        },
    }


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply environment variable overrides to config.

    Environment variables must be prefixed with REMORA_ and use double underscores
    for nesting. Example: REMORA_MODEL__BASE_URL sets model.base_url.
    """
    import os

    for key, value in os.environ.items():
        if not key.startswith("REMORA_"):
            continue

        parts = key[7:].lower().split("__")

        current = data
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]

        final_key = parts[-1]
        current[final_key] = _parse_env_value(value)

    return data


def _parse_env_value(value: str) -> Any:
    """Parse environment variable value to appropriate type."""
    if value.lower() in ("true", "yes", "1"):
        return True
    if value.lower() in ("false", "no", "0"):
        return False

    try:
        return int(value)
    except ValueError:
        pass

    try:
        return float(value)
    except ValueError:
        pass

    return value


def _build_config(data: dict[str, Any]) -> RemoraConfig:
    """Build RemoraConfig from parsed YAML data."""

    discovery_data = data.get("discovery", {})
    discovery = DiscoveryConfig(
        paths=discovery_data.get("paths", ["src/"]),
        languages=discovery_data.get("languages", ["python", "markdown"]),
    )

    bundles_data = data.get("bundles", {})
    bundles = BundleConfig(
        path=bundles_data.get("path", "agents"),
        mapping=bundles_data.get(
            "mapping",
            {
                "function": "lint",
                "class": "docstring",
                "file": "test",
            },
        ),
    )

    execution_data = data.get("execution", {})
    execution = ExecutionConfig(
        max_concurrency=execution_data.get("max_concurrency", 4),
        error_policy=execution_data.get("error_policy", "skip_downstream"),
        timeout=execution_data.get("timeout", 300),
    )

    indexer_data = data.get("indexer", {})
    indexer = IndexerConfig(
        watch_paths=indexer_data.get("watch_paths", ["src/"]),
        store_path=indexer_data.get("store_path", ".remora/index"),
    )

    dashboard_data = data.get("dashboard", {})
    dashboard = DashboardConfig(
        host=dashboard_data.get("host", "0.0.0.0"),
        port=dashboard_data.get("port", 8420),
    )

    workspace_data = data.get("workspace", {})
    workspace = WorkspaceConfig(
        base_path=workspace_data.get("base_path", ".remora/workspaces"),
        cleanup_after=workspace_data.get("cleanup_after", "1h"),
    )

    model_data = data.get("model", {})
    model = ModelConfig(
        base_url=model_data.get("base_url", "http://localhost:8000/v1"),
        default_model=model_data.get("default_model", "Qwen/Qwen3-4B"),
    )

    return RemoraConfig(
        discovery=discovery,
        bundles=bundles,
        execution=execution,
        indexer=indexer,
        dashboard=dashboard,
        workspace=workspace,
        model=model,
    )


__all__ = [
    "RemoraConfig",
    "DiscoveryConfig",
    "BundleConfig",
    "ExecutionConfig",
    "IndexerConfig",
    "DashboardConfig",
    "WorkspaceConfig",
    "ModelConfig",
    "load_config",
    "LANGUAGES",
]
