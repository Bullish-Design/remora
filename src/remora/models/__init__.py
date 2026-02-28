"""Request/response models for the Remora service API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from remora.core.config import RemoraConfig, serialize_config


def _from_mapping(data: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(data or {})


@dataclass(slots=True)
class SwarmEmitRequest:
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
        return asdict(self)


@dataclass(slots=True)
class SwarmEmitResponse:
    event_id: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InputResponse:
    request_id: str
    status: str = "submitted"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConfigSnapshot:
    discovery: dict[str, Any]
    bundles: dict[str, Any]
    execution: dict[str, Any]
    workspace: dict[str, Any]
    model: dict[str, Any]
    swarm: dict[str, Any]

    @classmethod
    def from_config(cls, config: RemoraConfig) -> "ConfigSnapshot":
        payload = serialize_config(config)
        model = dict(payload.get("model", {}))
        model.pop("api_key", None)
        return cls(
            discovery=dict(payload.get("discovery", {})),
            bundles=dict(payload.get("bundles", {})),
            execution=dict(payload.get("execution", {})),
            workspace=dict(payload.get("workspace", {})),
            model=model,
            swarm=dict(payload.get("swarm", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ConfigSnapshot",
    "InputResponse",
    "SwarmEmitRequest",
    "SwarmEmitResponse",
]
