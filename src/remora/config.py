"""Configuration management for Remora."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
import concurrent.futures
import os
import socket
import warnings
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field

from remora.errors import CONFIG_003, CONFIG_004

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


class ConfigError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    retry: RetryConfig = Field(default_factory=RetryConfig)


class RunnerConfig(BaseModel):
    max_turns: int = 20
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
    include_prompt_context: bool = False
    include_tool_guide: bool = True
    use_grammar_enforcement: bool = False


class OperationConfig(BaseModel):
    # extra="allow" is intentional: operation-specific keys (e.g. style="google")
    # are passed through to the subagent and are not validated by Remora.
    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    auto_accept: bool = False
    subagent: str
    model_id: str | None = None
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
    output: Path | None = None  # defaults to .remora_cache/llm_conversations.log
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
            ".remora_cache",
            ".agentfs",
        ]
    )
    debounce_ms: int = 500


def _default_operations() -> dict[str, OperationConfig]:
    return {
        "lint": OperationConfig(subagent="lint/lint_subagent.yaml"),
        "test": OperationConfig(subagent="test/test_subagent.yaml", priority="high"),
        "docstring": OperationConfig.model_validate(
            {"subagent": "docstring/docstring_subagent.yaml", "style": "google"}
        ),
        "sample_data": OperationConfig(
            subagent="sample_data/sample_data_subagent.yaml",
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
