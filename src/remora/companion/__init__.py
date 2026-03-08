"""Remora companion - node-resident agent system."""

from remora.companion.config import CompanionConfig, IndexingConfig
from remora.companion.node_agent import NodeAgent, NodeAgentResponse, NodeMessage
from remora.companion.registry import NodeAgentRegistry
from remora.companion.startup import start_companion

__all__ = [
    "start_companion",
    "CompanionConfig",
    "IndexingConfig",
    "NodeAgentRegistry",
    "NodeAgent",
    "NodeMessage",
    "NodeAgentResponse",
]
