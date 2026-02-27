"""Core configuration for Remora v0.4.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LANGUAGES: dict[str, str] = {
    ".py": "tree_sitter_python",
    ".pyi": "tree_sitter_python",
    ".toml": "tree_sitter_toml",
    ".md": "tree_sitter_markdown",
}


class ConfigError(Exception):
    """Raised when the configuration cannot be loaded or validated."""

    code = "CONFIG_ERROR"


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration for Cairn workspaces."""

    base_path: Path = Path(".remora/workspaces")
    cleanup_after: str = "1h"


@dataclass(frozen=True)
class BundleMetadata:
    """Describe how a bundle maps to node types and priorities."""

    bundle_name: str
    path: Path
    node_types: tuple[str, ...]
    priority: int = 0
    requires_context: bool = False


@dataclass(frozen=True)
class RemoraConfig:
    """Immutable representation of Remora project configuration."""

    model_base_url: str
    api_key: str
    bundle_metadata: dict[str, BundleMetadata] = field(default_factory=dict)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)


def load_config(config_path: Path | None = None) -> RemoraConfig:
    """Load `remora.yaml` with optional environment overrides."""
    if config_path is None:
        config_path = Path.cwd() / "remora.yaml"

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError("Config file must define a mapping.")

    raw = _apply_env_overrides(raw)
    return _build_config(raw)


def serialize_config(config: RemoraConfig) -> dict[str, Any]:
    """Return a JSON-serializable snapshot of the configuration."""
    return {
        "model_base_url": config.model_base_url,
        "api_key": config.api_key,
        "bundle_metadata": {
            name: {
                "path": str(metadata.path),
                "node_types": list(metadata.node_types),
                "priority": metadata.priority,
                "requires_context": metadata.requires_context,
            }
            for name, metadata in config.bundle_metadata.items()
        },
        "workspace": {
            "base_path": str(config.workspace.base_path),
            "cleanup_after": config.workspace.cleanup_after,
        },
    }


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply overrides from `REMORA_<PATH>__<KEY>=value` env vars."""

    import os

    def _assign(target: dict[str, Any], segments: list[str], value: Any) -> None:
        for segment in segments[:-1]:
            segment = segment.strip()
            if segment not in target or not isinstance(target[segment], dict):
                target[segment] = {}
            target = target[segment]  # type: ignore[assignment]
        target[segments[-1].strip()] = _parse_env_value(value)

    for key, value in os.environ.items():
        if not key.startswith("REMORA_"):
            continue
        segments = key[7:].split("__")
        if not segments:
            continue
        _assign(data, [segment.lower() for segment in segments], value)

    return data


def _parse_env_value(value: str) -> Any:
    """Convert environment value into bool/int/float when possible."""
    lowered = value.strip().lower()
    if lowered in ("true", "yes", "1"):
        return True
    if lowered in ("false", "no", "0"):
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
    """Construct a `RemoraConfig` from user data."""
    model_base_url = data.get("model_base_url", "http://localhost:8000/v1")
    api_key = data.get("api_key", "")

    workspace_raw = data.get("workspace", {})
    workspace = WorkspaceConfig(
        base_path=Path(workspace_raw.get("base_path", ".remora/workspaces")),
        cleanup_after=str(workspace_raw.get("cleanup_after", "1h")),
    )

    metadata_raw = data.get("bundle_metadata", {})
    bundle_metadata: dict[str, BundleMetadata] = {}
    for name, entry in metadata_raw.items():
        if not isinstance(entry, dict):
            continue
        node_types = entry.get("node_types", [])
        if isinstance(node_types, str):
            node_types = [node_types]
        bundle_metadata[name] = BundleMetadata(
            bundle_name=name,
            path=Path(entry.get("path", f"agents/{name}/bundle.yaml")),
            node_types=tuple(node_types),
            priority=int(entry.get("priority", 0)),
            requires_context=bool(entry.get("requires_context", False)),
        )

    return RemoraConfig(
        model_base_url=str(model_base_url),
        api_key=str(api_key),
        workspace=workspace,
        bundle_metadata=bundle_metadata,
    )


__all__ = [
    "BundleMetadata",
    "ConfigError",
    "RemoraConfig",
    "WorkspaceConfig",
    "load_config",
    "serialize_config",
]
