# Companion — Refactoring Guide

**Area:** `remora_demo/companion/`
**Components:** Runtime, LSP server, Neovim plugin, Timeline server
**Priority:** 3 (separate product, intentional architectural separation — most issues are documentation/alignment)

---

## Overview

The Companion is a standalone intelligent assistant that runs alongside a developer's editing session. It monitors cursor position, file edits, and open documents, then composes a contextual sidebar with relevant information (semantic search results, task inference, related code).

The Companion has a complete, multi-component implementation:

| Component | Path | Purpose |
|-----------|------|---------|
| Runtime | `runtime.py` | Wires sensors → agents (LLM pipeline) |
| LSP server | `lsp/server.py` | Editor ↔ runtime bridge |
| Neovim plugin | `nvim/lua/companion/init.lua` | Editor integration (sidebar, cursor tracking) |
| Timeline server | `timeline/server.py` | Debug web UI (agent activations + workspace state) |
| Demo harness | `demo/` | Scripted demo scenarios |
| Indexer | `indexing/` | Embedding-based semantic search |
| Agents | `agents/` | Sensors, extractors, analyzers, composers |

The Companion is **intentionally separate** from the main Remora LSP swarm. It is a distinct product with different semantics, different event primitives, and a different workspace model.

---

## Issue 1: Parallel Event System (Intentional — Document Only)

### Situation

The Companion defines its own events in `models/events.py`:

```python
@dataclass(frozen=True)
class CursorMoved:
    file: str; line: int; col: int; lingered: bool = False

@dataclass(frozen=True)
class ContentEdited:
    file: str; start_line: int; end_line: int; text: str

@dataclass(frozen=True)
class PathChanged:
    path: str; value: Any; previous: Any = None
```

The production core has similar events in `remora.core.events.interaction_events`:
```python
class CursorFocusEvent(_FrozenEvent):    # Pydantic, debounced
class ContentChangedEvent(_FrozenEvent): # Pydantic, full diff
```

### Why This Is Intentional

- Companion events use dataclasses (simple, frozen, no schema validation)
- Core events use Pydantic `_FrozenEvent` (serializable, schema-validated, timestamped)
- Companion `CursorMoved` is raw/high-frequency; `CursorFocusEvent` is post-debounce
- `PathChanged` is an internal workspace pub/sub signal — not a domain event

**Do not merge** these into `remora.core.events.*`.

### Action

Add a docstring to `models/events.py`:

```python
"""Companion-specific event types.

These are SEPARATE from remora.core.events.* and intentionally so:
- Companion events use dataclasses; core events use Pydantic _FrozenEvent
- CursorMoved is raw/high-frequency; CursorFocusEvent (core) is debounced
- PathChanged is internal workspace pub/sub — not a core domain event

Do not replace with core event types — semantics differ.

Translation map for future integration:
    CursorMoved(lingered=True) → CursorFocusEvent
    ContentEdited              → ContentChangedEvent (after diff)
    FileChanged(kind="modified") → FileSavedEvent
    PathChanged                → (no core equivalent — internal only)
"""
```

---

## Issue 2: `WorkspaceInterface` vs `CairnWorkspaceService` (Intentional — Document Only)

### Situation

The Companion defines its own workspace abstraction:
```python
class WorkspaceInterface(ABC):
    async def read(self, path: str) -> Any: ...
    async def write(self, path: str, value: Any) -> None: ...
    async def list(self, pattern: str) -> list[str]: ...
    async def delete(self, path: str) -> None: ...
```

With `InMemoryWorkspace` as the implementation. Agents communicate via workspace paths like `/companion/context/file_path`, `/companion/output/sidebar.md`.

### Why This Is Intentional

The companion uses `InMemoryWorkspace` for self-contained operation — no Cairn dependency needed to run a demo. The interface exists so a `CairnWorkspaceAdapter` could be added for production use without changing agent code.

### Action

Add docstring to `agents/base.py`:

```python
class WorkspaceInterface(ABC):
    """Workspace for agent-to-agent communication via shared paths.

    In the demo, InMemoryWorkspace provides self-contained operation.
    In production, a CairnWorkspaceAdapter wrapping CairnWorkspaceService
    (from remora.core.agents.cairn_bridge) could be used for a persistent,
    multi-session workspace backed by the same Cairn workspace as the LSP swarm.
    """
```

---

## Issue 3: `InMemoryWorkspace` Synchronous Fan-out (Low — Document)

`InMemoryWorkspace.write()` synchronously calls all registered listeners during each write. If a listener does LLM inference (possible for agents that respond to path changes), writes block the caller.

```python
# NOTE: InMemoryWorkspace dispatch is synchronous fan-out.
# All listeners run sequentially within write(). Slow agents block write callers.
# For high-throughput use, consider an asyncio.Queue-based approach.
```

---

## Issue 4: LSP Handler Pattern Divergence (Medium)

### Situation

`CompanionLanguageServer` uses the old pre-refactor pattern:
```python
_server: CompanionLanguageServer | None = None

def get_server(config=None) -> CompanionLanguageServer:
    global _server
    if _server is None:
        _server = CompanionLanguageServer(config)
        _register_handlers(_server)   # ← nested decorator registration
    return _server

def _register_handlers(server):
    @server.feature(lsp.INITIALIZE)
    async def on_initialize(...): ...
```

`RemoraLanguageServer` uses the current pattern:
```python
# server_setup.py — called explicitly:
def register_handlers(server: RemoraLanguageServer) -> None:
    ...  # explicit function calls, no nested decorators
```

### Fix

Extract handler registration to `companion_server_setup.py` and update `start_server()`:

```python
# companion/lsp/companion_server_setup.py
def register_handlers(server: CompanionLanguageServer) -> None:
    @server.feature(lsp.INITIALIZE)
    async def on_initialize(params): ...

    @server.feature("$/companion/cursorMoved")
    async def on_cursor_moved(params): ...
    # etc.

# companion/lsp/server.py — simplified:
def start_server(workspace_path=None, ...) -> None:
    config = CompanionConfig(...)
    server = CompanionLanguageServer(config)
    register_handlers(server)
    server.start_io()
```

Remove `get_server()` singleton entirely. `start_server()` is already the intended entry point.

---

## Issue 5: `$/companion/getSidebar` Protocol Mismatch (Medium)

### Situation

The Neovim plugin (`nvim/lua/companion/init.lua`) uses `client.request()` to call `$/companion/getSidebar`:

```lua
client.request("$/companion/getSidebar", {}, function(err, result)
    if result and result.markdown then
        update_sidebar_content(result.markdown)
    end
end)
```

The LSP spec defines `$/...` methods as **notifications only** — they cannot be requests (they have no defined response). Using `client.request()` for a `$/...` method is spec-violating. It works with pygls in practice (pygls echoes the return value of feature handlers back as a response), but:
- Other LSP clients may reject or ignore the request
- pygls behavior may change in future versions

### Fix Option A (Recommended): Use `workspace/executeCommand`

Align with how `remora.lsp` implements similar functionality:

```python
# companion/lsp/server.py
def _register_handlers(server):
    ...
    server.command("companion.getSidebar")(cmd_get_sidebar)

async def cmd_get_sidebar(ls, *args):
    sidebar = await ls.runtime.get_sidebar()
    return {"markdown": sidebar or "", "timestamp": 0.0}
```

```lua
-- companion/nvim/lua/companion/init.lua
client.request("workspace/executeCommand", {
    command = "companion.getSidebar",
    arguments = {},
}, function(err, result) ... end)
```

### Fix Option B: Server-Push Instead of Pull

The Neovim plugin already has a handler for `$/companion/sidebarUpdated`:
```lua
vim.lsp.handlers["$/companion/sidebarUpdated"] = function(_, result)
    if result and result.markdown then
        update_sidebar_content(result.markdown)
    end
end
```

But the server **never sends this notification** — the push handler is dead client code. To complete the push model, add a server-side push after each agent pipeline completes:

```python
# In CompanionRuntime, after sidebar is composed:
async def _maybe_push_sidebar(self) -> None:
    sidebar = await self.get_sidebar()
    if self._lsp_server:
        self._lsp_server.protocol.notify(
            "$/companion/sidebarUpdated",
            {"markdown": sidebar, "timestamp": time.time()}
        )
```

This is cleaner than polling from the client. The polling fallback in `refresh_sidebar()` can remain as a fallback.

### Current Status

The pull model works today (pygls handles it). The push model is wired on the client but missing on the server. Either fix is acceptable; Fix A is lower-risk (spec-compliant), Fix B is architecturally superior (event-driven).

---

## Issue 6: `$/companion/sidebarUpdated` Push — Dead Client Code

The Lua plugin registers a handler for `$/companion/sidebarUpdated` (line 225-229 in `init.lua`), but the companion LSP server has no code that calls `server.protocol.notify("$/companion/sidebarUpdated", ...)`. The push handler is never triggered.

See Issue 5 Fix Option B for how to implement the server-side push.

---

## Issue 7: `on_initialize` Config Mutation (Low)

```python
@server.feature(lsp.INITIALIZE)
async def on_initialize(params):
    if params.root_uri:
        root_path = to_fs_path(params.root_uri)
        server.config.workspace_path = Path(root_path)  # ← mutates config
```

`CompanionConfig` is a `@dataclass` (not frozen), so this works but silently overrides any `workspace_path` passed to `start_server()`. Use `dataclasses.replace` to create a new config:

```python
import dataclasses

async def on_initialize(params):
    if params.root_uri:
        root_path = to_fs_path(params.root_uri)
        server.config = dataclasses.replace(server.config, workspace_path=Path(root_path))
    await server.ensure_runtime_started()
```

---

## Issue 8: `$/companion/getSidebar` Returns Stale Timestamp (Low)

```python
return {"markdown": sidebar or "", "timestamp": 0.0}  # TODO: track actual timestamp
```

The constant `0.0` means clients that check timestamp to avoid re-rendering will either always re-render or never re-render depending on their comparison. Track the real timestamp when the sidebar was composed:

```python
# In CompanionRuntime:
self._sidebar_updated_at: float = 0.0

async def get_sidebar(self) -> str:
    ...  # existing logic
    # After composing:
    self._sidebar_updated_at = time.time()
    return self._sidebar_text

# In on_get_sidebar handler:
return {
    "markdown": sidebar or "",
    "timestamp": server.runtime._sidebar_updated_at,
}
```

---

## Issue 9: Timeline Server Uses `SimpleHTTPRequestHandler` in asyncio Process (Low)

`TimelineServer.start()` runs `HTTPServer` in a background thread using `threading.Thread`. The `TimelineHandler` accesses `self.runtime` which is the `CompanionRuntime` (an asyncio object). Accessing asyncio objects from a thread without an event loop is unsafe.

Specifically, `_serve_activations()` calls `self.runtime.get_activations()` — if `get_activations()` is a coroutine, this will raise `RuntimeError: no running event loop`.

```python
def _serve_activations(self):
    if self.runtime:
        activations = self.runtime.get_activations()  # ← safe only if sync
```

### Fix

Ensure `get_activations()` is a synchronous method (not async) that reads from a thread-safe in-memory list populated by the async runtime. Or replace the `SimpleHTTPRequestHandler` with a proper async ASGI server (e.g., Starlette) run in the same event loop.

---

## Issue 10: `refresh_sidebar()` Race Condition (Low)

The companion Lua plugin's `refresh_sidebar()` function:

```lua
function M.refresh_sidebar()
    local client = get_client({ silent = true })
    client.notify("$/companion/cursorMoved", ctx)   -- 1. send cursor
    vim.defer_fn(function()
        client.request("$/companion/getSidebar", ...) -- 2. request sidebar
    end, 200)                                          -- fixed 200ms wait
end
```

The 200ms wait is a heuristic — it assumes agents complete within 200ms. If agents are slow (e.g., LLM inference), the sidebar content will be stale. If agents are fast, 200ms is wasteful latency.

The proper fix is the server-push model (Issue 5 Fix B): server notifies client when sidebar is ready, client updates without polling.

---

## Neovim Plugin (`nvim/lua/companion/init.lua`) — Status

The companion Neovim plugin is well-implemented:

- Uses `vim.lsp.config["companion"]` / `vim.lsp.enable("companion")` ✅ (Neovim 0.11+ API)
- Sends `$/companion/cursorMoved` on `CursorHold` ✅
- Has `CompanionSidebar`, `CompanionRefresh`, `CompanionStatus` commands ✅
- Handles `$/companion/sidebarUpdated` push (wired, server not yet implemented) ⚠️
- Uses `client.request("$/companion/getSidebar", ...)` ⚠️ (spec concern, see Issue 5)

The plugin does NOT need major changes if Issue 5 is resolved at the server level (workspace/executeCommand or push model).

---

## Timeline Server (`timeline/server.py`) — Status

- Self-contained HTML debug UI — no external dependencies ✅
- Renders agent activations and workspace state ✅
- Runs in a daemon thread ⚠️ (see Issue 9: thread-safety with asyncio runtime)
- `_serve_workspace()` accesses `workspace._data` directly (private API) ⚠️

Fix for private API access:
```python
# Add to InMemoryWorkspace:
def snapshot(self) -> dict[str, Any]:
    """Return a copy of the current workspace state for debugging."""
    return dict(self._data)

# In timeline/server.py:
def _serve_workspace(self):
    if self.runtime and hasattr(self.runtime, "_workspace"):
        data = self.runtime._workspace.snapshot()
```

---

## Summary of Changes

| Issue | Area | Priority | Work |
|-------|------|----------|------|
| Document event system separation | `models/events.py` | High | Docstring |
| Document workspace abstraction boundary | `agents/base.py` | High | Docstring |
| LSP handler pattern: extract `companion_server_setup.py` | `lsp/server.py` | Medium | Refactor |
| `$/companion/getSidebar` protocol: use `workspace/executeCommand` or push | `lsp/server.py`, `nvim/` | Medium | Align protocol |
| Implement `$/companion/sidebarUpdated` push in server | `lsp/server.py` | Medium | Wire push notification |
| Fix `on_initialize` config mutation | `lsp/server.py` | Low | `dataclasses.replace` |
| Track real sidebar timestamp | `runtime.py`, `lsp/server.py` | Low | Track `_sidebar_updated_at` |
| Fix `TimelineHandler` thread-safety | `timeline/server.py` | Low | Make `get_activations()` sync-safe |
| Fix `_serve_workspace()` private API | `timeline/server.py` | Low | Add `workspace.snapshot()` |
| Document `InMemoryWorkspace` sync fan-out | `models/workspace.py` | Low | Code comment |
| Fix `refresh_sidebar()` race (heuristic 200ms) | `nvim/lua/companion/init.lua` | Low | Needs push model first |

---

## Verification

```bash
devenv shell -- python -c "from remora_demo.companion.runtime import CompanionRuntime, CompanionConfig; print('OK')"
devenv shell -- python -c "from remora_demo.companion.lsp.server import start_server; print('OK')"
devenv shell -- python -c "from remora_demo.companion.timeline.server import TimelineServer; print('OK')"
devenv shell -- python -m pytest remora_demo/companion/test_e2e.py -v
```
