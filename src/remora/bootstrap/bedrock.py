"""Bootstrap bedrock functions.

build_bedrock() creates the runtime external function map used by bootstrap
Grail tools.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from remora.core.agents.cairn_externals import CairnExternals


class BootstrapEvent(BaseModel):
    """Event envelope used by bootstrap event writes.

    Uses the same frozen Pydantic model style as core event types.
    """

    model_config = ConfigDict(frozen=True)

    event_type: str
    node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    from_agent: str | None = None
    to_agent: str | None = None
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()
    timestamp: float = Field(default_factory=time.time)


def build_bedrock(
    *,
    agent_id: str,
    cairn_externals: CairnExternals,
    event_store: Any,
    swarm_id: str,
) -> dict[str, Any]:
    """Build per-agent bootstrap bedrock functions."""

    node_store = event_store.nodes

    async def _cairn_read(path: str) -> str:
        return await cairn_externals.read_file(path) or ""

    async def _cairn_write(path: str, content: str) -> str:
        await cairn_externals.write_file(path, content)
        return "ok"

    async def _graph_read(selector: dict[str, Any]) -> str:
        return await node_store.read_graph(selector)

    async def _graph_write(op: str, data: dict[str, Any]) -> str:
        return await node_store.write_graph(op, data)

    async def _event_read(selector: dict[str, Any]) -> str:
        target_agent = str(selector.get("agent_id") or selector.get("node_id") or agent_id)
        limit = int(selector.get("limit", 10))
        events = await event_store.get_recent_events(target_agent, limit=limit)
        return json.dumps(events)

    async def _event_write(event_type: str, payload: dict[str, Any]) -> str:
        event = BootstrapEvent(
            event_type=event_type,
            node_id=payload.get("node_id"),
            payload=payload,
            from_agent=agent_id,
            to_agent=payload.get("to_agent"),
            correlation_id=payload.get("correlation_id"),
            tags=tuple(payload.get("tags", ())),
        )
        event_id = await event_store.append(swarm_id, event)
        return json.dumps({"event_id": event_id})

    return {
        "_cairn_read": _cairn_read,
        "_cairn_write": _cairn_write,
        "_graph_read": _graph_read,
        "_graph_write": _graph_write,
        "_event_read": _event_read,
        "_event_write": _event_write,
        # Grail currently cannot resolve external names that start with "_".
        # Provide underscore-free aliases for .pym tool declarations.
        "cairn_read": _cairn_read,
        "cairn_write": _cairn_write,
        "graph_read": _graph_read,
        "graph_write": _graph_write,
        "event_read": _event_read,
        "event_write": _event_write,
    }


async def make_files_provider(cairn_externals: CairnExternals) -> Callable[[], Awaitable[dict[str, str | bytes]]]:
    """Create a workspace files provider for Grail runtime usage.

    NOTE: This only lists immediate children under workspace root via
    ``list_dir(".")``. It is not recursive, so nested files are invisible.
    """

    async def files_provider() -> dict[str, str | bytes]:
        try:
            paths = await cairn_externals.list_dir(".")
        except Exception:
            return {}

        files: dict[str, str | bytes] = {}
        for path in paths or []:
            try:
                content = await cairn_externals.read_file(path)
            except Exception:
                continue
            files[path] = content
        return files

    return files_provider


async def extract_workspace_tools(cairn_externals: CairnExternals, tmp_dir: Path) -> Path:
    """Extract workspace tools from Cairn VFS into a real directory."""
    tools_dir = tmp_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    try:
        files = await cairn_externals.list_dir("tools")
    except Exception:
        return tools_dir

    for file_name in files or []:
        if not file_name.endswith(".pym"):
            continue
        try:
            content = await cairn_externals.read_file(f"tools/{file_name}")
        except Exception:
            continue
        if not content:
            continue
        (tools_dir / file_name).write_text(content, encoding="utf-8")
    return tools_dir


__all__ = [
    "BootstrapEvent",
    "build_bedrock",
    "make_files_provider",
    "extract_workspace_tools",
]
