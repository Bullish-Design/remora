# demo/__init__.py
"""Demo package - re-exports from src/remora/lsp for backward compatibility."""

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
    RemoraLanguageServer,
)

__version__ = "2.1.0"

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
    "RemoraLanguageServer",
]
