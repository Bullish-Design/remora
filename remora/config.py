"""Configuration management for Remora."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import warnings

import yaml
from pydantic import BaseModel, ConfigDict, Field

from remora.errors import CONFIG_003, CONFIG_004

DEFAULT_CONFIG_FILENAME = "remora.yaml"


class ConfigError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_concurrent_runners: int = 4
    timeout: int = 300


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    auto_accept: bool = False
    subagent: str
    model_id: str | None = None


class CairnConfig(BaseModel):
    timeout: int = 120


def _default_operations() -> dict[str, OperationConfig]:
    return {
        "lint": OperationConfig(subagent="lint/lint_subagent.yaml"),
        "test": OperationConfig(subagent="test/test_subagent.yaml"),
        "docstring": OperationConfig.model_validate(
            {"subagent": "docstring/docstring_subagent.yaml", "style": "google"}
        ),
        "sample_data": OperationConfig(
            subagent="sample_data/sample_data_subagent.yaml",
            enabled=False,
        ),
    }


class RemoraConfig(BaseModel):
    root_dirs: list[Path] = Field(default_factory=lambda: [Path(".")])
    queries: list[str] = Field(default_factory=lambda: ["function_def", "class_def"])
    agents_dir: Path = Path("agents")
    model_id: str = "ollama/functiongemma-4b-it"
    operations: dict[str, OperationConfig] = Field(default_factory=_default_operations)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    cairn: CairnConfig = Field(default_factory=CairnConfig)


def load_config(config_path: Path | None = None, overrides: dict[str, Any] | None = None) -> RemoraConfig:
    resolved_path = _resolve_config_path(config_path)
    base_dir = resolved_path.parent if resolved_path else Path.cwd()
    data: dict[str, Any] = {}
    if resolved_path is not None:
        data = _load_yaml(resolved_path)
    if overrides:
        data = _deep_update(data, overrides)
    config = RemoraConfig.model_validate(data)
    config = _resolve_agents_dir(config, base_dir)
    _ensure_agents_dir(config.agents_dir)
    _warn_missing_subagents(config)
    return config


def serialize_config(config: RemoraConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def _resolve_config_path(config_path: Path | None) -> Path | None:
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(CONFIG_003, f"Config file not found: {config_path}")
        return config_path
    default_path = Path.cwd() / DEFAULT_CONFIG_FILENAME
    return default_path if default_path.exists() else None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(CONFIG_003, f"Failed to read config file: {path}") from exc
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(CONFIG_003, f"Invalid YAML in config file: {path}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(CONFIG_003, "Config file must define a mapping.")
    return data


def _deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_update(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_agents_dir(config: RemoraConfig, base_dir: Path) -> RemoraConfig:
    agents_dir = config.agents_dir
    if not agents_dir.is_absolute():
        agents_dir = (base_dir / agents_dir).resolve()
    return config.model_copy(update={"agents_dir": agents_dir})


def _ensure_agents_dir(agents_dir: Path) -> None:
    if not agents_dir.exists():
        raise ConfigError(CONFIG_004, f"Agents directory not found: {agents_dir}")


def _warn_missing_subagents(config: RemoraConfig) -> None:
    for operation in config.operations.values():
        subagent_path = config.agents_dir / operation.subagent
        if not subagent_path.exists():
            warnings.warn(
                f"Subagent definition missing: {subagent_path}",
                stacklevel=2,
            )
