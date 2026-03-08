"""Remora companion - node-resident agent system.

Intentionally avoids eager imports so LSP startup does not pull heavy
companion dependencies until they are explicitly used.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "start_companion",
    "CompanionConfig",
    "IndexingConfig",
    "NodeAgentRegistry",
    "NodeAgent",
    "NodeMessage",
    "NodeAgentResponse",
]


def __getattr__(name: str) -> Any:
    if name in {"CompanionConfig", "IndexingConfig"}:
        from remora.companion.config import CompanionConfig, IndexingConfig

        return {"CompanionConfig": CompanionConfig, "IndexingConfig": IndexingConfig}[name]
    if name in {"NodeAgent", "NodeAgentResponse", "NodeMessage"}:
        from remora.companion.node_agent import NodeAgent, NodeAgentResponse, NodeMessage

        return {"NodeAgent": NodeAgent, "NodeAgentResponse": NodeAgentResponse, "NodeMessage": NodeMessage}[name]
    if name == "NodeAgentRegistry":
        from remora.companion.registry import NodeAgentRegistry

        return NodeAgentRegistry
    if name == "start_companion":
        from remora.companion.startup import start_companion

        return start_companion
    raise AttributeError(name)
