"""Request/response models for the Remora service API."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from remora.core.config import RemoraConfig, serialize_config


def _from_mapping(data: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(data or {})


@dataclass(slots=True)
class RunRequest:
    target_path: str
    bundle: str | None = None
    graph_id: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunRequest":
        payload = _from_mapping(data)
        return cls(
            target_path=str(payload.get("target_path", "")).strip(),
            bundle=payload.get("bundle"),
            graph_id=payload.get("graph_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RunResponse:
    graph_id: str
    status: str
    node_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InputResponse:
    request_id: str
    status: str = "submitted"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanRequest:
    target_path: str
    bundle: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanRequest":
        payload = _from_mapping(data)
        return cls(
            target_path=str(payload.get("target_path", "")).strip(),
            bundle=payload.get("bundle"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanResponse:
    nodes: list[dict[str, Any]]
    bundles: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConfigSnapshot:
    discovery: dict[str, Any]
    bundles: dict[str, Any]
    execution: dict[str, Any]
    workspace: dict[str, Any]
    model: dict[str, Any]

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
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "ConfigSnapshot",
    "InputResponse",
    "PlanRequest",
    "PlanResponse",
    "RunRequest",
    "RunResponse",
]
