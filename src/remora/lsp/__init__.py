# src/remora/lsp/__init__.py
from __future__ import annotations

from remora.lsp.models import (
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
)
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.watcher import ASTWatcher, inject_ids
from remora.lsp.server import RemoraLanguageServer


def main() -> None:
    """Entrypoint for `remora-lsp` command."""
    from remora.lsp.__main__ import main as _main

    _main()


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
    "main",
]
