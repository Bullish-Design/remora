# Neovim Expansion Brainstorm — Detail Analysis

> Deep-dive implementation analysis for brainstorm ideas #1, #2, #3, #4, and #7.
> Grounded in the actual Remora codebase architecture as of commit `76858ec`.

---

## 1. Kanata Layer Integration — Modal Agent Modes

### 1.1 Codebase Integration Points

The Kanata integration hooks into **state transitions** that already exist in the Remora Lua plugin. Every transition point is a place where a layer-switch command fires.

**Panel open/close lifecycle** (`panel.lua:487-622`, `panel.lua:652-655`):
- `M.open()` at line 487 — fires when user runs `:RemoraTogglePanel` or `<leader>ra`. This is the primary entry point to "agent mode." On open, switch Kanata to the `remora-agent` layer.
- `M.close()` at line 652 / `M._cleanup()` at line 624 — fires on explicit close (`q` in panel) or when the panel window is closed externally via the `WinClosed` autocmd at line 600. Switch Kanata back to the `coding` layer.
- The `WinClosed` autocmd (line 600-608) is critical: it calls `_cleanup()` on schedule, which means the layer-switch must happen inside `_cleanup()` itself, not just in `close()`, to catch external window closures.

**Proposal review flow** (`commands.py:147-170`, `panel.lua:242-267`):
- When a `RewriteProposalEvent` arrives (rendered at panel.lua line 242), the panel shows a diff. This is the natural trigger for `remora-review` layer — a layer with `y`/`n` for accept/reject, `j`/`k` for hunk navigation.
- `cmd_accept_proposal` (commands.py:148) and `cmd_reject_proposal` (commands.py:173) should switch back to `remora-agent` layer on completion.
- The layer switch needs to happen *client-side* (in Lua), triggered by the arrival of a `RewriteProposalEvent` via `panel.on_event()` at line 667.

**Mode transitions in `init.lua`**:
- `RemoraChat` command (line 221-224) — could switch to `remora-agent` if panel isn't already open.
- `RemoraRewrite` command (line 226-229) — triggers input flow, could momentarily switch to `remora-review`.
- The `$/remora/requestInput` handler (line 177-210) — when routing to panel input, this focuses the input window and enters insert mode. Could switch to a `remora-input` layer for typing.

### 1.2 The `kanata.lua` IPC Bridge

Kanata exposes a TCP or Unix domain socket for runtime commands. The bridge module manages this connection.

**Protocol**: Kanata's IPC accepts s-expression commands over a TCP or Unix socket. The key command is:

```
(layer-switch <layer-name>)
```

**Module structure** — `src/remora/lsp/nvim/lua/remora/kanata.lua`:

```lua
local M = {}
M._socket = nil        -- uv_tcp_t or uv_pipe_t handle
M._connected = false
M._enabled = false
M._socket_path = nil   -- "/tmp/kanata-ipc" or "127.0.0.1:9999"
M._current_layer = nil -- track current layer to avoid redundant switches
M._layers = {}         -- configurable layer name mapping

function M.configure(opts)
    -- opts.socket_path: string (Unix socket path or "host:port")
    -- opts.layers: table mapping logical names to Kanata layer names
    --   e.g. { coding = "coding", agent = "remora-agent", review = "remora-review" }
    -- opts.enabled: boolean
end

function M.connect()
    -- Create uv_pipe_t (Unix) or uv_tcp_t (TCP) via vim.uv
    -- Attempt async connection
    -- Set M._connected on success, log warning on failure
    -- Return true/false
end

function M.switch_layer(logical_name)
    -- If not enabled or not connected, no-op (graceful degradation)
    -- Look up actual Kanata layer name from M._layers table
    -- Skip if M._current_layer == target (debounce)
    -- Write "(layer-switch <layer-name>)\n" to socket
    -- Update M._current_layer
end

function M.disconnect()
    -- Close socket handle if connected
end
```

**Graceful degradation**: The most important design principle. If Kanata is not installed, the socket doesn't exist, or connection fails — the module silently does nothing. Every call to `switch_layer()` checks `M._enabled and M._connected` first. No errors propagate to the user. This makes Kanata integration entirely opt-in with zero cost when absent.

**Connection lifecycle**:
- Connect on first `switch_layer()` call (lazy), not on `setup()`.
- Reconnect on failure with a simple retry (one attempt per `switch_layer()` call if disconnected).
- Disconnect on `VimLeavePre` (already has a hook in init.lua line 297-302).

### 1.3 Layer Definitions

These are *user-defined* in the user's `kanata.kbd` config file. Remora does not ship Kanata configs — it ships documentation and a reference example. The Lua side only needs to know the *names* of the layers.

**Default logical-to-physical mapping** (configurable):

| Logical Name | Default Kanata Layer | Activated When |
|---|---|---|
| `coding` | `"coding"` | Panel closed, normal editing |
| `agent` | `"remora-agent"` | Panel open, chatting with agent |
| `review` | `"remora-review"` | Viewing a `RewriteProposalEvent` diff |
| `timeline` | `"remora-timeline"` | Timeline debugger open (future feature) |
| `theater` | `"remora-theater"` | Conversation theater open (future feature) |

**Reference agent layer design** (for documentation):

```lisp
(deflayer remora-agent
  ;; Home row agent actions (when holding a "remora" modifier or in layer):
  ;;   a = accept proposal       (:RemoraAccept)
  ;;   r = reject proposal       (:RemoraReject)
  ;;   c = chat                  (:RemoraChat)
  ;;   w = rewrite               (:RemoraRewrite)
  ;;   t = toggle tools          (t key in panel)
  ;;   q = close panel           (q key in panel)
  ;;   j/k = scroll chat         (j/k in panel buffer)
  ;;   i = focus input           (focus input window, enter insert)
  ...
)
```

The key insight: in the `remora-agent` layer, single keys like `a`, `r`, `c` directly trigger agent commands because there's no ambiguity — the layer *is* the context. No leader key needed.

### 1.4 Configuration Surface

Additions to `M.setup(opts)` in `init.lua`:

```lua
opts.kanata = {
    enabled = false,             -- Must explicitly opt in
    socket_path = nil,           -- Auto-detect: try /tmp/kanata-ipc, then 127.0.0.1:9999
    layers = {
        coding   = "coding",
        agent    = "remora-agent",
        review   = "remora-review",
        timeline = "remora-timeline",
        theater  = "remora-theater",
    },
}
```

If `opts.kanata` is nil or `opts.kanata.enabled` is false, the kanata module is never loaded. The `require("remora.kanata")` call is conditional:

```lua
-- In init.lua setup():
if opts.kanata and opts.kanata.enabled then
    local kanata = require("remora.kanata")
    kanata.configure(opts.kanata)
    -- Pass kanata to panel for lifecycle hooks
    panel.set_kanata(kanata)
end
```

### 1.5 Files to Create/Modify

| Action | File | Changes |
|--------|------|---------|
| **Create** | `src/remora/lsp/nvim/lua/remora/kanata.lua` | IPC bridge module (~120 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/panel.lua` | Add `M._kanata` field, call `switch_layer()` in `open()`, `_cleanup()`, and `on_event()` for proposal events |
| **Modify** | `src/remora/lsp/nvim/lua/remora/init.lua` | Conditional `require("remora.kanata")`, configure, pass to panel; add Kanata disconnect to `VimLeavePre` |

**panel.lua modifications** (minimal, ~15 lines):

```lua
-- New field:
M._kanata = nil

-- New function (called from init.lua):
function M.set_kanata(kanata)
    M._kanata = kanata
end

-- In M.open(), after line 621:
if M._kanata then M._kanata.switch_layer("agent") end

-- In M._cleanup(), after line 630:
if M._kanata then M._kanata.switch_layer("coding") end

-- In M.on_event(), when event_type == "RewriteProposalEvent":
if M._kanata then M._kanata.switch_layer("review") end
```

### 1.6 Complexity, Risks, and Priority

**Estimated effort**: 1-2 days. The Lua IPC bridge is small (~120 lines), panel modifications are ~15 lines, init.lua changes are ~10 lines. The Kanata protocol is trivial (plaintext s-expressions over a socket).

**Key risks**:
- **Socket path variability**: Kanata's IPC socket location varies by OS and user config. Auto-detection must try multiple paths (Unix: `/tmp/kanata-ipc`, `/run/user/$(id -u)/kanata-ipc`; TCP: `127.0.0.1:9999`).
- **Kanata version compatibility**: The `layer-switch` command is stable, but future Kanata versions could change the IPC protocol. Pin to the current s-expression format and document the tested version.
- **Testing**: Cannot unit-test against real Kanata easily. Test the Lua module with a mock TCP server that validates the sent commands.

**Priority: Low-medium.** This is a small, self-contained feature with high ergonomic value for Kanata users but zero impact for everyone else. It has **no dependencies** on other features and **no other features depend on it**. It's a pure quality-of-life enhancement. Ideal candidate for a quick side project when other work is blocked.

---


## 2. Playwright Web Clipper — Integration Gap Analysis

### 2.1 What Exists Now

The `browser_demo/` package is a fully standalone web clipper with 83 passing tests (79 unit + 4 integration). It lives at the repo root, not inside `src/remora/`. Here's the complete inventory:

| Module | Key Classes/Functions | Purpose |
|--------|----------------------|---------|
| `clipper.py` | `Clipper`, `ClipError`, `clip_url()` | Pipeline orchestrator: fetch → convert → store |
| `fetcher.py` | `Fetcher` (ABC), `PlaywrightFetcher` | Page fetching with Playwright; `_find_system_chromium()` for NixOS |
| `converter.py` | `html_to_markdown()`, `extract_title()` | HTML → markdown via markdownify; CSS selector extraction |
| `store.py` | `ClipStore` | SQLite index + FTS5 + markdown files on disk |
| `models.py` | `ClipMetadata`, `ClipRecord`, `FetchResult` | Pydantic models; YAML frontmatter serialization |
| `cli.py` | CLI entry point | Click-based CLI for `clip`, `search`, `list`, `get`, `delete` |

**What it can do today** (standalone, no Remora integration):
- Fetch any URL via headless Chromium (with NixOS system chromium auto-detection)
- Extract content by CSS selector
- Convert HTML to clean markdown, optionally stripping images
- Store clips as markdown files with YAML frontmatter + SQLite index with FTS5
- Full-text search across titles, content, and tags
- Tag-based filtering
- CRUD operations via CLI

**What it cannot do today** (the gaps):
- Agents cannot access clips — no `SwarmTool` or `RemoraGrailTool` integration
- No LSP commands for clipping from Neovim
- No Neovim UI for browsing, searching, or injecting clips
- No event integration — clipping doesn't emit `RemoraEvent`s
- Package coupling is unresolved — `browser_demo/` is a separate package with its own `pyproject.toml`

### 2.2 Gap: Remora Core Integration — `ClipTool` as a SwarmTool

The primary integration point is giving agents the ability to read and search clips. This means building a new `SwarmTool` subclass.

**Where tools are registered** (`grail.py:108-146`):

`discover_grail_tools()` takes an `AgentContext` and a directory, discovers `.pym` scripts, then appends swarm tools via `build_swarm_tools(context)`. The clip tool needs to be added to this pipeline.

**Option A — Add to `build_swarm_tools()`**: Add a `ClipSearchTool` and `ClipReadTool` alongside `SendMessageTool`, `SubscribeTool`, etc. in `swarm.py`. This is the cleanest integration — the tool gets `AgentContext` and can call into a `ClipStore` instance.

**Option B — Grail script**: Write a `.pym` script that wraps clip operations. Less desirable because Playwright is async and Grail scripts run in a sandbox — the async fetch would need special handling.

**Recommended: Option A.** Two new `SwarmTool` subclasses:

```python
# In src/remora/core/tools/clip_tools.py

class ClipSearchTool(SwarmTool):
    """Search web clips by query string (FTS) or tag."""
    
    def __init__(self, clip_store: ClipStore):
        super().__init__(
            name="clip_search",
            description="Search saved web clips by text query or tag.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "FTS search query"},
                    "tag": {"type": "string", "description": "Filter by tag (optional)"},
                    "limit": {"type": "integer", "description": "Max results", "default": 10},
                },
                "required": ["query"],
            },
        )
        self._store = clip_store
    
    async def execute(self, arguments, context):
        # Delegates to ClipStore.search() or .search_by_tag()
        ...


class ClipReadTool(SwarmTool):
    """Read the full content of a specific clip by ID."""
    
    def __init__(self, clip_store: ClipStore):
        super().__init__(
            name="clip_read",
            description="Read the full markdown content of a saved web clip.",
            parameters={
                "type": "object",
                "properties": {
                    "clip_id": {"type": "string", "description": "The clip ID to read"},
                },
                "required": ["clip_id"],
            },
        )
        self._store = clip_store
    
    async def execute(self, arguments, context):
        # Delegates to ClipStore.get()
        ...
```

**ClipStore lifecycle**: The `ClipStore` instance needs to be shared. It should be created once during `SwarmExecutor.__init__()` (or lazily on first use) with the clips directory configured via `Config`. The store is then passed to `ClipSearchTool` and `ClipReadTool` constructors. Since `ClipStore` uses SQLite WAL mode, concurrent reads from multiple agent turns are safe.

**Integration into tool discovery** (`grail.py:108-146`):

`discover_grail_tools()` currently returns `list[RemoraGrailTool | SwarmTool]`. The clip tools are `SwarmTool` subclasses, so they fit the existing return type. Add them after the `build_swarm_tools(context)` call:

```python
# In discover_grail_tools(), after line 144:
if clip_store is not None:
    from remora.core.tools.clip_tools import ClipSearchTool, ClipReadTool
    tools.append(ClipSearchTool(clip_store))
    tools.append(ClipReadTool(clip_store))
```

The `clip_store` parameter would be threaded from `SwarmExecutor` which owns the `Config` and knows the clips directory path.

**AgentContext extension**: No changes needed. The clip tools don't need swarm callbacks — they only need the `ClipStore` reference, which is injected at construction time. This is the same pattern as `RemoraGrailTool` which receives its dependencies via `__init__` rather than via `AgentContext`.

### 2.3 Gap: LSP Commands

Three new LSP commands for user-initiated clipping from Neovim:

**`remora.clip`** — Clip a URL:

```python
@server.command("remora.clip")
async def cmd_clip(ls, *args) -> dict | None:
    """Clip a URL and return the clip metadata."""
    # args[0] = { url: str, tags?: string[], selector?: str }
    # Uses clip_url() from browser_demo
    # Emits a ClipCreatedEvent via ls.emit_event()
    # Returns { clip_id, title, url, tags }
```

**`remora.clipSearch`** — Search clips:

```python
@server.command("remora.clipSearch")
async def cmd_clip_search(ls, *args) -> list[dict]:
    """Search clips by query. Returns list of clip metadata dicts."""
    # args[0] = { query: str, tag?: str, limit?: int }
    # Delegates to ClipStore.search() or .search_by_tag()
```

**`remora.clipInject`** — Inject clip content into the current buffer:

```python
@server.command("remora.clipInject")
async def cmd_clip_inject(ls, *args) -> dict | None:
    """Retrieve full clip content for injection into buffer."""
    # args[0] = { clip_id: str }
    # Returns { clip_id, title, content } for Lua-side buffer insertion
```

**Server-side `ClipStore` instance**: The `RemoraLanguageServer` needs a `clip_store` field, initialized lazily when the first clip command is invoked. The clips directory defaults to `<project_root>/.remora/clips/`. The server already has `event_store` and `proposals` — `clip_store` follows the same pattern.

**New event type**: `ClipCreatedEvent` added to `events.py`:

```python
class ClipCreatedEvent(BaseModel):
    event_type: Literal["ClipCreatedEvent"] = "ClipCreatedEvent"
    agent_id: str = "user"
    clip_id: str
    url: str
    title: str
    tags: list[str] = []
    timestamp: float
    correlation_id: str = ""
```

This integrates with the existing event flow — the timeline debugger (Section 3) would show clip events, and agents with subscriptions to `ClipCreatedEvent` could react to new clips.

### 2.4 Gap: Neovim UI — `clip.lua`

A new Lua module: `src/remora/lsp/nvim/lua/remora/clip.lua`

**Commands registered in `init.lua`**:

| Command | Keymap | Behavior |
|---------|--------|----------|
| `:RemoraClip [url]` | `<leader>rc` | Prompt for URL (or use arg), send `remora.clip`, show result in notification |
| `:RemoraClipSearch [query]` | `<leader>rs` | Open Telescope picker with FTS results from `remora.clipSearch` |
| `:RemoraClipInject` | `<leader>ri` | Telescope pick → insert clip content below cursor |
| `:RemoraClipBrowse` | `<leader>rb` | Telescope picker listing all clips (via `remora.clipSearch` with empty query or a `remora.clipList` command) |

**Telescope integration**:

The Telescope picker is the natural UI for clip search in Neovim. The picker:
1. Calls `remora.clipSearch` via `vim.lsp.buf_request()` with the prompt text
2. Displays results as `title | url | tags | date` rows
3. On selection (`<CR>`): injects the full clip content below the cursor (or into the panel input, if panel is focused)
4. Preview window shows the clip's markdown content

If Telescope is not available, fall back to `vim.ui.select()` with a simple list.

**Clip-from-visual-selection**: If the user has a URL selected in visual mode and runs `:RemoraClip`, extract the URL from the selection and clip it. This is a small ergonomic win.

**Panel integration**: When a clip is created (via `ClipCreatedEvent` arriving through `$/remora/event`), `panel.on_event()` renders it in the chat history — "Clipped: {title} ({url})". The agent can reference clips in conversation.

### 2.5 Gap: Package Coupling Decision

This is the key architectural question. Three options:

**Option A — Keep `browser_demo/` separate, import as dependency**:
- `src/remora/` adds `browser_demo` as a dependency in its `pyproject.toml`
- Pro: Clean separation, `browser_demo` is independently usable
- Con: Two packages to version, Playwright as a transitive dependency for all Remora users

**Option B — Move into `src/remora/clip/`**:
- Merge `browser_demo/src/browser_demo/*.py` into `src/remora/clip/`
- Pro: Single package, simpler deployment
- Con: Loses standalone usability, Playwright becomes a direct dep of `remora`

**Option C — Optional dependency with lazy import** (recommended):
- Keep `browser_demo/` as a separate package
- In `remora`, declare it as an optional extra: `remora[clip]`
- `ClipStore` is imported directly (it only needs `sqlite3`, no Playwright)
- `PlaywrightFetcher` is imported lazily only when `remora.clip` LSP command is invoked
- If not installed, clip commands return a helpful error: "Install remora[clip] to enable web clipping"

```toml
# In src/remora pyproject.toml
[project.optional-dependencies]
clip = ["browser-demo @ file:../browser_demo"]  # or a published version
```

**Option C is recommended** because:
1. Playwright is heavy (~200MB browser binaries) — not everyone needs it
2. Read-only clip tools (search/read) only need `ClipStore` which uses `sqlite3` — no Playwright
3. The `remora.clip` command (which fetches new pages) is the only path that needs Playwright
4. Graceful degradation: agents can search/read existing clips without Playwright installed

### 2.6 Files to Create/Modify

| Action | File | Changes |
|--------|------|---------|
| **Create** | `src/remora/core/tools/clip_tools.py` | `ClipSearchTool`, `ClipReadTool` (~80 lines) |
| **Create** | `src/remora/lsp/nvim/lua/remora/clip.lua` | Telescope picker, clip commands (~200 lines) |
| **Modify** | `src/remora/core/tools/grail.py` | Add clip tools to `discover_grail_tools()` (~5 lines) |
| **Modify** | `src/remora/core/events.py` | Add `ClipCreatedEvent` (~10 lines) |
| **Modify** | `src/remora/lsp/handlers/commands.py` | Add `remora.clip`, `remora.clipSearch`, `remora.clipInject` (~60 lines) |
| **Modify** | `src/remora/lsp/server.py` | Add `clip_store` field, lazy init (~15 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/init.lua` | Register clip commands and keymaps (~20 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/panel.lua` | Render `ClipCreatedEvent` in chat history (~10 lines) |

### 2.7 Complexity, Risks, and Priority

**Estimated effort**: 2-3 days. The standalone clipper is done; this is integration wiring. The biggest pieces are `clip.lua` (Telescope picker) and the LSP commands.

**Key risks**:
- **Playwright dependency weight**: Even as an optional dep, users who want clipping must install Playwright + Chromium. The `_find_system_chromium()` fallback mitigates this on NixOS, but other distros may still need `playwright install chromium`.
- **SQLite concurrent access**: Both the `EventStore` and `ClipStore` use SQLite with WAL mode. If they're in the same process, this is fine. If the CLI clips while the LSP server is running, they share the same `index.db` — WAL handles concurrent readers + one writer, but two writers can conflict. The LSP server's `ClipStore` should use a connection pool or serialize writes.
- **Telescope optional dependency**: Telescope is not guaranteed to be installed. The Lua code must check for Telescope availability and fall back gracefully.

**Dependencies on other features**: None. The Web Clipper integration is fully self-contained. However, it *enhances* other features:
- **Ritual System (Section 5)** can use a `clip` step type
- **Agent Timeline (Section 3)** renders `ClipCreatedEvent`
- **Agents** gain `clip_search` and `clip_read` tools

**Priority: Medium.** The standalone clipper already works. Integration adds agent-accessible research context and a Neovim-native workflow, but it's not blocking any other feature. The read-only tools (`clip_search`, `clip_read`) are quick wins; the full `remora.clip` command with Playwright is the heavier lift.

## 3. Agent Timeline Debugger — Event Replay Visualization

### 3.1 Data Layer: EventStore Queries

The EventStore already has the core queries the timeline needs. Here's what exists and what's missing:

**Existing query methods that directly serve the timeline**:

| Method | Location | What It Returns | Timeline Use |
|--------|----------|----------------|--------------|
| `replay()` | `event_store.py:347-393` | Async iterator of event dicts, filtered by graph_id, event_types, since/until, after_id | Primary data source — fetches all events in a time range |
| `get_events_for_correlation()` | `event_store.py:425-448` | All events sharing a correlation_id, chronological ASC | Correlation chain highlighting — when user selects an event, show all related events |
| `get_recent_events()` | `event_store.py:395-423` | Recent events for a specific agent (as sender or recipient), newest-first | Agent-focused timeline filtering |
| `get_graph_ids()` | `event_store.py:519-564` | Graph IDs with start/end timestamps and event counts | Graph/session picker — which execution runs are available |

**Missing query: events grouped by agent within a time range**:

The swimlane view needs events organized by agent (from_agent). The existing `replay()` returns a flat chronological stream. The timeline UI could group client-side, but a server-side query avoids transferring and re-grouping large event sets:

```python
async def get_timeline_data(
    self,
    graph_id: str,
    *,
    since: float | None = None,
    until: float | None = None,
    agent_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Get timeline data grouped by agent for swimlane rendering.
    
    Returns:
        {
            "agents": ["agent_a", "agent_b", ...],  # ordered by first event time
            "events": [...],  # flat chronological list
            "correlations": {"corr_1": [event_ids], ...},  # pre-grouped
            "time_range": {"start": float, "end": float},
        }
    """
```

This query does three things the client needs:
1. **Agent list** — distinct `from_agent` values, ordered by first appearance. This defines the swimlane rows.
2. **Flat event list** — chronological, with all fields. The Lua side assigns events to lanes by `from_agent`.
3. **Correlation groups** — pre-computed grouping of event IDs by `correlation_id`, so highlighting a correlation chain is instant (no second round-trip).

**Existing tables that feed the timeline**:

- `events` table: the primary source. All columns are useful — `id`, `event_type`, `timestamp`, `from_agent`, `to_agent`, `correlation_id`, `tags`, `payload`.
- `activation_chain` table (`event_store.py:168-174`): tracks `(correlation_id, agent_id, depth)`. This tells the timeline the *causal depth* of each agent in a correlation chain — depth 0 is the initiator, depth 1 is a direct responder, etc. The replay engine (Section 3.5) uses this for step-through visualization.
- `nodes` table: provides agent metadata (name, file_path, status) for the swimlane labels.

### 3.2 LSP Command: `remora.getTimeline`

A single LSP command serves the timeline data:

```python
@server.command("remora.getTimeline")
async def cmd_get_timeline(ls, *args) -> dict | None:
    """Return timeline data for swimlane rendering.
    
    args[0] = {
        graph_id?: str,           # specific execution (default: latest)
        since?: float,            # start timestamp
        until?: float,            # end timestamp  
        agent_ids?: list[str],    # filter to specific agents
        correlation_id?: str,     # filter to a correlation chain
        limit?: int,              # max events (default: 500)
    }
    
    Returns: {
        agents: [
            { id: str, name: str, status: str, file_path: str }
        ],
        events: [
            { id: int, event_type: str, timestamp: float,
              from_agent: str, to_agent: str, correlation_id: str,
              payload: dict, summary: str }
        ],
        correlations: { [correlation_id]: [event_id, ...] },
        time_range: { start: float, end: float },
        total_events: int,        # total count (before limit)
    }
    """
```

**Why a single command instead of multiple**: The timeline needs agents + events + correlations atomically. Separate requests could return inconsistent data if events arrive between calls. A single command with a single SQLite transaction guarantees consistency.

**Pagination**: For large event sets, `limit` + `after_id` (or `since`/`until` narrowing) provides cursor-based pagination. The Lua side requests the initial window, then fetches more as the user scrolls.

**Correlation-focused mode**: When `correlation_id` is provided, the command returns only events in that chain plus the agents involved. This is the "zoom into correlation" action.

### 3.3 The `timeline.lua` Buffer

The timeline renders in a dedicated buffer (not the panel — the panel is for single-agent chat). The buffer uses extmarks for coloring and virtual text.

**Layout — swimlane rendering**:

```
 Agent A  │ ●─────────●────●           ●──●
 Agent B  │      ●────────────●──●
 Agent C  │           ●──────────────●
          └──────────────────────────────────→ time
           t₀        t₁       t₂     t₃
```

Each row is a "swimlane" for one agent. Events are markers (●) placed proportionally along the time axis. Lines between events in the same correlation chain show causal flow.

**Rendering algorithm**:

1. **Compute lane assignments**: Each unique `from_agent` gets a lane (row index). Order by first event timestamp.
2. **Compute time axis**: Map `[time_range.start, time_range.end]` to `[label_width, win_width]` columns. This is a linear scale with configurable zoom.
3. **Place event markers**: For each event, compute `col = label_width + (event.timestamp - start) / (end - start) * available_cols`. Place a marker character at `(lane, col)`.
4. **Draw correlation lines**: For events sharing a `correlation_id`, draw connecting characters (`─`, `│`, `┌`, `└`, `→`) between markers across lanes. This is the trickiest rendering — it requires a 2D character grid.
5. **Render with NuiLine**: Build the buffer content line by line. Use extmarks for coloring: each event type gets a highlight group (`RemoraTimelineStart`, `RemoraTimelineComplete`, `RemoraTimelineError`, `RemoraTimelineTool`, `RemoraTimelineMessage`).

**Marker characters by event type**:

| Event Type | Marker | Color (highlight group) |
|-----------|--------|------------------------|
| `AgentStartEvent` | `▶` | `RemoraTimelineStart` (green) |
| `AgentCompleteEvent` | `✓` | `RemoraTimelineComplete` (blue) |
| `AgentErrorEvent` | `✗` | `RemoraTimelineError` (red) |
| `ToolCallEvent` | `⚙` | `RemoraTimelineTool` (yellow) |
| `ToolResultEvent` | `◆` | `RemoraTimelineTool` (yellow) |
| `AgentMessageEvent` | `◀▶` | `RemoraTimelineMessage` (cyan) |
| `ModelRequestEvent` | `↑` | `RemoraTimelineModel` (magenta) |
| `ModelResponseEvent` | `↓` | `RemoraTimelineModel` (magenta) |
| Other | `●` | `RemoraTimelineDefault` (gray) |

**Adaptive width compression**: When many events cluster in a short time window, the linear scale produces overlapping markers. Solution: use a log-scale or "fish-eye" zoom where the area around the cursor gets expanded and distant areas compress. Toggle between linear and adaptive with `z`.

**Label column**: Left-aligned agent names, truncated to `label_width` (configurable, default 16). Shows the agent's display name from the `nodes` table (not the raw node_id). If no name is available, falls back to the last path component of `node_id`.

### 3.4 Interaction Model

The timeline buffer is read-only (like the panel chat buffer). All interaction is through keybindings:

| Key | Action | Implementation |
|-----|--------|----------------|
| `h`/`l` | Scroll time axis left/right | Shift `since`/`until` window, re-render |
| `j`/`k` | Move cursor between lanes | Standard cursor movement (each lane is one line) |
| `<CR>` | Inspect event under cursor | Open floating window with full event details (payload, correlation, timestamps) |
| `c` | Highlight correlation chain | Find `correlation_id` of event under cursor, highlight all events in that chain with a distinctive color |
| `f` | Toggle follow mode | When on, new events auto-append and the view scrolls to the latest. When off, the view is frozen. |
| `z` | Toggle zoom mode | Switch between linear and adaptive time scale |
| `+`/`-` | Zoom in/out | Narrow/widen the `since`/`until` range around the cursor's timestamp |
| `r` | Enter replay mode | Step-through replay (Section 3.5) |
| `g` | Go to source | Navigate to the agent's source file (`AgentNode.file_path:start_line`) |
| `q` | Close timeline | Close the buffer and window |

**Floating inspect window**: When `<CR>` is pressed, a floating window (via `vim.api.nvim_open_win` with `relative='cursor'`) shows:

```
┌─────────────────────────────────────┐
│ AgentCompleteEvent                  │
│ Agent: code_reviewer                │
│ Time: 2026-03-03 14:23:45.123      │
│ Correlation: abc123                 │
│ Depth: 1                           │
│ ──────────────────────────────────  │
│ result_summary: "Found 3 issues"   │
│ response: "The function has..."     │
└─────────────────────────────────────┘
```

The window is closed by pressing `q` or `<Esc>`, or by moving the cursor in the timeline buffer.

### 3.5 Replay Engine

Replay mode walks through a correlation chain step-by-step, showing how events cascaded through agents.

**Activation**: Press `r` on any event in the timeline. The replay engine:

1. Reads the `correlation_id` from the event under cursor.
2. Queries `get_events_for_correlation(correlation_id)` for all events in the chain.
3. Queries the `activation_chain` table for depth information.
4. Enters "replay mode" — a modal state where:
   - Only events in the correlation chain are highlighted; everything else is dimmed.
   - A replay cursor (distinct from the Vim cursor) moves through events chronologically.
   - `n`/`N` step forward/backward through the chain.
   - The floating inspect window auto-opens for each step.
   - A status line shows: `Step 3/12 | AgentA → AgentB | depth=1 | ToolCallEvent`

**Subscription match display**: At each step, the replay engine shows *why* the event triggered the next agent:

```
Step 3/12: AgentMessageEvent from agent_a → agent_b
  Matched subscription: agent_b listens for AgentMessageEvent from agent_a
  Subscription pattern: { event_types: ["AgentMessageEvent"], from_agents: ["agent_a"] }
```

This requires querying the `subscriptions` table for the target agent and showing the matching pattern. The LSP server can include subscription match info in the timeline response (or expose a separate `remora.getSubscriptions` command).

**Source code navigation**: When stepping through events involving an agent, pressing `g` opens the agent's source file at the relevant line. This uses `AgentNode.file_path` and `AgentNode.start_line` from the `nodes` table.

### 3.6 Live Tail Integration

The timeline can show events in real-time by hooking into the existing `$/remora/event` notification stream.

**How it works**: The `$/remora/event` notification handler in `init.lua` (line ~173) already calls `panel.on_event(ev)`. Add a similar dispatch to `timeline.on_event(ev)`:

```lua
-- In init.lua, in the $/remora/event handler:
if timeline.is_open() then
    timeline.on_event(ev)
end
```

**`timeline.on_event(ev)`**:
1. Append the event to the in-memory event list.
2. If the event introduces a new `from_agent`, add a new swimlane row.
3. If follow mode is active (`f` toggle), scroll to show the new event and re-render.
4. If follow mode is off, add a "[N new events]" indicator at the right edge.

**Buffer update strategy**: Don't re-render the entire buffer on every event. Instead:
- Append a new marker to the appropriate lane line using `nvim_buf_set_text()`.
- Update correlation lines only if the new event extends an existing chain.
- Full re-render only on zoom/scroll/resize.

### 3.7 Files to Create/Modify

| Action | File | Changes |
|--------|------|---------|
| **Create** | `src/remora/lsp/nvim/lua/remora/timeline.lua` | Swimlane renderer, interaction model, replay engine, live tail (~500-700 lines) |
| **Modify** | `src/remora/core/event_store.py` | Add `get_timeline_data()` method (~40 lines) |
| **Modify** | `src/remora/lsp/handlers/commands.py` | Add `remora.getTimeline` command handler (~40 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/init.lua` | Register `:RemoraTimeline` command, `<leader>rt` keymap, dispatch events to timeline (~15 lines) |

### 3.8 Complexity, Risks, and Priority

**Estimated effort**: 4-6 days. The `timeline.lua` is the largest single Lua module in the project. The swimlane rendering algorithm, correlation line drawing, and replay engine are each non-trivial. The server-side query and LSP command are straightforward.

**Key risks**:
- **Terminal rendering constraints**: Unicode box-drawing characters may not render correctly in all terminal emulators. Need a fallback using ASCII (`-`, `|`, `+`). The marker characters (▶, ✓, ✗, ⚙) depend on font support — use Nerd Font icons or fall back to simpler ASCII.
- **Performance with large event sets**: A busy swarm can generate thousands of events per minute. The timeline must handle 10K+ events without lag. Strategies: server-side pagination (limit parameter), client-side viewport culling (only render visible lines), debounced re-render on scroll.
- **Correlation line complexity**: Drawing lines between events across lanes is a 2D routing problem. For a first version, draw simple vertical drops (no horizontal routing around obstacles). Complex routing can be added later.
- **Follow mode races**: If events arrive faster than rendering can keep up, buffer updates can queue up. Use `vim.schedule()` to coalesce rapid updates into a single re-render per frame.

**Dependencies**:
- Reads from `EventStore` (already exists)
- Needs `activation_chain` table (already exists)
- Benefits from `ClipCreatedEvent` (Section 2) and room events (Section 4) being in the event stream, but doesn't require them
- The Kanata integration (Section 1) can switch to a `remora-timeline` layer when the timeline is open

**Priority: High.** This is the most impactful debugging tool for understanding multi-agent behavior. The EventStore already captures all the data — the timeline just makes it visible. It has high standalone value: even without other new features, the timeline visualizes existing agent interactions. This should be one of the first features implemented.

---

## 4. Multi-Agent Conversation Theater — Structured Group Chat

### 4.1 The Room Concept

A "room" is a space where multiple agents and the human can have a structured conversation. It maps to existing Remora primitives:

**Correlation chain → implicit room**: Every `correlation_id` in the EventStore already represents a causal chain across agents. When Agent A messages Agent B, and Agent B messages Agent C, and C responds back — the entire chain shares a `correlation_id`. The theater can render this as a room retroactively: "show me the conversation that happened around this correlation."

**File-based agent group → topical room**: All agents discovered in a single file form a natural group. A room scoped to `models/user.py` includes all `AgentNode`s in that file. This maps to `EventStore.list_nodes(file_path=...)`.

**Manual room → explicit creation**: The human creates a room, picks agents, and starts a conversation. This is the most interactive mode — the brainstorm's "observe multiple agents discussing a topic."

**Room lifecycle**:

| Type | Created By | Lifetime | Storage |
|------|-----------|----------|---------|
| **Transient** | Auto-detected from correlation chain | Exists only while events are flowing; GC'd when idle | No extra storage — reads from `events` + `activation_chain` tables |
| **Persistent** | Manual `remora.createRoom` command | Until explicitly closed or archived | New `rooms` table in EventStore DB |

The key design insight: transient rooms require **zero new server-side state**. They are a UI-only concept that reads existing data differently. Persistent rooms need a small amount of new state (a `rooms` table with participant list).

### 4.2 Server-Side Room Manager

New file: `src/remora/core/rooms.py`

```python
class Room(BaseModel):
    """A persistent multi-agent conversation room."""
    room_id: str
    name: str
    agent_ids: list[str]          # participants
    created_at: float
    status: Literal["active", "archived"] = "active"
    correlation_id: str | None = None  # links room to a correlation chain

class RoomManager:
    """Manages room lifecycle and message routing."""
    
    def __init__(self, event_store: EventStore):
        self._store = event_store
    
    async def create_room(self, name: str, agent_ids: list[str]) -> Room:
        """Create a persistent room and store it."""
        # Generates a correlation_id for the room
        # Inserts into rooms table
        # Returns Room model
    
    async def get_room(self, room_id: str) -> Room | None:
        """Retrieve room metadata."""
    
    async def get_room_messages(self, room_id: str) -> list[dict]:
        """Get all messages in a room (events with matching correlation_id)."""
        # Delegates to EventStore.get_events_for_correlation()
    
    async def send_message(self, room_id: str, from_agent: str, content: str) -> None:
        """Route a message to all participants in the room."""
        # Creates an AgentMessageEvent with the room's correlation_id
        # Appends to EventStore (which triggers subscriptions)
    
    async def list_rooms(self, status: str = "active") -> list[Room]:
        """List all rooms with given status."""
```

**Database table** (added to EventStore schema):

```sql
CREATE TABLE IF NOT EXISTS rooms (
    room_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    agent_ids TEXT NOT NULL,      -- JSON array
    correlation_id TEXT,
    status TEXT DEFAULT 'active',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

**Message routing**: When a message is sent to a room, the `RoomManager` creates an `AgentMessageEvent` with `to_agent` set to each participant (excluding the sender). This piggybacks on the existing subscription system — each participant agent already has a default subscription for `AgentMessageEvent` with matching `to_agent`. No new subscription patterns needed.

Alternatively, for efficiency, introduce a `RoomMessageEvent` that carries the `room_id` and broadcasts once (not per-participant). Agents subscribe to `RoomMessageEvent` with a `tags` match on the room_id. This is more efficient for rooms with many participants.

### 4.3 New Events

Three new event types in `events.py`:

```python
class RoomCreatedEvent(_FrozenEvent):
    """A conversation room was created."""
    room_id: str
    name: str
    agent_ids: tuple[str, ...]
    created_by: str = "user"         # "user" or agent_id
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)

class RoomMessageEvent(_FrozenEvent):
    """A message sent in a conversation room."""
    room_id: str
    from_agent: str
    content: str
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)

class RoomClosedEvent(_FrozenEvent):
    """A room was archived/closed."""
    room_id: str
    timestamp: float = Field(default_factory=time.time)
```

**Relationship to existing `AgentMessageEvent`**: The `AgentMessageEvent` (events.py:111-119) is point-to-point (`from_agent` → `to_agent`). `RoomMessageEvent` is broadcast to a room. They serve different patterns:
- `AgentMessageEvent`: direct message, 1-to-1, already handled by subscriptions
- `RoomMessageEvent`: group message, 1-to-N, needs room membership check

The theater UI renders both: `AgentMessageEvent`s that share the room's `correlation_id` appear alongside `RoomMessageEvent`s. This means a room conversation can include both direct and broadcast messages.

### 4.4 LSP Layer

Four new commands:

**`remora.createRoom`** — Create a persistent room:
```python
@server.command("remora.createRoom")
async def cmd_create_room(ls, *args) -> dict | None:
    # args[0] = { name: str, agent_ids: list[str] }
    # Creates room via RoomManager
    # Emits RoomCreatedEvent
    # Returns { room_id, name, agent_ids, correlation_id }
```

**`remora.getRoom`** — Get room data for rendering:
```python
@server.command("remora.getRoom")
async def cmd_get_room(ls, *args) -> dict | None:
    # args[0] = { room_id: str } OR { correlation_id: str } (for transient rooms)
    # Returns { room: {id, name, agents: [{id, name, status}]}, messages: [...] }
```

**`remora.sendRoomMessage`** — Send a message as the human:
```python
@server.command("remora.sendRoomMessage")
async def cmd_send_room_message(ls, *args) -> None:
    # args[0] = { room_id: str, content: str }
    # Creates RoomMessageEvent with from_agent="user"
    # Triggers agent subscriptions
```

**`remora.listRooms`** — List active rooms:
```python
@server.command("remora.listRooms")
async def cmd_list_rooms(ls, *args) -> list[dict]:
    # Returns [{ room_id, name, agent_count, last_message_at }]
```

**LSP notification**: `$/remora/roomEvent` — sent when a room message arrives, so the theater UI can update in real-time. This parallels `$/remora/event` but is scoped to room activity:

```json
{
    "room_id": "room_abc",
    "event": { "event_type": "RoomMessageEvent", "from_agent": "agent_a", "content": "...", ... }
}
```

Alternatively, reuse `$/remora/event` (which already carries all events) and let the Lua side filter by `room_id` in the payload. This avoids a new notification type but means the theater needs to inspect every event. Given that `panel.on_event()` already does event-type filtering, this is the simpler approach.

### 4.5 The `theater.lua` UI

Layout — three-pane split:

```
┌──────────────────────────────┬──────────┐
│                              │ Agents   │
│   Conversation               │ ─────    │
│                              │ ● agent_a│
│  [agent_a] 14:23             │ ● agent_b│
│  I think we should use a     │ ○ agent_c│
│  factory pattern here.       │          │
│                              │          │
│  [agent_b] 14:24             │          │
│  Agreed, but we need to      │          │
│  handle the edge case...     │          │
│                              │          │
│  [You] 14:25                 │          │
│  What about error handling?  │          │
│                              │          │
├──────────────────────────────┤          │
│ > Type message here...       │          │
└──────────────────────────────┴──────────┘
```

**Three windows**:
1. **Conversation buffer** (top-left): scrollable, read-only, shows all messages with agent names colored distinctly per participant
2. **Participant sidebar** (right): narrow, shows agent names with status icons (● active, ○ idle, ✗ error)
3. **Input buffer** (bottom-left): single-line input for the human

**Message rendering**: Each message gets a header line with agent name (or "You") and timestamp, followed by indented content lines. Agent names are colored with distinct highlight groups assigned round-robin:

```lua
local agent_colors = {
    "RemoraTheaterAgent1",  -- e.g. blue
    "RemoraTheaterAgent2",  -- e.g. green
    "RemoraTheaterAgent3",  -- e.g. yellow
    "RemoraTheaterAgent4",  -- e.g. magenta
    "RemoraTheaterAgent5",  -- e.g. cyan
}
```

Color assignment is stable: agent_id → hash → color index. Same agent always gets the same color within a session.

**Opening the theater**:
- `:RemoraTheater` — opens room picker (Telescope or `vim.ui.select`) listing active rooms
- `:RemoraTheater <room_id>` — opens specific room
- `:RemoraTheaterNew <name>` — creates a new room, picks agents from current file's nodes

### 4.6 Relationship to `panel.lua`

The theater and panel share rendering patterns but are independent UIs:

| Aspect | Panel (`panel.lua`) | Theater (`theater.lua`) |
|--------|-------------------|----------------------|
| **Scope** | Single agent at cursor | Multiple agents in a room |
| **Window** | Right vsplit, 2 panes (chat + input) | Larger layout, 3 panes (conversation + sidebar + input) |
| **Data source** | `remora.getAgentPanel` → single agent events | `remora.getRoom` → room messages |
| **Event rendering** | Many event types (proposals, errors, tools) | Primarily messages (RoomMessageEvent, AgentMessageEvent) |
| **Cursor tracking** | Updates when cursor moves between agents | Static — tied to a room, not cursor position |

**Shared utilities to extract**: Both modules use NuiLine, event_icons, event_hls, format_time, sanitize. These should be extracted into `src/remora/lsp/nvim/lua/remora/ui.lua`:

```lua
-- remora/ui.lua — shared UI utilities
local M = {}
M.event_icons = { ... }
M.event_hls = { ... }
M.status_icons = { ... }
M.status_hls = { ... }
function M.format_time(ts) ... end
function M.sanitize(s) ... end
function M.render_message_lines(ev, lines) ... end  -- shared message rendering
return M
```

This refactor is not required but reduces duplication. It should be done as a preparatory step before building `theater.lua`.

### 4.7 Auto-Room Formation

The system can automatically detect multi-agent conversations and surface them as transient rooms.

**Detection algorithm**: When the `activation_chain` table shows multiple agents at depth > 0 for a single `correlation_id`, that chain involves multiple agents communicating. Threshold: 3+ agents, or 2 agents with 4+ messages.

**Implementation**: A background check runs periodically (or on each new event with a correlation_id). When a qualifying chain is detected:

1. Query `activation_chain` for all `(correlation_id, agent_id, depth)` tuples.
2. If `COUNT(DISTINCT agent_id) >= 3` for a correlation_id, it qualifies.
3. Create a transient room entry (in-memory, not persisted) with those agents.
4. Send a `$/remora/event` notification with a `TransientRoomDetectedEvent` (or reuse `RoomCreatedEvent` with a `transient=true` flag).
5. The Lua side shows a notification: "Multi-agent conversation detected: agent_a, agent_b, agent_c — [Open Theater]"

**This is a stretch goal.** For the initial implementation, rooms are created manually. Auto-detection adds discoverability later.

### 4.8 Files to Create/Modify

| Action | File | Changes |
|--------|------|---------|
| **Create** | `src/remora/core/rooms.py` | `Room` model, `RoomManager` class (~150 lines) |
| **Create** | `src/remora/lsp/nvim/lua/remora/theater.lua` | Three-pane UI, message rendering, input handling (~400-500 lines) |
| **Create** | `src/remora/lsp/nvim/lua/remora/ui.lua` | Shared rendering utilities extracted from panel.lua (~80 lines) |
| **Modify** | `src/remora/core/events.py` | Add `RoomCreatedEvent`, `RoomMessageEvent`, `RoomClosedEvent` (~30 lines) |
| **Modify** | `src/remora/core/event_store.py` | Add `rooms` table to schema, room CRUD methods (~60 lines) |
| **Modify** | `src/remora/lsp/handlers/commands.py` | Add `remora.createRoom`, `remora.getRoom`, `remora.sendRoomMessage`, `remora.listRooms` (~80 lines) |
| **Modify** | `src/remora/lsp/server.py` | Add `room_manager` field (~5 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/init.lua` | Register `:RemoraTheater`, `:RemoraTheaterNew` commands and keymaps (~20 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/panel.lua` | Import shared utilities from `ui.lua` (refactor, no new functionality) |

### 4.9 Complexity, Risks, and Priority

**Estimated effort**: 5-7 days. The theater is a complex UI (three-pane layout with independent buffers), the room manager is new server-side state, and the event integration needs careful design. The `ui.lua` extraction is a refactoring prerequisite.

**Key risks**:
- **Multi-agent message ordering**: In a room with 3+ agents, messages arrive asynchronously. The conversation buffer must handle out-of-order messages gracefully (sort by timestamp on each render, not by arrival order).
- **Agent response time**: When the human sends a message to a room, all agents receive it via subscriptions and respond independently. Responses may arrive seconds to minutes apart. The UI must show "agent_b is thinking..." indicators while waiting.
- **Window layout complexity**: Three-pane layouts in Neovim are fragile. Window IDs can become invalid if the user manually closes or rearranges windows. Need robust `WinClosed` handling (same pattern as panel.lua line 600-608).
- **Conversation threading**: Linear message order doesn't capture "agent_b is responding to agent_a's message, not to the human's message." Full threading is too complex for v1; use timestamp ordering with `correlation_id` hints for visual grouping.

**Dependencies**:
- Benefits from the `ui.lua` shared utility extraction (but can work without it, duplicating code)
- Uses `EventStore` event flow (already exists)
- Enhanced by Kanata integration (Section 1): `remora-theater` layer
- Enhanced by Timeline debugger (Section 3): can link room conversations to timeline view
- No hard dependencies on other features

**Priority: Medium-low.** This is the most complex UI feature. It delivers a novel interaction mode (watching agents collaborate), but the use case is less frequent than single-agent chat or timeline debugging. Consider implementing after the Timeline Debugger, when the event infrastructure and Lua rendering patterns are well-established.

---

## 5. Project Ritual System — Automated Workflow Orchestration

### 5.1 Ritual Definition Schema

Rituals are YAML files stored in `.remora/rituals/`. Each file defines a reusable workflow:

```yaml
name: daily-review
description: "Run code review across all changed files, summarize findings, and clip reference docs."

triggers:
  - type: manual                     # Only runs when invoked explicitly
  - type: event                      # Or triggered by an event
    event_type: FileSavedEvent
    path_glob: "src/**/*.py"

steps:
  - name: find_changes
    type: shell
    command: "git diff --name-only HEAD~1"

  - name: review_each_file
    type: agent_batch
    node_filter:
      file_paths: "{{ find_changes.stdout | split('\n') }}"
      node_type: function
    message: "Review this function for correctness, edge cases, and performance."
    parallel: true                   # Run all matching agents concurrently
    max_concurrency: 5

  - name: summarize
    type: agent
    node_id: "project_summarizer"    # Specific agent by ID
    message: |
      Summarize the review findings:
      {% for result in review_each_file.results %}
      - {{ result.agent_name }}: {{ result.response | truncate(200) }}
      {% endfor %}

  - name: clip_references
    type: clip
    urls:
      - "https://docs.python.org/3/library/typing.html"
    tags: ["reference", "daily-review"]
    condition: "{{ summarize.response | contains('type hint') }}"

  - name: human_approval
    type: checkpoint
    prompt: "Review complete. Approve to continue with auto-fixes?"
    
  - name: apply_fixes
    type: agent
    node_id: "code_fixer"
    message: "Apply the suggested fixes from the review: {{ summarize.response }}"
    condition: "{{ human_approval.approved }}"
```

**Step types**:

| Type | Purpose | Input | Output |
|------|---------|-------|--------|
| `shell` | Run a shell command | `command` string | `stdout`, `stderr`, `exit_code` |
| `agent` | Run a single specific agent | `node_id` + `message` | `response` string |
| `agent_batch` | Run multiple agents matching a filter | `node_filter` + `message` | `results[]` with per-agent responses |
| `checkpoint` | Pause for human approval | `prompt` string | `approved` boolean, `feedback` string |
| `conditional` | Skip/branch based on expression | `condition` Jinja2 expr | Passes through |
| `parallel` | Run multiple sub-steps concurrently | `steps[]` list | Combined results |
| `clip` | Clip web pages | `urls[]`, `tags`, `selector` | `clips[]` with clip IDs |

### 5.2 Template Engine

Jinja2 provides variable substitution across steps. Each step's output is available to subsequent steps via `{{ step_name.field }}`.

**Context accumulation**:

```python
class RitualContext:
    """Accumulates step outputs for Jinja2 template rendering."""
    
    def __init__(self):
        self._data: dict[str, Any] = {}
    
    def set_step_output(self, step_name: str, output: dict[str, Any]) -> None:
        self._data[step_name] = output
    
    def render(self, template_str: str) -> str:
        """Render a Jinja2 template with accumulated context."""
        from jinja2 import Environment
        env = Environment()
        # Register custom filters
        env.filters["split"] = lambda s, sep: s.split(sep)
        env.filters["truncate"] = lambda s, n: s[:n] + "..." if len(s) > n else s
        env.filters["contains"] = lambda s, sub: sub in s
        template = env.from_string(template_str)
        return template.render(**self._data)
```

**Step output schemas** (what each step type puts into context):

| Step Type | Output Keys |
|-----------|------------|
| `shell` | `stdout: str`, `stderr: str`, `exit_code: int`, `success: bool` |
| `agent` | `response: str`, `agent_id: str`, `agent_name: str` |
| `agent_batch` | `results: list[{agent_id, agent_name, response}]`, `count: int` |
| `checkpoint` | `approved: bool`, `feedback: str` |
| `clip` | `clips: list[{clip_id, url, title}]` |

### 5.3 The Ritual Runner

New file: `src/remora/core/rituals.py`

```python
class RitualRunner:
    """Executes ritual YAML workflows step by step."""
    
    def __init__(
        self,
        event_store: EventStore,
        swarm_executor: SwarmExecutor,
        clip_store: ClipStore | None = None,
    ):
        self._store = event_store
        self._executor = swarm_executor
        self._clip_store = clip_store
        self._running: dict[str, RitualExecution] = {}  # ritual_id -> execution state
    
    async def load_ritual(self, path: Path) -> RitualDefinition:
        """Parse a YAML ritual file into a RitualDefinition model."""
    
    async def run(self, ritual: RitualDefinition) -> RitualResult:
        """Execute a ritual from start to finish."""
        ctx = RitualContext()
        execution = RitualExecution(ritual=ritual, context=ctx)
        self._running[execution.ritual_id] = execution
        
        try:
            for step in ritual.steps:
                # Check condition
                if step.condition and not ctx.evaluate(step.condition):
                    execution.skip_step(step.name)
                    continue
                
                execution.start_step(step.name)
                # Emit RitualStepEvent
                await self._store.append(graph_id, RitualStepEvent(...))
                
                output = await self._execute_step(step, ctx)
                ctx.set_step_output(step.name, output)
                execution.complete_step(step.name, output)
            
            return RitualResult(status="completed", context=ctx)
        except RitualCancelledError:
            return RitualResult(status="cancelled", context=ctx)
        finally:
            del self._running[execution.ritual_id]
    
    async def cancel(self, ritual_id: str) -> None:
        """Cancel a running ritual."""
        if execution := self._running.get(ritual_id):
            execution.cancel()
```

### 5.4 Step Type Implementations

**`shell` step** — subprocess execution:

```python
async def _execute_shell(self, step: RitualStep, ctx: RitualContext) -> dict:
    command = ctx.render(step.command)
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(self._executor._project_root),
    )
    stdout, stderr = await proc.communicate()
    return {
        "stdout": stdout.decode(),
        "stderr": stderr.decode(),
        "exit_code": proc.returncode,
        "success": proc.returncode == 0,
    }
```

**`agent` step** — single agent targeting via `EventStore.get_node()`:

```python
async def _execute_agent(self, step: RitualStep, ctx: RitualContext) -> dict:
    node_id = ctx.render(step.node_id)
    node = await self._store.get_node(node_id)
    if not node:
        raise RitualError(f"Agent {node_id} not found")
    
    message = ctx.render(step.message)
    # Create a ManualTriggerEvent as the trigger
    trigger = ManualTriggerEvent(to_agent=node_id, reason=f"Ritual step: {step.name}")
    
    # Inject the message into the agent's context
    msg_event = AgentMessageEvent(
        from_agent="ritual_runner",
        to_agent=node_id,
        content=message,
        correlation_id=self._correlation_id,
    )
    await self._store.append(self._graph_id, msg_event)
    
    response = await self._executor.run_agent(node, trigger)
    return {"response": response, "agent_id": node_id, "agent_name": node.name}
```

**`agent_batch` step** — pattern matching via `list_nodes()`:

```python
async def _execute_agent_batch(self, step: RitualStep, ctx: RitualContext) -> dict:
    # Resolve filter
    nodes = await self._resolve_node_filter(step.node_filter, ctx)
    
    message_template = step.message
    max_concurrency = step.max_concurrency or 5
    semaphore = asyncio.Semaphore(max_concurrency)
    
    async def run_one(node):
        async with semaphore:
            message = ctx.render(message_template)
            trigger = ManualTriggerEvent(to_agent=node.node_id, reason=f"Ritual batch: {step.name}")
            response = await self._executor.run_agent(node, trigger)
            return {"agent_id": node.node_id, "agent_name": node.name, "response": response}
    
    if step.parallel:
        results = await asyncio.gather(*[run_one(n) for n in nodes], return_exceptions=True)
    else:
        results = [await run_one(n) for n in nodes]
    
    # Filter out exceptions, log them
    clean_results = [r for r in results if isinstance(r, dict)]
    return {"results": clean_results, "count": len(clean_results)}
```

**`checkpoint` step** — uses existing `HumanInputRequestEvent`:

```python
async def _execute_checkpoint(self, step: RitualStep, ctx: RitualContext) -> dict:
    prompt = ctx.render(step.prompt)
    request_id = generate_id()
    
    # Emit HumanInputRequestEvent — reuses existing human-in-the-loop flow
    event = HumanInputRequestEvent(
        graph_id=self._graph_id,
        agent_id="ritual_runner",
        request_id=request_id,
        question=prompt,
        options=("approve", "reject"),
    )
    await self._store.append(self._graph_id, event)
    
    # Wait for HumanInputResponseEvent with matching request_id
    # Uses EventBus.wait_for() with predicate and timeout
    response = await self._event_bus.wait_for(
        lambda ev: (
            isinstance(ev, HumanInputResponseEvent)
            and ev.request_id == request_id
        ),
        timeout=step.timeout or 3600,  # Default 1 hour
    )
    
    return {
        "approved": response.response.lower() in ("approve", "yes", "y"),
        "feedback": response.response,
    }
```

**`clip` step** — delegates to `clip_url()` from browser_demo:

```python
async def _execute_clip(self, step: RitualStep, ctx: RitualContext) -> dict:
    if self._clip_store is None:
        raise RitualError("Clip step requires browser_demo to be installed")
    
    from browser_demo.clipper import clip_url
    
    urls = [ctx.render(u) for u in step.urls]
    tags = step.tags or []
    clips = []
    
    for url in urls:
        record = await clip_url(url, self._clip_store.clips_dir, tags=tags)
        clips.append({"clip_id": record.clip_id, "url": record.url, "title": record.title})
    
    return {"clips": clips}
```

### 5.5 LSP Layer

Four commands:

**`remora.runRitual`** — Start a ritual:
```python
@server.command("remora.runRitual")
async def cmd_run_ritual(ls, *args) -> dict | None:
    # args[0] = { path: str } or { name: str }
    # Loads YAML, starts async execution via RitualRunner
    # Returns { ritual_id, name, step_count }
    # Ritual runs in background; progress via notifications
```

**`remora.listRituals`** — List available rituals:
```python
@server.command("remora.listRituals")
async def cmd_list_rituals(ls, *args) -> list[dict]:
    # Scans .remora/rituals/*.yaml
    # Returns [{ name, description, step_count, triggers }]
```

**`remora.ritualStatus`** — Get status of running ritual:
```python
@server.command("remora.ritualStatus")
async def cmd_ritual_status(ls, *args) -> dict | None:
    # args[0] = { ritual_id: str }
    # Returns { ritual_id, name, status, current_step, steps: [{name, status, elapsed_ms}] }
```

**`remora.cancelRitual`** — Cancel a running ritual:
```python
@server.command("remora.cancelRitual")
async def cmd_cancel_ritual(ls, *args) -> None:
    # args[0] = { ritual_id: str }
    # Calls RitualRunner.cancel()
```

**Progress notification**: `$/remora/ritualProgress` — sent after each step completes:

```json
{
    "ritual_id": "abc123",
    "step_name": "review_each_file",
    "step_status": "completed",
    "step_index": 2,
    "total_steps": 6,
    "elapsed_ms": 45230
}
```

Alternatively, emit ritual events through the standard `$/remora/event` notification stream. The Lua side filters by event_type prefix `Ritual*`. This avoids a new notification type and means ritual events show up in the timeline debugger automatically.

### 5.6 The `ritual.lua` UI

A progress panel showing ritual execution:

```
┌─ Ritual: daily-review ──────────────────────┐
│                                              │
│  ✓ find_changes        (0.3s)               │
│  ✓ review_each_file    (45.2s) [5 agents]   │
│  ⏳ summarize           (running...)         │
│  ○ clip_references     (pending)             │
│  ○ human_approval      (pending)             │
│  ○ apply_fixes         (pending)             │
│                                              │
│  Elapsed: 45.5s                              │
└──────────────────────────────────────────────┘
```

**Commands**:

| Command | Keymap | Behavior |
|---------|--------|----------|
| `:RemoraRitual` | `<leader>rR` | Telescope picker listing available rituals; select to run |
| `:RemoraRitualStatus` | none | Show progress panel for currently running ritual |
| `:RemoraRitualCancel` | none | Cancel the running ritual |

**Step status icons**:

| Status | Icon |
|--------|------|
| pending | `○` |
| running | `⏳` |
| completed | `✓` |
| failed | `✗` |
| skipped | `⊘` |
| cancelled | `⊗` |

**Live updates**: The ritual UI subscribes to `$/remora/event` (or `$/remora/ritualProgress`) and updates the progress panel in real-time. Each step transition triggers a re-render of the affected line.

**Checkpoint interaction**: When a `checkpoint` step is reached, the UI shows the prompt and waits for input. The input can come from:
1. The ritual progress panel itself (a mini input buffer appears)
2. The standard `$/remora/requestInput` flow (reuses the existing human-in-the-loop UI)

Option 2 is preferred because it reuses existing infrastructure. The checkpoint emits `HumanInputRequestEvent`, which triggers the standard `$/remora/requestInput` notification, which `init.lua` already handles.

### 5.7 Event Integration

Three new event types:

```python
class RitualStartedEvent(_FrozenEvent):
    """A ritual workflow started execution."""
    ritual_id: str
    ritual_name: str
    step_count: int
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)

class RitualStepEvent(_FrozenEvent):
    """A ritual step changed status."""
    ritual_id: str
    step_name: str
    step_type: str
    status: str  # "started", "completed", "failed", "skipped"
    output_summary: str = ""  # brief summary of step output
    elapsed_ms: int = 0
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)

class RitualCompletedEvent(_FrozenEvent):
    """A ritual workflow completed (success or failure)."""
    ritual_id: str
    ritual_name: str
    status: str  # "completed", "failed", "cancelled"
    total_elapsed_ms: int = 0
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)
```

These events are appended to the EventStore with the ritual's `correlation_id`, so:
- The **Timeline Debugger** (Section 3) shows ritual steps as events in the swimlane
- The **Event replay** can walk through a ritual's execution step by step
- Other agents can subscribe to `RitualCompletedEvent` and react (e.g., send a notification)

### 5.8 Trigger System

Rituals can be triggered three ways:

**Manual**: User invokes `:RemoraRitual` and picks a ritual. This is the primary mode for v1.

**Event-reactive**: A ritual's `triggers` section specifies event types and filters. When a matching event arrives, the ritual auto-starts. Implementation: register a `SubscriptionPattern` for the ritual's trigger events. The "agent" that receives the trigger is a virtual "ritual_runner" agent that calls `RitualRunner.run()`.

```yaml
triggers:
  - type: event
    event_type: FileSavedEvent
    path_glob: "src/**/*.py"
```

Maps to:

```python
SubscriptionPattern(
    event_types=["FileSavedEvent"],
    path_glob="src/**/*.py",
    to_agent="ritual:daily-review",  # virtual agent ID
)
```

**Cron-like (future)**: Periodic triggers. Not for v1 — requires a timer/scheduler that doesn't exist in the current architecture. Could be added later with `asyncio.create_task` running a loop.

### 5.9 Files to Create/Modify

| Action | File | Changes |
|--------|------|---------|
| **Create** | `src/remora/core/rituals.py` | `RitualRunner`, `RitualContext`, `RitualDefinition`, step executors (~400-500 lines) |
| **Create** | `src/remora/lsp/nvim/lua/remora/ritual.lua` | Progress panel, Telescope picker (~200 lines) |
| **Modify** | `src/remora/core/events.py` | Add `RitualStartedEvent`, `RitualStepEvent`, `RitualCompletedEvent` (~30 lines) |
| **Modify** | `src/remora/lsp/handlers/commands.py` | Add `remora.runRitual`, `remora.listRituals`, `remora.ritualStatus`, `remora.cancelRitual` (~80 lines) |
| **Modify** | `src/remora/lsp/server.py` | Add `ritual_runner` field, lazy init (~10 lines) |
| **Modify** | `src/remora/lsp/nvim/lua/remora/init.lua` | Register `:RemoraRitual*` commands and keymaps (~15 lines) |

**Ritual storage directory**: `.remora/rituals/` under the project root. Discovered by scanning `*.yaml` files.

### 5.10 Complexity, Risks, and Priority

**Estimated effort**: 5-7 days. The ritual runner is the most complex Python module (async step orchestration, Jinja2 templating, multiple step type implementations). The Lua UI is simpler than the timeline or theater.

**Key risks**:
- **Jinja2 security**: Jinja2 templates can execute arbitrary Python in some configurations. Use `SandboxedEnvironment` to restrict template capabilities. Only expose safe filters and the ritual context variables.
- **Agent targeting reliability**: The `agent` step type requires knowing the `node_id` at ritual-write time. If nodes are renamed or files restructured, the ritual breaks. Mitigation: support node queries (by name pattern, by file, by type) in addition to exact IDs.
- **Long-running rituals**: A ritual with many `agent_batch` steps can run for minutes. Need robust cancellation (propagate to `SwarmExecutor`), timeout handling (per-step timeouts), and crash recovery (persist ritual state so it can resume after LSP server restart — stretch goal).
- **Checkpoint blocking**: The `checkpoint` step blocks the ritual until human input arrives. If the user closes Neovim or the LSP server restarts, the checkpoint is lost. For v1, this is acceptable; for v2, persist checkpoint state.
- **Dependency on other features**: The `clip` step type depends on the Web Clipper integration (Section 2). Without it, `clip` steps fail with a helpful error. All other step types work independently.

**Dependencies**:
- `SwarmExecutor.run_agent()` — already exists, the ritual runner delegates to it
- `EventStore` — already exists, ritual events flow through it
- `HumanInputRequestEvent`/`HumanInputResponseEvent` — already exist, checkpoints reuse them
- `EventBus.wait_for()` — already exists, checkpoints use it
- `ClipStore` / `clip_url()` — optional, only for `clip` step type

**Priority: Medium-high.** Rituals are the most powerful automation primitive. They compose all other Remora capabilities (agents, events, clips, human-in-the-loop) into reusable workflows. High value for power users who want to codify their development processes. However, the complexity is significant, so it should be implemented after the Timeline Debugger (which provides essential debugging for ritual execution).

---

## 6. Cross-Feature Dependencies and Priority Matrix

### 6.1 Dependency Graph

No feature has a *hard* dependency on another — each can be implemented independently. However, several features *enhance* each other when present:

```
                  ┌──────────────┐
                  │  Kanata (1)  │
                  └──────┬───────┘
                         │ enhances (layer switches)
                    ┌────┴────┬──────────┐
                    ▼         ▼          ▼
            ┌──────────┐ ┌────────┐ ┌──────────┐
            │Timeline(3)│ │Panel   │ │Theater(4)│
            └──────┬───┘ │(exist) │ └──────┬───┘
                   │      └────────┘        │
                   │ visualizes             │ renders
                   ▼                        ▼
            ┌──────────────────────────────────────┐
            │         EventStore (existing)         │
            └──────────┬───────────────┬───────────┘
                       │               │
                ┌──────┴──┐     ┌──────┴───┐
                │Ritual(5)│     │Clipper(2)│
                └────┬────┘     └──────────┘
                     │ uses clip step
                     └────────── ▶ Clipper (optional)
```

**Enhancement relationships** (not hard dependencies):

| Source Feature | Enhances | How |
|---------------|----------|-----|
| Kanata (1) | Timeline (3), Theater (4), Panel | Layer switches when these UIs open/close |
| Clipper (2) | Ritual (5) | `clip` step type in rituals |
| Clipper (2) | Agents (existing) | `clip_search`, `clip_read` tools |
| Timeline (3) | Ritual (5) | Visualizes ritual step events in swimlanes |
| Timeline (3) | Theater (4) | Links room conversations to timeline view |
| Theater (4) | Timeline (3) | Can open timeline filtered to a room's correlation_id |
| Ritual (5) | All features | Orchestrates agents, clips, checkpoints in sequences |

### 6.2 Shared Infrastructure

All five features share these common patterns:

**New event types**: Every feature except Kanata introduces new event types to `events.py`. These must be added to the `RemoraEvent` union type and the `__all__` list.

| Feature | New Events |
|---------|-----------|
| Clipper (2) | `ClipCreatedEvent` |
| Timeline (3) | None (reads existing events) |
| Theater (4) | `RoomCreatedEvent`, `RoomMessageEvent`, `RoomClosedEvent` |
| Ritual (5) | `RitualStartedEvent`, `RitualStepEvent`, `RitualCompletedEvent` |

**New LSP commands**: All features add commands to `commands.py`. The pattern is identical: `@server.command("remora.xyz")` + async handler + args dict.

| Feature | New Commands |
|---------|-------------|
| Clipper (2) | `remora.clip`, `remora.clipSearch`, `remora.clipInject` |
| Timeline (3) | `remora.getTimeline` |
| Theater (4) | `remora.createRoom`, `remora.getRoom`, `remora.sendRoomMessage`, `remora.listRooms` |
| Ritual (5) | `remora.runRitual`, `remora.listRituals`, `remora.ritualStatus`, `remora.cancelRitual` |

**New Lua modules**: Each UI feature creates a new Lua module under `src/remora/lsp/nvim/lua/remora/`.

| Feature | New Lua File | Approximate Lines |
|---------|-------------|-------------------|
| Kanata (1) | `kanata.lua` | ~120 |
| Clipper (2) | `clip.lua` | ~200 |
| Timeline (3) | `timeline.lua` | ~500-700 |
| Theater (4) | `theater.lua` + `ui.lua` | ~400-500 + ~80 |
| Ritual (5) | `ritual.lua` | ~200 |

**`init.lua` modifications**: Every feature adds commands and keymaps to `init.lua`. These are additive and don't conflict.

### 6.3 Implementation Order

Based on dependencies, standalone value, and complexity, the recommended order is:

1. **Kanata Layer Integration** (1-2 days) — smallest feature, zero dependencies, pure add-on. Can be done as a quick side project any time.

2. **Web Clipper Integration** (2-3 days) — mostly wiring. The standalone clipper exists; this connects it. Creates the `clip` step type infrastructure needed by rituals.

3. **Agent Timeline Debugger** (4-6 days) — highest-impact feature. Reads existing data, no new server-side state required. Establishes the Lua rendering patterns and `ui.lua` shared utilities that theater and ritual UIs build on.

4. **Project Ritual System** (5-7 days) — the most architecturally significant feature. Introduces the workflow orchestration layer. Benefits from clipper (clip steps) and timeline (debugging ritual execution) being available.

5. **Conversation Theater** (5-7 days) — the most complex UI. Benefits from all other features being in place: Kanata (layer switching), timeline (correlation linking), ui.lua (shared rendering), and rituals (can trigger multi-agent conversations).

### 6.4 Priority Matrix

```
                    Impact
                    High ┃
                         ┃  Timeline(3)    Ritual(5)
                         ┃
                    Med  ┃  Clipper(2)     Theater(4)
                         ┃
                    Low  ┃  Kanata(1)
                         ┃
                         ┗━━━━━━━━━━━━━━━━━━━━━━━━
                         Low    Med    High
                                Effort
```

| Feature | Effort | Impact | Priority Score |
|---------|--------|--------|---------------|
| Kanata (1) | Low (1-2d) | Low | Do anytime — quick win for Kanata users |
| Clipper Integration (2) | Low-Med (2-3d) | Medium | Do early — enables ritual clip steps |
| Timeline Debugger (3) | Medium (4-6d) | High | **Do first** — essential for debugging |
| Theater (4) | High (5-7d) | Medium | Do last — complex, niche use case |
| Ritual System (5) | High (5-7d) | High | Do after timeline — needs debugging support |

---

## 7. Summary and Recommended Roadmap

### 7.1 Phase 1 — Quick Wins (Week 1-2)

**Goal**: Ship independently useful features with minimal cross-cutting changes.

| Feature | Estimated Days | Key Deliverables |
|---------|---------------|-----------------|
| Kanata Layer Integration | 1-2 | `kanata.lua`, panel.lua hooks, init.lua config |
| Web Clipper Integration | 2-3 | `clip_tools.py`, `clip.lua`, LSP commands, `ClipCreatedEvent` |

**Phase 1 total**: 3-5 days

**Why these first**: Both are small, self-contained, and don't require any shared infrastructure changes beyond adding event types and LSP commands. Kanata is opt-in ergonomics. Clipper gives agents research context and establishes the optional-dependency pattern.

**Shared work in Phase 1**:
- Establish the pattern for adding new event types to `events.py`
- Establish the pattern for adding new LSP commands to `commands.py`
- Establish the pattern for adding new Lua modules and registering them in `init.lua`

### 7.2 Phase 2 — Core Infrastructure (Week 3-5)

**Goal**: Build the high-impact features that become the foundation for everything else.

| Feature | Estimated Days | Key Deliverables |
|---------|---------------|-----------------|
| Agent Timeline Debugger | 4-6 | `timeline.lua`, `get_timeline_data()`, `remora.getTimeline`, swimlane renderer, replay engine |
| `ui.lua` extraction | 1 | Shared rendering utilities from panel.lua |

**Phase 2 total**: 5-7 days

**Why the Timeline first**: It's the highest-impact feature for understanding multi-agent behavior. It reads existing EventStore data — no new server-side state. It forces the creation of `ui.lua` (shared utilities), which benefits all subsequent UI features. And it provides the debugging tool needed to develop and test the Ritual System.

### 7.3 Phase 3 — Complex Features (Week 6-10)

**Goal**: Build the advanced orchestration and collaboration features.

| Feature | Estimated Days | Key Deliverables |
|---------|---------------|-----------------|
| Project Ritual System | 5-7 | `rituals.py`, `ritual.lua`, YAML schema, step executors, ritual events |
| Conversation Theater | 5-7 | `rooms.py`, `theater.lua`, room events, three-pane UI |

**Phase 3 total**: 10-14 days

**Why this order**: Rituals before Theater because rituals have higher standalone value (automated workflows) and the theater benefits from having rituals available (rituals can set up multi-agent conversations for the theater to display).

### 7.4 Open Questions for All Features

These cross-cutting design decisions affect multiple features and should be resolved before implementation begins:

1. **Event type explosion**: Adding 7+ new event types (ClipCreated, RoomCreated, RoomMessage, RoomClosed, RitualStarted, RitualStep, RitualCompleted) to the `RemoraEvent` union. Should the union be replaced with a registry pattern (dynamic event types) instead of a static union? Pros: extensibility. Cons: lose type safety.

2. **LSP command namespace**: Current commands use flat names (`remora.chat`, `remora.clip`). As the command count grows (from ~8 to ~20+), should we namespace them (`remora.clip.search`, `remora.room.create`)? LSP protocol supports dotted names.

3. **Lua module loading strategy**: Currently `init.lua` directly requires all modules. With 7+ Lua files, consider lazy loading: only `require("remora.timeline")` when `:RemoraTimeline` is first invoked. This reduces startup time for users who don't use all features.

4. **Telescope as hard or soft dependency**: Multiple features (clip, ritual, theater) benefit from Telescope pickers. Should Telescope be declared as a dependency of the Neovim plugin, or should all features provide `vim.ui.select` fallbacks? The `vim.ui.select` fallback is more portable but less powerful (no fuzzy search, no preview).

5. **EventStore as universal store**: The EventStore already stores events, nodes, subscriptions, edges, activation chains, proposals, cursor focus, and command queue. Adding rooms and rituals pushes it further toward a general-purpose database. Should there be a separate DB for non-event data, or is a single SQLite file the right choice for simplicity?

6. **`ui.lua` extraction scope**: How much of panel.lua should move to `ui.lua`? Minimal: just the shared constants (icons, highlights, format_time). Maximal: shared message rendering functions that both panel and theater use. The answer depends on how much actual rendering code is truly shared vs. just superficially similar.

7. **Configuration surface growth**: Each feature adds options to `setup(opts)`. With 5 features, the config object grows significantly. Should features use sub-tables (`opts.kanata`, `opts.clip`, `opts.timeline`) or stay flat? Sub-tables are cleaner but mean deeper nested configs. Section 1 already uses `opts.kanata = { ... }` — follow that pattern for consistency.

---

### 1. [Kanata Layer Integration — Modal Agent Modes](#1-kanata-layer-integration--modal-agent-modes)
- **1.1 Codebase Integration Points** — Where layer switches fire: `panel.lua` open/close lifecycle, proposal accept/reject flow, `init.lua` mode transitions
- **1.2 The `kanata.lua` IPC Bridge** — TCP/Unix socket client, layer-switch command protocol, connection management, graceful degradation when Kanata is absent
- **1.3 Layer Definitions** — Concrete layer specs for coding, agent-interaction, proposal-review, and timeline-debugger contexts; mapping to existing Remora keymaps
- **1.4 Configuration Surface** — `setup(opts)` additions: `kanata_socket`, `kanata_layers` table, `kanata_enabled` toggle
- **1.5 Files to Create/Modify** — New: `kanata.lua`; Modified: `panel.lua`, `init.lua`
- **1.6 Complexity, Risks, and Priority** — Estimated effort, dependency on user having Kanata, testing strategy

### 2. [Playwright Web Clipper — Integration Gap Analysis](#2-playwright-web-clipper--integration-gap-analysis)
- **2.1 What Exists Now** — `browser_demo/` package inventory: `Clipper`, `PlaywrightFetcher`, `ClipStore`, `ClipRecord`, CLI, FTS search — 83 tests
- **2.2 Gap: Remora Core Integration** — `ReadClipTool` as a `SwarmTool`, registration in `discover_grail_tools()`, `AgentContext` clip access
- **2.3 Gap: LSP Commands** — `remora.clip`, `remora.clipSearch`, `remora.clipInject` command handlers in `commands.py`
- **2.4 Gap: Neovim UI** — `clip.lua` module: `:RemoraClip`, `:RemoraClipSearch` (Telescope picker), `:RemoraClipInject`, `:RemoraClipBrowse`
- **2.5 Gap: Package Coupling** — Moving from standalone `browser_demo/` to integrated `src/remora/clip/`, or keeping as external dependency
- **2.6 Files to Create/Modify** — New: `clip.lua`, `src/remora/core/tools/clip.py`, LSP commands; Modified: `commands.py`, `init.lua`
- **2.7 Complexity, Risks, and Priority** — Playwright dependency weight, NixOS considerations, effort estimate

### 3. [Agent Timeline Debugger — Event Replay Visualization](#3-agent-timeline-debugger--event-replay-visualization)
- **3.1 Data Layer: EventStore Queries** — Existing methods that serve the timeline: `replay()`, `get_events_for_correlation()`, `get_recent_events()`, `get_graph_ids()`; new query: events-grouped-by-agent-within-time-range
- **3.2 LSP Command: `remora.getTimeline`** — Request/response schema, time range parameters, agent filtering, correlation chain grouping
- **3.3 The `timeline.lua` Buffer** — Swimlane rendering algorithm: agents as rows, time as columns, event markers as extmarks; adaptive width compression; NuiLine rendering
- **3.4 Interaction Model** — Keybindings: h/l scroll, j/k lane switch, CR inspect, c correlation highlight, f follow mode, z zoom, r replay; floating inspect window
- **3.5 Replay Engine** — Step-through replay: correlation_id chain walk, subscription match display, source code navigation, temporal highlighting
- **3.6 Live Tail Integration** — Hooking into `$/remora/event` notification stream for real-time timeline updates
- **3.7 Files to Create/Modify** — New: `timeline.lua`, LSP command; Modified: `commands.py`, `init.lua`, `event_store.py` (new query methods)
- **3.8 Complexity, Risks, and Priority** — Terminal rendering constraints, performance with large event sets, estimated effort

### 4. [Multi-Agent Conversation Theater — Structured Group Chat](#4-multi-agent-conversation-theater--structured-group-chat)
- **4.1 The Room Concept** — Mapping rooms to correlation chains, file-based agent groups, manual room creation; room lifecycle (transient vs persistent)
- **4.2 Server-Side Room Manager** — `src/remora/core/rooms.py`: `Room` model, `RoomManager` class, room creation/join/leave, message routing
- **4.3 New Events** — `RoomCreatedEvent`, `RoomMessageEvent`, `RoomClosedEvent`; integration with existing `AgentMessageEvent` flow and `RemoraEvent` union
- **4.4 LSP Layer** — `remora.getRoom`, `remora.createRoom`, `remora.sendRoomMessage` commands; `$/remora/roomEvent` notification
- **4.5 The `theater.lua` UI** — Split-pane layout: conversation buffer + participant sidebar + input buffer; message rendering per-agent; human intervention
- **4.6 Relationship to `panel.lua`** — Shared rendering patterns (NuiLine, event icons, status highlights), but independent window management; potential shared utility extraction
- **4.7 Auto-Room Formation** — Detecting multi-agent correlation chains and offering transient rooms; using `activation_chain` table
- **4.8 Files to Create/Modify** — New: `rooms.py`, `theater.lua`, events, LSP commands; Modified: `events.py`, `event_store.py`, `commands.py`, `init.lua`
- **4.9 Complexity, Risks, and Priority** — UI complexity, event routing, estimated effort

### 5. [Project Ritual System — Automated Workflow Orchestration](#5-project-ritual-system--automated-workflow-orchestration)
- **5.1 Ritual Definition Schema** — YAML structure: `name`, `description`, `steps[]`, `triggers[]`; step types: `shell`, `agent`, `agent_batch`, `checkpoint`, `conditional`, `parallel`, `clip`
- **5.2 Template Engine** — Jinja2 variable substitution: `{{ step_name }}` referencing previous step outputs; context accumulation across steps
- **5.3 The Ritual Runner** — `src/remora/core/rituals.py`: YAML parser, step executor, async orchestration, integration with `SwarmExecutor.run_agent()`, `EventStore.append()`
- **5.4 Step Type Implementations** — `shell`: subprocess with capture; `agent`: single node targeting via `EventStore.get_node()`; `agent_batch`: pattern matching via `list_nodes()`; `checkpoint`: `HumanInputRequestEvent`; `conditional`: Jinja2 expression evaluation; `parallel`: `asyncio.gather()`; `clip`: `clip_url()` from browser_demo
- **5.5 LSP Layer** — `remora.runRitual`, `remora.listRituals`, `remora.ritualStatus`, `remora.cancelRitual`; `$/remora/ritualProgress` notification
- **5.6 The `ritual.lua` UI** — Progress panel: step list with status icons, elapsed time, failure details; `:RemoraRitual` commands
- **5.7 Event Integration** — Ritual events: `RitualStartedEvent`, `RitualStepEvent`, `RitualCompletedEvent`; feeding into EventStore for timeline visibility
- **5.8 Trigger System** — Manual, event-reactive, and cron-like triggers; integration with `SubscriptionPattern`
- **5.9 Files to Create/Modify** — New: `rituals.py`, `ritual.lua`, events, LSP commands, `.remora/rituals/` directory; Modified: `events.py`, `commands.py`, `init.lua`
- **5.10 Complexity, Risks, and Priority** — Jinja2 security, agent targeting, estimated effort

### 6. [Cross-Feature Dependencies and Priority Matrix](#6-cross-feature-dependencies-and-priority-matrix)
- **6.1 Dependency Graph** — Which features enhance which; shared infrastructure (new events, LSP commands, EventStore queries)
- **6.2 Shared Infrastructure** — Common patterns: new LSP command registration, new event types, new Lua modules, `init.lua` command registration
- **6.3 Implementation Order** — Recommended sequence based on dependencies, standalone value, and complexity
- **6.4 Priority Matrix** — Effort vs impact grid for all five features

### 7. [Summary and Recommended Roadmap](#7-summary-and-recommended-roadmap)
- **7.1 Phase 1** — Quick wins with high standalone value
- **7.2 Phase 2** — Core infrastructure features
- **7.3 Phase 3** — Complex UI features that build on Phase 1-2
- **7.4 Open Questions for All Features** — Cross-cutting design decisions that affect multiple features

---

