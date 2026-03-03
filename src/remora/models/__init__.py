"""Request/response models for the Remora service API."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel

from remora.core.config import Config, serialize_config


class SwarmEmitRequest(BaseModel):
    event_type: str
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SwarmEmitRequest":
        payload = dict(data or {})
        return cls(
            event_type=str(payload.get("event_type", "")).strip(),
            data=dict(payload.get("data", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class SwarmEmitResponse(BaseModel):
    event_id: int

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class InputResponse(BaseModel):
    request_id: str
    status: str = "submitted"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ConfigSnapshot(BaseModel):
    discovery: dict[str, Any]
    bundles: dict[str, Any]
    execution: dict[str, Any]
    workspace: dict[str, Any]
    model: dict[str, Any]
    swarm: dict[str, Any]

    @classmethod
    def from_config(cls, config: Config) -> "ConfigSnapshot":
        payload = serialize_config(config)
        return cls(
            discovery={
                "paths": payload.get("discovery_paths", []),
                "languages": payload.get("discovery_languages"),
                "max_workers": payload.get("discovery_max_workers", 4),
            },
            bundles={
                "path": payload.get("bundle_root", "agents"),
                "mapping": payload.get("bundle_mapping", {}),
            },
            execution={
                "max_concurrency": payload.get("max_concurrency", 4),
                "timeout": payload.get("timeout_s", 300.0),
                "max_turns": payload.get("max_turns", 8),
                "truncation_limit": payload.get("truncation_limit", 1024),
            },
            workspace={
                "ignore_patterns": payload.get("workspace_ignore_patterns", []),
                "ignore_dotfiles": payload.get("workspace_ignore_dotfiles", True),
            },
            model={
                "base_url": payload.get("model_base_url", "http://localhost:8000/v1"),
                "default_model": payload.get("model_default", "Qwen/Qwen3-4B"),
            },
            swarm={
                "max_trigger_depth": payload.get("max_trigger_depth", 5),
                "trigger_cooldown_ms": payload.get("trigger_cooldown_ms", 1000),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


__all__ = [
    "ConfigSnapshot",
    "InputResponse",
    "SwarmEmitRequest",
    "SwarmEmitResponse",
]
