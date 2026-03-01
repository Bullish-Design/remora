# demo/core/__init__.py
"""Demo core module - re-exports from src/remora/lsp for backward compatibility."""

from remora.lsp import (
    ASTAgentNode,
    ToolSchema,
    RewriteProposal,
    AgentEvent,
    HumanChatEvent,
    AgentMessageEvent,
    RewriteProposalEvent,
    RewriteAppliedEvent,
    RewriteRejectedEvent,
    AgentErrorEvent,
    generate_id,
    RemoraDB,
    LazyGraph,
    ASTWatcher,
    inject_ids,
)

__all__ = [
    "ASTAgentNode",
    "ToolSchema",
    "RewriteProposal",
    "AgentEvent",
    "HumanChatEvent",
    "AgentMessageEvent",
    "RewriteProposalEvent",
    "RewriteAppliedEvent",
    "RewriteRejectedEvent",
    "AgentErrorEvent",
    "generate_id",
    "RemoraDB",
    "LazyGraph",
    "ASTWatcher",
    "inject_ids",
]
