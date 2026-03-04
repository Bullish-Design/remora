# src/remora/lsp/__init__.py
from __future__ import annotations

from remora.core.agent_node import AgentNode, ToolSchema
from remora.lsp.models import (
    RewriteProposal,
    LspAgentEvent,
    LspHumanChatEvent,
    LspAgentMessageEvent,
    LspRewriteProposalEvent,
    LspRewriteAppliedEvent,
    LspRewriteRejectedEvent,
    LspAgentErrorEvent,
    generate_id,
)
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph
from remora.lsp.watcher import ASTWatcher, inject_ids
from remora.lsp.server import RemoraLanguageServer


def main() -> None:
    """Entrypoint for ``remora-lsp`` command (spawned by Neovim).

    Creates an EventStore + SubscriptionRegistry before handing off to
    the real server loop.  Without this the LSP server starts with
    ``event_store=None`` and every command that tries to resolve an
    agent fails with "no event_store available".
    """
    import asyncio
    from pathlib import Path

    from remora.lsp.__main__ import main as _main

    async def _prepare():
        from remora.core.event_bus import EventBus
        from remora.core.event_store import EventStore
        from remora.core.projections import NodeProjection
        from remora.core.subscriptions import SubscriptionRegistry

        root = Path.cwd()
        swarm_path = root / ".remora"
        event_store_path = swarm_path / "events" / "events.db"
        subscriptions_path = swarm_path / "subscriptions.db"

        event_bus = EventBus()
        subscriptions = SubscriptionRegistry(subscriptions_path)
        projection = NodeProjection()
        event_store = EventStore(
            event_store_path,
            subscriptions=subscriptions,
            event_bus=event_bus,
            projection=projection,
        )

        await event_store.initialize()
        await subscriptions.initialize()

        event_store.set_subscriptions(subscriptions)
        event_store.set_event_bus(event_bus)

        return event_store, subscriptions

    event_store, subscriptions = asyncio.run(_prepare())

    _main(
        event_store=event_store,
        subscriptions=subscriptions,
    )


__all__ = [
    "AgentNode",
    "ToolSchema",
    "RewriteProposal",
    "LspAgentEvent",
    "LspHumanChatEvent",
    "LspAgentMessageEvent",
    "LspRewriteProposalEvent",
    "LspRewriteAppliedEvent",
    "LspRewriteRejectedEvent",
    "LspAgentErrorEvent",
    "generate_id",
    "RemoraDB",
    "LazyGraph",
    "ASTWatcher",
    "inject_ids",
    "RemoraLanguageServer",
    "main",
]
