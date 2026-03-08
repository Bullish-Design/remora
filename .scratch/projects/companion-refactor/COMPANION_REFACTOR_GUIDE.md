# Companion Refactor — Implementation Guide

**Audience:** Junior developer implementing the node-resident agent companion from scratch.
**Concept doc:** Read `COMPANION_REFACTOR_CONCEPT.md` first — this guide is the implementation
of that concept, not a re-explanation of the why.

> **NO BACKWARDS COMPATIBILITY.** Delete everything old. Write everything new clean.
> **NO SUBAGENTS.** Do all work directly.

---

## Table of Contents

| Phase | What | Files |
|-------|------|-------|
| [Phase 0](#phase-0-delete-everything-old) | Delete old companion code | (deletions) |
| [Phase 1](#phase-1-new-events-module) | New events module | `companion/events.py` |
| [Phase 2](#phase-2-new-config) | New config | `companion/config.py` |
| [Phase 3](#phase-3-node-workspace-conventions) | Workspace layout + types | `companion/node_workspace.py` |
| [Phase 4](#phase-4-microswarms) | MicroSwarm pipeline | `companion/swarms/` |
| [Phase 5](#phase-5-cross-node-links) | Link types + resolver | `companion/links/` |
| [Phase 6](#phase-6-sidebar-composer) | Sidebar composer | `companion/sidebar/` |
| [Phase 7](#phase-7-nodeagent) | NodeAgent core class | `companion/node_agent.py` |
| [Phase 8](#phase-8-nodeagentregistry) | Agent pool + LRU | `companion/registry.py` |
| [Phase 9](#phase-9-nodeagentrouter) | EventBus routing | `companion/router.py` |
| [Phase 10](#phase-10-startup-and-package-init) | Startup + package init | `companion/startup.py`, `companion/__init__.py` |
| [Phase 11](#phase-11-lsp-integration) | LSP command handlers | `lsp/handlers/companion.py`, `lsp/server_setup.py` |
| [Phase 12](#phase-12-main-wiring) | Wire Cairn + registry into server | `lsp/__main__.py` |
| [Phase 13](#phase-13-tests) | Unit tests | `tests/unit/companion/` |
| [Phase 14](#phase-14-neovim-plugin) | Neovim companion plugin | `remora_demo/companion/nvim/` |
| [Phase 15](#phase-15-acceptance-criteria) | Verification checklist | — |

---

## Orientation: What You Are NOT Touching

These files are infrastructure. Do not modify them. Read them to understand the APIs you build on.

| File | What it provides |
|------|-----------------|
| `src/remora/core/agents/agent_node.py` | `AgentNode` — identity model for every CST node |
| `src/remora/core/agents/cairn_bridge.py` | `CairnWorkspaceService` — creates/manages Cairn workspaces |
| `src/remora/core/agents/workspace.py` | `AgentWorkspace` — file read/write abstraction over Cairn |
| `src/remora/core/agents/kernel_factory.py` | `create_kernel()` — creates LLM `AgentKernel` instances |
| `src/remora/core/events/event_bus.py` | `EventBus` — in-process pub/sub |
| `src/remora/core/events/event_store.py` | `EventStore` — SQLite-backed append-only event log |
| `src/remora/core/events/agent_events.py` | `_FrozenEvent` — base class for all events |
| `src/remora/core/events/interaction_events.py` | `CursorFocusEvent`, `ContentChangedEvent`, `FileSavedEvent` |
| `src/remora/companion/indexing_service.py` | `IndexingService` — vector search via embeddy |

Key facts to internalize before writing any code:

1. `CursorFocusEvent.focused_agent_id` is already the **node_id** string of whichever CST node
   the cursor is on. Your router does not need to resolve anything — use it directly.

2. `CairnWorkspaceService.get_agent_workspace(agent_id)` returns an `AgentWorkspace` keyed by
   `agent_id`. For node agents, `agent_id = node_id`. Workspaces persist on disk between sessions.

3. `AgentWorkspace` supports: `read(path)`, `write(path, content)`, `exists(path)`,
   `list_dir(path)`, `delete(path)`. All paths are relative within the workspace virtual FS.

4. `create_kernel(model_name, base_url, api_key, tools, observer)` returns an `AgentKernel`
   with a `.run(messages, tool_schemas, max_turns)` method.

5. `_FrozenEvent` is a Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True)`.
   All events must subclass it.

---

## Phase 0: Delete Everything Old

Run these commands from the repo root. No partial deletions — everything listed here is dead code.

```bash
# Delete old companion handlers (all 10 files)
git rm -r src/remora/companion/handlers/

# Delete old companion core files
git rm src/remora/companion/dispatcher.py
git rm src/remora/companion/state.py
git rm src/remora/companion/startup.py
git rm src/remora/companion/events.py
git rm src/remora/companion/config.py

# Delete standalone ChatSession (replaced by NodeAgent.send())
git rm src/remora/core/agents/chat.py

# Delete old demo companion (entire directory)
git rm -r remora_demo/companion/

# Keep: src/remora/companion/__init__.py (will be rewritten)
# Keep: src/remora/companion/indexing_service.py (still used)
```

After deletion, confirm the directory state:

```bash
ls src/remora/companion/
# Expected: __init__.py  indexing_service.py
```

Run the test suite. Some tests will fail (those that imported deleted modules). That is expected.
Record which tests fail — they will be fixed or replaced in Phase 13.

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q 2>&1 | grep FAILED
```

---

## Phase 1: New Events Module

**File:** `src/remora/companion/events.py`

Replace the old Companion* event hierarchy with NodeAgent* events. These events represent
things that happen TO or WITHIN a node agent, not steps in a signal processing pipeline.

```python
"""NodeAgent event types for the companion system.

All events extend _FrozenEvent (Pydantic, frozen, timestamped).
These are emitted on the EventBus so the LSP server can react to them.
"""
from __future__ import annotations

import time
from pydantic import Field
from remora.core.events.agent_events import _FrozenEvent


class NodeAgentSidebarReady(_FrozenEvent):
    """Emitted when a node agent has composed its sidebar content.

    The LSP server subscribes to this event to push
    $/remora/companionSidebarUpdated to the Neovim client.
    """
    node_id: str
    markdown: str
    timestamp: float = Field(default_factory=time.time)


class NodeAgentExchangeIndexed(_FrozenEvent):
    """Emitted by SummarizerSwarm after indexing a chat exchange.

    The summary and tags are written into the node's workspace
    chat/index.json and also emitted here for observability.
    """
    node_id: str
    session_id: str
    summary: str
    tags: tuple[str, ...] = ()
    timestamp: float = Field(default_factory=time.time)


class NodeAgentLinkDiscovered(_FrozenEvent):
    """Emitted by LinkerSwarm when a cross-node connection is found.

    Written to the source node's links/links.json workspace file
    and also emitted on the EventBus for observability.
    """
    source_node_id: str
    target_node_id: str
    relationship: str
    confidence: float
    note: str = ""
    timestamp: float = Field(default_factory=time.time)


class NodeAgentNoteUpdated(_FrozenEvent):
    """Emitted by ReflectionSwarm after updating notes/agent_notes.md.

    note_type is one of: "agent_notes", "guide_understanding",
    "guide_refactoring", "guide_pitfalls".
    """
    node_id: str
    note_type: str
    timestamp: float = Field(default_factory=time.time)


class NodeAgentMessageReceived(_FrozenEvent):
    """Emitted when an agent receives an inter-agent message.

    Used by the LSP server to optionally notify the user that
    another node's agent sent a message.
    """
    target_node_id: str
    from_node_id: str
    content: str
    timestamp: float = Field(default_factory=time.time)


__all__ = [
    "NodeAgentSidebarReady",
    "NodeAgentExchangeIndexed",
    "NodeAgentLinkDiscovered",
    "NodeAgentNoteUpdated",
    "NodeAgentMessageReceived",
]
```

---

## Phase 2: New Config

**File:** `src/remora/companion/config.py`

Cairn is no longer optional. `CairnWorkspaceService` is passed directly to `start_companion()`,
not buried in config. Config only holds companion-specific tuning parameters.

```python
"""Configuration for the companion node-agent system."""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field

from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig


class IndexingConfig(BaseModel):
    """Vector search configuration (wraps embeddy)."""
    embedder: EmbedderConfig = Field(
        default_factory=lambda: EmbedderConfig(mode="remote")
    )
    store: StoreConfig = Field(
        default_factory=lambda: StoreConfig(db_path=".companion/vectors.db")
    )
    chunk: ChunkConfig = Field(default_factory=ChunkConfig)
    collections: dict[str, str] = Field(default_factory=lambda: {
        "python": "python",
        "markdown": "markdown",
        "config": "config",
    })


class CompanionConfig(BaseModel):
    """Configuration for the companion system.

    Note: CairnWorkspaceService is NOT in this config — it is a required
    argument to start_companion() because it must be shared with the rest
    of the LSP server. Do not add cairn_service here.
    """
    workspace_path: Path = Field(default_factory=Path.cwd)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    auto_index: bool = True
    max_active_agents: int = 20
    agent_idle_timeout_s: float = 300.0
    # LLM settings for node agent chat
    model_name: str = "Qwen/Qwen3-4B"
    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = ""
    max_turns_per_message: int = 10


__all__ = ["CompanionConfig", "IndexingConfig"]
```

---

## Phase 3: Node Workspace Conventions

**File:** `src/remora/companion/node_workspace.py`

All workspace path conventions live in one place. Every other module imports paths from here
rather than hardcoding strings. This makes the layout easy to change in one edit.

```python
"""Node workspace layout conventions and helpers.

Every NodeAgent has a Cairn AgentWorkspace keyed by node_id.
All paths within that workspace follow the conventions defined here.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from remora.core.agents.workspace import AgentWorkspace


# ─── Path constants ───────────────────────────────────────────────────────────

META               = "meta.json"
USER_NOTES         = "notes/user_notes.md"
AGENT_NOTES        = "notes/agent_notes.md"
CHAT_INDEX         = "chat/index.json"
LINKS              = "links/links.json"
CONTEXT_LATEST     = "context/latest_extraction.json"
SOURCE_SNAPSHOT    = "context/source_snapshot.md"

# Parameterized paths (use as f-strings):
# chat/{session_id}.md           — full conversation transcript
# guides/{name}.md               — agent-authored guide (understanding, refactoring, pitfalls)
# scripts/{name}.py              — agent-created utility script
# inbox/{from_node_id}_{ts}.md   — inter-agent inbox message


# ─── Data types ───────────────────────────────────────────────────────────────

@dataclass
class ChatIndexEntry:
    session_id: str
    timestamp: float
    summary: str
    tags: list[str] = field(default_factory=list)
    turn_count: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "tags": self.tags,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatIndexEntry":
        return cls(
            session_id=d["session_id"],
            timestamp=d.get("timestamp", 0.0),
            summary=d.get("summary", ""),
            tags=d.get("tags", []),
            turn_count=d.get("turn_count", 0),
        )


@dataclass
class NodeMeta:
    node_id: str
    node_type: str
    name: str
    file_path: str
    first_seen: float = field(default_factory=time.time)
    last_visited: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "name": self.name,
            "file_path": self.file_path,
            "first_seen": self.first_seen,
            "last_visited": self.last_visited,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NodeMeta":
        return cls(**d)


# ─── Workspace helpers ────────────────────────────────────────────────────────

async def read_json(workspace: AgentWorkspace, path: str) -> Any:
    """Read and parse a JSON file from the workspace. Returns None if missing."""
    try:
        text = await workspace.read(path)
        return json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def write_json(workspace: AgentWorkspace, path: str, data: Any) -> None:
    """Serialize data to JSON and write to workspace."""
    await workspace.write(path, json.dumps(data, indent=2))


async def read_text(workspace: AgentWorkspace, path: str, default: str = "") -> str:
    """Read a text file from the workspace. Returns default if missing."""
    try:
        return await workspace.read(path)
    except FileNotFoundError:
        return default


async def append_text(workspace: AgentWorkspace, path: str, content: str) -> None:
    """Append content to a text file in the workspace."""
    existing = await read_text(workspace, path)
    await workspace.write(path, existing + content)


async def load_chat_index(workspace: AgentWorkspace) -> list[ChatIndexEntry]:
    """Load the chat session index from workspace."""
    raw = await read_json(workspace, CHAT_INDEX)
    if not raw:
        return []
    return [ChatIndexEntry.from_dict(e) for e in raw]


async def save_chat_index(workspace: AgentWorkspace, index: list[ChatIndexEntry]) -> None:
    """Save the chat session index to workspace."""
    await write_json(workspace, CHAT_INDEX, [e.to_dict() for e in index])


async def ensure_meta(workspace: AgentWorkspace, node_id: str, node_type: str,
                       name: str, file_path: str) -> NodeMeta:
    """Create or load node metadata. Updates last_visited on each call."""
    raw = await read_json(workspace, META)
    if raw:
        meta = NodeMeta.from_dict(raw)
        meta.last_visited = time.time()
    else:
        meta = NodeMeta(
            node_id=node_id, node_type=node_type, name=name, file_path=file_path
        )
    await write_json(workspace, META, meta.to_dict())
    return meta


__all__ = [
    "META", "USER_NOTES", "AGENT_NOTES", "CHAT_INDEX", "LINKS",
    "CONTEXT_LATEST", "SOURCE_SNAPSHOT",
    "ChatIndexEntry", "NodeMeta",
    "read_json", "write_json", "read_text", "append_text",
    "load_chat_index", "save_chat_index", "ensure_meta",
]
```

---

## Phase 4: MicroSwarms

MicroSwarms are small async functions that run after every chat exchange. They are
non-blocking — they run via `asyncio.create_task()` and write results into the node's workspace.

### `src/remora/companion/swarms/__init__.py`

```python
from remora.companion.swarms.base import SwarmContext, run_post_exchange_swarms
from remora.companion.swarms.summarizer import SummarizerSwarm
from remora.companion.swarms.categorizer import CategorizerSwarm
from remora.companion.swarms.linker import LinkerSwarm
from remora.companion.swarms.reflection import ReflectionSwarm

__all__ = [
    "SwarmContext",
    "run_post_exchange_swarms",
    "SummarizerSwarm",
    "CategorizerSwarm",
    "LinkerSwarm",
    "ReflectionSwarm",
]
```

### `src/remora/companion/swarms/base.py`

```python
"""MicroSwarm base types and orchestrator."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace
    from remora.core.events.event_bus import EventBus

logger = logging.getLogger("remora.companion.swarms")


@dataclass
class SwarmContext:
    """All context a MicroSwarm might need."""
    node_id: str
    node: "AgentNode"
    workspace: "AgentWorkspace"
    session_id: str
    user_message: str
    assistant_message: str
    event_bus: "EventBus"
    model_name: str
    model_base_url: str
    model_api_key: str


class MicroSwarm(Protocol):
    """Protocol for MicroSwarm implementations."""
    async def run(self, ctx: SwarmContext) -> None: ...


async def run_post_exchange_swarms(
    ctx: SwarmContext,
    swarms: list[MicroSwarm],
) -> None:
    """Run all swarms in parallel. Failures are logged and ignored."""
    async def _run_one(swarm: MicroSwarm) -> None:
        try:
            await swarm.run(ctx)
        except Exception:
            logger.exception(
                "MicroSwarm %s failed for node %s",
                type(swarm).__name__, ctx.node_id
            )

    await asyncio.gather(*[_run_one(s) for s in swarms])


__all__ = ["SwarmContext", "MicroSwarm", "run_post_exchange_swarms"]
```

### `src/remora/companion/swarms/summarizer.py`

The summarizer writes one entry to `chat/index.json` per exchange.

```python
"""SummarizerSwarm — indexes chat exchanges with a summary."""
from __future__ import annotations

import time
import uuid

from remora.companion.swarms.base import SwarmContext
from remora.companion.node_workspace import (
    load_chat_index, save_chat_index, write_text, ChatIndexEntry,
)
from remora.companion.events import NodeAgentExchangeIndexed
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

SUMMARY_SYSTEM = """You summarize a chat exchange between a developer and a code node agent.
Output a single sentence (max 120 chars) describing what was discussed or accomplished.
Output ONLY the sentence, no preamble."""


class SummarizerSwarm:
    async def run(self, ctx: SwarmContext) -> None:
        exchange_text = f"User: {ctx.user_message}\n\nAgent: {ctx.assistant_message}"

        # Use LLM to generate summary
        kernel = create_kernel(
            model_name=ctx.model_name,
            base_url=ctx.model_base_url,
            api_key=ctx.model_api_key or "EMPTY",
        )
        try:
            messages = [
                KernelMessage(role="system", content=SUMMARY_SYSTEM),
                KernelMessage(role="user", content=exchange_text),
            ]
            result = await kernel.run(messages, [], max_turns=1)
            summary = (result.final_message.content or "").strip()[:120]
        finally:
            await kernel.close()

        if not summary:
            summary = ctx.user_message[:80]

        # Append to chat index
        index = await load_chat_index(ctx.workspace)
        entry = ChatIndexEntry(
            session_id=ctx.session_id,
            timestamp=time.time(),
            summary=summary,
            turn_count=1,
        )
        index.append(entry)
        await save_chat_index(ctx.workspace, index)

        # Emit event
        await ctx.event_bus.emit(NodeAgentExchangeIndexed(
            node_id=ctx.node_id,
            session_id=ctx.session_id,
            summary=summary,
        ))
```

### `src/remora/companion/swarms/categorizer.py`

Categorizer adds structured tags to the most recent chat index entry.

```python
"""CategorizerSwarm — tags chat exchanges."""
from __future__ import annotations

import json

from remora.companion.swarms.base import SwarmContext
from remora.companion.node_workspace import load_chat_index, save_chat_index
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

VALID_TAGS = [
    "bug", "question", "refactor", "explanation", "debugging",
    "test", "documentation", "performance", "design", "tooling",
    "edge_case", "insight", "todo", "warning",
]

CATEGORIZER_SYSTEM = f"""You categorize a chat exchange between a developer and a code agent.
Output a JSON array of 1-3 tags from this list:
{json.dumps(VALID_TAGS)}
Output ONLY the JSON array, nothing else. Example: ["bug", "debugging"]"""


class CategorizerSwarm:
    async def run(self, ctx: SwarmContext) -> None:
        exchange_text = f"User: {ctx.user_message}\n\nAgent: {ctx.assistant_message}"

        kernel = create_kernel(
            model_name=ctx.model_name,
            base_url=ctx.model_base_url,
            api_key=ctx.model_api_key or "EMPTY",
        )
        try:
            messages = [
                KernelMessage(role="system", content=CATEGORIZER_SYSTEM),
                KernelMessage(role="user", content=exchange_text),
            ]
            result = await kernel.run(messages, [], max_turns=1)
            raw = (result.final_message.content or "").strip()
            tags = json.loads(raw)
            if not isinstance(tags, list):
                tags = []
            tags = [t for t in tags if t in VALID_TAGS][:3]
        except Exception:
            tags = []
        finally:
            await kernel.close()

        if not tags:
            return

        # Update the most recent index entry for this session
        index = await load_chat_index(ctx.workspace)
        for entry in reversed(index):
            if entry.session_id == ctx.session_id:
                entry.tags = list(set(entry.tags + tags))
                break
        await save_chat_index(ctx.workspace, index)
```

### `src/remora/companion/swarms/linker.py`

LinkerSwarm uses text matching (not LLM) to find cross-node connections mentioned in the exchange.
This is intentionally cheap — it runs on every exchange.

```python
"""LinkerSwarm — discovers cross-node links from exchange text."""
from __future__ import annotations

import json
import time

from remora.companion.swarms.base import SwarmContext
from remora.companion.node_workspace import read_json, write_json, LINKS
from remora.companion.events import NodeAgentLinkDiscovered


class LinkerSwarm:
    """Find node references in the exchange and write them to links.json.

    v1 uses simple text matching. The exchange text is scanned for
    node_id patterns and known file paths. Future version can use LLM.
    """

    async def run(self, ctx: SwarmContext) -> None:
        exchange_text = ctx.user_message + "\n" + ctx.assistant_message

        # Load existing links to avoid duplicates
        raw = await read_json(ctx.workspace, LINKS) or []
        existing_targets = {(l.get("target_node_id"), l.get("relationship")) for l in raw}

        new_links = []

        # Pattern: "test_{function_name}" in a test file → tested_by relationship
        node_name = ctx.node.name
        test_node_pattern = f"test_{node_name}"
        if test_node_pattern.lower() in exchange_text.lower():
            key = (test_node_pattern, "tested_by")
            if key not in existing_targets:
                new_links.append({
                    "target_node_id": test_node_pattern,
                    "relationship": "tested_by",
                    "confidence": 0.6,
                    "note": "Mentioned in exchange",
                    "timestamp": time.time(),
                })

        if not new_links:
            return

        raw.extend(new_links)
        await write_json(ctx.workspace, LINKS, raw)

        for link in new_links:
            await ctx.event_bus.emit(NodeAgentLinkDiscovered(
                source_node_id=ctx.node_id,
                target_node_id=link["target_node_id"],
                relationship=link["relationship"],
                confidence=link["confidence"],
                note=link.get("note", ""),
            ))
```

### `src/remora/companion/swarms/reflection.py`

ReflectionSwarm writes an agent observation to `notes/agent_notes.md`. Only runs when the
exchange is substantive (≥100 chars total) to avoid noise.

```python
"""ReflectionSwarm — distills agent observations into notes/agent_notes.md."""
from __future__ import annotations

import time

from remora.companion.swarms.base import SwarmContext
from remora.companion.node_workspace import read_text, append_text, AGENT_NOTES
from remora.companion.events import NodeAgentNoteUpdated
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

REFLECTION_SYSTEM = """You are observing a conversation between a developer and a code agent.
Extract ONE concrete insight, concern, or recommendation revealed by this exchange.
The insight should be useful to remember for future conversations about this code node.
Write it as a single bullet point starting with "- ".
If there is nothing noteworthy, output exactly: SKIP"""


class ReflectionSwarm:
    async def run(self, ctx: SwarmContext) -> None:
        total_len = len(ctx.user_message) + len(ctx.assistant_message)
        if total_len < 100:
            return  # Not substantive enough to reflect on

        exchange_text = f"User: {ctx.user_message}\n\nAgent: {ctx.assistant_message}"
        existing_notes = await read_text(ctx.workspace, AGENT_NOTES)

        kernel = create_kernel(
            model_name=ctx.model_name,
            base_url=ctx.model_base_url,
            api_key=ctx.model_api_key or "EMPTY",
        )
        try:
            messages = [
                KernelMessage(role="system", content=REFLECTION_SYSTEM),
                KernelMessage(role="user", content=exchange_text),
            ]
            result = await kernel.run(messages, [], max_turns=1)
            observation = (result.final_message.content or "").strip()
        finally:
            await kernel.close()

        if not observation or observation == "SKIP" or not observation.startswith("- "):
            return

        # Append timestamped observation
        timestamp = time.strftime("%Y-%m-%d")
        note_line = f"\n{observation} *(from {timestamp})*\n"
        await append_text(ctx.workspace, AGENT_NOTES, note_line)

        await ctx.event_bus.emit(NodeAgentNoteUpdated(
            node_id=ctx.node_id,
            note_type="agent_notes",
        ))
```

---

## Phase 5: Cross-Node Links

### `src/remora/companion/links/__init__.py`

```python
from remora.companion.links.types import NodeLink, LinkRelationship
from remora.companion.links.resolver import LinksResolver

__all__ = ["NodeLink", "LinkRelationship", "LinksResolver"]
```

### `src/remora/companion/links/types.py`

```python
"""Cross-node link types."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LinkRelationship(str, Enum):
    CALLS = "calls"
    CALLED_BY = "called_by"
    TESTS = "tests"
    TESTED_BY = "tested_by"
    DOCUMENTS = "documents"
    DOCUMENTED_BY = "documented_by"
    IMPORTS = "imports"
    IMPORTED_BY = "imported_by"
    SIMILAR_TO = "similar_to"
    RELATED_TO = "related_to"


@dataclass
class NodeLink:
    source_node_id: str
    target_node_id: str
    relationship: str
    confidence: float
    note: str = ""

    @classmethod
    def from_dict(cls, source_node_id: str, d: dict) -> "NodeLink":
        return cls(
            source_node_id=source_node_id,
            target_node_id=d["target_node_id"],
            relationship=d["relationship"],
            confidence=d.get("confidence", 1.0),
            note=d.get("note", ""),
        )

    @classmethod
    def from_agent_node(cls, source_node_id: str, target_node_id: str,
                         relationship: str) -> "NodeLink":
        """Create a graph-derived link (from AgentNode caller/callee data)."""
        return cls(
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            relationship=relationship,
            confidence=1.0,
            note="graph-derived",
        )


__all__ = ["NodeLink", "LinkRelationship"]
```

### `src/remora/companion/links/resolver.py`

```python
"""LinksResolver — aggregates cross-node links for sidebar display.

Reads links from the active node's workspace AND synthesizes graph-derived
links from the AgentNode's caller_ids/callee_ids fields.
Does NOT query all workspaces — only the active node's workspace.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from remora.companion.links.types import NodeLink, LinkRelationship
from remora.companion.node_workspace import read_json, LINKS

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace


class LinksResolver:
    """Resolves links for a single node from workspace + AgentNode graph data."""

    async def get_links(
        self, node: "AgentNode", workspace: "AgentWorkspace"
    ) -> list[NodeLink]:
        """Return all links for this node (workspace + graph-derived)."""
        links: list[NodeLink] = []

        # 1. Graph-derived links from AgentNode (calls/called_by)
        for callee_id in node.callee_ids:
            links.append(NodeLink.from_agent_node(node.node_id, callee_id, "calls"))
        for caller_id in node.caller_ids:
            links.append(NodeLink.from_agent_node(node.node_id, caller_id, "called_by"))

        # 2. Workspace-stored links (discovered by swarms or user)
        raw = await read_json(workspace, LINKS) or []
        for entry in raw:
            try:
                links.append(NodeLink.from_dict(node.node_id, entry))
            except (KeyError, TypeError):
                continue

        # De-duplicate by (target_node_id, relationship)
        seen: set[tuple[str, str]] = set()
        deduped: list[NodeLink] = []
        for link in links:
            key = (link.target_node_id, link.relationship)
            if key not in seen:
                seen.add(key)
                deduped.append(link)

        return deduped


__all__ = ["LinksResolver"]
```

---

## Phase 6: Sidebar Composer

**File:** `src/remora/companion/sidebar/__init__.py` — empty.

**File:** `src/remora/companion/sidebar/composer.py`

The sidebar composer reads from a node's workspace and renders markdown. It is NOT a handler
and NOT an event subscriber — it is called by NodeAgent directly.

```python
"""NodeAgentSidebarComposer — renders a node's workspace as sidebar markdown."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

from remora.companion.node_workspace import (
    read_text, load_chat_index, AGENT_NOTES, USER_NOTES,
)
from remora.companion.links.resolver import LinksResolver

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace


_resolver = LinksResolver()


async def compose_sidebar(node: "AgentNode", workspace: "AgentWorkspace") -> str:
    """Compose the full sidebar markdown for a node agent.

    Reads from workspace: notes, chat history index, links.
    Returns a markdown string for display in Neovim.
    """
    lines: list[str] = []

    # Header
    lines.append(f"# {node.name}")
    lines.append(f"`{node.node_type}` — `{node.file_path}:{node.start_line}`")
    lines.append("")

    # User notes (highest priority — user wrote these)
    user_notes = await read_text(workspace, USER_NOTES)
    if user_notes.strip():
        lines.append("## Notes")
        lines.append(user_notes.strip())
        lines.append("")

    # Agent notes
    agent_notes = await read_text(workspace, AGENT_NOTES)
    if agent_notes.strip():
        lines.append("## Agent Observations")
        lines.append(agent_notes.strip())
        lines.append("")

    # Recent conversations
    index = await load_chat_index(workspace)
    if index:
        # Show up to 5 most recent
        recent = sorted(index, key=lambda e: e.timestamp, reverse=True)[:5]
        lines.append("## Recent Conversations")
        for entry in recent:
            ts = time.strftime("%Y-%m-%d", time.localtime(entry.timestamp))
            tag_str = f" `{'` `'.join(entry.tags)}`" if entry.tags else ""
            lines.append(f"- **{ts}**{tag_str}: {entry.summary}")
        lines.append("")

    # Connections
    links = await _resolver.get_links(node, workspace)
    if links:
        lines.append("## Connections")
        for link in links[:8]:
            lines.append(f"- `{link.target_node_id}` ({link.relationship})")
            if link.note and link.note != "graph-derived":
                lines.append(f"  *{link.note}*")
        lines.append("")

    if not user_notes.strip() and not agent_notes.strip() and not index and not links:
        lines.append("*First visit. Start a conversation below.*")

    return "\n".join(lines)


__all__ = ["compose_sidebar"]
```

---

## Phase 7: NodeAgent

**File:** `src/remora/companion/node_agent.py`

This is the core class. Each CST node has exactly one `NodeAgent`. It owns its Cairn workspace,
its conversation history (in-memory cache of recent turns), and its LLM kernel factory.

```python
"""NodeAgent — a persistent, per-CST-node agent backed by a Cairn workspace."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel

from remora.companion.events import NodeAgentSidebarReady
from remora.companion.node_workspace import (
    ensure_meta, read_text, write_text, append_text,
    CONTEXT_LATEST, SOURCE_SNAPSHOT, AGENT_NOTES,
)
from remora.companion.sidebar.composer import compose_sidebar
from remora.companion.swarms.base import SwarmContext, run_post_exchange_swarms
from remora.companion.swarms.summarizer import SummarizerSwarm
from remora.companion.swarms.categorizer import CategorizerSwarm
from remora.companion.swarms.linker import LinkerSwarm
from remora.companion.swarms.reflection import ReflectionSwarm
from remora.core.agents.kernel_factory import create_kernel
from structured_agents.types import Message as KernelMessage

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace
    from remora.core.events.event_bus import EventBus
    from remora.companion.config import CompanionConfig

logger = logging.getLogger("remora.companion.node_agent")

_SWARMS = [SummarizerSwarm(), CategorizerSwarm(), LinkerSwarm(), ReflectionSwarm()]


class NodeMessage(BaseModel):
    """A single message in a node agent conversation."""
    role: str   # "user" | "assistant" | "system"
    content: str
    timestamp: float = 0.0

    @classmethod
    def user(cls, content: str) -> "NodeMessage":
        return cls(role="user", content=content, timestamp=time.time())

    @classmethod
    def assistant(cls, content: str) -> "NodeMessage":
        return cls(role="assistant", content=content, timestamp=time.time())


class NodeAgentResponse(BaseModel):
    """Response from a NodeAgent.send() call."""
    message: NodeMessage
    turn_count: int
    node_id: str


class NodeAgent:
    """Persistent agent for a single CST node.

    Instantiated lazily by NodeAgentRegistry on first cursor visit.
    Holds a reference to the node's Cairn workspace (persistent across sessions).
    Handles messages, cursor events, file changes, and inter-agent messages.
    """

    def __init__(
        self,
        node: "AgentNode",
        workspace: "AgentWorkspace",
        event_bus: "EventBus",
        config: "CompanionConfig",
    ) -> None:
        self.node = node
        self.workspace = workspace
        self._event_bus = event_bus
        self._config = config
        self._history: list[NodeMessage] = []
        self._last_visited: float = time.time()
        self._session_id: str = str(uuid.uuid4())

    @property
    def node_id(self) -> str:
        return self.node.node_id

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Called once after construction. Loads workspace metadata."""
        await ensure_meta(
            self.workspace,
            node_id=self.node.node_id,
            node_type=self.node.node_type,
            name=self.node.name,
            file_path=self.node.file_path,
        )

    # ─── Event handlers ───────────────────────────────────────────────────────

    async def on_cursor_focus(self) -> None:
        """Called when the cursor focuses on this node.

        Updates last_visited, refreshes context, composes and emits sidebar.
        """
        self._last_visited = time.time()
        sidebar = await compose_sidebar(self.node, self.workspace)
        await self._event_bus.emit(NodeAgentSidebarReady(
            node_id=self.node_id,
            markdown=sidebar,
        ))

    async def on_content_changed(self, path: str, diff: str | None) -> None:
        """Called when this node's file is modified.

        Summarizes the change and appends a note to agent_notes.md.
        Does NOT trigger a full LLM run — just logs the change.
        """
        if diff:
            note = f"\n- *File changed ({time.strftime('%Y-%m-%d')})*: {diff[:120]}\n"
            await append_text(self.workspace, AGENT_NOTES, note)

    async def on_file_saved(self, path: str) -> None:
        """Called when this node's file is saved.

        Snapshots the current source code into context/source_snapshot.md.
        Triggers sidebar refresh.
        """
        try:
            import pathlib
            source = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
            await self.workspace.write(SOURCE_SNAPSHOT, f"```\n{source}\n```")
        except Exception:
            pass
        await self.on_cursor_focus()  # Refresh sidebar

    async def on_inter_agent_message(self, from_node_id: str, content: str) -> None:
        """Called when another node's agent sends a message to this node.

        Writes the message to inbox/ and refreshes sidebar.
        """
        ts = int(time.time())
        inbox_path = f"inbox/{from_node_id}_{ts}.md"
        await self.workspace.write(
            inbox_path,
            f"# Message from `{from_node_id}`\n\n*{time.strftime('%Y-%m-%d %H:%M')}*\n\n{content}\n"
        )
        await self.on_cursor_focus()

    # ─── Chat ─────────────────────────────────────────────────────────────────

    async def send(self, content: str) -> NodeAgentResponse:
        """Accept a user message, return agent response, trigger MicroSwarms.

        MicroSwarms run asynchronously (non-blocking) after the response is returned.
        """
        user_msg = NodeMessage.user(content)
        self._history.append(user_msg)

        system_prompt = await self._build_system_prompt()
        kernel_messages = [KernelMessage(role="system", content=system_prompt)]
        kernel_messages += [
            KernelMessage(role=m.role, content=m.content)  # type: ignore[arg-type]
            for m in self._history
        ]

        tools = self._build_tools()
        kernel = create_kernel(
            model_name=self._config.model_name,
            base_url=self._config.model_base_url,
            api_key=self._config.model_api_key or "EMPTY",
            tools=tools,
            observer=self._event_bus,
        )

        try:
            result = await kernel.run(
                kernel_messages,
                [t.schema for t in tools],
                max_turns=self._config.max_turns_per_message,
            )
        finally:
            await kernel.close()

        assistant_msg = NodeMessage.assistant(result.final_message.content or "")
        self._history.append(assistant_msg)

        # Persist transcript
        await self._persist_exchange(user_msg, assistant_msg)

        # Trigger MicroSwarms (non-blocking)
        ctx = SwarmContext(
            node_id=self.node_id,
            node=self.node,
            workspace=self.workspace,
            session_id=self._session_id,
            user_message=content,
            assistant_message=assistant_msg.content,
            event_bus=self._event_bus,
            model_name=self._config.model_name,
            model_base_url=self._config.model_base_url,
            model_api_key=self._config.model_api_key,
        )
        asyncio.create_task(self._run_swarms(ctx))

        return NodeAgentResponse(
            message=assistant_msg,
            turn_count=result.turn_count,
            node_id=self.node_id,
        )

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _build_system_prompt(self) -> str:
        """Build the LLM system prompt from AgentNode identity + workspace memory."""
        base = self.node.to_system_prompt()

        agent_notes = await read_text(self.workspace, AGENT_NOTES)
        if agent_notes.strip():
            base += f"\n# My Observations About This Node\n{agent_notes.strip()}\n"

        # Include recent chat summaries for memory
        from remora.companion.node_workspace import load_chat_index
        index = await load_chat_index(self.workspace)
        if index:
            recent = sorted(index, key=lambda e: e.timestamp, reverse=True)[:3]
            summary_block = "\n".join(f"- {e.summary}" for e in recent)
            base += f"\n# Recent Conversation History (summaries)\n{summary_block}\n"

        return base

    def _build_tools(self) -> list:
        """Build the tool set for this node agent."""
        from remora.companion.node_agent_tools import build_node_agent_tools
        return build_node_agent_tools(self)

    async def _persist_exchange(self, user_msg: NodeMessage, assistant_msg: NodeMessage) -> None:
        """Append the exchange to chat/{session_id}.md in the workspace."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n---\n\n**{timestamp}**\n\n"
            f"**User:** {user_msg.content}\n\n"
            f"**Agent:** {assistant_msg.content}\n"
        )
        transcript_path = f"chat/{self._session_id}.md"
        await append_text(self.workspace, transcript_path, entry)

    async def _run_swarms(self, ctx: SwarmContext) -> None:
        """Run MicroSwarms then refresh sidebar."""
        await run_post_exchange_swarms(ctx, _SWARMS)
        # Refresh sidebar after swarms complete
        sidebar = await compose_sidebar(self.node, self.workspace)
        await self._event_bus.emit(NodeAgentSidebarReady(
            node_id=self.node_id,
            markdown=sidebar,
        ))


__all__ = ["NodeAgent", "NodeMessage", "NodeAgentResponse"]
```

**File:** `src/remora/companion/node_agent_tools.py`

The tool implementations for the NodeAgent. Keep these in a separate file so `node_agent.py`
stays focused on the agent lifecycle.

```python
"""Tool implementations for NodeAgent.

These tools are available to the LLM during chat interactions.
They operate on the node's workspace and can read other node workspaces.
"""
from __future__ import annotations

import inspect
import json
from typing import Any, Callable, Awaitable, TYPE_CHECKING

from structured_agents import Tool
from structured_agents.types import ToolCall, ToolResult, ToolSchema

if TYPE_CHECKING:
    from remora.companion.node_agent import NodeAgent


_PY_TYPE_TO_JSON: dict[type, str] = {
    str: "string", int: "integer", float: "number", bool: "boolean",
}


def _params_schema(func: Callable[..., Any]) -> dict[str, Any]:
    from typing import get_type_hints
    sig = inspect.signature(func)
    hints = get_type_hints(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        json_type = _PY_TYPE_TO_JSON.get(hints.get(name, str), "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class FunctionTool:
    def __init__(self, func: Callable[..., Awaitable[Any]]) -> None:
        self._func = func
        self._schema = ToolSchema(
            name=func.__name__,
            description=func.__doc__ or func.__name__,
            parameters=_params_schema(func),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None = None) -> ToolResult:
        call_id = context.id if context else "unknown"
        try:
            result = await self._func(**arguments)
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(call_id=call_id, name=self._schema.name, output=output, is_error=False)
        except Exception as exc:
            return ToolResult(call_id=call_id, name=self._schema.name, output=str(exc), is_error=True)


def build_node_agent_tools(agent: "NodeAgent") -> list[Tool]:
    """Build the standard tool set for a NodeAgent."""
    workspace = agent.workspace

    async def read_workspace_file(path: str) -> str:
        """Read a file from this node's workspace."""
        return await workspace.read(path)

    async def write_workspace_file(path: str, content: str) -> str:
        """Write a file to this node's workspace (notes, guides, scripts)."""
        await workspace.write(path, content)
        return f"Written: {path}"

    async def list_workspace(path: str = ".") -> list:
        """List files in this node's workspace directory."""
        return await workspace.list_dir(path)

    async def append_to_user_notes(note: str) -> str:
        """Append a note to notes/user_notes.md in this node's workspace."""
        from remora.companion.node_workspace import append_text, USER_NOTES
        import time
        timestamped = f"\n- *{time.strftime('%Y-%m-%d')}*: {note}\n"
        await append_text(workspace, USER_NOTES, timestamped)
        return "Note saved."

    async def get_node_info(node_id: str) -> str:
        """Get basic info about another node in the codebase graph."""
        return json.dumps({
            "note": "Node lookup requires event store integration — not yet implemented.",
            "node_id": node_id,
        })

    async def create_guide(name: str, content: str) -> str:
        """Create or update a guide file in guides/{name}.md in this node's workspace."""
        await workspace.write(f"guides/{name}.md", content)
        return f"Guide saved: guides/{name}.md"

    async def create_script(name: str, content: str) -> str:
        """Create or update a script in scripts/{name}.py in this node's workspace."""
        await workspace.write(f"scripts/{name}.py", content)
        return f"Script saved: scripts/{name}.py"

    return [
        FunctionTool(read_workspace_file),
        FunctionTool(write_workspace_file),
        FunctionTool(list_workspace),
        FunctionTool(append_to_user_notes),
        FunctionTool(get_node_info),
        FunctionTool(create_guide),
        FunctionTool(create_script),
    ]


__all__ = ["build_node_agent_tools"]
```

---

## Phase 8: NodeAgentRegistry

**File:** `src/remora/companion/registry.py`

The registry is a pool of live `NodeAgent` instances. It lazy-loads from Cairn on first
access and evicts the least-recently-visited agent when the pool is full.

```python
"""NodeAgentRegistry — manages the pool of live NodeAgent instances."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from remora.companion.node_agent import NodeAgent

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
    from remora.core.events.event_bus import EventBus
    from remora.companion.config import CompanionConfig

logger = logging.getLogger("remora.companion.registry")


class NodeAgentRegistry:
    """Lazy-loading, LRU-evicting pool of NodeAgent instances.

    Thread-safe per-node locking prevents double-instantiation when two
    events arrive for the same node concurrently.
    """

    def __init__(
        self,
        cairn_service: "CairnWorkspaceService",
        event_bus: "EventBus",
        config: "CompanionConfig",
    ) -> None:
        self._cairn = cairn_service
        self._event_bus = event_bus
        self._config = config
        self._agents: dict[str, NodeAgent] = {}
        self._node_locks: dict[str, asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()

    async def get_or_create(self, node: "AgentNode") -> NodeAgent:
        """Get or lazily instantiate a NodeAgent for the given node.

        Evicts LRU agent if pool is at capacity.
        """
        node_id = node.node_id

        # Fast path: already loaded
        if node_id in self._agents:
            return self._agents[node_id]

        # Ensure per-node lock exists
        async with self._pool_lock:
            if node_id not in self._node_locks:
                self._node_locks[node_id] = asyncio.Lock()

        # Slow path: instantiate under per-node lock
        async with self._node_locks[node_id]:
            if node_id in self._agents:
                return self._agents[node_id]

            # Evict if at capacity
            if len(self._agents) >= self._config.max_active_agents:
                await self._evict_lru()

            workspace = await self._cairn.get_agent_workspace(node_id)
            agent = NodeAgent(
                node=node,
                workspace=workspace,
                event_bus=self._event_bus,
                config=self._config,
            )
            await agent.initialize()
            self._agents[node_id] = agent
            logger.debug("NodeAgent created for %s (pool size: %d)", node_id, len(self._agents))
            return agent

    def get(self, node_id: str) -> NodeAgent | None:
        """Get an already-loaded agent. Returns None if not in pool."""
        return self._agents.get(node_id)

    async def evict(self, node_id: str) -> None:
        """Explicitly evict an agent from the pool."""
        async with self._pool_lock:
            self._agents.pop(node_id, None)
            logger.debug("NodeAgent evicted: %s", node_id)

    async def _evict_lru(self) -> None:
        """Evict the least recently visited agent from the pool."""
        if not self._agents:
            return
        lru_id = min(self._agents, key=lambda nid: self._agents[nid]._last_visited)
        self._agents.pop(lru_id)
        logger.debug("NodeAgent LRU evicted: %s", lru_id)

    @property
    def active_count(self) -> int:
        return len(self._agents)


__all__ = ["NodeAgentRegistry"]
```

---

## Phase 9: NodeAgentRouter

**File:** `src/remora/companion/router.py`

The router subscribes to EventBus events and routes them to the correct NodeAgent.
`CursorFocusEvent.focused_agent_id` is already the node_id — use it directly.

For `ContentChangedEvent` and `FileSavedEvent`, it routes to all agents whose node is in
the changed file.

```python
"""NodeAgentRouter — routes EventBus events to the correct NodeAgent."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from remora.core.events.interaction_events import (
    CursorFocusEvent, ContentChangedEvent, FileSavedEvent,
)

if TYPE_CHECKING:
    from remora.core.store.event_store import EventStore
    from remora.companion.registry import NodeAgentRegistry

logger = logging.getLogger("remora.companion.router")


class NodeAgentRouter:
    """Subscribes to core interaction events and routes them to NodeAgents.

    The router's job is event routing only — it does not contain any
    agent logic. All agent logic lives in NodeAgent.
    """

    def __init__(self, registry: "NodeAgentRegistry", event_store: "EventStore") -> None:
        self._registry = registry
        self._event_store = event_store
        self._active_node_id: str | None = None

    def subscribe(self, event_bus) -> None:
        """Register all event subscriptions on the EventBus."""
        event_bus.subscribe(CursorFocusEvent, self._on_cursor_focus)
        event_bus.subscribe(ContentChangedEvent, self._on_content_changed)
        event_bus.subscribe(FileSavedEvent, self._on_file_saved)

    async def _on_cursor_focus(self, event: CursorFocusEvent) -> None:
        """Route cursor focus to the focused node's agent."""
        node_id = event.focused_agent_id
        if not node_id:
            return

        self._active_node_id = node_id

        # Look up the AgentNode from EventStore
        node = await self._resolve_node(node_id)
        if node is None:
            logger.debug("cursor focus: no AgentNode found for %s", node_id)
            return

        try:
            agent = await self._registry.get_or_create(node)
            await agent.on_cursor_focus()
        except Exception:
            logger.exception("cursor focus handler failed for %s", node_id)

    async def _on_content_changed(self, event: ContentChangedEvent) -> None:
        """Route content change to all agents for nodes in the changed file."""
        for node_id, agent in list(self._registry._agents.items()):
            if agent.node.file_path == event.path:
                try:
                    await agent.on_content_changed(event.path, event.diff)
                except Exception:
                    logger.exception("content changed handler failed for %s", node_id)

    async def _on_file_saved(self, event: FileSavedEvent) -> None:
        """Route file save to all agents for nodes in the saved file."""
        for node_id, agent in list(self._registry._agents.items()):
            if agent.node.file_path == event.path:
                try:
                    await agent.on_file_saved(event.path)
                except Exception:
                    logger.exception("file saved handler failed for %s", node_id)

    async def _resolve_node(self, node_id: str):
        """Look up an AgentNode from the EventStore's node projection."""
        try:
            return await self._event_store.nodes.get(node_id)
        except Exception:
            logger.debug("node lookup failed for %s", node_id)
            return None

    @property
    def active_node_id(self) -> str | None:
        return self._active_node_id


__all__ = ["NodeAgentRouter"]
```

---

## Phase 10: Startup and Package Init

**File:** `src/remora/companion/startup.py`

```python
"""Companion system startup.

Call start_companion() from lsp/__main__.py after CairnWorkspaceService
is initialized. Returns the NodeAgentRegistry for use by the LSP server.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from remora.companion.config import CompanionConfig
from remora.companion.registry import NodeAgentRegistry
from remora.companion.router import NodeAgentRouter

if TYPE_CHECKING:
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
    from remora.core.events.event_bus import EventBus
    from remora.core.store.event_store import EventStore

logger = logging.getLogger("remora.companion.startup")


async def start_companion(
    event_store: "EventStore",
    event_bus: "EventBus",
    cairn_service: "CairnWorkspaceService",
    config: CompanionConfig | None = None,
) -> NodeAgentRegistry:
    """Start the companion system and return the NodeAgentRegistry.

    cairn_service is REQUIRED. There is no fallback.

    Steps:
    1. Create NodeAgentRegistry (lazy agent pool)
    2. Create NodeAgentRouter (EventBus subscriber)
    3. Subscribe router to EventBus
    4. Optionally index the workspace for vector search

    Returns the registry so the LSP server can use it for command handling.
    """
    cfg = config or CompanionConfig()

    registry = NodeAgentRegistry(
        cairn_service=cairn_service,
        event_bus=event_bus,
        config=cfg,
    )

    router = NodeAgentRouter(registry=registry, event_store=event_store)
    router.subscribe(event_bus)

    logger.info("Companion started (max_active_agents=%d)", cfg.max_active_agents)

    # Optionally kick off vector indexing in background
    if cfg.auto_index:
        import asyncio
        from remora.companion.indexing_service import IndexingService
        try:
            indexing = IndexingService(cfg.indexing)
            await indexing.initialize()
            asyncio.create_task(indexing.index_directory(cfg.workspace_path))
            logger.info("Background workspace indexing started")
        except Exception:
            logger.warning("Failed to start vector indexing (non-fatal)", exc_info=True)

    return registry


__all__ = ["start_companion"]
```

**File:** `src/remora/companion/__init__.py`

```python
"""Remora companion — node-resident agent system.

Each CST node has a persistent NodeAgent backed by a Cairn workspace.
The companion sidebar reflects the active node's accumulated knowledge.

Entry point: start_companion() in startup.py.
"""
from remora.companion.startup import start_companion
from remora.companion.config import CompanionConfig, IndexingConfig
from remora.companion.registry import NodeAgentRegistry
from remora.companion.node_agent import NodeAgent, NodeMessage, NodeAgentResponse

__all__ = [
    "start_companion",
    "CompanionConfig",
    "IndexingConfig",
    "NodeAgentRegistry",
    "NodeAgent",
    "NodeMessage",
    "NodeAgentResponse",
]
```

---

## Phase 11: LSP Integration

### `src/remora/lsp/handlers/companion.py`

New file. All companion-related LSP commands live here. The `server` object exposes
`server.companion_registry` (set in Phase 12) and `server.companion_router`.

```python
"""Companion LSP command handlers.

All companion functionality surfaces via workspace/executeCommand.
No new LSP protocol methods — all pushes use $/remora/companionSidebarUpdated.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp.companion")


def register_companion_handlers(server: "LspServer") -> None:
    """Register all companion workspace/executeCommand handlers."""

    @server.command("companion.getSidebar")
    async def cmd_get_sidebar(ls, args) -> dict:
        """Return the current sidebar markdown for the active node."""
        registry = getattr(ls, "companion_registry", None)
        router = getattr(ls, "companion_router", None)
        if not registry or not router:
            return {"markdown": "", "node_id": ""}
        node_id = router.active_node_id
        if not node_id:
            return {"markdown": "*No node focused.*", "node_id": ""}
        agent = registry.get(node_id)
        if not agent:
            return {"markdown": "*Node not loaded.*", "node_id": node_id}
        from remora.companion.sidebar.composer import compose_sidebar
        markdown = await compose_sidebar(agent.node, agent.workspace)
        return {"markdown": markdown, "node_id": node_id}

    @server.command("companion.sendMessage")
    async def cmd_send_message(ls, args) -> dict:
        """Send a chat message to the active node's agent.

        args: [{"node_id": str, "content": str}]
        Returns: {"message": {"role": str, "content": str}, "turn_count": int}
        """
        registry = getattr(ls, "companion_registry", None)
        if not registry or not args:
            return {"error": "companion not available"}
        params = args[0] if isinstance(args, list) else args
        node_id = params.get("node_id") or ""
        content = params.get("content") or ""
        if not node_id or not content:
            return {"error": "node_id and content are required"}
        agent = registry.get(node_id)
        if not agent:
            return {"error": f"agent not loaded for {node_id}"}
        try:
            response = await agent.send(content)
            return {
                "message": {"role": "assistant", "content": response.message.content},
                "turn_count": response.turn_count,
                "node_id": node_id,
            }
        except Exception:
            logger.exception("companion.sendMessage failed for %s", node_id)
            return {"error": "agent error"}

    @server.command("companion.writeNote")
    async def cmd_write_note(ls, args) -> dict:
        """Append a user note to the active node's notes/user_notes.md.

        args: [{"node_id": str, "note": str}]
        """
        registry = getattr(ls, "companion_registry", None)
        if not registry or not args:
            return {"ok": False}
        params = args[0] if isinstance(args, list) else args
        node_id = params.get("node_id") or ""
        note = params.get("note") or ""
        if not node_id or not note:
            return {"ok": False}
        agent = registry.get(node_id)
        if not agent:
            return {"ok": False, "error": "agent not loaded"}
        import time
        from remora.companion.node_workspace import append_text, USER_NOTES
        timestamped = f"\n- *{time.strftime('%Y-%m-%d')}*: {note}\n"
        await append_text(agent.workspace, USER_NOTES, timestamped)
        return {"ok": True}

    @server.command("companion.getLinks")
    async def cmd_get_links(ls, args) -> dict:
        """Return all cross-node links for a node.

        args: [{"node_id": str}]
        """
        registry = getattr(ls, "companion_registry", None)
        if not registry or not args:
            return {"links": []}
        params = args[0] if isinstance(args, list) else args
        node_id = params.get("node_id") or ""
        agent = registry.get(node_id)
        if not agent:
            return {"links": []}
        from remora.companion.links.resolver import LinksResolver
        resolver = LinksResolver()
        links = await resolver.get_links(agent.node, agent.workspace)
        return {
            "links": [
                {
                    "target_node_id": l.target_node_id,
                    "relationship": l.relationship,
                    "confidence": l.confidence,
                    "note": l.note,
                }
                for l in links
            ]
        }

    @server.command("companion.listHistory")
    async def cmd_list_history(ls, args) -> dict:
        """Return the chat session index for a node.

        args: [{"node_id": str}]
        """
        registry = getattr(ls, "companion_registry", None)
        if not registry or not args:
            return {"history": []}
        params = args[0] if isinstance(args, list) else args
        node_id = params.get("node_id") or ""
        agent = registry.get(node_id)
        if not agent:
            return {"history": []}
        from remora.companion.node_workspace import load_chat_index
        index = await load_chat_index(agent.workspace)
        return {
            "history": [e.to_dict() for e in sorted(index, key=lambda e: e.timestamp, reverse=True)]
        }

    @server.command("companion.getHistory")
    async def cmd_get_history(ls, args) -> dict:
        """Return the full transcript for a specific session.

        args: [{"node_id": str, "session_id": str}]
        """
        registry = getattr(ls, "companion_registry", None)
        if not registry or not args:
            return {"markdown": ""}
        params = args[0] if isinstance(args, list) else args
        node_id = params.get("node_id") or ""
        session_id = params.get("session_id") or ""
        agent = registry.get(node_id)
        if not agent:
            return {"markdown": ""}
        from remora.companion.node_workspace import read_text
        transcript = await read_text(agent.workspace, f"chat/{session_id}.md")
        return {"markdown": transcript}
```

### Update `src/remora/lsp/server_setup.py`

Add one import and one call at the end of `register_handlers()`:

```python
# ADD at top of file:
from remora.lsp.handlers.companion import register_companion_handlers

def register_handlers(server: LspServer) -> None:
    """Register all LSP handlers on the server instance."""
    if getattr(server, "_handlers_registered", False):
        return
    server._handlers_registered = True

    from remora.lsp.handlers.actions import register_action_handlers
    from remora.lsp.handlers.capabilities import register_capability_handlers
    from remora.lsp.handlers.commands import register_command_handlers
    from remora.lsp.handlers.documents import register_document_handlers
    from remora.lsp.handlers.hover import register_hover_handlers
    from remora.lsp.handlers.lens import register_lens_handlers
    from remora.lsp.notifications import register_notification_handlers

    register_command_handlers(server)
    register_document_handlers(server)
    register_action_handlers(server)
    register_capability_handlers(server)
    register_hover_handlers(server)
    register_lens_handlers(server)
    register_notification_handlers(server)
    register_companion_handlers(server)   # ADD THIS LINE
```

---

## Phase 12: `__main__.py` Wiring

Three changes to `src/remora/lsp/__main__.py`:

### Change 1: Add CairnWorkspaceService to `_prepare()`

In the `_prepare()` coroutine, after creating `event_store`, add:

```python
async def _prepare():
    from remora.core.code.projections import NodeProjection
    from remora.core.events.event_bus import EventBus
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.event_store import EventStore
    from remora.core.config import load_config                      # ADD
    from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode  # ADD

    root = Path.cwd()
    swarm_path = root / ".remora"
    event_store_path = swarm_path / "events" / "events.db"
    subscriptions_path = swarm_path / "subscriptions.db"

    event_bus = EventBus()
    subscriptions = SubscriptionRegistry(subscriptions_path)
    # ... (projection, event_store setup unchanged) ...

    # Initialize Cairn (required for companion)                     # ADD
    config = load_config()                                           # ADD
    cairn_service = CairnWorkspaceService(config, project_root=root) # ADD
    await cairn_service.initialize(sync_mode=SyncMode.FULL)          # ADD

    return event_store, subscriptions, event_bus, cairn_service      # ADD event_bus, cairn_service
```

### Change 2: Update `_run_server()` signature

```python
def _run_server(
    event_store=None,
    subscriptions=None,
    event_bus=None,          # ADD
    cairn_service=None,      # ADD
) -> None:
    # ... existing code ...

    # Store on server for companion access
    server.companion_registry = None   # will be set in _on_initialized
    server.companion_router = None
    server._companion_event_bus = event_bus     # ADD
    server._companion_cairn_service = cairn_service  # ADD
```

### Change 3: Wire companion in `_on_initialized`

Inside the `_on_initialized` handler, add after starting the runner:

```python
@server.feature(lsp.INITIALIZED)
async def _on_initialized(*args) -> None:
    # ... existing code (runner startup, background scan) ...

    # Start companion system                                    # ADD
    event_bus = getattr(ls, "_companion_event_bus", None)       # ADD
    cairn_svc = getattr(ls, "_companion_cairn_service", None)   # ADD
    if event_bus and cairn_svc and ls.event_store:              # ADD
        try:                                                     # ADD
            from remora.companion.startup import start_companion # ADD
            from remora.companion.config import CompanionConfig  # ADD
            from remora.companion.events import NodeAgentSidebarReady  # ADD
                                                                 # ADD
            comp_config = CompanionConfig(workspace_path=root)   # ADD
            registry = await start_companion(                    # ADD
                event_store=ls.event_store,                      # ADD
                event_bus=event_bus,                             # ADD
                cairn_service=cairn_svc,                         # ADD
                config=comp_config,                              # ADD
            )                                                    # ADD
            ls.companion_registry = registry                     # ADD
                                                                 # ADD
            # Subscribe sidebar push to client                   # ADD
            async def _push_sidebar(event: NodeAgentSidebarReady) -> None:  # ADD
                try:                                             # ADD
                    ls.protocol.notify(                          # ADD
                        "$/remora/companionSidebarUpdated",      # ADD
                        {"markdown": event.markdown, "node_id": event.node_id}  # ADD
                    )                                            # ADD
                except Exception:                               # ADD
                    pass                                         # ADD
                                                                 # ADD
            event_bus.subscribe(NodeAgentSidebarReady, _push_sidebar)  # ADD
            startup_log.info("Companion system started")         # ADD
        except Exception:                                        # ADD
            startup_log.exception("Companion startup failed (non-fatal)")  # ADD
```

### Change 4: Update `main()` call site

```python
# In main():
event_store, subscriptions, event_bus, cairn_service = asyncio.run(_prepare())
_run_server(
    event_store=event_store,
    subscriptions=subscriptions,
    event_bus=event_bus,          # ADD
    cairn_service=cairn_service,  # ADD
)
```

---

## Phase 13: Tests

All new tests go under `tests/unit/companion/`. Create `tests/unit/companion/__init__.py` (empty).

### `tests/unit/companion/test_node_workspace.py`

```python
"""Tests for node workspace conventions and helpers."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from remora.companion.node_workspace import (
    read_json, write_json, read_text, append_text,
    load_chat_index, save_chat_index, ensure_meta,
    ChatIndexEntry, NodeMeta,
)


def make_workspace():
    """Create a mock AgentWorkspace backed by an in-memory dict."""
    store: dict[str, str] = {}

    ws = MagicMock()

    async def read(path):
        if path not in store:
            raise FileNotFoundError(path)
        return store[path]

    async def write(path, content):
        store[path] = content if isinstance(content, str) else content.decode()

    async def exists(path):
        return path in store

    ws.read = read
    ws.write = write
    ws.exists = exists
    return ws, store


@pytest.mark.asyncio
async def test_read_json_missing_returns_none():
    ws, _ = make_workspace()
    result = await read_json(ws, "missing.json")
    assert result is None


@pytest.mark.asyncio
async def test_write_read_json_roundtrip():
    ws, _ = make_workspace()
    data = {"key": "value", "nums": [1, 2, 3]}
    await write_json(ws, "test.json", data)
    result = await read_json(ws, "test.json")
    assert result == data


@pytest.mark.asyncio
async def test_read_text_missing_returns_default():
    ws, _ = make_workspace()
    result = await read_text(ws, "missing.md", default="hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_append_text_creates_file():
    ws, _ = make_workspace()
    await append_text(ws, "notes.md", "first line\n")
    await append_text(ws, "notes.md", "second line\n")
    result = await read_text(ws, "notes.md")
    assert "first line" in result
    assert "second line" in result


@pytest.mark.asyncio
async def test_chat_index_roundtrip():
    ws, _ = make_workspace()
    entry = ChatIndexEntry(
        session_id="abc123",
        timestamp=1000.0,
        summary="We discussed the timeout bug.",
        tags=["bug", "debugging"],
        turn_count=3,
    )
    await save_chat_index(ws, [entry])
    loaded = await load_chat_index(ws)
    assert len(loaded) == 1
    assert loaded[0].session_id == "abc123"
    assert loaded[0].summary == "We discussed the timeout bug."
    assert "bug" in loaded[0].tags


@pytest.mark.asyncio
async def test_ensure_meta_creates_on_first_call():
    ws, _ = make_workspace()
    meta = await ensure_meta(ws, "node_abc", "function", "my_func", "foo.py")
    assert meta.node_id == "node_abc"
    assert meta.node_type == "function"
    assert meta.name == "my_func"


@pytest.mark.asyncio
async def test_ensure_meta_updates_last_visited():
    ws, _ = make_workspace()
    meta1 = await ensure_meta(ws, "node_abc", "function", "my_func", "foo.py")
    import time; time.sleep(0.01)
    meta2 = await ensure_meta(ws, "node_abc", "function", "my_func", "foo.py")
    assert meta2.last_visited >= meta1.last_visited
```

### `tests/unit/companion/test_swarms.py`

```python
"""Tests for MicroSwarm base and orchestration."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.companion.swarms.base import SwarmContext, run_post_exchange_swarms


def make_ctx(**overrides):
    node = MagicMock()
    node.name = "my_func"
    node.node_id = "node_abc"
    defaults = dict(
        node_id="node_abc",
        node=node,
        workspace=MagicMock(),
        session_id="session_1",
        user_message="Why does this break?",
        assistant_message="It breaks because of the off-by-one on line 42.",
        event_bus=AsyncMock(),
        model_name="test-model",
        model_base_url="http://localhost:8000/v1",
        model_api_key="",
    )
    defaults.update(overrides)
    return SwarmContext(**defaults)


@pytest.mark.asyncio
async def test_run_post_exchange_swarms_all_run():
    called = []

    class FakeSwarm:
        async def run(self, ctx):
            called.append(type(self).__name__)

    swarms = [FakeSwarm(), FakeSwarm()]
    await run_post_exchange_swarms(make_ctx(), swarms)
    assert len(called) == 2


@pytest.mark.asyncio
async def test_run_post_exchange_swarms_failure_does_not_propagate():
    class BadSwarm:
        async def run(self, ctx):
            raise RuntimeError("swarm failed")

    class GoodSwarm:
        async def run(self, ctx):
            pass  # succeeds

    # Should not raise
    await run_post_exchange_swarms(make_ctx(), [BadSwarm(), GoodSwarm()])
```

### `tests/unit/companion/test_registry.py`

```python
"""Tests for NodeAgentRegistry."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.companion.registry import NodeAgentRegistry
from remora.companion.config import CompanionConfig


def make_registry(max_active=5):
    cairn = MagicMock()
    cairn.get_agent_workspace = AsyncMock(return_value=MagicMock())
    event_bus = AsyncMock()
    config = CompanionConfig(max_active_agents=max_active)
    return NodeAgentRegistry(cairn_service=cairn, event_bus=event_bus, config=config)


def make_node(node_id="node_abc"):
    node = MagicMock()
    node.node_id = node_id
    node.node_type = "function"
    node.name = "my_func"
    node.file_path = "src/foo.py"
    node.callee_ids = []
    node.caller_ids = []
    return node


@pytest.mark.asyncio
async def test_get_or_create_creates_agent():
    registry = make_registry()
    node = make_node()

    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance._last_visited = 1000.0
        MockAgent.return_value = mock_instance

        agent = await registry.get_or_create(node)
        assert agent is mock_instance
        mock_instance.initialize.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_returns_cached():
    registry = make_registry()
    node = make_node()

    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance._last_visited = 1000.0
        MockAgent.return_value = mock_instance

        agent1 = await registry.get_or_create(node)
        agent2 = await registry.get_or_create(node)
        assert agent1 is agent2
        assert MockAgent.call_count == 1  # only created once


@pytest.mark.asyncio
async def test_evict_lru_when_at_capacity():
    registry = make_registry(max_active=2)

    agents_created = []

    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        def make_mock_agent(*args, **kwargs):
            m = AsyncMock()
            m._last_visited = float(len(agents_created))
            agents_created.append(m)
            return m
        MockAgent.side_effect = make_mock_agent

        node_a = make_node("node_a")
        node_b = make_node("node_b")
        node_c = make_node("node_c")

        await registry.get_or_create(node_a)  # LRU: _last_visited=0
        await registry.get_or_create(node_b)  # _last_visited=1
        # Pool at capacity (2). Adding node_c should evict node_a (lowest last_visited)
        await registry.get_or_create(node_c)

        assert registry.get("node_a") is None   # evicted
        assert registry.get("node_b") is not None
        assert registry.get("node_c") is not None


@pytest.mark.asyncio
async def test_explicit_evict():
    registry = make_registry()
    node = make_node()

    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance._last_visited = 1000.0
        MockAgent.return_value = mock_instance

        await registry.get_or_create(node)
        assert registry.get("node_abc") is not None

        await registry.evict("node_abc")
        assert registry.get("node_abc") is None
```

### `tests/unit/companion/test_node_agent.py`

```python
"""Tests for NodeAgent core logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.companion.node_agent import NodeAgent, NodeMessage, NodeAgentResponse
from remora.companion.config import CompanionConfig


def make_agent():
    node = MagicMock()
    node.node_id = "node_abc"
    node.node_type = "function"
    node.name = "my_func"
    node.file_path = "src/foo.py"
    node.start_line = 10
    node.callee_ids = []
    node.caller_ids = []
    node.to_system_prompt.return_value = "You are my_func."

    workspace = MagicMock()
    workspace.read = AsyncMock(side_effect=FileNotFoundError)
    workspace.write = AsyncMock()
    workspace.list_dir = AsyncMock(return_value=[])

    event_bus = AsyncMock()
    config = CompanionConfig(model_name="test", model_base_url="http://localhost", model_api_key="")

    return NodeAgent(node=node, workspace=workspace, event_bus=event_bus, config=config)


@pytest.mark.asyncio
async def test_node_message_factory():
    msg = NodeMessage.user("hello")
    assert msg.role == "user"
    assert msg.content == "hello"

    msg2 = NodeMessage.assistant("response")
    assert msg2.role == "assistant"


@pytest.mark.asyncio
async def test_on_cursor_focus_emits_sidebar():
    agent = make_agent()

    with patch("remora.companion.node_agent.compose_sidebar", new_callable=AsyncMock) as mock_compose:
        mock_compose.return_value = "# my_func\nfirst visit"
        await agent.on_cursor_focus()
        agent._event_bus.emit.assert_called_once()
        emitted = agent._event_bus.emit.call_args[0][0]
        assert emitted.node_id == "node_abc"
        assert "my_func" in emitted.markdown


@pytest.mark.asyncio
async def test_send_returns_response():
    agent = make_agent()

    mock_result = MagicMock()
    mock_result.final_message.content = "The bug is on line 42."
    mock_result.turn_count = 2

    mock_kernel = AsyncMock()
    mock_kernel.run = AsyncMock(return_value=mock_result)

    with patch("remora.companion.node_agent.create_kernel", return_value=mock_kernel):
        with patch("remora.companion.node_agent.run_post_exchange_swarms", new_callable=AsyncMock):
            with patch("remora.companion.node_agent.compose_sidebar", new_callable=AsyncMock, return_value=""):
                response = await agent.send("Why does this break?")

    assert response.node_id == "node_abc"
    assert response.turn_count == 2
    assert "42" in response.message.content
    assert len(agent._history) == 2  # user + assistant
```

### Run all tests

```bash
devenv shell -- python -m pytest tests/unit/companion/ -v
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
devenv shell -- tach check
```

---

## Phase 14: Neovim Plugin

The old `remora_demo/companion/` directory is deleted (Phase 0). Create a fresh, minimal plugin.

```bash
mkdir -p remora_demo/nvim-companion/lua/companion
```

**File:** `remora_demo/nvim-companion/lua/companion/init.lua`

```lua
-- Companion sidebar plugin for Neovim.
-- Connects to the SAME remora-lsp server (no separate server).
-- Requires: require("remora").setup() called first.

local M = {}
local _sidebar_win = nil
local _sidebar_buf = nil
local _active_node_id = nil

-- ─── Helpers ──────────────────────────────────────────────────────────────────

local function get_remora_client()
    local clients = vim.lsp.get_clients({ name = "remora" })
    return clients and clients[1] or nil
end

local function set_sidebar_content(markdown)
    if not _sidebar_buf or not vim.api.nvim_buf_is_valid(_sidebar_buf) then
        return
    end
    local lines = vim.split(markdown or "*No companion context yet.*", "\n", { plain = true })
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", true)
    vim.api.nvim_buf_set_lines(_sidebar_buf, 0, -1, false, lines)
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", false)
end

local function open_sidebar()
    if _sidebar_win and vim.api.nvim_win_is_valid(_sidebar_win) then
        return  -- already open
    end
    _sidebar_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_option(_sidebar_buf, "filetype", "markdown")
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", false)
    vim.api.nvim_buf_set_name(_sidebar_buf, "Companion")

    -- Open as right split
    vim.cmd("botright vsplit")
    _sidebar_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(_sidebar_win, _sidebar_buf)
    vim.api.nvim_win_set_width(_sidebar_win, 52)
    vim.api.nvim_win_set_option(_sidebar_win, "wrap", true)
    vim.api.nvim_win_set_option(_sidebar_win, "winfixwidth", true)
    vim.api.nvim_win_set_option(_sidebar_win, "number", false)
    vim.api.nvim_win_set_option(_sidebar_win, "signcolumn", "no")

    -- Return focus to previous window
    vim.cmd("wincmd p")

    -- Clean up references when window is closed
    vim.api.nvim_create_autocmd("WinClosed", {
        pattern = tostring(_sidebar_win),
        once = true,
        callback = function()
            _sidebar_win = nil
            _sidebar_buf = nil
        end,
    })
end

local function fetch_sidebar()
    local client = get_remora_client()
    if not client then return end
    client.request("workspace/executeCommand", {
        command = "companion.getSidebar",
        arguments = {},
    }, function(err, result)
        if err or not result then return end
        _active_node_id = result.node_id
        set_sidebar_content(result.markdown)
    end)
end

-- ─── Chat input ───────────────────────────────────────────────────────────────

local function send_message(content)
    local client = get_remora_client()
    if not client then
        vim.notify("[companion] No remora client connected.", vim.log.levels.WARN)
        return
    end
    if not _active_node_id or _active_node_id == "" then
        vim.notify("[companion] No node focused. Move cursor to a function or class.", vim.log.levels.WARN)
        return
    end

    -- Show "thinking..." placeholder
    set_sidebar_content("*Thinking...*")

    client.request("workspace/executeCommand", {
        command = "companion.sendMessage",
        arguments = { { node_id = _active_node_id, content = content } },
    }, function(err, result)
        if err or not result then
            set_sidebar_content("*Error: agent did not respond.*")
            return
        end
        local msg = result.message and result.message.content or ""
        -- Show response then fetch full updated sidebar
        set_sidebar_content("**Agent:** " .. msg .. "\n\n*Updating sidebar...*")
        vim.defer_fn(fetch_sidebar, 2000)  -- swarms need ~2s
    end)
end

local function prompt_and_send()
    vim.ui.input({ prompt = "Ask agent: " }, function(input)
        if input and input ~= "" then
            send_message(input)
        end
    end)
end

-- ─── Push notification handler ────────────────────────────────────────────────

local function register_push_handler()
    vim.lsp.handlers["$/remora/companionSidebarUpdated"] = function(_, result)
        if not result then return end
        if result.node_id then
            _active_node_id = result.node_id
        end
        -- Only update if sidebar is open
        if _sidebar_win and vim.api.nvim_win_is_valid(_sidebar_win) then
            set_sidebar_content(result.markdown or "")
        end
    end
end

-- ─── Public API ───────────────────────────────────────────────────────────────

function M.setup(opts)
    opts = opts or {}
    register_push_handler()

    -- Command: open sidebar and fetch content
    vim.api.nvim_create_user_command("CompanionSidebar", function()
        open_sidebar()
        fetch_sidebar()
    end, { desc = "Open companion sidebar for current node" })

    -- Command: refresh sidebar manually
    vim.api.nvim_create_user_command("CompanionRefresh", function()
        fetch_sidebar()
    end, { desc = "Refresh companion sidebar" })

    -- Command: send message to active node's agent
    vim.api.nvim_create_user_command("CompanionChat", function()
        open_sidebar()
        prompt_and_send()
    end, { desc = "Chat with the active node agent" })

    -- Command: add a note to active node
    vim.api.nvim_create_user_command("CompanionNote", function()
        local client = get_remora_client()
        if not client or not _active_node_id then
            vim.notify("[companion] No node focused.", vim.log.levels.WARN)
            return
        end
        vim.ui.input({ prompt = "Note: " }, function(input)
            if not input or input == "" then return end
            client.request("workspace/executeCommand", {
                command = "companion.writeNote",
                arguments = { { node_id = _active_node_id, note = input } },
            }, function(err, result)
                if result and result.ok then
                    vim.notify("[companion] Note saved.")
                    vim.defer_fn(fetch_sidebar, 500)
                end
            end)
        end)
    end, { desc = "Add a note to the current node" })

    -- Optional: auto-open sidebar when LSP attaches
    if opts.auto_open then
        vim.api.nvim_create_autocmd("LspAttach", {
            callback = function(ev)
                local client = vim.lsp.get_client_by_id(ev.data.client_id)
                if client and client.name == "remora" then
                    vim.defer_fn(function()
                        open_sidebar()
                        fetch_sidebar()
                    end, 500)
                end
            end,
        })
    end
end

return M
```

**Installation in user's init.lua:**

```lua
-- In user's Neovim config:
require("remora").setup({ ... })          -- start remora-lsp (existing)
require("companion").setup({
    auto_open = true,                     -- open sidebar on LSP attach
})

-- Suggested keymaps:
vim.keymap.set("n", "<leader>cs", "<cmd>CompanionSidebar<CR>", { desc = "Companion sidebar" })
vim.keymap.set("n", "<leader>cc", "<cmd>CompanionChat<CR>",    { desc = "Chat with node agent" })
vim.keymap.set("n", "<leader>cn", "<cmd>CompanionNote<CR>",    { desc = "Add companion note" })
vim.keymap.set("n", "<leader>cr", "<cmd>CompanionRefresh<CR>", { desc = "Refresh companion" })
```

---

## Phase 15: Acceptance Criteria

Run each check in order. All must pass before the refactor is considered complete.

### Structural checks

```bash
# 1. No old companion files remain
ls src/remora/companion/handlers/ 2>&1 | grep "No such file"
ls src/remora/companion/dispatcher.py 2>&1 | grep "No such file"
ls src/remora/companion/state.py 2>&1 | grep "No such file"
ls src/remora/core/agents/chat.py 2>&1 | grep "No such file"
ls remora_demo/companion/ 2>&1 | grep "No such file"
```

### Import checks

```bash
devenv shell -- python -c "from remora.companion import start_companion, CompanionConfig, NodeAgentRegistry; print('OK')"
devenv shell -- python -c "from remora.companion.node_agent import NodeAgent, NodeMessage, NodeAgentResponse; print('OK')"
devenv shell -- python -c "from remora.companion.swarms.base import SwarmContext, run_post_exchange_swarms; print('OK')"
devenv shell -- python -c "from remora.companion.links.resolver import LinksResolver; print('OK')"
devenv shell -- python -c "from remora.companion.sidebar.composer import compose_sidebar; print('OK')"
devenv shell -- python -c "from remora.lsp.handlers.companion import register_companion_handlers; print('OK')"
```

### Integration smoke test

```bash
devenv shell -- python -c "
import asyncio, pathlib, tempfile

async def test():
    from remora.core.events.event_bus import EventBus
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.event_store import EventStore
    from remora.core.config import Config
    from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
    from remora.companion.startup import start_companion
    from remora.companion.config import CompanionConfig

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        config = Config(bundle_root=str(tmp / '.remora'))
        cairn = CairnWorkspaceService(config, project_root=tmp)
        await cairn.initialize(sync_mode=SyncMode.NONE)

        bus = EventBus()
        store_path = tmp / 'events.db'
        store = EventStore(store_path)
        await store.initialize()
        store.set_event_bus(bus)

        registry = await start_companion(
            event_store=store,
            event_bus=bus,
            cairn_service=cairn,
            config=CompanionConfig(workspace_path=tmp, auto_index=False),
        )
        print(f'Companion started OK — registry type: {type(registry).__name__}')
        await cairn.close()
        await store.close()

asyncio.run(test())
"
```

### Test suite

```bash
# New companion tests
devenv shell -- python -m pytest tests/unit/companion/ -v

# Full suite (expect only pre-existing failures)
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# Architecture check
devenv shell -- tach check
```

### Functional checks (manual, with Neovim)

- [ ] Move cursor to a Python function → sidebar opens with node name and "First visit" message
- [ ] Move cursor away and back → sidebar updates, shows node again
- [ ] `:CompanionChat` → type a message → agent responds → sidebar updates ~2s later with indexed exchange
- [ ] `:CompanionNote "this function has a subtle edge case"` → note appears in sidebar on next refresh
- [ ] Revisit the function in a new session → notes and chat history are still there (Cairn persisted)
- [ ] `$/remora/companionSidebarUpdated` is pushed automatically (sidebar refreshes without polling)

---

*End of implementation guide.*
*Reference: `COMPANION_REFACTOR_CONCEPT.md` for the architectural rationale behind each decision.*
