"""Core contracts for bootstrap-native tools, agents, and templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(slots=True, frozen=True)
class BootstrapTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


@dataclass(slots=True, frozen=True)
class BootstrapAgent:
    name: str
    description: str
    node_types: tuple[str, ...] = field(default_factory=tuple)
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class BootstrapTemplate:
    name: str
    description: str
    body: str
