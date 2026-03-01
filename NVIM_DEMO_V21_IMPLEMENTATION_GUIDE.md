# Neovim V2.1 LSP Demo — Implementation Guide

A step-by-step guide to transform the demo into a production-quality, first-class
component of the Remora library. Based on findings from
[NVIM_V21_CODE_REVIEW.md](file:///c:/Users/Andrew/Documents/Projects/remora/NVIM_V21_CODE_REVIEW.md).

---

## Table of Contents

### [Phase 0: Project Scaffolding & Convention Fixes](#phase-0-project-scaffolding--convention-fixes)
Move the demo into `src/remora/lsp/`, add `pyproject.toml` entrypoint, add filepath
comments, `from __future__ import annotations`, and convert plain classes to Pydantic.

### [Phase 1: P0 Runtime Bug Fixes](#phase-1-p0-runtime-bug-fixes)
Fix the 5 blocking bugs: `did_save()` attribute error, broken `publish_code_lenses()`,
`trigger()` chain check, `__main__.py` server startup, and event timestamps.

### [Phase 2: Async Database Layer](#phase-2-async-database-layer)
Wrap all synchronous SQLite calls in `asyncio.to_thread()` and enable WAL mode. This
unblocks the event loop and is the single biggest performance improvement.

### [Phase 3: Watcher & Parser Fixes](#phase-3-watcher--parser-fixes)
Fix the double-parse bug, remove the phantom `method_definition` check, improve
the regex fallback to handle indented methods, and wire `inject_ids()` into the
save flow.

### [Phase 4: Agent Integration — Unify Models](#phase-4-agent-integration--unify-models)
Bridge the demo's Pydantic `ASTAgentNode` with the existing `AgentState` dataclass.
Add an `LSPBridgeMixin` protocol so any agent state can export to LSP types.
Unify the demo's event models with `remora.core.events`.

### [Phase 5: Agent Integration — Wire to SwarmExecutor](#phase-5-agent-integration--wire-to-swarmexecutor)
Replace `MockLLMClient` with the real `SwarmExecutor` → `AgentKernel` pipeline.
Bridge Grail `.pym` tools into LSP code actions. Use the existing `EventStore`
and `SubscriptionRegistry` as the backend.

### [Phase 6: LSP Server Hardening](#phase-6-lsp-server-hardening)
Implement missing LSP handlers (`documentSymbol`, `didClose` cleanup). Fix
`publish_diagnostics()` filtering. Add proper error handling. Implement the
`execute_extension_tool()` stub. Add `read_node` tool result handling.

### [Phase 7: Neovim Client Polish](#phase-7-neovim-client-polish)
Fix `__init__.lua` circular require. Upgrade from `nui.popup` to `nui-components`
with reactive Signals. Add highlight groups. Add keybindings. Write a
cross-platform start script (PowerShell).

### [Phase 8: CLI Entrypoint & pyproject.toml](#phase-8-cli-entrypoint--pyprojecttoml)
Add `remora-lsp` script entrypoint. Integrate with existing `remora swarm start --nvim`
flag. Wire the LSP server startup into the CLI so the server can be invoked standalone
or as part of the swarm.

### [Phase 9: Testing](#phase-9-testing)
Unit tests for `RemoraDB` (async wrapper), `ASTWatcher` parse correctness, LSP
handler response shapes. Integration test: start server → send didOpen → verify
codeLens response.

### [Phase 10: Documentation & README Update](#phase-10-documentation--readme-update)
Update `demo/README.md`, add inline docstrings, update `HOW_TO_CREATE_AN_AGENT.md`
with LSP integration section.

---

<!-- Sections will be appended incrementally below -->

## Phase 0: Project Scaffolding & Convention Fixes

**Goal:** Move the demo from a standalone `demo/` directory into the proper
`src/remora/lsp/` package namespace and fix every project convention violation.

### Step 0.1 — Create `src/remora/lsp/` package

Move and rename files from `demo/` into the library's source tree. The demo
directory will remain as a thin shell with re-exports for backward compat.

```
src/remora/lsp/
├── __init__.py            # Package exports
├── server.py              # RemoraLanguageServer (from demo/lsp/server.py)
├── models.py              # ASTAgentNode, RewriteProposal, events (from demo/core/models.py)
├── db.py                  # RemoraDB (from demo/core/db.py)
├── graph.py               # LazyGraph (from demo/core/graph.py)
├── watcher.py             # ASTWatcher (from demo/core/watcher.py)
├── runner.py              # AgentRunner (from demo/agent/runner.py)
└── nvim/
    └── lua/
        └── remora/
            ├── init.lua           # Setup + handlers
            ├── panel.lua          # Sidepanel UI
            └── remora_starter.lua # Full starter file
```

### Step 0.2 — Add filepath comments to every file

Every Python file must start with a single-line comment containing the filepath.

```python
# src/remora/lsp/models.py
```

Apply to all 7 Python files: `__init__.py`, `server.py`, `models.py`, `db.py`,
`graph.py`, `watcher.py`, `runner.py`.

### Step 0.3 — Add `from __future__ import annotations`

Add to every Python file, immediately after the filepath comment:

```python
# src/remora/lsp/models.py
from __future__ import annotations
```

This eliminates the need for quoted type hints like `list["ToolSchema"]`.

After adding:
- Remove all quoted type hints: `list["ToolSchema"]` → `list[ToolSchema]`
- Remove all quoted type hints: `list["AgentEvent"]` → `list[AgentEvent]`

### Step 0.4 — Convert plain classes to Pydantic

#### `Trigger` (currently in `runner.py`)

```python
# Before
class Trigger:
    def __init__(self, agent_id: str, correlation_id: str, context: dict = None):
        self.agent_id = agent_id
        self.correlation_id = correlation_id
        self.context = context or {}

# After
class Trigger(BaseModel):
    agent_id: str
    correlation_id: str
    context: dict = Field(default_factory=dict)
```

#### `ExtensionNode` (currently in `runner.py`)

```python
# Before
class ExtensionNode:
    @classmethod
    def matches(cls, node_type: str, name: str) -> bool:
        return False
    ...

# After
class ExtensionNode(BaseModel):
    model_config = ConfigDict(frozen=False)

    @classmethod
    def matches(cls, node_type: str, name: str) -> bool:
        return False

    @property
    def system_prompt(self) -> str:
        return ""

    def get_workspaces(self) -> str:
        return ""

    def get_tool_schemas(self) -> list[ToolSchema]:
        return []
```

### Step 0.5 — Fix event model `__init__` overrides

The current event subclasses override `__init__` to set `event_type` and
`summary`. This is non-idiomatic for Pydantic. Use `model_validator` instead:

```python
# Before
class HumanChatEvent(AgentEvent):
    to_agent: str = ""
    message: str = ""

    def __init__(self, **data):
        data["event_type"] = "HumanChatEvent"
        data["summary"] = f"Human message to {data.get('to_agent', '')}"
        super().__init__(**data)

# After
class HumanChatEvent(AgentEvent):
    to_agent: str = ""
    message: str = ""

    @model_validator(mode="before")
    @classmethod
    def _set_defaults(cls, values: dict) -> dict:
        values.setdefault("event_type", "HumanChatEvent")
        values.setdefault("summary", f"Human message to {values.get('to_agent', '')}")
        return values
```

Apply the same pattern to: `AgentMessageEvent`, `RewriteProposalEvent`,
`RewriteAppliedEvent`, `RewriteRejectedEvent`, `AgentErrorEvent`.

### Step 0.6 — Fix bare `except` in `graph.py`

```python
# Before
except:
    pass

# After
except Exception:
    pass
```

### Step 0.7 — Update internal imports

All `from demo.core import ...` and `from demo.lsp.server import ...` references
must change to `from remora.lsp import ...`.

The circular import between `runner.py` and `server.py` must be broken by
injecting the server reference at runtime rather than importing it at module level:

```python
# runner.py — BEFORE
from demo.lsp.server import server, publish_diagnostics, emit_event

# runner.py — AFTER
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.lsp.server import RemoraLanguageServer
```

The `AgentRunner.__init__` should accept the server as a constructor parameter:

```python
class AgentRunner(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    server: RemoraLanguageServer
    llm: MockLLMClient = Field(default_factory=MockLLMClient)
    queue: asyncio.Queue = Field(default_factory=asyncio.Queue)
    _running: bool = False
```

---

## Phase 1: P0 Runtime Bug Fixes

**Goal:** Fix the 5 bugs that prevent the server from running at all.

### Step 1.1 — Fix `did_save()` attribute error

**File:** `server.py`, in `did_save()` handler.

The `old_by_key` dict contains raw SQLite `dict` rows, not `ASTAgentNode`
objects. Accessing `.remora_id` on a dict raises `AttributeError`.

```python
# Before (line ~113 of server.py)
node.remora_id = old_by_key[key].remora_id

# After
node.remora_id = old_by_key[key]["id"]
```

### Step 1.2 — Fix `trigger()` activation chain check

**File:** `runner.py`, in `AgentRunner.trigger()`.

`get_activation_chain()` returns `list[str]`, but the code treats items as
objects with an `.agent_id` attribute.

```python
# Before (line ~60 of runner.py)
if agent_id in [e.agent_id for e in chain]:

# After
if agent_id in chain:
```

### Step 1.3 — Fix `publish_code_lenses()`

**File:** `server.py`, the `publish_code_lenses()` function.

You cannot push code lenses via notification — the client *requests* them.
The current approach tries to notify with `textDocument/codeLens` params,
which is invalid. Instead, ask the client to refresh.

```python
# Before
async def publish_code_lenses(uri: str, nodes: list[ASTAgentNode]):
    lenses = [node.to_code_lens() for node in nodes]
    server.text_document_publish_diagnostics(
        lsp.PublishDiagnosticsParams(uri=uri, diagnostics=[])
    )
    server.protocol.notify(
        "textDocument/codeLens",
        lsp.CodeLensParams(text_document=lsp.TextDocumentIdentifier(uri=uri))
    )

# After
async def refresh_code_lenses():
    """Ask the client to re-request code lenses."""
    try:
        await server.workspace_code_lens_refresh_async()
    except Exception:
        # Client may not support workspace/codeLens/refresh
        pass
```

Update all call sites to use `await refresh_code_lenses()` (no arguments needed).

### Step 1.4 — Fix `__main__.py` server startup

**File:** `__main__.py`

The current code starts the runner but never starts the LSP server. The
pygls server must run on its own event loop. The fix is to start the server
via `start_io()` (stdio) or `start_tcp()` and embed the runner loop.

```python
# src/remora/lsp/__main__.py
from __future__ import annotations

import asyncio

from remora.lsp.server import server
from remora.lsp.runner import AgentRunner


def main():
    """Start the Remora LSP server with agent runner."""
    runner = AgentRunner(server=server)
    server.runner = runner

    @server.thread()
    async def _start_runner():
        await runner.run_forever()

    server.start_io()


if __name__ == "__main__":
    main()
```

> **Note:** `pygls` manages its own event loop inside `start_io()`. The
> `@server.thread()` decorator schedules the runner coroutine on the
> server's loop. Alternatively, use `server.start_tcp("127.0.0.1", 7777)`
> for TCP mode during development.

### Step 1.5 — Fix event timestamps

**File:** `server.py`, in `emit_event()`.

`asyncio.get_event_loop().time()` returns monotonic clock seconds (useless
for display). Use `time.time()` for Unix epoch timestamps.

```python
# Before
async def emit_event(event):
    event.timestamp = event.timestamp or asyncio.get_event_loop().time()
    ...

# After
import time as _time

async def emit_event(event):
    if not event.timestamp:
        event.timestamp = _time.time()
    server.db.store_event(event)
    server.protocol.notify("$/remora/event", event.model_dump())
    return event
```

### Step 1.6 — Fix `did_open()` diagnostics scope

**File:** `server.py`, in `did_open()`.

Currently publishes **all** in-memory proposals, not just ones for the
opened file:

```python
# Before
await publish_diagnostics(uri, list(server.proposals.values()))

# After
file_proposals = [
    p for p in server.proposals.values()
    if p.file_path == uri
]
await publish_diagnostics(uri, file_proposals)
```

---

## Phase 2: Async Database Layer

**Goal:** Prevent the SQLite calls from blocking the pygls event loop.

### Step 2.1 — Enable WAL mode

Add WAL mode for better concurrent read/write performance:

```python
# db.py — in __init__
self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
self.conn.execute("PRAGMA journal_mode=WAL")
self.conn.execute("PRAGMA synchronous=NORMAL")
self.conn.row_factory = sqlite3.Row
```

### Step 2.2 — Create async wrappers for every public method

Every public method on `RemoraDB` must become async. The simplest approach
is a decorator that offloads the synchronous call to a thread:

```python
# src/remora/lsp/db.py
from __future__ import annotations

import asyncio
import functools
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def async_db(fn):
    """Decorator: run sync DB method in a thread."""
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        return await asyncio.to_thread(fn, self, *args, **kwargs)
    return wrapper
```

Then apply to each method:

```python
class RemoraDB:
    ...

    @async_db
    def upsert_nodes(self, nodes: list[ASTAgentNode]) -> None:
        ...  # existing sync code, unchanged

    @async_db
    def get_node(self, node_id: str) -> dict | None:
        ...

    @async_db
    def get_nodes_for_file(self, uri: str) -> list[dict]:
        ...

    # ... same for all other methods
```

### Step 2.3 — Update all call sites to `await`

Every call to `server.db.*()` in `server.py` and `runner.py` must become
`await server.db.*()`:

```python
# Before
nodes = server.db.get_nodes_for_file(uri)

# After
nodes = await server.db.get_nodes_for_file(uri)
```

**Affected locations** (exhaustive list):
- `server.py`: `did_open()` (3 calls), `did_save()` (5 calls), `hover()` (2),
  `code_lens()` (1), `code_action()` (1), `execute_command()` (3),
  `on_input_submitted()` (1), `emit_event()` (1)
- `runner.py`: `trigger()` (1), `execute_turn()` (5), `create_proposal()` (3),
  `refresh_code_lens()` (1)

---

## Phase 3: Watcher & Parser Fixes

**Goal:** Fix parsing bugs and wire ID injection into the workflow.

### Step 3.1 — Remove double parse

**File:** `watcher.py`, line 27-28.

```python
# Before
self.parser.parse(bytes(text, "utf8"))          # ← result discarded
tree = self.parser.parse(bytes(text, "utf8"))

# After
tree = self.parser.parse(bytes(text, "utf8"))
```

### Step 3.2 — Remove phantom `method_definition` check

Tree-sitter-python does not have a `method_definition` node type. Methods
are `function_definition` nodes nested inside `class_definition` bodies.

To properly detect methods, check if the parent node is a `class_definition`:

```python
# In _find_definitions()
if node.type == "function_definition":
    name_node = node.child_by_field_name("name")
    if name_node:
        name = text[name_node.start_byte:name_node.end_byte]
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        source = text[node.start_byte:node.end_byte]
        source_hash = hashlib.md5(source.encode()).hexdigest()

        # Determine if this is a method (parent is class body)
        is_method = (
            node.parent
            and node.parent.type == "block"
            and node.parent.parent
            and node.parent.parent.type == "class_definition"
        )
        node_type = "method" if is_method else "function"
        ...

elif node.type == "class_definition":
    ...
```

Delete the entire `elif node.type == "method_definition":` block (lines 69-97).

### Step 3.3 — Improve regex fallback for methods

The regex fallback only matches `^(def|class)` at column zero. Add indented
method support:

```python
# Before
for match in re.finditer(r"^(def|class)\s+(\w+)", text, re.MULTILINE):
    ...
    node_type = "function" if match.group(1) == "def" else "class"

# After
for match in re.finditer(
    r"^(\s*)(def|class)\s+(\w+)", text, re.MULTILINE
):
    indent = match.group(1)
    keyword = match.group(2)
    name = match.group(3)
    line_num = text[:match.start()].count("\n") + 1

    if keyword == "class":
        node_type = "class"
    elif indent:
        node_type = "method"
    else:
        node_type = "function"
    ...
```

### Step 3.4 — Wire `inject_ids()` into the save flow

The `inject_ids()` function exists but is never called. Wire it into the
`did_save()` handler so that Remora IDs appear in source files:

```python
# In did_save() — after upserting new nodes
from remora.lsp.watcher import inject_ids

# Only inject if the file is a local path
file_path = Path(uri_to_path(uri))
if file_path.exists():
    inject_ids(file_path, new_nodes)
```

> **Caution:** Writing back to the file during `didSave` can trigger another
> `didSave` event. Guard against recursion with a flag:

```python
# In RemoraLanguageServer.__init__
self._injecting: set[str] = set()

# In did_save()
if uri in server._injecting:
    server._injecting.discard(uri)
    return  # Skip re-processing after our own write

# After inject_ids():
server._injecting.add(uri)
inject_ids(file_path, new_nodes)
```

### Step 3.5 — Add file-level ID support

The concept describes `# remora-file: rm_xyz12345` on the first line. Add
a "file" node to the watcher output:

```python
# In parse_and_inject_ids(), before returning nodes:
file_source = text[:200]  # First 200 chars as summary
file_hash = hashlib.md5(text.encode()).hexdigest()

# Check for existing file-level ID
key = (Path(uri).stem, "file")
if key in old_by_key:
    file_id = old_by_key[key]["id"]
else:
    file_id = generate_id()

nodes.insert(0, ASTAgentNode(
    remora_id=file_id,
    node_type="file",
    name=Path(uri).stem,
    file_path=uri,
    start_line=1,
    end_line=len(text.splitlines()),
    source_code=file_source,
    source_hash=file_hash,
))
```

---

## Phase 4: Agent Integration — Unify Models

**Goal:** Bridge the demo's Pydantic LSP models with the existing Remora
`AgentState` and event system so both systems share a single source of truth.

### Step 4.1 — Create `LSPBridgeMixin`

**File:** [NEW] `src/remora/lsp/bridge.py`

A protocol mixin that adds LSP conversion methods to any object with the
standard agent identity fields:

```python
# src/remora/lsp/bridge.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from lsprotocol import types as lsp


@runtime_checkable
class LSPExportable(Protocol):
    """Any object with these fields can export to LSP types."""
    remora_id: str
    node_type: str
    name: str
    file_path: str
    start_line: int
    end_line: int
    status: str


class LSPBridgeMixin:
    """Adds LSP conversion methods to agent identity objects."""

    def to_range(self) -> lsp.Range:
        return lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=0),
            end=lsp.Position(line=self.end_line - 1, character=0),
        )

    def to_code_lens(self) -> lsp.CodeLens:
        icons = {
            "active": "●", "running": "▶",
            "pending_approval": "⏸", "orphaned": "○",
        }
        return lsp.CodeLens(
            range=lsp.Range(
                start=lsp.Position(
                    line=self.start_line - 1, character=0
                ),
                end=lsp.Position(
                    line=self.start_line - 1, character=0
                ),
            ),
            command=lsp.Command(
                title=f"{icons.get(self.status, '?')} {self.remora_id}",
                command="remora.selectAgent",
                arguments=[self.remora_id],
            ),
        )

    def to_hover(
        self, recent_events: list | None = None
    ) -> lsp.Hover:
        lines = [
            f"## {self.name}",
            f"**ID:** `{self.remora_id}`",
            f"**Type:** {self.node_type}",
            f"**Status:** {self.status}",
        ]
        if recent_events:
            lines.extend(["", "---", "", "### Recent Events"])
            for ev in recent_events[:5]:
                summary = getattr(ev, "summary", str(ev))
                lines.append(f"- {summary}")

        return lsp.Hover(
            contents=lsp.MarkupContent(
                kind=lsp.MarkupKind.Markdown,
                value="\n".join(lines),
            ),
            range=self.to_range(),
        )
```

### Step 4.2 — Make `ASTAgentNode` extend `LSPBridgeMixin`

```python
# models.py
class ASTAgentNode(LSPBridgeMixin, BaseModel):
    ...
```

The existing methods (`to_code_lens`, `to_hover`, etc.) on `ASTAgentNode`
stay as overrides with richer functionality. The mixin provides the base
implementations.

### Step 4.3 — Create factory: `AgentState` → `ASTAgentNode`

Add a class method to `ASTAgentNode` that constructs from an existing
`AgentState`:

```python
@classmethod
def from_agent_state(cls, state: AgentState) -> ASTAgentNode:
    """Create an LSP-compatible node from a swarm AgentState."""
    return cls(
        remora_id=state.agent_id,
        node_type=state.node_type,
        name=state.name,
        file_path=state.file_path,
        start_line=state.range[0] if state.range else 1,
        end_line=state.range[1] if state.range else 1,
        source_code="",  # Loaded lazily
        source_hash="",
        parent_id=state.parent_id,
        status="active",
    )
```

### Step 4.4 — Unify event models

The demo defines Pydantic event models (`HumanChatEvent`, `AgentMessageEvent`,
etc.). The existing Remora library uses frozen dataclasses in
`remora.core.events`.

**Strategy:** Keep the Pydantic LSP-specific event models in
`src/remora/lsp/models.py` for LSP serialization, but add converters to/from
the core dataclass events:

```python
# In lsp/models.py
from remora.core.events import (
    AgentMessageEvent as CoreAgentMessageEvent,
    AgentStartEvent as CoreAgentStartEvent,
)

class AgentEvent(BaseModel):
    ...

    def to_core_event(self) -> Any:
        """Convert to core Remora event dataclass."""
        # Override in subclasses
        raise NotImplementedError

    @classmethod
    def from_core_event(cls, event: Any) -> AgentEvent:
        """Create from core Remora event dataclass."""
        event_type = type(event).__name__
        return cls(
            event_type=event_type,
            timestamp=getattr(event, "timestamp", 0.0),
            correlation_id=getattr(
                event, "correlation_id", ""
            ) or "",
            agent_id=getattr(event, "agent_id", None),
            summary=str(event),
        )
```

### Step 4.5 — Use existing `EventStore` as backend

**File:** `server.py`

Replace the custom `db.store_event()` / `db.get_recent_events()` with the
existing `EventStore` from `remora.core.event_store`:

```python
class RemoraLanguageServer(LanguageServer):
    def __init__(
        self,
        event_store: EventStore | None = None,
        subscriptions: SubscriptionRegistry | None = None,
        swarm_state: SwarmState | None = None,
    ):
        super().__init__(name="remora", version="0.1.0")
        self.db = RemoraDB()  # Still used for nodes/edges
        self.event_store = event_store
        self.subscriptions = subscriptions
        self.swarm_state = swarm_state
        ...
```

Update `emit_event()`:

```python
async def emit_event(event):
    if not event.timestamp:
        event.timestamp = time.time()
    # Store in both LSP DB (for quick queries) and EventStore
    await server.db.store_event(event)
    if server.event_store:
        core_event = event.to_core_event()
        await server.event_store.append("swarm", core_event)
    server.protocol.notify(
        "$/remora/event", event.model_dump()
    )
    return event
```

---

## Phase 5: Agent Integration — Wire to SwarmExecutor

**Goal:** Replace the mock LLM client with the real Remora execution pipeline.

### Step 5.1 — Inject `SwarmExecutor` into `AgentRunner`

```python
# runner.py
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.core.swarm_executor import SwarmExecutor
    from remora.lsp.server import RemoraLanguageServer


class AgentRunner(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    server: RemoraLanguageServer
    executor: SwarmExecutor | None = None
    queue: asyncio.Queue = Field(default_factory=asyncio.Queue)
    _running: bool = False
```

### Step 5.2 — Replace `execute_turn()` LLM call

When `executor` is available, delegate to `SwarmExecutor.run_agent()`:

```python
async def execute_turn(self, trigger: Trigger) -> None:
    agent_id = trigger.agent_id
    correlation_id = trigger.correlation_id

    await self.server.db.set_status(agent_id, "running")
    await refresh_code_lenses()
    await self.server.db.add_to_chain(correlation_id, agent_id)

    node = await self.server.db.get_node(agent_id)
    if not node:
        await self.emit_error(
            agent_id, "Node not found", correlation_id
        )
        return

    try:
        if self.executor:
            # Use real SwarmExecutor pipeline
            state = await self._load_agent_state(agent_id)
            if state:
                trigger_event = await self._build_trigger_event(
                    trigger
                )
                await self.executor.run_agent(
                    state, trigger_event
                )
        else:
            # Fallback to mock (for testing)
            agent = ASTAgentNode(**node)
            messages = [
                {
                    "role": "system",
                    "content": agent.to_system_prompt(),
                },
            ]
            response = await MockLLMClient().chat(messages)
            await self.handle_response(
                agent, response, correlation_id
            )
    except Exception as e:
        await self.emit_error(agent_id, str(e), correlation_id)
    finally:
        await self.server.db.set_status(agent_id, "active")
        await refresh_code_lenses()
```

### Step 5.3 — Bridge Grail tools to LSP code actions

When the LSP server discovers agent nodes, also discover their Grail tools
and expose them as code actions:

```python
# In server.py — add a method to RemoraLanguageServer
async def discover_tools_for_agent(
    self, agent: ASTAgentNode
) -> list[ToolSchema]:
    """Discover Grail tools from bundle and convert to
    ToolSchema for LSP code actions."""
    from remora.core.config import load_config
    from remora.core.tools.grail import discover_grail_tools

    config = load_config()
    bundle_name = config.bundle_mapping.get(
        agent.node_type
    )
    if not bundle_name:
        return []

    bundle_dir = (
        Path(config.bundle_root) / bundle_name / "tools"
    )
    if not bundle_dir.exists():
        return []

    grail_tools = discover_grail_tools(
        str(bundle_dir), {}, lambda: {}
    )
    return [
        ToolSchema(
            name=t.schema.name,
            description=t.schema.description,
            parameters=t.schema.parameters,
        )
        for t in grail_tools
    ]
```

Wire this into `did_open()`:

```python
# In did_open(), after upserting nodes:
for node in nodes:
    tools = await server.discover_tools_for_agent(node)
    node.extra_tools = tools
```

### Step 5.4 — Implement `execute_extension_tool()`

Replace the empty stub with actual Grail tool execution:

```python
async def execute_extension_tool(
    self,
    agent: ASTAgentNode,
    tool_name: str,
    params: dict,
    correlation_id: str,
) -> None:
    """Execute a Grail .pym tool by name."""
    from remora.core.tools.grail import discover_grail_tools

    tools = discover_grail_tools(...)
    matching = [
        t for t in tools if t.schema.name == tool_name
    ]
    if not matching:
        await self.emit_error(
            agent.remora_id,
            f"Tool '{tool_name}' not found",
            correlation_id,
        )
        return

    tool = matching[0]
    result = await tool.execute(params, context=None)

    if result.is_error:
        await self.emit_error(
            agent.remora_id, result.output, correlation_id
        )
    else:
        # Emit success event
        await emit_event(AgentEvent(
            event_type="ToolResultEvent",
            agent_id=agent.remora_id,
            correlation_id=correlation_id,
            summary=f"Tool {tool_name}: {result.output[:100]}",
            timestamp=0.0,
        ))
```

### Step 5.5 — Use `SubscriptionRegistry` for event routing

When a `$/remora/submitInput` notification arrives with a chat message,
route it through the `SubscriptionRegistry` so any agent subscribed to
that pattern can receive it:

```python
# In on_input_submitted()
if server.subscriptions and server.event_store:
    from remora.core.events import AgentMessageEvent as CoreMsg

    core_event = CoreMsg(
        from_agent="human",
        to_agent=agent_id,
        content=message,
    )
    await server.event_store.append("swarm", core_event)
    # SubscriptionRegistry handles routing
```

---

## Phase 6: LSP Server Hardening

**Goal:** Implement all missing LSP handlers, fix remaining issues, and
add proper error handling.

### Step 6.1 — Implement `documentSymbol` handler

```python
@server.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
async def document_symbol(
    params: lsp.DocumentSymbolParams,
) -> list[lsp.DocumentSymbol]:
    uri = params.text_document.uri
    nodes = await server.db.get_nodes_for_file(uri)

    symbols = []
    for n in nodes:
        agent = ASTAgentNode(**n)
        symbol_kind = {
            "function": lsp.SymbolKind.Function,
            "class": lsp.SymbolKind.Class,
            "method": lsp.SymbolKind.Method,
            "file": lsp.SymbolKind.File,
        }.get(agent.node_type, lsp.SymbolKind.Variable)

        symbols.append(lsp.DocumentSymbol(
            name=f"{agent.name} [{agent.remora_id}]",
            kind=symbol_kind,
            range=agent.to_range(),
            selection_range=agent.to_range(),
            detail=f"Status: {agent.status}",
        ))

    return symbols
```

### Step 6.2 — Implement `didClose` cleanup

```python
@server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
async def did_close(params: lsp.DidCloseTextDocumentParams):
    uri = params.text_document.uri
    # Clear file-specific proposals from memory
    to_remove = [
        pid for pid, p in server.proposals.items()
        if p.file_path == uri
    ]
    for pid in to_remove:
        del server.proposals[pid]
```

### Step 6.3 — Add `read_node` tool result handling

The `read_node` tool reads another agent's source but does nothing with the
result. Return it so the LLM can use the content:

```python
# In handle_response(), read_node case:
case "read_node":
    target_id = args.get("target_id", "")
    target = await self.server.db.get_node(target_id)
    if target:
        # Return the source code as a tool result
        tool_result = {
            "name": target["name"],
            "type": target["node_type"],
            "source": target.get("source_code", ""),
            "file": target.get("file_path", ""),
        }
        messages.append({
            "role": "tool",
            "content": json.dumps(tool_result),
            "tool_call_id": getattr(
                tool_call, "id", ""
            ),
        })
```

### Step 6.4 — Add structured error handling to all handlers

Wrap each LSP handler in try/except to prevent crashing:

```python
import logging

logger = logging.getLogger("remora.lsp")

@server.feature(lsp.TEXT_DOCUMENT_HOVER)
async def hover(params: lsp.HoverParams) -> lsp.Hover | None:
    try:
        uri = params.text_document.uri
        pos = params.position
        node = await server.db.get_node_at_position(
            uri, pos.line + 1, pos.character
        )
        if not node:
            return None
        agent = ASTAgentNode(**node)
        events = await server.db.get_recent_events(
            agent.remora_id, limit=5
        )
        return agent.to_hover(events)
    except Exception:
        logger.exception("Error in hover handler")
        return None
```

Apply the same pattern to `code_lens`, `code_action`, `document_symbol`,
`execute_command`, and `on_input_submitted`.

### Step 6.5 — Register `$/remora/submitInput` properly

`pygls` may not support `@server.feature()` for custom notification method
names. Use the lower-level `@server.lsp.fm.notification()` decorator or
register manually via `server.lsp.fm.builtin_features`:

```python
# Check pygls version — v1.x uses this pattern:
from pygls.lsp import SERVER_FEATURES

@server.feature("$/remora/submitInput")
async def on_input_submitted(params: dict):
    ...

# If that doesn't work, register manually:
server.lsp.fm.notification("$/remora/submitInput")(
    on_input_submitted
)
```

> **Test this immediately.** If `pygls` silently ignores the registration,
> custom notifications from Neovim will be dropped.

---

## Phase 7: Neovim Client Polish

**Goal:** Fix Lua bugs, upgrade UI, and add cross-platform support.

### Step 7.1 — Fix `__init__.lua` circular require

**Problem:** `__init__.lua` returns `require("remora")` which Lua resolves
back to `__init__.lua` (infinite loop).

```lua
-- Before (demo/nvim/lua/remora/__init__.lua)
return require("remora")

-- After (demo/nvim/lua/remora/init.lua)
-- This IS the remora module. Export the panel + setup.
local M = {}

local panel = require("remora.panel")

M.panel = panel

function M.setup(opts)
    opts = opts or {}
    -- Register custom notification handlers
    vim.lsp.handlers["$/remora/event"] = function(_, result)
        panel.add_event(result)
    end

    vim.lsp.handlers["$/remora/requestInput"] =
        function(_, result)
        local prompt = result.prompt or "Input:"
        vim.ui.input({ prompt = prompt }, function(input)
            if input then
                local params = { input = input }
                if result.agent_id then
                    params.agent_id = result.agent_id
                end
                if result.proposal_id then
                    params.proposal_id = result.proposal_id
                end
                vim.lsp.buf_notify(
                    0, "$/remora/submitInput", params
                )
            end
        end)
    end

    vim.lsp.handlers["$/remora/agentSelected"] =
        function(_, result)
        panel.select_agent(result.agent_id)
    end
end

function M.toggle_panel()
    if panel.is_open() then
        panel.close()
    else
        panel.open()
    end
end

return M
```

### Step 7.2 — Add highlight groups

```lua
-- In M.setup():
local function setup_highlights()
    vim.api.nvim_set_hl(
        0, "RemoraActive", { fg = "#a6e3a1" }
    )
    vim.api.nvim_set_hl(
        0, "RemoraRunning", { fg = "#89b4fa" }
    )
    vim.api.nvim_set_hl(
        0, "RemoraPending", { fg = "#f9e2af" }
    )
    vim.api.nvim_set_hl(
        0, "RemoraOrphaned", { fg = "#6c7086" }
    )
    vim.api.nvim_set_hl(
        0, "RemoraBorder",
        { fg = "#89b4fa", bg = "NONE" }
    )
end

setup_highlights()
```

Update `panel.lua` to use these highlights instead of generic
`DiagnosticOk`, `DiagnosticInfo`, etc.

### Step 7.3 — Add keybindings

```lua
-- In M.setup():
local opts = vim.tbl_deep_extend(
    "force",
    { prefix = "<leader>r" },
    opts or {}
)

local prefix = opts.prefix

vim.keymap.set(
    "n", prefix .. "a", M.toggle_panel,
    { desc = "Toggle Remora agent panel" }
)
vim.keymap.set(
    "n", prefix .. "c",
    function() vim.cmd("RemoraChat") end,
    { desc = "Chat with Remora agent" }
)
vim.keymap.set(
    "n", prefix .. "r",
    function() vim.cmd("RemoraRewrite") end,
    { desc = "Request agent rewrite" }
)
vim.keymap.set(
    "n", prefix .. "y",
    function() vim.cmd("RemoraAccept") end,
    { desc = "Accept proposal" }
)
vim.keymap.set(
    "n", prefix .. "n",
    function() vim.cmd("RemoraReject") end,
    { desc = "Reject proposal" }
)
```

### Step 7.4 — Write cross-platform start script

**File:** [NEW] `scripts/start_lsp.ps1`

```powershell
# scripts/start_lsp.ps1
# Start the Remora LSP server (Windows/PowerShell)

Write-Host "=== Remora LSP Server ==="

# Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python not found"
    exit 1
}

# Check dependencies
$deps = @("pygls", "lsprotocol", "tree_sitter")
foreach ($dep in $deps) {
    $result = python -c "import $dep" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] $dep"
    } else {
        Write-Warning "  [WARN] $dep not installed"
    }
}

# Start server
Write-Host ""
Write-Host "Starting Remora LSP server..."
python -m remora.lsp
```

Also create a `start_lsp.sh` that mirrors it for Linux/macOS.

---

## Phase 8: CLI Entrypoint & pyproject.toml

**Goal:** Make the LSP server a first-class `pyproject.toml` entrypoint,
integrated with the existing CLI.

### Step 8.1 — Add `remora-lsp` script entrypoint

**File:** `pyproject.toml`

```toml
[project.scripts]
remora = "remora.cli:main"
remora-index = "remora.indexer.cli:main"
remora-lsp = "remora.lsp:main"          # ← NEW
```

This requires `src/remora/lsp/__init__.py` to export `main`:

```python
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
    "RemoraDB",
    "LazyGraph",
    "ASTWatcher",
    "RemoraLanguageServer",
    "main",
]
```

After adding, run:

```bash
uv pip install -e .
```

Verify with:

```bash
remora-lsp --help
# or
python -m remora.lsp
```

### Step 8.2 — Add `--lsp` flag to existing `remora swarm start`

**File:** `src/remora/cli/main.py`

The existing `swarm_start()` already has an `--nvim` flag. Add `--lsp` as
an alternative that starts the LSP server instead of the JSON-RPC NvimServer:

```python
@swarm.command("start")
@click.option("--project-root", "-p", default=None)
@click.option("--config-path", "-c", default=None)
@click.option("--nvim", is_flag=True, help="Start JSON-RPC NvimServer")
@click.option(
    "--lsp", is_flag=True,
    help="Start LSP server for Neovim integration",
)
def swarm_start(
    project_root, config_path, nvim, lsp
):
    async def _start():
        ...
        if lsp:
            from remora.lsp.__main__ import main as lsp_main
            lsp_main()
        elif nvim:
            ...  # existing NvimServer code
        else:
            ...  # existing swarm-only code

    asyncio.run(_start())
```

### Step 8.3 — Add `__main__.py` for `python -m remora.lsp`

Ensure `src/remora/lsp/__main__.py` is the canonical entry point (already
done in Step 1.4). Verify it works:

```bash
python -m remora.lsp   # Should start the LSP server on stdio
```

### Step 8.4 — Update hatch build config to include `src/remora/lsp/`

The Lua files need to be included in the wheel:

```toml
# pyproject.toml
[tool.hatch.build.targets.wheel]
packages = ["src/remora", "scripts", "demo"]
include = [
    "src/remora/indexer/scripts/**/*.pym",
    "src/remora/fixtures/**",
    "src/remora/lsp/nvim/**/*.lua",     # ← NEW
    "src/remora/lsp/nvim/**/*.vim",     # ← NEW
]
```

---

## Phase 9: Testing

**Goal:** Add tests that validate the major integration points.

### Step 9.1 — Unit test: `RemoraDB` async wrapper

**File:** [NEW] `tests/unit/test_lsp_db.py`

```python
# tests/unit/test_lsp_db.py
from __future__ import annotations

import pytest

from remora.lsp.db import RemoraDB
from remora.lsp.models import ASTAgentNode


@pytest.fixture
async def db(tmp_path):
    db = RemoraDB(str(tmp_path / "test.db"))
    yield db
    db.close()


async def test_upsert_and_get_node(db):
    node = ASTAgentNode(
        remora_id="rm_test1234",
        node_type="function",
        name="my_func",
        file_path="file:///test.py",
        start_line=1,
        end_line=10,
        source_code="def my_func(): pass",
        source_hash="abc123",
    )
    await db.upsert_nodes([node])
    result = await db.get_node("rm_test1234")
    assert result is not None
    assert result["name"] == "my_func"


async def test_get_nodes_for_file(db):
    nodes = [
        ASTAgentNode(
            remora_id=f"rm_test000{i}",
            node_type="function",
            name=f"func_{i}",
            file_path="file:///test.py",
            start_line=i * 10,
            end_line=i * 10 + 5,
            source_code=f"def func_{i}(): pass",
            source_hash=f"hash{i}",
        )
        for i in range(3)
    ]
    await db.upsert_nodes(nodes)
    results = await db.get_nodes_for_file("file:///test.py")
    assert len(results) == 3
```

### Step 9.2 — Unit test: `ASTWatcher` parse correctness

**File:** [NEW] `tests/unit/test_lsp_watcher.py`

```python
# tests/unit/test_lsp_watcher.py
from __future__ import annotations

from remora.lsp.watcher import ASTWatcher


def test_parse_functions_and_classes():
    watcher = ASTWatcher()
    text = '''
def top_level():
    pass

class MyClass:
    def my_method(self):
        pass

def another():
    pass
'''
    nodes = watcher.parse_and_inject_ids(
        "file:///test.py", text
    )
    names = [(n.name, n.node_type) for n in nodes]
    assert ("top_level", "function") in names
    assert ("MyClass", "class") in names
    assert ("my_method", "method") in names
    assert ("another", "function") in names


def test_parse_preserves_ids():
    """Existing IDs should be reused on re-parse."""
    watcher = ASTWatcher()
    text = "def foo(): pass\n"
    nodes1 = watcher.parse_and_inject_ids(
        "file:///t.py", text
    )
    old_nodes = [
        {"name": n.name, "node_type": n.node_type,
         "id": n.remora_id}
        for n in nodes1
    ]
    nodes2 = watcher.parse_and_inject_ids(
        "file:///t.py", text, old_nodes
    )
    assert nodes1[0].remora_id == nodes2[0].remora_id
```

### Step 9.3 — Unit test: LSP model conversions

**File:** [NEW] `tests/unit/test_lsp_models.py`

```python
# tests/unit/test_lsp_models.py
from __future__ import annotations

from remora.lsp.models import (
    ASTAgentNode, ToolSchema, RewriteProposal,
)


def test_tool_schema_to_llm_tool():
    tool = ToolSchema(
        name="my_tool",
        description="Does something",
        parameters={
            "type": "object",
            "properties": {
                "arg1": {"type": "string"},
            },
        },
    )
    llm = tool.to_llm_tool()
    assert llm["function"]["name"] == "my_tool"


def test_rewrite_proposal_diff():
    proposal = RewriteProposal(
        proposal_id="rm_prop1234",
        agent_id="rm_test1234",
        file_path="file:///test.py",
        old_source="def foo(): return 1",
        new_source="def foo(): return 2",
        start_line=1, end_line=1,
        correlation_id="corr_1",
    )
    assert proposal.diff  # Should be non-empty
    ws_edit = proposal.to_workspace_edit()
    assert ws_edit.changes  # Should have edit
```

### Step 9.4 — Integration test: LSP server lifecycle

**File:** [NEW] `tests/integration/test_lsp_server.py`

```python
# tests/integration/test_lsp_server.py
from __future__ import annotations

import asyncio

import pytest
from lsprotocol import types as lsp

from remora.lsp.server import RemoraLanguageServer


@pytest.fixture
async def server(tmp_path):
    """Create a server with a temp DB."""
    srv = RemoraLanguageServer()
    srv.db = RemoraDB(str(tmp_path / "test.db"))
    yield srv
    srv.db.close()


async def test_did_open_creates_nodes(server):
    """Opening a Python file should create agent nodes."""
    text = "def hello(): pass\n"
    params = lsp.DidOpenTextDocumentParams(
        text_document=lsp.TextDocumentItem(
            uri="file:///test.py",
            language_id="python",
            version=1,
            text=text,
        )
    )
    # Call the handler directly
    await did_open(params)

    nodes = await server.db.get_nodes_for_file(
        "file:///test.py"
    )
    assert len(nodes) >= 1
    assert nodes[0]["name"] == "hello"
```

### Step 9.5 — Run all tests

```bash
uv run pytest tests/unit/test_lsp_*.py -v
uv run pytest tests/integration/test_lsp_server.py -v
```

---

## Phase 10: Documentation & README Update

**Goal:** Update all documentation to reflect the new first-class LSP integration.

### Step 10.1 — Update `demo/README.md`

Replace the current `quick_start` section to reference the new entrypoint:

```markdown
## Quick Start

### Install
```bash
uv pip install -e ".[dev]"
```

### Start the LSP Server
```bash
# Standalone
remora-lsp

# Or via CLI
remora swarm start --lsp

# Or via Python module
python -m remora.lsp
```

### Configure Neovim
Add to your `init.lua`:
```lua
vim.lsp.start({
    name = "remora",
    cmd = { "remora-lsp" },
    root_dir = vim.fn.getcwd(),
    filetypes = { "python" },
})
require("remora").setup()
```
```

### Step 10.2 — Add docstrings to all modules

Every module and class should have a docstring. Key ones:

- `server.py`: Module-level docstring explaining the LSP server's role
- `RemoraLanguageServer`: Class docstring listing all features
- `RemoraDB`: Class docstring explaining the schema
- `AgentRunner`: Class docstring explaining the reactive loop
- `ASTWatcher`: Class docstring explaining parsing strategy

### Step 10.3 — Update `HOW_TO_CREATE_AN_AGENT.md`

Add a new section at the end:

```markdown
## LSP Integration

When running with the Neovim LSP integration (`remora-lsp`),
agents automatically get:

- **Code Lens** showing agent ID and status on each function/class
- **Hover** showing agent identity and recent events
- **Code Actions** for chat, rewrite, and tool execution
- **Diagnostics** for pending rewrite proposals
- **Document Symbols** in the outline view

### How It Works

The LSP server uses your `bundle.yaml` configuration to:
1. Discover Grail tools and expose them as code actions
2. Route LLM responses through the same `SwarmExecutor`
3. Display rewrite proposals as diagnostics with accept/reject
4. Forward human chat messages through `SubscriptionRegistry`

No additional agent configuration is needed — the LSP layer
reads the same `remora.yaml` and `bundle.yaml` files.
```

### Step 10.4 — Update `NEOVIM_DEMO_V21_FINAL_CONCEPT.md`

Add a "Current Status" section at the top noting which features are
implemented, which are in progress, and which remain. Link to this
implementation guide for details.

---

## Summary: File Change Matrix

| File | Phase | Action |
|------|-------|--------|
| `pyproject.toml` | 8 | Add `remora-lsp` script, update hatch include |
| [NEW] `src/remora/lsp/__init__.py` | 0, 8 | Package exports + `main()` |
| [NEW] `src/remora/lsp/__main__.py` | 1 | Server+runner startup |
| [NEW] `src/remora/lsp/bridge.py` | 4 | `LSPBridgeMixin` + `LSPExportable` protocol |
| `src/remora/lsp/models.py` | 0, 4 | Add filepath comment, `__future__`, event converters |
| `src/remora/lsp/db.py` | 0, 2 | Add `async_db` decorator, WAL mode |
| `src/remora/lsp/graph.py` | 0, 3 | Fix bare except, add `get_callees()` |
| `src/remora/lsp/watcher.py` | 0, 3 | Fix double parse, method detection, file-level IDs |
| `src/remora/lsp/server.py` | 0, 1, 2, 6 | Fix bugs, add handlers, async calls |
| `src/remora/lsp/runner.py` | 0, 1, 5 | Pydantic, inject executor, wire SwarmExecutor |
| `src/remora/cli/main.py` | 8 | Add `--lsp` flag |
| `nvim/lua/remora/init.lua` | 7 | Fix circular require, add handlers |
| `nvim/lua/remora/panel.lua` | 7 | Use custom highlight groups |
| [NEW] `scripts/start_lsp.ps1` | 7 | Windows start script |
| [NEW] `tests/unit/test_lsp_db.py` | 9 | DB async wrapper tests |
| [NEW] `tests/unit/test_lsp_watcher.py` | 9 | Parser correctness tests |
| [NEW] `tests/unit/test_lsp_models.py` | 9 | Model conversion tests |
| [NEW] `tests/integration/test_lsp_server.py` | 9 | Server lifecycle test |
| `demo/README.md` | 10 | Update quick start |
| `docs/HOW_TO_CREATE_AN_AGENT.md` | 10 | Add LSP integration section |

