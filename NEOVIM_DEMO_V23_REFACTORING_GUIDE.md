# Neovim Demo V2.3: Refactoring Guide

> **Date:** 2026-03-01
> **Scope:** Bugs, gaps, and refactoring steps for the existing V2.1 LSP implementation
> **Input:** Full audit of `src/remora/lsp/` against `NEOVIM_DEMO_V21_FINAL_CONCEPT.md`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Critical: `remora swarm start --lsp` Crash](#2-critical-remora-swarm-start---lsp-crash)
3. [Syntax Error in `runner.py`](#3-syntax-error-in-runnerpy)
4. [`graph.py` Calls Async DB Methods Synchronously](#4-graphpy-calls-async-db-methods-synchronously)
5. [Dead Code: `bridge.py`](#5-dead-code-bridgepy)
6. [`ExtensionNode` Defined After First Reference](#6-extensionnode-defined-after-first-reference)
7. [Missing `model_rebuild()` for Forward References](#7-missing-model_rebuild-for-forward-references)
8. [LSP `initialize` Missing Capability Declarations](#8-lsp-initialize-missing-capability-declarations)
9. [`emit_event` Uses `server.protocol.notify` Directly](#9-emit_event-uses-serverprotocolnotify-directly)
10. [`uri_to_path` is Platform-Broken](#10-uri_to_path-is-platform-broken)
11. [DB: `check_same_thread=False` Without Connection Pooling](#11-db-check_same_threadfalse-without-connection-pooling)
12. [Watcher: `_parse_fallback` End-Line Detection is Wrong](#12-watcher-_parse_fallback-end-line-detection-is-wrong)
13. [Lua: `panel.lua` Uses `nui.popup` Instead of `nui-components`](#13-lua-panellua-uses-nuipopup-instead-of-nui-components)
14. [Lua: `remora_starter.lua` Duplicates `init.lua`](#14-lua-remora_starterlua-duplicates-initlua)
15. [Lua: `init.lua` Missing `register_lsp()` Call](#15-lua-initlua-missing-register_lsp-call)
16. [Missing Core Swarm Integration in LSP Server](#16-missing-core-swarm-integration-in-lsp-server)
17. [Test Coverage Gaps](#17-test-coverage-gaps)
18. [Refactoring Opportunities](#18-refactoring-opportunities)

---

## 1. Executive Summary

The LSP module (`src/remora/lsp/`) now exists and implements the core V2.1 concept:
- `models.py` — `ASTAgentNode`, `ToolSchema`, `RewriteProposal`, event classes ✅
- `server.py` — `pygls` server with all LSP handlers ✅
- `runner.py` — `AgentRunner` with Pydantic model, tool dispatch ✅
- `db.py` — SQLite schema matching the concept ✅
- `graph.py` — `LazyGraph` with rustworkx ✅
- `watcher.py` — Tree-sitter parsing + ID injection ✅
- `nvim/lua/` — Lua plugin with LSP setup, panel, handlers ✅
- `bridge.py` — Dead code, superseded by `models.py`

**However**, the implementation has **multiple runtime-breaking bugs** that prevent the server from starting, plus several correctness and architectural issues. This guide catalogs every issue found and provides fix-by-fix implementation instructions.

### Issue Severity Summary

| Severity | Count | Description |
|----------|-------|-------------|
| 🔴 **Crash** | 3 | Server won't start at all |
| 🟡 **Runtime Bug** | 5 | Will crash during use |
| 🟢 **Code Quality** | 6 | Dead code, duplication, missed concept features |
| 🔵 **Test Gaps** | 3 | Missing coverage for critical paths |

---

## 2. Critical: `remora swarm start --lsp` Crash

### Error

```
pydantic.errors.PydanticUserError: `AgentRunner` is not fully defined;
you should define `RemoraLanguageServer`, then call `AgentRunner.model_rebuild()`.
```

### Root Cause

In [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/runner.py), `AgentRunner` is a `BaseModel` with a field typed as `RemoraLanguageServer`:

```python
class AgentRunner(BaseModel):
    server: "RemoraLanguageServer"  # Forward reference
```

But `RemoraLanguageServer` is only imported under `TYPE_CHECKING`:

```python
if TYPE_CHECKING:
    from remora.lsp.server import RemoraLanguageServer
```

With `from __future__ import annotations`, **all** annotations become strings. Pydantic needs to resolve these at model creation time, but `RemoraLanguageServer` is never actually imported at runtime. So Pydantic can't build the validator.

### Fix

Add `model_rebuild()` after the real import is available. In [__main__.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/__main__.py):

```python
# src/remora/lsp/__main__.py
from __future__ import annotations

from remora.lsp.server import RemoraLanguageServer, server
from remora.lsp.runner import AgentRunner

# Resolve the forward reference now that both classes are imported
AgentRunner.model_rebuild()


def main() -> None:
    """Start the Remora LSP server with agent runner."""
    runner = AgentRunner(server=server)
    server.runner = runner

    @server.thread()
    async def _start_runner() -> None:
        await runner.run_forever()

    server.start_io()
```

**Alternative (cleaner):** Remove `AgentRunner` from being a Pydantic `BaseModel` entirely. It has an `asyncio.Queue` field which is fundamentally not serializable. Make it a regular class:

```python
class AgentRunner:
    """Agent execution loop. NOT a Pydantic model — it holds non-serializable state."""

    def __init__(self, server: RemoraLanguageServer) -> None:
        self.server = server
        self.llm = MockLLMClient()
        self.executor: SwarmExecutor | None = None
        self.queue: asyncio.Queue[Trigger] = asyncio.Queue()
        self._running = False
```

> [!IMPORTANT]
> The `asyncio.Queue` and `RemoraLanguageServer` fields make `AgentRunner` a poor fit for Pydantic. It's never serialized or validated. Converting to a plain class eliminates the entire category of `model_rebuild` issues.

---

## 3. Syntax Error in `runner.py`

### Location

[runner.py:96](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/runner.py#L96)

### Current Code

```python
await self_id, "Node not found", correlation.emit_error(agent_id)
```

This is a garbled line — it `await`s a tuple and calls a nonexistent `.emit_error` attribute on a string.

### Fix

```python
await self.emit_error(agent_id, "Node not found", correlation_id)
```

---

## 4. `graph.py` Calls Async DB Methods Synchronously

### Problem

[graph.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/graph.py) is entirely synchronous, but
`RemoraDB` methods are all decorated with `@async_db` (which wraps them in `asyncio.to_thread`). Every call to
`self.db.get_nodes_for_file()`, `self.db.get_node()`, `self.db.get_neighborhood()`, and `self.db.get_edges_for_nodes()`
returns a coroutine that is **never awaited**.

### Affected Lines

| Line | Call |
|------|------|
| 25 | `self.db.get_nodes_for_file(file_path)` in `invalidate()` |
| 41 | `self.db.get_node(node_id)` in `ensure_loaded()` |
| 45 | `self.db.get_neighborhood(node_id, depth=2)` in `ensure_loaded()` |
| 52 | `self.db.get_edges_for_nodes(...)` in `ensure_loaded()` |

### Fix Options

**Option A: Make `LazyGraph` methods async:**

```python
async def invalidate(self, file_path: str) -> None:
    self.loaded_files.discard(file_path)
    if RUSTWORKX_AVAILABLE and self.graph:
        nodes = await self.db.get_nodes_for_file(file_path)
        for node in nodes:
            if node["id"] in self.node_indices:
                idx = self.node_indices.pop(node["id"])
                try:
                    self.graph.remove_node(idx)
                except Exception:
                    pass

async def ensure_loaded(self, node_id: str) -> None:
    # ... same pattern, add await to all db calls
```

Then update all callers in `server.py` to `await` graph methods.

**Option B: Give `LazyGraph` its own sync SQLite connection** (separate from the async-wrapped `RemoraDB`). This is cleaner for a graph that needs batch reads:

```python
class LazyGraph:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # ... use self._conn directly for sync reads
```

---

## 5. Dead Code: `bridge.py`

### Problem

[bridge.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/bridge.py) defines `LSPExportable` (a Protocol) and `LSPBridgeMixin` with `to_range()`, `to_code_lens()`, and `to_hover()` methods. These are **never imported or used anywhere**. All of this behavior already lives directly on `ASTAgentNode` in `models.py` with richer implementations.

### Fix

Delete `src/remora/lsp/bridge.py`. It adds no value and creates confusion about where the LSP conversion logic lives.

---

## 6. `ExtensionNode` Defined After First Reference

### Problem

In [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/runner.py), the function `load_extensions_from_disk()` (line 318) references `ExtensionNode` in an `issubclass()` check:

```python
if isinstance(obj, type) and issubclass(obj, ExtensionNode) and obj is not ExtensionNode:
```

But `ExtensionNode` is defined **below** this function at line 341. Python handles this fine since the function body isn't executed at module load time, but it's confusing and fragile.

### Fix

Move `ExtensionNode` class definition **above** `load_extensions_from_disk()`. Better yet, move both to a separate `extensions.py` file as the V2.1 concept suggests:

```
src/remora/lsp/
├── extensions.py    # ExtensionNode base + load_extensions_from_disk()
├── runner.py        # AgentRunner (imports from extensions.py)
```

---

## 7. Missing `model_rebuild()` for Forward References

### Problem

Multiple Pydantic models in `models.py` use forward references via string annotations (because of `from __future__ import annotations`):

- `ASTAgentNode.extra_tools: list[ToolSchema]` — `ToolSchema` is a forward ref
- `AgentEvent.to_core_event()` return type — unresolvable

Pydantic can usually handle these when both classes are in the same module, but the `from __future__ import annotations` behavior means all type hints are strings. If models are imported piecemeal (e.g., in tests), this can cause validation failures.

### Fix

Add explicit `model_rebuild()` calls at the bottom of `models.py`:

```python
# Bottom of models.py — resolve forward references
ASTAgentNode.model_rebuild()
RewriteProposal.model_rebuild()
AgentEvent.model_rebuild()
HumanChatEvent.model_rebuild()
AgentMessageEvent.model_rebuild()
RewriteProposalEvent.model_rebuild()
RewriteAppliedEvent.model_rebuild()
RewriteRejectedEvent.model_rebuild()
AgentErrorEvent.model_rebuild()
```

---

## 8. LSP `initialize` Missing Capability Declarations

### Problem

The `pygls` server in [server.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/server.py) never declares its capabilities. While `pygls` auto-registers capabilities for handlers decorated with `@server.feature()`, the server should explicitly declare its capabilities for proper client negotiation, especially for:

- Code lens support (refresh capability)
- Code action resolve support
- Document symbol support
- Execute command registration (list of supported commands)

### Fix

Override the `initialize` handler or configure capabilities in the server constructor:

```python
class RemoraLanguageServer(LanguageServer):
    def __init__(self, event_store=None, subscriptions=None, swarm_state=None):
        super().__init__(
            name="remora",
            version="0.1.0",
        )
        # ... existing init ...
```

And register the execute command options so that the client knows which commands are available:

```python
@server.feature(lsp.INITIALIZE)
async def on_initialize(params: lsp.InitializeParams) -> None:
    """Declare supported commands on initialization."""
    server.server_capabilities.execute_command_provider = lsp.ExecuteCommandOptions(
        commands=[
            "remora.chat",
            "remora.requestRewrite",
            "remora.executeTool",
            "remora.acceptProposal",
            "remora.rejectProposal",
            "remora.selectAgent",
            "remora.messageNode",
        ]
    )
```

> [!NOTE]
> `pygls` populates `server_capabilities` automatically from `@server.feature` registrations, but the `commands` list for `workspace/executeCommand` must be explicitly provided since different commands are dispatched via a single handler.

---

## 9. `emit_event` Uses `server.protocol.notify` Directly

### Problem

In [server.py:91](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/server.py#L91):

```python
server.protocol.notify("$/remora/event", event.model_dump())
```

This accesses the internal `protocol` attribute directly instead of using the public `pygls` API. It also bypasses any error handling or connection checks.

### Fix

Use the public `send_notification` method (or `notify` at the server level):

```python
server.send_notification("$/remora/event", event.model_dump())
```

Apply the same fix in `execute_command` handler where `server.protocol.notify` is used for `$/remora/requestInput` and `$/remora/agentSelected` notifications (lines 281, 285–287, 323–324, 329).

---

## 10. `uri_to_path` is Platform-Broken

### Problem

[server.py:65-68](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/server.py#L65-L68):

```python
def uri_to_path(uri: str) -> str:
    if uri.startswith("file://"):
        return uri[7:]
    return uri
```

On Windows, a file URI looks like `file:///C:/Users/...` (three slashes). Stripping `file://` leaves `/C:/Users/...` which is not a valid Windows path. On Unix, `file:///home/...` leaves `/home/...` which works by accident.

### Fix

Use the standard library:

```python
from urllib.parse import unquote
from pathlib import PurePosixPath
import sys

def uri_to_path(uri: str) -> str:
    """Convert a file:// URI to a local filesystem path, cross-platform."""
    if not uri.startswith("file://"):
        return uri
    path = unquote(uri[len("file://"):])
    # On Windows, URIs have an extra leading slash: file:///C:/...
    if sys.platform == "win32" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path
```

Or even simpler, use `pygls.uris.to_fs_path()` which already exists in the `pygls` library:

```python
from pygls.uris import to_fs_path

def uri_to_path(uri: str) -> str:
    return to_fs_path(uri)
```

---

## 11. DB: `check_same_thread=False` Without Connection Pooling

### Problem

[db.py:33](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/db.py#L33) creates a single SQLite connection with `check_same_thread=False` and uses it from multiple threads via `asyncio.to_thread()`. SQLite connections are not thread-safe for concurrent writes. The `@async_db` decorator offloads each call to a thread, meaning two concurrent handler calls can write simultaneously on different threads using the same connection.

### Fix Options

**Option A (simplest):** Add a threading lock:

```python
import threading

class RemoraDB:
    def __init__(self, db_path: str = ".remora/indexer.db"):
        # ... existing init ...
        self._lock = threading.Lock()

# Update async_db decorator:
def async_db(fn):
    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        def _locked():
            with self._lock:
                return fn(self, *args, **kwargs)
        return await asyncio.to_thread(_locked)
    return wrapper
```

**Option B (better):** Use `aiosqlite` for a proper async-native SQLite wrapper that handles connection management safely.

---

## 12. Watcher: `_parse_fallback` End-Line Detection is Wrong

### Problem

The fallback regex parser in [watcher.py:160-166](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#L160-L166) tries to find where a function/class ends by looking for the next un-indented line:

```python
for i in range(line_num - 1, len(lines)):
    if lines[i].strip() and not lines[i].startswith(" ") and not lines[i].startswith("\t"):
        if i > line_num - 1:
            end_line = i
            break
```

This fails for:
1. **Nested classes** — a method definition at indent level 2 would cause the class at indent level 1 to "end" prematurely
2. **Empty lines** — `lines[i].strip()` skips blank lines, so `end_line` may include unrelated code after a blank line
3. **The first definition** — if `line_num - 1` itself is un-indented, the `if i > line_num - 1` guard prevents immediate matching, but the next un-indented line (another function) becomes the end

### Fix

This only matters when tree-sitter is unavailable. Given that `tree-sitter` and `tree-sitter-python` are declared dependencies in `pyproject.toml`, the fallback should log a warning and produce conservative (full-file-range) nodes rather than silently producing wrong ranges:

```python
def _parse_fallback(self, uri: str, text: str, old_nodes=None) -> list[ASTAgentNode]:
    """Regex fallback when tree-sitter is unavailable. Produces approximate ranges."""
    import logging
    logging.getLogger("remora.lsp").warning(
        "tree-sitter not available; using fallback parser with approximate ranges"
    )
    # ... improved logic or just full-file ranges ...
```

---

## 13. Lua: `panel.lua` Uses `nui.popup` Instead of `nui-components`

### Problem

The V2.1 concept (Appendix A) specifies using `nui-components.nvim` with reactive `Signal` state, `n.rows()`, `n.columns()`, `n.tabs()`, etc. The actual [panel.lua](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/panel.lua) uses basic `nui.popup` with manual buffer line rendering:

```lua
local nui_popup = require("nui.popup")  -- ← v1 API

-- Manual line-by-line rendering:
vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
for i, hl_group in ipairs(hl) do
    vim.api.nvim_buf_add_highlight(buf, -1, hl_group, line_num, 0, -1)
end
```

This is the imperative approach from v1. The concept wants declarative reactive components.

### Fix

Rewrite to use `nui-components` as specified in the concept. The rewrite involves:

1. **Replace `nui.popup` with `nui-components` renderer:**

```lua
local n = require("nui-components")
local Signal = require("nui-components.signal")

M.state = Signal.create({
    expanded = false,
    selected_agent = nil,
    agents = {},
    events = {},
    border_hl = "RemoraBorder",
})
```

2. **Replace manual `render()` with declarative component tree** as shown in concept sections A1-A4 (collapsible sidebar, agent header, events tab, chat tab).

3. **Remove `M.popup` lifecycle** — `nui-components` manages its own mounting/unmounting.

> [!NOTE]
> `nui-components.nvim` must be installed as a Neovim plugin dependency. Add it to the plugin's documentation. It's a separate package from `nui.nvim`.

---

## 14. Lua: `remora_starter.lua` Duplicates `init.lua`

### Problem

[remora_starter.lua](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora_starter.lua) (246 lines) duplicates nearly all functionality from [init.lua](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua) (149 lines):

- Both register the LSP server
- Both create `:RemoraChat`, `:RemoraRewrite`, `:RemoraAccept`, `:RemoraReject` commands
- Both handle `$/remora/requestInput`
- `remora_starter.lua` additionally has `:RemoraStart`, `:RemoraStop`, `:RemoraRestart`, `:RemoraParse` which manually call `vim.lsp.start()` and send raw `textDocument/didOpen` notifications

The starter's manual LSP lifecycle management (`vim.lsp.start()`, manual `didOpen` notifications) conflicts with `init.lua`'s use of `vim.lsp.config` + `vim.lsp.enable()` which handles lifecycle automatically.

### Fix

**Delete `remora_starter.lua`.** It's a crutch from before `init.lua` existed. Users should use:

```lua
require("remora").setup()
```

If any useful commands from `remora_starter.lua` are needed (`:RemoraStatus`, `:RemoraParse`, `:RemoraStop`), merge them into `init.lua`.

---

## 15. Lua: `init.lua` Missing `register_lsp()` Call

### Problem

[init.lua:12-17](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/nvim/lua/remora/init.lua#L12-L17) directly sets `vim.lsp.config["remora"]` but doesn't verify the API exists. `vim.lsp.config` and `vim.lsp.enable()` require **Neovim 0.11+**. On older versions, this silently fails.

### Fix

Add version check:

```lua
function M.setup(opts)
    opts = opts or {}

    if not vim.lsp.config then
        vim.notify(
            "[Remora] Neovim 0.11+ required for LSP integration",
            vim.log.levels.ERROR
        )
        return
    end

    vim.lsp.config["remora"] = {
        cmd = opts.cmd or { "remora-lsp" },
        -- ...
    }
    vim.lsp.enable("remora")
    -- ...
end
```

---

## 16. Missing Core Swarm Integration in LSP Server

### Problem

The LSP server is designed to optionally integrate with the existing Remora core swarm (`EventStore`, `SubscriptionRegistry`, `SwarmState`), but the integration is incomplete:

1. **`server.py` accepts `event_store`, `subscriptions`, `swarm_state` in `__init__`** but the solo `main()` in `__main__.py` never initializes them:

   ```python
   # __main__.py just does:
   runner = AgentRunner(server=server)
   server.start_io()
   # ← No core service initialization
   ```

2. **The `--lsp` path in `cli/main.py`** also just calls `lsp_main()` without setting up core services:

   ```python
   if lsp:
       from remora.lsp.__main__ import main as lsp_main
       lsp_main()  # ← No EventStore, no SwarmState
       return
   ```

3. **`to_core_event()` raises `NotImplementedError`** on the base `AgentEvent` class (line 313), and no subclass overrides it. The `emit_event()` function calls this at line 89:

   ```python
   if server.event_store:
       core_event = event.to_core_event()  # ← NotImplementedError
   ```

### Fix

**Phase 1 (standalone LSP):** The LSP server should work without core services. Guard the `to_core_event()` call:

```python
async def emit_event(event) -> Any:
    if not event.timestamp:
        event.timestamp = time.time()
    await server.db.store_event(event)
    if server.event_store:
        try:
            core_event = event.to_core_event()
            await server.event_store.append("swarm", core_event)
        except NotImplementedError:
            pass  # Standalone mode — no core event bridge
    server.send_notification("$/remora/event", event.model_dump())
    return event
```

**Phase 2 (full integration):** Implement `to_core_event()` on each event subclass to bridge LSP events to core events:

```python
class HumanChatEvent(AgentEvent):
    def to_core_event(self):
        from remora.core.events import AgentMessageEvent as CoreMsg
        return CoreMsg(
            from_agent="human",
            to_agent=self.to_agent,
            content=self.message,
        )
```

**Phase 3 (CLI integration):** Update `swarm_start` with `--lsp` to initialize core services before starting the LSP server:

```python
if lsp:
    from remora.lsp.__main__ import main as lsp_main
    # Initialize core services
    event_store = EventStore(event_store_path, ...)
    await event_store.initialize()
    # Pass to server
    server.event_store = event_store
    server.subscriptions = subscriptions
    server.swarm_state = swarm_state
    lsp_main()
    return
```

---

## 17. Test Coverage Gaps

### Current Tests

| Test File | Coverage |
|-----------|----------|
| `test_lsp_models.py` | `ToolSchema.to_llm_tool()`, `RewriteProposal.diff`, `RewriteProposal.to_workspace_edit()` |
| `test_lsp_db.py` | `upsert_nodes`, `get_node`, `get_nodes_for_file` |
| `test_lsp_watcher.py` | `parse_and_inject_ids` (tree-sitter + ID preservation) |

### Missing Tests

1. **`ASTAgentNode` LSP conversions** — `to_hover()`, `to_code_lens()`, `to_code_actions()`, `to_document_symbol()`, `to_system_prompt()` are untested
2. **`RewriteProposal.to_diagnostic()`** — untested
3. **`RewriteProposal.to_code_actions()`** — untested (accept/reject pair)
4. **`RemoraDB` activation chain** — `add_to_chain()`, `get_activation_chain()` untested
5. **`RemoraDB` proposals** — `store_proposal()`, `get_proposals_for_file()`, `update_proposal_status()` untested
6. **`AgentRunner.trigger()` cycle detection** — untested
7. **Event model validators** — `_set_defaults` on all event subclasses untested
8. **`inject_ids()` function** — file I/O, ID regex replacement untested
9. **`LazyGraph`** — entirely untested (and currently broken, see Issue #4)
10. **Server handler integration** — no integration tests for LSP request/response cycle

### Recommended Test Additions

```python
# tests/unit/test_lsp_models.py — additions

def test_ast_agent_node_to_code_lens():
    node = _make_node(status="active")
    lens = node.to_code_lens()
    assert lens.command.command == "remora.selectAgent"
    assert node.remora_id in lens.command.title

def test_ast_agent_node_to_hover():
    node = _make_node()
    hover = node.to_hover()
    assert node.remora_id in hover.contents.value

def test_ast_agent_node_to_code_actions():
    node = _make_node()
    actions = node.to_code_actions()
    commands = [a.command.command for a in actions]
    assert "remora.chat" in commands
    assert "remora.requestRewrite" in commands
    assert "remora.messageNode" in commands

def test_rewrite_proposal_to_code_actions():
    proposal = _make_proposal()
    actions = proposal.to_code_actions()
    assert len(actions) == 2
    commands = [a.command.command for a in actions]
    assert "remora.acceptProposal" in commands
    assert "remora.rejectProposal" in commands

def test_event_defaults():
    evt = HumanChatEvent(to_agent="rm_test", message="hi", correlation_id="c1")
    assert evt.event_type == "HumanChatEvent"
    assert "rm_test" in evt.summary
```

---

## 18. Refactoring Opportunities

### 18a. Split `server.py` Into Handler Modules

`server.py` is 423 lines with all handlers in one file. The V2.1 concept and the previous V2.2 guide both recommend splitting into:

```
src/remora/lsp/
├── server.py             # RemoraLanguageServer class + server instance only
├── handlers/
│   ├── documents.py      # didOpen, didSave, didClose
│   ├── hover.py          # textDocument/hover
│   ├── lens.py           # textDocument/codeLens
│   ├── actions.py        # textDocument/codeAction
│   └── commands.py       # workspace/executeCommand
└── notifications.py      # $/remora/submitInput
```

Each handler file imports the `server` instance and registers features on it. This keeps files under 100 lines each.

### 18b. Move `discover_tools_for_agent` Off the Class

[server.py:385-414](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/server.py#L385-L414) defines `discover_tools_for_agent` as a standalone function then monkey-patches it onto the class:

```python
RemoraLanguageServer.discover_tools_for_agent = discover_tools_for_agent
```

This should be a proper method defined in the class body, or moved to `extensions.py`.

### 18c. Consolidate Lua Plugin Files

The `nvim/lua/` directory has three files that should be two:
- Keep `init.lua` and `panel.lua`
- Delete `remora_starter.lua` (see Issue #14)

### 18d. Add `py.typed` Marker

The `src/remora/lsp/` package should have a `py.typed` marker for type checking consumers.

---

## Implementation Order

Based on dependencies, implement fixes in this order:

| Step | Issue | Blocking? | Est. Effort |
|------|-------|-----------|-------------|
| 1 | [§3 Syntax error in runner.py](#3-syntax-error-in-runnerpy) | 🔴 Yes | 1 min |
| 2 | [§2 Pydantic forward-ref crash](#2-critical-remora-swarm-start---lsp-crash) | 🔴 Yes | 15 min |
| 3 | [§7 model_rebuild() calls](#7-missing-model_rebuild-for-forward-references) | 🔴 Yes | 5 min |
| 4 | [§9 protocol.notify → send_notification](#9-emit_event-uses-serverprotocolnotify-directly) | 🟡 | 5 min |
| 5 | [§10 uri_to_path fix](#10-uri_to_path-is-platform-broken) | 🟡 | 5 min |
| 6 | [§4 graph.py async fix](#4-graphpy-calls-async-db-methods-synchronously) | 🟡 | 20 min |
| 7 | [§11 DB thread safety](#11-db-check_same_threadfalse-without-connection-pooling) | 🟡 | 15 min |
| 8 | [§16 Core swarm integration](#16-missing-core-swarm-integration-in-lsp-server) | 🟡 | 30 min |
| 9 | [§8 Capability declarations](#8-lsp-initialize-missing-capability-declarations) | 🟢 | 10 min |
| 10 | [§5 Delete bridge.py](#5-dead-code-bridgepy) | 🟢 | 1 min |
| 11 | [§6 Move ExtensionNode](#6-extensionnode-defined-after-first-reference) | 🟢 | 10 min |
| 12 | [§12 Fallback parser fix](#12-watcher-_parse_fallback-end-line-detection-is-wrong) | 🟢 | 10 min |
| 13 | [§14 Delete remora_starter.lua](#14-lua-remora_starterlua-duplicates-initlua) | 🟢 | 5 min |
| 14 | [§15 Neovim version check](#15-lua-initlua-missing-register_lsp-call) | 🟢 | 5 min |
| 15 | [§13 Panel nui-components rewrite](#13-lua-panellua-uses-nuipopup-instead-of-nui-components) | 🟢 | 2-4 hrs |
| 16 | [§18 Server.py split](#18-refactoring-opportunities) | 🟢 | 30 min |
| 17 | [§17 Tests](#17-test-coverage-gaps) | 🔵 | 1-2 hrs |

**Steps 1-3 unblock the server from starting.** Steps 4-8 fix runtime bugs. Steps 9-16 improve quality. Step 17 adds test coverage.
