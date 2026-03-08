# Companion — Refactoring Guide

**Area:** `remora_demo/companion/` (old demo) → integrate `src/remora/companion/` (production)
**Priority:** 1 (companion pipeline never runs in current codebase)
**Scope:** Complete replacement of old demo companion; integration of production companion into main LSP

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview) — what the production companion is and how it works
2. [The Integration Gap](#2-the-integration-gap) — why the companion never runs today
3. [Fix: Wire Companion into Main LSP Server](#3-fix-wire-companion-into-main-lsp-server) — changes to `__main__.py` and `server_setup.py`
4. [Fix: Companion Sidebar Command](#4-fix-companion-sidebar-command) — `companion.getSidebar` LSP command handler
5. [Fix: Server-Push Sidebar Updates](#5-fix-server-push-sidebar-updates) — `$/remora/companionSidebarUpdated`
6. [Fix: Rewrite Companion Neovim Plugin](#6-fix-rewrite-companion-neovim-plugin) — connect to remora-lsp, not companion-lsp
7. [Deprecate Old Companion LSP Server](#7-deprecate-old-companion-lsp-server) — archive `remora_demo/companion/lsp/`
8. [CompanionConfig Setup](#8-companionconfig-setup) — how to configure the production companion
9. [Cairn Integration (Optional)](#9-cairn-integration-optional) — workspace persistence
10. [Acceptance Criteria](#10-acceptance-criteria)

---

## 1. Architecture Overview

The production companion lives at `src/remora/companion/`. It is NOT a standalone app — it is a pipeline of event-driven handlers that plugs into the main remora LSP server's EventBus.

### Event Pipeline

```
[Neovim cursor move]
    ↓  $/remora/cursorMoved (LSP notification)
[lsp/notifications.py on_cursor_moved]
    ↓  schedule_cursor_update(delay_ms=200)
[lsp/runtime_ops.py do_cursor_update]
    ↓  event_store.append("cursor", CursorFocusEvent)
[EventStore.append]
    ↓  event_bus.emit(CursorFocusEvent)          ← KEY: triggers companion
[CompanionDispatcher (via EventBus subscription)]
    ↓  ContextExtractorHandler.handle(CursorFocusEvent, state)
[ContextExtractorHandler]
    ↓  reads file, extracts structure → [CompanionContextExtracted]
    ↓  event_store.append → event_bus.emit
[CompanionDispatcher routes CompanionContextExtracted to:]
    ├─ SearchHandler → [CompanionSearchCompleted]
    │      ↓  event_bus.emit → ConnectionFinderHandler → [CompanionConnectionsFound]
    │      ↓  event_bus.emit → SidebarComposerHandler
    ├─ TaskInferrerHandler → [CompanionTaskInferred]
    ├─ ClaimCheckerHandler → [CompanionClaimsChecked]
    └─ SidebarComposerHandler → [CompanionSidebarComposed]
         ↓  markdown sidebar content stored in EventStore
         ↓  push $/remora/companionSidebarUpdated to Neovim
```

### Components

| Component | File | Role |
|-----------|------|------|
| Entry point | `src/remora/companion/startup.py` | `start_companion()` — wires everything |
| Config | `src/remora/companion/config.py` | `CompanionConfig` (Pydantic), `IndexingConfig` |
| Events | `src/remora/companion/events.py` | All companion events extending `_FrozenEvent` |
| State | `src/remora/companion/state.py` | `CompanionState` — event projection |
| Dispatcher | `src/remora/companion/dispatcher.py` | `CompanionDispatcher` — EventBus wiring |
| Indexing | `src/remora/companion/indexing_service.py` | `IndexingService` wrapping `embeddy` |
| Handler base | `src/remora/companion/handlers/base.py` | `CompanionHandlerBase`, `CompanionHandler` protocol |
| Context | `src/remora/companion/handlers/context_extractor.py` | Handles `CursorFocusEvent` |
| Edit | `src/remora/companion/handlers/edit_summarizer.py` | Handles `ContentChangedEvent` |
| Index | `src/remora/companion/handlers/indexing_handler.py` | Handles `FileSavedEvent` |
| Search | `src/remora/companion/handlers/search_handler.py` | Handles `CompanionContextExtracted` |
| Task | `src/remora/companion/handlers/task_inferrer.py` | Handles `CompanionContextExtracted` |
| Claims | `src/remora/companion/handlers/claim_checker.py` | Handles `CompanionContextExtracted` |
| Connections | `src/remora/companion/handlers/connection_finder.py` | Handles `CompanionSearchCompleted` |
| Sidebar | `src/remora/companion/handlers/sidebar_composer.py` | Handles `CompanionContextExtracted`, `CompanionSearchCompleted` |

### Event Imports (Canonical)

```python
# Production companion events — all extend _FrozenEvent
from remora.companion.events import (
    CompanionContextExtracted, CompanionEditSummary,
    CompanionSearchCompleted, CompanionIndexUpdated, CompanionSearchResult,
    CompanionConnectionsFound, CompanionTaskInferred, CompanionClaimsChecked,
    CompanionSidebarComposed,
)

# Core events companion subscribes to (triggers)
from remora.core.events.interaction_events import CursorFocusEvent, ContentChangedEvent, FileSavedEvent
```

---

## 2. The Integration Gap

`src/remora/lsp/__main__.py` creates an `EventBus` and `EventStore` but **never calls `start_companion()`**. As a result:

- `CompanionDispatcher` is never instantiated
- No handlers subscribe to `CursorFocusEvent` via EventBus
- The entire companion pipeline is dead code
- `$/remora/cursorMoved` notifications reach the server, `CursorFocusEvent` is appended to EventStore and emitted on the EventBus, but no one is listening

The old `remora_demo/companion/` compensated with its own standalone LSP server (`companion-lsp`) and its own `CompanionRuntime`. This entire approach is wrong:
- Duplicates cursor tracking (`$/companion/cursorMoved` vs `$/remora/cursorMoved`)
- Duplicates event models (custom dataclasses vs `_FrozenEvent`)
- Uses a separate LSP server that the Neovim plugin must connect to independently
- Has no integration with `EventStore`, `EventBus`, or `CairnWorkspaceService`

---

## 3. Fix: Wire Companion into Main LSP Server

### Change to `src/remora/lsp/__main__.py`

In the `_prepare()` coroutine, after creating `event_store`, call `start_companion()`:

```python
async def _prepare():
    from remora.core.code.projections import NodeProjection
    from remora.core.events.event_bus import EventBus
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.store.event_store import EventStore
    from remora.companion.startup import start_companion          # ADD
    from remora.companion.config import CompanionConfig           # ADD

    root = Path.cwd()
    swarm_path = root / ".remora"
    event_store_path = swarm_path / "events" / "events.db"
    subscriptions_path = swarm_path / "subscriptions.db"

    event_bus = EventBus()
    subscriptions = SubscriptionRegistry(subscriptions_path)
    # ... projection, event_store setup (unchanged) ...

    # Wire companion pipeline into shared EventBus                 # ADD
    companion_config = CompanionConfig(                            # ADD
        workspace_path=root,                                       # ADD
        auto_index=True,                                           # ADD
    )                                                              # ADD
    await start_companion(                                         # ADD
        event_store=event_store,                                   # ADD
        event_bus=event_bus,                                       # ADD
        cairn_service=None,   # wire Cairn here when available     # ADD
        config=companion_config,                                   # ADD
    )                                                              # ADD

    return event_store, subscriptions
```

`start_companion()` is async and returns the `CompanionDispatcher`. It:
1. Creates `CompanionState`
2. Creates `IndexingService` (wraps `embeddy` for vector search)
3. Instantiates all 8 handlers
4. Creates `CompanionDispatcher` — which subscribes all handlers to EventBus
5. Optionally indexes the workspace (if `auto_index=True` and `IndexingService` is available)

After this, every `CursorFocusEvent` emitted by `do_cursor_update()` will trigger the companion pipeline.

---

## 4. Fix: Companion Sidebar Command

The Neovim companion plugin needs to retrieve the current sidebar content. Add a `workspace/executeCommand` handler to the main LSP server.

### New file: `src/remora/lsp/handlers/companion.py`

```python
"""Companion sidebar command handlers for the Remora LSP server."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.lsp.protocols import LspServer

logger = logging.getLogger("remora.lsp.companion")


def register_companion_handlers(server: LspServer) -> None:
    """Register companion-specific workspace commands."""

    @server.command("companion.getSidebar")
    async def cmd_get_sidebar(ls, args) -> dict:
        """Return the current companion sidebar markdown."""
        if ls.event_store is None:
            return {"markdown": "", "timestamp": 0.0}
        try:
            # Query EventStore for the latest CompanionSidebarComposed event
            events = await ls.event_store.get_recent_events_by_type(
                "CompanionSidebarComposed", limit=1
            )
            if events:
                latest = events[0]
                payload = latest.get("payload", {})
                return {
                    "markdown": payload.get("markdown", ""),
                    "timestamp": latest.get("timestamp", 0.0),
                }
        except Exception:
            logger.exception("companion.getSidebar failed")
        return {"markdown": "", "timestamp": 0.0}

    @server.command("companion.getState")
    async def cmd_get_state(ls, args) -> dict:
        """Return the current companion state for debugging."""
        if ls.event_store is None:
            return {}
        try:
            events = await ls.event_store.get_recent_events_by_type(
                "CompanionContextExtracted", limit=1
            )
            if events:
                latest = events[0]
                return latest.get("payload", {})
        except Exception:
            logger.exception("companion.getState failed")
        return {}
```

### Wire into `src/remora/lsp/server_setup.py`

```python
from remora.lsp.handlers.companion import register_companion_handlers

def register_handlers(server: RemoraLanguageServer) -> None:
    if server._handlers_registered:
        return
    server._handlers_registered = True
    # ... existing registrations ...
    register_companion_handlers(server)     # ADD
```

**Note:** If `EventStore` doesn't yet have a `get_recent_events_by_type()` method, add one to `event_store_queries.py` or use the existing query methods. Alternatively, query directly:

```python
# Direct query approach (no new EventStore method needed):
async def _get_latest_sidebar(event_store) -> dict | None:
    rows = await event_store.query_events(
        event_type="CompanionSidebarComposed", limit=1, order="DESC"
    )
    return rows[0] if rows else None
```

---

## 5. Fix: Server-Push Sidebar Updates

When `SidebarComposerHandler` produces a `CompanionSidebarComposed` event, the server should push it to the Neovim client immediately rather than waiting for a poll.

### Subscribe to CompanionSidebarComposed in `__main__.py`

After calling `start_companion()`, subscribe a push callback to the EventBus:

```python
from remora.companion.events import CompanionSidebarComposed

def _make_sidebar_push_callback(server):
    async def _push_sidebar(event: CompanionSidebarComposed) -> None:
        try:
            server.protocol.notify(
                "$/remora/companionSidebarUpdated",
                {
                    "markdown": event.markdown,
                    "timestamp": event.timestamp,
                }
            )
        except Exception:
            pass  # Server may not be connected yet
    return _push_sidebar
```

This callback must be registered AFTER the server is initialized (in the `_on_initialized` handler):

```python
@server.feature(lsp.INITIALIZED)
async def _on_initialized(*args) -> None:
    # ... existing startup code ...
    if event_bus is not None:
        event_bus.subscribe(
            CompanionSidebarComposed,
            _make_sidebar_push_callback(server)
        )
```

**Wire `event_bus` into `_run_server()`** — currently `__main__.py` passes only `event_store` and `subscriptions` to `_run_server()`. Add `event_bus` as a third parameter:

```python
def _run_server(event_store=None, subscriptions=None, event_bus=None) -> None:
    ...
    # Store event_bus on server for later use
    server.event_bus = event_bus
```

---

## 6. Fix: Rewrite Companion Neovim Plugin

**`remora_demo/companion/nvim/lua/companion/init.lua`** must be completely rewritten.

### What changes

| Old (wrong) | New (correct) |
|-------------|---------------|
| Connects to separate `companion-lsp` server | Connects to main `remora-lsp` server |
| Sends `$/companion/cursorMoved` | Removed — cursor already tracked by `$/remora/cursorMoved` in `init.lua` |
| `client.request("$/companion/getSidebar", ...)` (spec violation) | `client.request("workspace/executeCommand", {command="companion.getSidebar"}, ...)` |
| Dead `$/companion/sidebarUpdated` handler | Live `$/remora/companionSidebarUpdated` handler |
| Separate plugin startup/client management | Reuses `remora` LSP client from `remora.init.lua` |

### New companion plugin design

The companion plugin should be a **lightweight Neovim plugin** that:
1. Waits for the `remora` LSP client to connect (no separate server)
2. Opens a sidebar window and populates it with `companion.getSidebar`
3. Handles `$/remora/companionSidebarUpdated` push to auto-refresh

```lua
-- remora_demo/companion/nvim/lua/companion/init.lua
-- Companion sidebar plugin — connects to the main remora-lsp server.
-- Does NOT start its own LSP. Requires remora.setup() to be called first.

local M = {}
local _sidebar_win = nil
local _sidebar_buf = nil

-- Get the active remora LSP client (same one panel.lua uses)
local function get_remora_client()
    local clients = vim.lsp.get_clients({ name = "remora" })
    return clients and clients[1] or nil
end

-- Update sidebar buffer content
local function update_sidebar(markdown)
    if not _sidebar_buf or not vim.api.nvim_buf_is_valid(_sidebar_buf) then
        return
    end
    local lines = vim.split(markdown or "No companion context yet.", "\n")
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", true)
    vim.api.nvim_buf_set_lines(_sidebar_buf, 0, -1, false, lines)
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", false)
end

-- Open or focus the companion sidebar window
local function open_sidebar()
    if _sidebar_win and vim.api.nvim_win_is_valid(_sidebar_win) then
        vim.api.nvim_set_current_win(_sidebar_win)
        return
    end
    -- Create scratch buffer
    _sidebar_buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_option(_sidebar_buf, "filetype", "markdown")
    vim.api.nvim_buf_set_option(_sidebar_buf, "modifiable", false)
    vim.api.nvim_buf_set_name(_sidebar_buf, "Companion Sidebar")
    -- Open right split
    vim.cmd("botright vsplit")
    _sidebar_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(_sidebar_win, _sidebar_buf)
    vim.api.nvim_win_set_width(_sidebar_win, 50)
    vim.api.nvim_win_set_option(_sidebar_win, "wrap", true)
    vim.api.nvim_win_set_option(_sidebar_win, "winfixwidth", true)
    -- Return to previous window
    vim.cmd("wincmd p")
end

-- Fetch sidebar via workspace/executeCommand
local function fetch_sidebar()
    local client = get_remora_client()
    if not client then return end
    client.request("workspace/executeCommand", {
        command = "companion.getSidebar",
        arguments = {},
    }, function(err, result)
        if err or not result then return end
        update_sidebar(result.markdown)
    end)
end

-- Register push notification handler (called from setup())
local function register_push_handler()
    vim.lsp.handlers["$/remora/companionSidebarUpdated"] = function(_, result)
        if result and result.markdown then
            update_sidebar(result.markdown)
        end
    end
end

function M.setup()
    register_push_handler()

    -- Commands
    vim.api.nvim_create_user_command("CompanionSidebar", function()
        open_sidebar()
        fetch_sidebar()
    end, { desc = "Open companion sidebar" })

    vim.api.nvim_create_user_command("CompanionRefresh", function()
        fetch_sidebar()
    end, { desc = "Refresh companion sidebar" })
end

return M
```

### Installation

```lua
-- In user's init.lua — companion uses the SAME remora-lsp:
require("remora").setup({ ... })  -- start remora-lsp
require("companion").setup()      -- attach companion sidebar to same client
```

**No separate server startup needed.** The companion pipeline runs inside remora-lsp.

---

## 7. Deprecate Old Companion LSP Server

The following files are **obsolete** once companion is integrated into the main LSP server:

| File | Status |
|------|--------|
| `remora_demo/companion/lsp/server.py` | Delete — replaced by integration in `lsp/__main__.py` |
| `remora_demo/companion/runtime.py` | Delete — replaced by `src/remora/companion/startup.py` |
| `remora_demo/companion/timeline/server.py` | Delete — or keep as debug tool (no companion LSP server to reference) |
| `remora_demo/companion/demo/` | Archive — demo scenarios can be re-created against real pipeline |
| `remora_demo/companion/agents/` | Delete — replaced by `src/remora/companion/handlers/` |
| `remora_demo/companion/models/` | Delete — replaced by `src/remora/companion/events.py` |
| `remora_demo/companion/indexing/` | Delete — replaced by `src/remora/companion/indexing_service.py` |

**Keep:**
- `remora_demo/companion/nvim/lua/companion/` — rewrite (see Section 6)

The `src/remora/companion/` package is the authoritative implementation. The old demo is a historical artifact.

---

## 8. CompanionConfig Setup

`CompanionConfig` in `src/remora/companion/config.py` uses `embeddy` for vector search configuration:

```python
from remora.companion.config import CompanionConfig, IndexingConfig
from embeddy.config import EmbedderConfig, StoreConfig, ChunkConfig

config = CompanionConfig(
    workspace_path=Path.cwd(),
    indexing=IndexingConfig(
        embedder=EmbedderConfig(model="Qwen/Qwen3-Embedding-0.6B"),
        store=StoreConfig(path=".remora/companion/vectors"),
        chunk=ChunkConfig(size=256, overlap=32),
    ),
    session_id=None,              # auto-generated if None
    sidebar_output_path=None,     # file to mirror sidebar to (optional)
    auto_index=True,              # index workspace on startup
)
```

For simpler setups, `CompanionConfig()` uses sensible defaults. The minimum config for `start_companion()` is:

```python
CompanionConfig(workspace_path=Path.cwd())
```

### If `embeddy` is not available

The `IndexingService` wraps `embeddy`. If `embeddy` is not installed, `SearchHandler` will not find results. The rest of the pipeline (ContextExtractor, TaskInferrer, ClaimChecker, SidebarComposer) still works — it just won't show related content.

`start_companion()` should guard against `ImportError` when creating `IndexingService`:

```python
# In startup.py (check existing implementation):
try:
    indexing_service = IndexingService(config.indexing)
except ImportError:
    indexing_service = None   # search disabled, rest of pipeline runs
```

---

## 9. Cairn Integration (Optional)

`start_companion()` accepts `cairn_service: CairnWorkspaceService | None`. When `None`, handlers use their default in-memory state. When provided, `CompanionHandlerBase.initialize(cairn_service)` gives each handler an `AgentWorkspace` backed by Cairn for persistent state across sessions.

To wire Cairn:

```python
from remora.core.agents.cairn_bridge import CairnWorkspaceService

cairn_service = CairnWorkspaceService(...)  # or load from config
await start_companion(event_store, event_bus, cairn_service, config)
```

This is optional for the initial integration. Pass `cairn_service=None` to start.

---

## 10. Acceptance Criteria

- [ ] `start_companion()` is called in `src/remora/lsp/__main__.py`
- [ ] `CompanionDispatcher` subscribes to `CursorFocusEvent`, `ContentChangedEvent`, `FileSavedEvent` on the EventBus
- [ ] Moving cursor in Neovim triggers `ContextExtractorHandler` (verify via log: `EventBus.emit: CursorFocusEvent ... handlers for CursorFocusEvent`)
- [ ] `workspace/executeCommand` `companion.getSidebar` registered in `server_setup.py`
- [ ] `CompanionSidebar` command in Neovim opens sidebar and fetches content
- [ ] `$/remora/companionSidebarUpdated` pushed to client after each `SidebarComposerHandler` run
- [ ] Old `remora_demo/companion/lsp/server.py` and `runtime.py` deleted
- [ ] Old companion Neovim plugin replaced with new minimal plugin
- [ ] `devenv shell -- tach check` passes
- [ ] Full test suite passes

---

## Verification

```bash
# Check companion imports
devenv shell -- python -c "from remora.companion.startup import start_companion; print('OK')"
devenv shell -- python -c "from remora.companion.config import CompanionConfig; print('OK')"
devenv shell -- python -c "from remora.companion.dispatcher import CompanionDispatcher; print('OK')"

# Check integration
devenv shell -- python -c "
from remora.core.events.event_bus import EventBus
from remora.companion.startup import start_companion
from remora.companion.config import CompanionConfig
import asyncio, pathlib

async def test():
    from remora.core.store.event_store import EventStore
    from remora.core.events.subscriptions import SubscriptionRegistry
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmp:
        store = EventStore(os.path.join(tmp, 'events.db'))
        await store.initialize()
        bus = EventBus()
        store.set_event_bus(bus)
        dispatcher = await start_companion(store, bus, None, CompanionConfig(workspace_path=pathlib.Path(tmp)))
        print('Companion started OK')
        print(f'EventBus handlers: {len(bus._handlers)} event types subscribed')

asyncio.run(test())
"
```
