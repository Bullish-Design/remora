"""
src/remora/config.py

Remora Configuration Module.

Configuration Precedence (Highest to Lowest):
1. CLI Arguments (e.g., --max-turns 5)
2. Operation-Specific Configs in remora.yaml (e.g., operations.lint.model_id)
3. Global Setting in remora.yaml (e.g., server.default_adapter)
4. Bundle Defaults (bundle.yaml in agent folder)
5. Pydantic Default Values
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import concurrent.futures
import os
import socket
import warnings
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from remora.errors import ConfigurationError
from remora.constants import CACHE_DIR
DEFAULT_CONFIG_FILENAME = "remora.yaml"


def _default_cache_dir() -> Path:
    cache_root = os.getenv("XDG_CACHE_HOME")
    if cache_root:
        return Path(cache_root) / "remora"
    return Path.home() / ".cache" / "remora"


def _default_event_output() -> Path:
    return _default_cache_dir() / "events.jsonl"


def _default_event_control() -> Path:
    return _default_cache_dir() / "events.control"


class ConfigError(ConfigurationError):
    pass


class RetryConfig(BaseModel):
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 30.0
    backoff_factor: float = 2.0


class ServerConfig(BaseModel):
    base_url: str = "http://remora-server:8000/v1"
    api_key: str = "EMPTY"
    timeout: int = 120
    default_adapter: str = "google/functiongemma-270m-it"
    default_plugin: str = "function_gemma"
    retry: RetryConfig = Field(default_factory=RetryConfig)


class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
    max_history_messages: int = 50


class OperationConfig(BaseModel):
    # extra="allow" is intentional: operation-specific keys (e.g. style="google")
    # are passed through to the subagent and are not validated by Remora.
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    auto_accept: bool = False
    subagent: str
    model_id: str | None = None
    model_plugin: str | None = None
    priority: Literal["low", "normal", "high"] = "normal"


class DiscoveryConfig(BaseModel):
    language: str = "python"
    query_pack: str = "remora_core"
    query_dir: Path | None = None  # None = use built-in queries inside the package


class CairnConfig(BaseModel):
    home: Path | None = None
    max_concurrent_agents: int = 16
    timeout: int = 300
    limits_preset: Literal["strict", "default", "permissive"] = "default"
    limits_override: dict[str, Any] = Field(default_factory=dict)
    pool_workers: int = 4  # ProcessPoolExecutor max_workers
    max_queue_size: int = 100
    workspace_cache_size: int = 100
    # Snapshot pause/resume (Phase 6)
    enable_snapshots: bool = False  # Opt-in: most tools don't need pause/resume
    max_snapshots: int = 50  # Max concurrent suspended scripts
    max_resumes_per_script: int = 5  # Safety cap per snapshot


class EventStreamConfig(BaseModel):
    enabled: bool = False
    output: Path | None = Field(default_factory=_default_event_output)
    control_file: Path | None = Field(default_factory=_default_event_control)
    include_payloads: bool = True
    max_payload_chars: int = 4000


class LlmLogConfig(BaseModel):
    enabled: bool = False
    output: Path | None = None  # defaults to {CACHE_DIR}/llm_conversations.log
    include_full_prompts: bool = False
    max_content_lines: int = 100


class WatchConfig(BaseModel):
    """Configuration for the 'remora watch' command."""

    extensions: set[str] = Field(default={".py"})
    ignore_patterns: list[str] = Field(
        default=[
            "__pycache__",
            ".git",
            ".jj",
            ".venv",
            "node_modules",
            CACHE_DIR,
            ".agentfs",
            ".remora",
        ]
    )
    debounce_ms: int = 500


class HubConfig(BaseModel):
    """Configuration for the Node State Hub daemon."""

    # Enable/disable modes
    mode: Literal["in-process", "daemon", "disabled"] = "disabled"

    # Database location (relative to project root)
    db_path: Path | None = None  # Default: .remora/hub.db

    # Indexing behavior
    index_on_startup: bool = True
    watch_for_changes: bool = True

    # Freshness thresholds
    stale_threshold_seconds: float = 5.0
    max_adhoc_files: int = 5

    # Ignore patterns (in addition to watch.ignore_patterns)
    additional_ignore_patterns: list[str] = Field(default_factory=list)

    # Cross-file analysis (Phase 2)
    enable_cross_file_analysis: bool = False
    cross_file_analysis_depth: int = 2  # How many hops to follow

    # Performance tuning
    batch_size: int = 50  # Files to index per batch
    index_delay_ms: int = 100  # Delay between batches

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


def _default_operations() -> dict[str, OperationConfig]:
    return {
        "lint": OperationConfig(subagent="lint"),
        "test": OperationConfig(subagent="test", priority="high"),
        "docstring": OperationConfig.model_validate({"subagent": "docstring", "style": "google"}),
        "sample_data": OperationConfig(
            subagent="sample_data",
            enabled=False,
        ),
    }


class RemoraConfig(BaseModel):
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    agents_dir: Path = Path("agents")
    server: ServerConfig = Field(default_factory=ServerConfig)
    operations: dict[str, OperationConfig] = Field(default_factory=_default_operations)
    runner: RunnerConfig = Field(default_factory=RunnerConfig)
    cairn: CairnConfig = Field(default_factory=CairnConfig)
    event_stream: EventStreamConfig = Field(default_factory=EventStreamConfig)
    llm_log: LlmLogConfig = Field(default_factory=LlmLogConfig)
    watch: WatchConfig = Field(default_factory=WatchConfig)
    hub: HubConfig = Field(default_factory=HubConfig)

    @model_validator(mode='after')
    def validate_and_resolve_precedence(self) -> "RemoraConfig":
        # 1. Resolve cairn.home vs agents_dir overrides
        # Ensure cairn has a home directory even if not explicitly provided, routing it 
        # to a hidden folder inside the agents_dir.
        if hasattr(self, 'cairn') and not self.cairn.home and hasattr(self, 'agents_dir') and self.agents_dir:
            self.cairn.home = self.agents_dir / ".cairn"
            
        # 2. Model Adapter precedence
        # For each operation, if it doesn't specify a model_id, inherit from server.default_adapter
        if hasattr(self, 'operations') and hasattr(self, 'server'):
            for op_name, op_config in self.operations.items():
                if getattr(op_config, 'model_id', None) is None:
                    op_config.model_id = self.server.default_adapter
                if getattr(op_config, 'model_plugin', None) is None:
                    op_config.model_plugin = self.server.default_plugin
                    
        return self


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
    _warn_unreachable_server(config.server)
    return config


def resolve_grail_limits(config: CairnConfig) -> dict[str, Any]:
    """Resolve Grail resource limits from config preset + overrides."""
    import grail.limits

    presets: dict[str, dict[str, Any]] = {
        "strict": grail.limits.STRICT,
        "default": grail.limits.DEFAULT,
        "permissive": grail.limits.PERMISSIVE,
    }
    base = presets[config.limits_preset].copy()
    base.update(config.limits_override)
    return base


def serialize_config(config: RemoraConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")


def _resolve_config_path(config_path: Path | None) -> Path | None:
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        return config_path
    default_path = Path.cwd() / DEFAULT_CONFIG_FILENAME
    return default_path if default_path.exists() else None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Failed to read config file: {path}") from exc
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file: {path}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError("Config file must define a mapping.")
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
        raise ConfigError(f"Agents directory not found: {agents_dir}")


def _warn_missing_subagents(config: RemoraConfig) -> None:
    for operation in config.operations.values():
        subagent_path = config.agents_dir / operation.subagent
        if not subagent_path.exists():
            warnings.warn(
                f"Subagent definition missing: {subagent_path}",
                stacklevel=2,
            )


def _warn_unreachable_server(server: ServerConfig) -> None:
    parsed = urlparse(server.base_url)
    hostname = parsed.hostname
    if hostname is None:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(socket.getaddrinfo, hostname, None)
        try:
            future.result(timeout=1.0)
        except (socket.gaierror, concurrent.futures.TimeoutError):
            warnings.warn(
                f"vLLM server hostname not reachable: {server.base_url}",
                stacklevel=2,
            )
