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
    import os
    import sys
    import time
    from dataclasses import dataclass
    from pathlib import Path

    from remora.lsp.__main__ import main as _main

    @dataclass
    class _WorkspaceProcessLock:
        lock_path: Path
        pid_path: Path
        handle: object | None = None

        def acquire(self) -> None:
            import fcntl

            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                owner_pid = self._read_owner_pid()
                handle.close()
                message = f"Another remora-lsp instance is already active for this workspace"
                if owner_pid:
                    message += f" (pid={owner_pid})"
                raise RuntimeError(message) from exc

            self.handle = handle
            self.pid_path.write_text(f"{os.getpid()}\n{int(time.time())}\n", encoding="utf-8")

        def release(self) -> None:
            if self.handle is None:
                return
            try:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.handle.close()
            finally:
                self.handle = None
            try:
                self.pid_path.unlink(missing_ok=True)
            except Exception:
                pass

        def _read_owner_pid(self) -> int | None:
            try:
                line = self.pid_path.read_text(encoding="utf-8").splitlines()[0].strip()
                return int(line)
            except Exception:
                return None

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
        await event_store.checkpoint_wal("PASSIVE")

        event_store.set_subscriptions(subscriptions)
        event_store.set_event_bus(event_bus)

        return event_store, subscriptions

    root = Path.cwd()
    swarm_path = root / ".remora"
    process_lock = _WorkspaceProcessLock(
        lock_path=swarm_path / "lsp.lock",
        pid_path=swarm_path / "lsp.pid",
    )
    try:
        process_lock.acquire()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc

    try:
        event_store, subscriptions = asyncio.run(_prepare())
        _main(
            event_store=event_store,
            subscriptions=subscriptions,
        )
    finally:
        process_lock.release()


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
