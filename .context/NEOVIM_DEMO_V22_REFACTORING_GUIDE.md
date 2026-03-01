# Neovim Demo V2.2: Refactoring Guide

> **Status:** Draft — generated from V2.1 concept audit against current codebase  
> **Date:** 2026-03-01  
> **Scope:** Bridge the gap between the V2.1 LSP-native concept and the current dataclass/JSON-RPC implementation

---

## Table of Contents

### 1. [Executive Summary](#1-executive-summary)
High-level gap analysis: what the V2.1 concept describes vs what actually exists in the codebase today.

### 2. [Critical Bug: `remora swarm start --lsp` Crash](#2-critical-bug-remora-swarm-start---lsp-crash)
The immediate `PydanticUserError` crash when running `remora swarm start --lsp`. Root cause and fix.

### 3. [Phase 1 — Pydantic Model Layer](#3-phase-1--pydantic-model-layer)
Migrate `AgentState`, `AgentMetadata`, `CSTNode`, all events, and `Config` from frozen dataclasses to Pydantic `BaseModel`. Create the `ASTAgentNode`, `ToolSchema`, and `RewriteProposal` bridge models from the V2.1 concept.

### 4. [Phase 2 — LSP Server (`src/remora/lsp/`)](#4-phase-2--lsp-server-srcremora-lsp)
Create the `pygls`-based `RemoraLanguageServer` with all LSP handlers: `didOpen`, `didSave`, `hover`, `codeLens`, `codeAction`, `executeCommand`, diagnostics, and custom `$/remora/*` notifications.

### 5. [Phase 3 — CLI Integration & Entrypoints](#5-phase-3--cli-integration--entrypoints)
Wire the new LSP server into `cli/main.py` with a proper `--lsp` flag and a `remora lsp` subcommand. Register `remora-lsp` as a `pyproject.toml` script entrypoint.

### 6. [Phase 4 — Lua Plugin Rewrite (LSP-Native)](#6-phase-4--lua-plugin-rewrite-lsp-native)
Replace the v1 JSON-RPC Lua plugin with the LSP-native architecture: `vim.lsp.config`, custom notification handlers, nui-components sidepanel, and SSE event subscription.

### 7. [Phase 5 — AgentRunner ↔ LSP Bridge](#7-phase-5--agentrunner--lsp-bridge)
Connect the existing `AgentRunner`/`SwarmExecutor` pipeline to the new LSP server so agent execution results flow back as LSP notifications, diagnostics, and workspace edits.

### 8. [Phase 6 — ID Management & Injection](#8-phase-6--id-management--injection)
Implement the `rm_` prefixed ID scheme from the concept, including file-level IDs, inline injection on definition lines, and stable ID preservation across saves.

### 9. [Phase 7 — Graph & Cycle Detection](#9-phase-7--graph--cycle-detection)
Add the SQLite `activation_chain` table for cascade prevention. Integrate the `LazyGraph` (Rustworkx) for parent/caller/callee lookups used in hover and prompt generation.

### 10. [Phase 8 — Extension Discovery](#10-phase-8--extension-discovery)
Implement `.remora/models/` extension loading: `ExtensionNode` base class, tool schema conversion, and dynamic code action injection.

### 11. [Appendix A — File-by-File Audit](#11-appendix-a--file-by-file-audit)
Detailed per-file status of what exists, what's missing, and what needs changing.

### 12. [Appendix B — Dependency Check](#12-appendix-b--dependency-check)
Verify `pygls`, `lsprotocol`, and `nui-components.nvim` are properly available.

---

## 1. Executive Summary

The V2.1 concept document (`NEOVIM_DEMO_V21_FINAL_CONCEPT.md`) describes an **LSP-native architecture** where Remora acts as a language server using `pygls`, with Pydantic models serving as the bridge between agent structures, SQLite storage, and LSP protocol types. The current codebase implements **none of this**.

### What the V2.1 Concept Describes

| Component | V2.1 Vision |
|-----------|-------------|
| **Models** | Pydantic `BaseModel` classes (`ASTAgentNode`, `ToolSchema`, `RewriteProposal`) with `.to_hover()`, `.to_code_lens()`, `.to_code_action()` methods |
| **Server** | `pygls` `LanguageServer` with standard LSP handlers (`textDocument/hover`, `codeLens`, `codeAction`, `executeCommand`) |
| **Neovim client** | Thin Lua layer using `vim.lsp.config` + `vim.lsp.enable()`, custom `$/remora/*` notification handlers |
| **Events** | Pydantic models with LSP notification export |
| **ID scheme** | `rm_` prefix IDs injected inline on definition lines |
| **CLI** | `remora lsp` subcommand (or `--lsp` flag on `swarm start`) |

### What Actually Exists

| Component | Current State |
|-----------|---------------|
| **Models** | Frozen `dataclass` objects: `AgentState`, `AgentMetadata`, `CSTNode`, all events. No Pydantic models in `core/`. `models/__init__.py` has request/response dataclasses for the REST API only. |
| **Server** | [nvim/server.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/nvim/server.py) — a **JSON-RPC over Unix socket** server. Not LSP. No `pygls`. No hover, code lens, or code actions. |
| **Neovim client** | [plugin/remora_nvim.lua](file:///c:/Users/Andrew/Documents/Projects/remora/plugin/remora_nvim.lua) + `lua/remora_nvim/.v1/` — v1 JSON-RPC client. Not LSP-native. |
| **Events** | All frozen dataclasses in [events.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/events.py). No Pydantic, no LSP conversion methods. |
| **ID scheme** | SHA256 hash IDs via `compute_node_id()` — no `rm_` prefix, no inline injection. |
| **CLI** | `swarm start` has `--nvim` flag (JSON-RPC server). **No** `--lsp` flag. **No** `src/remora/lsp/` package. |

### The User's Immediate Error

The user runs `remora swarm start --lsp`, which hits a traceback at:
1. `cli/main.py:46` calls `lsp_main()` — but the **current** `cli/main.py` has no such call (it has `--nvim` on line 30)
2. `lsp/__main__.py:12` creates `AgentRunner(server=server)` treating it as a **Pydantic model** — but the real `AgentRunner` is a plain class with no `server` field

> [!CAUTION]
> The user's installed version has a `src/remora/lsp/` module and `--lsp` CLI flag that are **not in the current git working tree**. This is likely a stale editable install with files that were deleted or never committed. Quick fix: re-install with `uv pip install -e .`. Proper fix: implement the LSP module (this guide).

### Gap Severity

| Gap | Severity | Effort |
|-----|----------|--------|
| Missing `lsp/` package | 🔴 Blocking | Large |
| Dataclass → Pydantic migration | 🟡 Foundation | Medium |
| LSP handler implementations | 🟡 Core feature | Large |
| Lua plugin rewrite | 🟡 Core feature | Medium |
| ID injection system | 🟢 Enhancement | Small |
| Extension discovery | 🟢 Enhancement | Small |

---

## 2. Critical Bug: `remora swarm start --lsp` Crash

### Error

```
pydantic.errors.PydanticUserError: `AgentRunner` is not fully defined;
you should define `RemoraLanguageServer`, then call `AgentRunner.model_rebuild()`.
```

### Root Cause

The traceback walks through code that **does not exist in the current git tree**:

| Traceback Line | What It References | Current State |
|---|---|---|
| `cli/main.py:46` → `lsp_main()` | A `--lsp` flag and `lsp_main` import | Current file has `--nvim` flag on line 30, no `--lsp` |
| `lsp/__main__.py:12` → `AgentRunner(server=server)` | A Pydantic `AgentRunner` in an `lsp/` package | No `src/remora/lsp/` directory exists |
| `AgentRunner` expects `RemoraLanguageServer` | Forward-ref Pydantic field | `AgentRunner` in `core/agent_runner.py` is a plain class |

**Diagnosis:** The devenv has a stale editable install. Either:
1. A prior version created `src/remora/lsp/__main__.py` with a Pydantic-based `AgentRunner` wrapper
2. A partial scaffolding attempt left files on disk that were removed from git

The Pydantic error occurs because `AgentRunner` has a field typed as `RemoraLanguageServer` (forward reference), but `RemoraLanguageServer` was never defined.

### Immediate Fix (Unblocks the User)

```bash
# Option A: Re-install to match the git tree
cd ~/Documents/Projects/remora
uv pip install -e .

# Option B: Use the working --nvim flag
remora swarm start --nvim
```

### Proper Fix

Create the full `src/remora/lsp/` package with a real `RemoraLanguageServer` class, proper `AgentRunner` integration, and the `--lsp` CLI flag. Covered in **Phase 2** and **Phase 3** below.

---

## 3. Phase 1 — Pydantic Model Layer

The V2.1 concept's core thesis is that **Pydantic models serve triple duty**: database schema, agent prompt context, and LSP protocol types. Currently everything is frozen dataclasses. This phase converts the foundations.

> [!IMPORTANT]
> Do NOT attempt to convert `structured_agents.events` re-exports. Those are external. Only convert Remora-owned models.

### 3a. Models to Convert (Dataclass → Pydantic)

#### [MODIFY] [agent_state.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/agent_state.py)

**Current:** `@dataclass` `AgentState` with manual `to_dict()`/`from_dict()` serialization.

**Target:** Pydantic `BaseModel` with native `.model_dump()` / `.model_validate()`.

```python
# src/remora/core/agent_state.py
from __future__ import annotations
from pydantic import BaseModel, Field
from remora.core.subscriptions import SubscriptionPattern

class AgentState(BaseModel):
    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    range: tuple[int, int] | None = None
    connections: dict[str, str] = Field(default_factory=dict)
    chat_history: list[dict[str, Any]] = Field(default_factory=list)
    custom_subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
    last_updated: float = Field(default_factory=time.time)
```

**Key changes:**
- Remove `to_dict()` / `from_dict()` — Pydantic handles this natively
- Update `load()` / `save()` functions to use `.model_dump_json()` / `.model_validate_json()`
- `SubscriptionPattern` must also become Pydantic (see below)

#### [MODIFY] [swarm_state.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/swarm_state.py)

**Current:** `@dataclass` `AgentMetadata`

**Target:** Pydantic `BaseModel` with optional LSP conversion methods

```python
class AgentMetadata(BaseModel):
    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    start_line: int = 1
    end_line: int = 1
    status: str = "active"
    created_at: float | None = None
    updated_at: float | None = None
```

#### [MODIFY] [discovery.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/discovery.py)

**Current:** `@dataclass(frozen=True, slots=True)` `CSTNode`

**Target:** Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True)`

```python
from pydantic import BaseModel, ConfigDict

class CSTNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int

    def __hash__(self) -> int:
        return hash(self.node_id)
```

#### [MODIFY] [events.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/events.py)

**Current:** All frozen dataclasses with `field(default_factory=time.time)`

**Target:** Pydantic `BaseModel` with `ConfigDict(frozen=True)` and `Field(default_factory=...)`

> [!WARNING]
> The `RemoraEvent` union type must remain a `type` union (not `Annotated[...]`). Pydantic handles `isinstance` checks on union members natively.

```python
from pydantic import BaseModel, ConfigDict, Field

class AgentStartEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    graph_id: str
    agent_id: str
    node_name: str
    timestamp: float = Field(default_factory=time.time)
```

Apply the same pattern to all 10 Remora event classes. Leave the `structured_agents` re-exports as-is.

#### [MODIFY] [subscriptions.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/subscriptions.py)

`SubscriptionPattern` is a dataclass used by `AgentState`. Convert to Pydantic for consistent serialization.

#### [MODIFY] [config.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/config.py)

**Current:** `@dataclass(slots=True)` `Config` with manual `serialize_config()` function.

**Target:** Pydantic `BaseModel`. This gives free YAML/JSON serialization and validation.

```python
class Config(BaseModel):
    project_path: str = "."
    discovery_paths: tuple[str, ...] = ("src/",)
    # ... same fields ...
    nvim_socket: str = ".remora/nvim.sock"
```

Delete the `serialize_config()` function — use `.model_dump()` instead.

#### [MODIFY] [models/__init__.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/models/__init__.py)

**Current:** Dataclass request/response models for REST API.

**Target:** Pydantic `BaseModel`. These are simple to convert — mechanical change.

### 3b. New Bridge Models (Does Not Exist Yet)

These are the core V2.1 concept models that don't exist anywhere in the codebase.

#### [NEW] `src/remora/lsp/models.py`

Create the **three bridge models** from the concept:

**`ASTAgentNode`** — The universal agent structure that serves triple duty. This is the central model of V2.1. It wraps data from `AgentMetadata` + `CSTNode` + `AgentState` and adds LSP conversion methods:

- `.to_document_symbol()` → `lsp.DocumentSymbol`
- `.to_range()` → `lsp.Range`
- `.to_code_lens()` → `lsp.CodeLens`
- `.to_hover()` → `lsp.Hover`
- `.to_code_actions()` → `list[lsp.CodeAction]`
- `.to_system_prompt()` → `str`

**`ToolSchema`** — Tool definition that converts to both `lsp.CodeAction` and vLLM function-calling format:

- `.to_code_action(agent_id)` → `lsp.CodeAction`
- `.to_llm_tool()` → `dict`

**`RewriteProposal`** — Agent-proposed code changes:

- `.diff` (computed field) → unified diff
- `.to_workspace_edit()` → `lsp.WorkspaceEdit`
- `.to_diagnostic()` → `lsp.Diagnostic`
- `.to_code_actions()` → accept/reject `CodeAction` pair

See the V2.1 concept document sections 1a–1c for the exact field definitions and method implementations.

### 3c. Migration Impact

| File | Consumers That Need Updating |
|------|-----|
| `agent_state.py` | `agent_runner.py`, `reconciler.py`, `swarm_executor.py` — update `asdict()` → `.model_dump()`, `from_dict()` → `.model_validate()` |
| `swarm_state.py` | `swarm_executor.py`, `nvim/server.py` — `_row_to_metadata()` uses keyword args, same pattern works |
| `discovery.py` | `reconciler.py`, `swarm_executor.py` — `CSTNode` construction is positional, needs `model_validate()` |
| `events.py` | `event_store.py` — `_serialize_event()` uses `asdict()`, change to `.model_dump()`. `is_dataclass()` check needs update. |
| `config.py` | `cli/main.py`, `swarm_executor.py` — `_build_config()` uses `Config(**data)`, same pattern works for Pydantic |

### 3d. Migration Order

1. `SubscriptionPattern` (leaf dependency)
2. `Config` (standalone)
3. `CSTNode` (standalone)
4. `AgentMetadata` (standalone)
5. Events (standalone, but update `event_store.py` serialization)
6. `AgentState` (depends on `SubscriptionPattern`)
7. `models/__init__.py` (standalone REST models)
8. `ASTAgentNode` / `ToolSchema` / `RewriteProposal` (new, depend on `lsprotocol`)

---

## 4. Phase 2 — LSP Server (`src/remora/lsp/`)

This is the **largest new component**. The entire `src/remora/lsp/` package needs to be created from scratch.

### 4a. Package Structure

```
src/remora/lsp/
├── __init__.py           # Exports RemoraLanguageServer
├── __main__.py           # Entry: python -m remora.lsp (stdio mode)
├── server.py             # RemoraLanguageServer class
├── models.py             # ASTAgentNode, ToolSchema, RewriteProposal
├── handlers/
│   ├── __init__.py
│   ├── documents.py      # didOpen, didSave, didClose
│   ├── hover.py          # textDocument/hover
│   ├── lens.py           # textDocument/codeLens
│   ├── actions.py        # textDocument/codeAction
│   └── commands.py       # workspace/executeCommand
└── notifications.py      # Custom $/remora/* handlers
```

### 4b. Server Core

#### [NEW] `src/remora/lsp/server.py`

```python
# src/remora/lsp/server.py
from __future__ import annotations
from pygls.server import LanguageServer
from remora.core.event_store import EventStore
from remora.core.swarm_state import SwarmState
from remora.core.subscriptions import SubscriptionRegistry

class RemoraLanguageServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__(name="remora", version="0.1.0")
        self.event_store: EventStore | None = None
        self.swarm_state: SwarmState | None = None
        self.subscriptions: SubscriptionRegistry | None = None
        self.proposals: dict[str, RewriteProposal] = {}

    async def initialize_services(
        self,
        event_store: EventStore,
        swarm_state: SwarmState,
        subscriptions: SubscriptionRegistry,
    ) -> None:
        self.event_store = event_store
        self.swarm_state = swarm_state
        self.subscriptions = subscriptions
```

Key design decisions:
- **Do NOT put `AgentRunner` as a Pydantic field on this class** — that was the exact bug. The server holds references to shared services, not the runner.
- The `AgentRunner` should be created separately and passed a reference to the server for sending notifications back to the client.
- Use `pygls` async features — the server runs in its own event loop.

#### [NEW] `src/remora/lsp/__main__.py`

```python
# src/remora/lsp/__main__.py
from __future__ import annotations
from remora.lsp.server import RemoraLanguageServer

def main() -> None:
    server = RemoraLanguageServer()
    # Register all handlers (imported for side effects)
    import remora.lsp.handlers.documents   # noqa: F401
    import remora.lsp.handlers.hover       # noqa: F401
    import remora.lsp.handlers.lens        # noqa: F401
    import remora.lsp.handlers.actions     # noqa: F401
    import remora.lsp.handlers.commands    # noqa: F401
    import remora.lsp.notifications        # noqa: F401

    server.start_io()

if __name__ == "__main__":
    main()
```

### 4c. Handler Implementations

Each handler file registers features on a module-level `server` instance. Follow the `pygls` pattern.

#### [NEW] `src/remora/lsp/handlers/documents.py`

Implements `textDocument/didOpen` and `textDocument/didSave`:
- On open: parse file with tree-sitter, upsert nodes into `SwarmState`, publish code lenses
- On save: re-parse, preserve IDs via name+type matching, detect orphans, invalidate graph

Uses `discovery.parse_file()` (already exists) to get `CSTNode` list, then converts to `ASTAgentNode` for LSP export.

#### [NEW] `src/remora/lsp/handlers/hover.py`

Implements `textDocument/hover`:
- Look up `ASTAgentNode` at cursor position via `SwarmState.get_agent()`
- Call `.to_hover(recent_events)` to generate markdown content
- Recent events come from `EventStore.replay()` filtered by agent ID

#### [NEW] `src/remora/lsp/handlers/lens.py`

Implements `textDocument/codeLens`:
- Query all agents for the current file from `SwarmState`
- Convert each to `ASTAgentNode` and call `.to_code_lens()`
- Returns list of `lsp.CodeLens` with `remora.selectAgent` commands

#### [NEW] `src/remora/lsp/handlers/actions.py`

Implements `textDocument/codeAction`:
- Find agent at cursor range
- Call `.to_code_actions()` for base tools (chat, rewrite, message)
- If agent has `pending_proposal_id`, add accept/reject actions from `RewriteProposal`
- Extension tools are injected from `.extra_tools`

#### [NEW] `src/remora/lsp/handlers/commands.py`

Implements `workspace/executeCommand` with match/case dispatch:
- `remora.chat` → send `$/remora/requestInput` notification
- `remora.requestRewrite` → send input prompt
- `remora.executeTool` → run extension tool
- `remora.acceptProposal` → apply `WorkspaceEdit` via `server.apply_edit()`
- `remora.rejectProposal` → send feedback prompt
- `remora.selectAgent` → send `$/remora/agentSelected`

#### [NEW] `src/remora/lsp/notifications.py`

Custom `$/remora/*` notification handlers:
- `$/remora/submitInput` — processes user input from Neovim UI
  - If `agent_id` present → chat message, trigger agent execution
  - If `proposal_id` present → rejection feedback, re-trigger agent

### 4d. Integration Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  RemoraLanguageServer                     │
│                                                           │
│   handlers/*.py ───▶ SwarmState (agents DB)               │
│                  ───▶ EventStore (events DB)              │
│                  ───▶ proposals dict (in-memory)          │
│                                                           │
│   notifications.py ──▶ AgentRunner.trigger()             │
│                     ◀── EventBus (agent results)         │
└─────────────────────────────────────────────────────────┘
```

The LSP server does NOT own the `AgentRunner`. Instead:
1. LSP handlers write to `EventStore` (triggers subscriptions)
2. `AgentRunner` picks up triggers from `EventStore.get_triggers()`
3. Agent results flow back via `EventBus` → LSP server's event handler → sends `$/remora/event` notifications to Neovim

---

## 5. Phase 3 — CLI Integration & Entrypoints

### 5a. Add `--lsp` Flag to `swarm start`

#### [MODIFY] [cli/main.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/cli/main.py)

The current `swarm_start` command has `--nvim` (line 30). Add a `--lsp` flag that starts the `pygls` LSP server instead of (or alongside) the JSON-RPC `NvimServer`:

```python
@swarm.command("start")
@click.option("--project-root", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--config", "config_path", type=click.Path(dir_okay=False, resolve_path=True))
@click.option("--nvim/--no-nvim", default=False, help="Start JSON-RPC Neovim server")
@click.option("--lsp/--no-lsp", default=False, help="Start LSP server (stdio)")
def swarm_start(project_root, config_path, nvim, lsp):
    # ... existing setup ...
    if lsp:
        from remora.lsp.__main__ import main as lsp_main
        lsp_main()  # This blocks — stdio mode
        return
    # ... rest of existing swarm start (runner, nvim server, etc.) ...
```

> [!WARNING]
> The LSP server runs in **stdio mode** (blocking). When `--lsp` is passed, the swarm start should initialize services, then hand control to the LSP server's event loop. The `AgentRunner` must run as a background task within the same event loop.

### 5b. Add Standalone `remora lsp` Subcommand

```python
@main.command()
def lsp():
    """Start the Remora LSP server (stdio mode for editor integration)."""
    from remora.lsp.__main__ import main as lsp_main
    lsp_main()
```

### 5c. Add `pyproject.toml` Script Entrypoint

#### [MODIFY] [pyproject.toml](file:///c:/Users/Andrew/Documents/Projects/remora/pyproject.toml)

```toml
[project.scripts]
remora = "remora.cli:main"
remora-lsp = "remora.lsp.__main__:main"   # NEW
remora-index = "remora.indexer.cli:main"
```

This allows Neovim to use `cmd = { "remora-lsp" }` or `cmd = { "remora", "lsp" }` in the LSP config.

---

## 6. Phase 4 — Lua Plugin Rewrite (LSP-Native)

The current Lua plugin is a v1 JSON-RPC client that connects to a Unix socket server. The V2.1 concept replaces this with standard LSP client integration plus custom notification handlers.

### 6a. Current State (To Be Replaced)

| File | Purpose | Status |
|------|---------|--------|
| `plugin/remora_nvim.lua` | Plugin entry — registers `:RemoraToggle`, `:RemoraConnect`, `:RemoraChat`, `:RemoraRefresh` | **Replace** — commands should use LSP code actions |
| `lua/remora_nvim/.v1/init.lua` | JSON-RPC client setup | **Delete** — LSP replaces this |
| `lua/remora_nvim/.v1/bridge.lua` | Unix socket JSON-RPC transport | **Delete** — LSP handles transport |
| `lua/remora_nvim/.v1/sidepanel.lua` | nui.nvim sidebar (9KB) | **Rewrite** — migrate to nui-components with reactive Signals |
| `lua/remora_nvim/.v1/chat.lua` | Chat window | **Rewrite** — use `$/remora/submitInput` |
| `lua/remora_nvim/.v1/navigation.lua` | Agent navigation | **Rewrite** — use `textDocument/codeLens` |

### 6b. New Plugin Structure

```
lua/remora/
├── init.lua          # Setup: vim.lsp.config + vim.lsp.enable()
├── handlers.lua      # $/remora/* notification handlers
├── panel.lua         # nui-components sidepanel (reactive Signals)
├── sse.lua           # SSE event subscription (background curl job)
└── highlights.lua    # Remora-specific highlight groups
plugin/
└── remora.lua        # Plugin entry (renamed from remora_nvim.lua)
```

### 6c. Core Setup

#### [NEW] `lua/remora/init.lua`

```lua
-- lua/remora/init.lua
local M = {}

function M.setup(opts)
    opts = opts or {}

    -- Register Remora as a language server (Neovim 0.11+ API)
    vim.lsp.config["remora"] = {
        cmd = opts.cmd or { "remora-lsp" },
        filetypes = opts.filetypes or { "python" },
        root_markers = { ".remora", ".git" },
        settings = {},
    }

    vim.lsp.enable("remora")

    -- Custom notification handlers
    vim.lsp.handlers["$/remora/event"] = M.on_event
    vim.lsp.handlers["$/remora/requestInput"] = M.on_request_input
    vim.lsp.handlers["$/remora/agentSelected"] = M.on_agent_selected

    -- Set up highlights
    require("remora.highlights").setup()

    -- Set up commands
    M.setup_commands()
end

function M.on_event(err, result, ctx)
    -- Forward to panel if open
    local panel = require("remora.panel")
    panel.handle_event(result)
end

function M.on_request_input(err, result, ctx)
    vim.ui.input({ prompt = result.prompt }, function(input)
        if input then
            vim.lsp.buf_notify(0, "$/remora/submitInput", {
                agent_id = result.agent_id,
                proposal_id = result.proposal_id,
                input = input,
            })
        end
    end)
end

function M.setup_commands()
    vim.api.nvim_create_user_command("RemoraChat", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command
                    and action.command.command == "remora.chat"
            end,
            apply = true,
        })
    end, { desc = "Chat with agent at cursor" })

    vim.api.nvim_create_user_command("RemoraRewrite", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command
                    and action.command.command == "remora.requestRewrite"
            end,
            apply = true,
        })
    end, { desc = "Request agent rewrite" })

    vim.api.nvim_create_user_command("RemoraAccept", function()
        vim.lsp.buf.code_action({
            filter = function(action)
                return action.command
                    and action.command.command == "remora.acceptProposal"
            end,
            apply = true,
        })
    end, { desc = "Accept pending proposal" })

    vim.api.nvim_create_user_command("RemoraToggle", function()
        require("remora.panel").toggle()
    end, { desc = "Toggle Remora sidepanel" })
end

return M
```

### 6d. What You Get For Free (Standard LSP)

Once the Python LSP server is running, these features work automatically without any custom Lua:

| Feature | How | Custom Lua Needed? |
|---------|-----|--------------------|
| Agent IDs inline on defs | `textDocument/codeLens` → virtual text | ❌ No |
| Hover for agent details | `textDocument/hover` → popup | ❌ No |
| Tool menu on cursor | `textDocument/codeAction` → quickfix menu | ❌ No |
| Pending proposals | `publishDiagnostics` → gutter signs | ❌ No |
| Apply rewrites | `workspace/applyEdit` → buffer edits | ❌ No |
| Input prompts | `$/remora/requestInput` → `vim.ui.input` | ✅ Minimal |
| Event stream | `$/remora/event` → panel update | ✅ Minimal |
| Rich sidebar | nui-components reactive panel | ✅ Yes |

### 6e. Panel Rewrite (nui-components)

The v1 `sidepanel.lua` (9KB) uses raw `nui.nvim` buffers. The V2.1 concept uses `nui-components` with reactive `Signal` state. This is a full rewrite — see the V2.1 concept Appendix A sections A1–A5 for the target implementation with:

- Collapsible sidebar (4-col collapsed → 40-col expanded)
- Reactive agent status updates via Signals
- Tabbed views (State, Events, Chat)
- SSE event subscription for real-time updates
- Grail trigger border flash effects

---

## 7. Phase 5 — AgentRunner ↔ LSP Bridge

The existing `AgentRunner` and `SwarmExecutor` in `core/` are functional. The challenge is connecting them to the new LSP server so that:
1. User actions in Neovim (via LSP) trigger agent execution
2. Agent results flow back to Neovim as LSP notifications/diagnostics/workspace edits

### 7a. Current AgentRunner Architecture

```
EventStore.get_triggers()  →  AgentRunner._process_trigger()
                                    ↓
                              SwarmExecutor.run_agent()
                                    ↓
                              AgentKernel (structured-agents)
                                    ↓
                              EventBus.emit(AgentCompleteEvent)
```

This is **already event-driven** via `EventStore` triggers and `EventBus` emissions. The key insight: the LSP server just needs to:
- **Write** events to `EventStore` (this triggers `AgentRunner` automatically)
- **Listen** to `EventBus` for results

### 7b. LSP Server ← EventBus Subscription

#### [MODIFY] [lsp/server.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/lsp/server.py)

Add an `EventBus` subscriber that forwards agent events to Neovim as `$/remora/event` notifications:

```python
class RemoraLanguageServer(LanguageServer):
    async def initialize_services(self, ..., event_bus: EventBus) -> None:
        # ... existing setup ...
        self._event_bus = event_bus
        event_bus.subscribe(AgentCompleteEvent, self._on_agent_complete)
        event_bus.subscribe(AgentErrorEvent, self._on_agent_error)
        event_bus.subscribe_all(self._on_any_event)

    async def _on_agent_complete(self, event: AgentCompleteEvent) -> None:
        # If agent produced a rewrite, create a RewriteProposal
        # and publish as diagnostic
        await self.send_notification("$/remora/event", {
            "event_type": "AgentCompleteEvent",
            "agent_id": event.agent_id,
            "result_summary": event.result_summary,
        })
        # Refresh code lenses for the agent's file
        # (status changed from "running" back to "active")

    async def _on_any_event(self, event) -> None:
        # Forward all events to Neovim for the sidepanel
        event_type = type(event).__name__
        await self.send_notification("$/remora/event", {
            "event_type": event_type,
            "agent_id": getattr(event, "agent_id", None),
        })
```

### 7c. LSP Server → EventStore Writes

When the user triggers a chat or rewrite via code action, the LSP command handler writes to `EventStore`:

```python
# In lsp/handlers/commands.py
async def handle_chat(server, agent_id, message):
    event = AgentMessageEvent(
        from_agent="human",
        to_agent=agent_id,
        content=message,
    )
    await server.event_store.append(server.swarm_id, event)
    # This automatically triggers AgentRunner via subscription matching
```

### 7d. RewriteProposal Flow

When an agent produces a rewrite (via `rewrite_self` tool call):

1. `SwarmExecutor` handles the tool call response
2. Creates a `RewriteProposal` and stores it on the LSP server
3. Publishes diagnostic to Neovim (yellow squiggly on the affected lines)
4. User sees the diagnostic, triggers `:RemoraAccept` code action
5. LSP server applies the `WorkspaceEdit` via `server.apply_edit()`

> [!NOTE]
> This requires adding `rewrite_self` tool result handling in `SwarmExecutor.run_agent()`. Currently, `SwarmExecutor` just stores chat history — it doesn't create `RewriteProposal` objects. The proposal creation logic from V2.1 concept Section 3a `handle_response()` needs to be integrated.

### 7e. Concurrency Model

The LSP server and `AgentRunner` share the same async event loop:

```python
async def start_lsp_with_runner():
    server = RemoraLanguageServer()
    # ... initialize services ...

    runner = AgentRunner(event_store=..., ...)
    runner_task = asyncio.create_task(runner.run_forever())

    try:
        server.start_io()  # Blocks, but pygls uses asyncio internally
    finally:
        runner_task.cancel()
```

---

## 8. Phase 6 — ID Management & Injection

The V2.1 concept uses short, human-readable `rm_` prefixed IDs injected as inline comments on definition lines. The current codebase uses 16-char SHA256 hash IDs that are never visible in source files.

### 8a. Current ID Scheme

In [discovery.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/discovery.py):

```python
def compute_node_id(file_path: str, name: str, start_line: int, end_line: int) -> str:
    content = f"{file_path}:{name}:{start_line}:{end_line}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

Problems:
- IDs change when line numbers shift (fragile)
- IDs are invisible to users (no inline presence in source)
- IDs are not human-readable (16 hex chars)

### 8b. Target ID Scheme

```
rm_a1b2c3d4  (rm_ prefix + 8 lowercase alphanumeric)
```

- **Prefix:** `rm_` (always)
- **Body:** 8 lowercase alphanumeric characters
- **Placement:** End of definition line as inline comment

```python
class ConfigLoader:  # rm_a1b2c3d4
    def load(self):  # rm_e5f6g7h8
        ...
```

File-level IDs go on line 1 (or after shebang):

```python
# remora-file: rm_xyz12345
"""This module handles configuration loading."""
```

### 8c. Implementation

#### [NEW] `src/remora/core/ids.py`

```python
# src/remora/core/ids.py
from __future__ import annotations
import re
import secrets
import string

ID_PREFIX = "rm_"
ID_BODY_LENGTH = 8
ID_ALPHABET = string.ascii_lowercase + string.digits
ID_PATTERN = re.compile(r'# rm_[a-z0-9]{8}\s*$')
FILE_ID_PATTERN = re.compile(r'^# remora-file: rm_[a-z0-9]{8}')

def generate_id() -> str:
    body = ''.join(secrets.choice(ID_ALPHABET) for _ in range(ID_BODY_LENGTH))
    return f"{ID_PREFIX}{body}"

def inject_ids(file_path: Path, nodes: list[ASTAgentNode]) -> str:
    """Inject/update remora IDs in source file."""
    lines = file_path.read_text().splitlines()
    nodes_sorted = sorted(nodes, key=lambda n: n.start_line, reverse=True)
    for node in nodes_sorted:
        line_idx = node.start_line - 1
        line = lines[line_idx]
        line = ID_PATTERN.sub('', line)  # Remove existing
        lines[line_idx] = f"{line}  # {node.remora_id}"
    return "\n".join(lines) + "\n"
```

#### [MODIFY] [discovery.py](file:///c:/Users/Andrew/Documents/Projects/remora/src/remora/core/discovery.py)

Update `compute_node_id()` to use the new `rm_` scheme. For **new** nodes, generate a fresh `rm_` ID. For **existing** nodes (re-parse on save), match by `(name, node_type)` to preserve the existing ID.

### 8d. ID Preservation Across Saves

On `textDocument/didSave`:
1. Parse new AST to get new nodes
2. Match against old nodes by `(name, node_type)` key
3. Carry over `remora_id` from old to new where matched
4. Mark unmatched old nodes as "orphaned"
5. Generate new `rm_` IDs for unmatched new nodes
6. Re-inject IDs into the file

---

## 9. Phase 7 — Graph & Cycle Detection

### 9a. SQLite Schema Additions

The V2.1 concept describes additional tables not present in the current schema. The existing `EventStore` has an `events` table, and `SwarmState` has an `agents` table. Missing:

#### Activation Chain Table

```sql
CREATE TABLE activation_chain (
    correlation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    PRIMARY KEY (correlation_id, agent_id)
);
CREATE INDEX idx_chain_correlation ON activation_chain(correlation_id);
```

**Current state:** `AgentRunner` tracks cascade depth in an **in-memory** dict (`_correlation_depth`). This works but doesn't survive restarts and can't be queried by the LSP server.

**Target:** Move to SQLite for persistence and cross-component visibility. Add this table to `SwarmState` or create a dedicated `ActivationTracker` class.

#### Edges Table

```sql
CREATE TABLE edges (
    from_id TEXT NOT NULL REFERENCES agents(agent_id),
    to_id TEXT NOT NULL REFERENCES agents(agent_id),
    edge_type TEXT NOT NULL,  -- parent_of, calls, imports
    PRIMARY KEY (from_id, to_id, edge_type)
);
```

**Current state:** `CSTNode` has no caller/callee relationships. Discovery only extracts definitions, not call graphs.

**Target:** Add call-graph extraction to the tree-sitter discovery phase. This is a **nice-to-have** for V2.2 — the parent/child relationship is already tracked via `parent_id` in `SwarmState`.

### 9b. LazyGraph (Rustworkx)

The V2.1 concept describes a `LazyGraph` using `rustworkx.PyDiGraph` for in-memory graph queries. This is needed for:
- Parent/child navigation (hover details)
- Caller/callee display
- Cycle detection in activation chains

**Current state:** No `rustworkx` usage anywhere. The `pyproject.toml` doesn't list it as a dependency.

**Recommendation for V2.2:** Skip `rustworkx` initially. Use SQLite queries for graph traversal. The `edges` table + simple recursive queries cover the MVP use cases. Add `rustworkx` later for performance if needed.

---

## 10. Phase 8 — Extension Discovery

### 10a. Concept

The V2.1 concept allows users to define custom agent behaviors in `.remora/models/*.py` files. These `ExtensionNode` subclasses inject:
- Custom system prompts
- Mounted workspaces
- Extra tools (as `ToolSchema` objects → code actions in Neovim)

### 10b. Implementation

#### [NEW] `src/remora/lsp/extensions.py`

```python
# src/remora/lsp/extensions.py
from __future__ import annotations
import importlib.util
from pathlib import Path
from pydantic import BaseModel

class ExtensionNode(BaseModel):
    """Base class for user-defined agent extensions."""
    target_node_type: str | None = None
    target_name_pattern: str | None = None
    system_prompt: str = ""

    def matches(self, node_type: str, name: str) -> bool:
        if self.target_node_type and self.target_node_type != node_type:
            return False
        if self.target_name_pattern:
            import re
            if not re.match(self.target_name_pattern, name):
                return False
        return True

    def get_workspaces(self) -> str:
        return ""

    def get_tool_schemas(self) -> list[ToolSchema]:
        return []


def load_extensions(models_dir: Path) -> list[type[ExtensionNode]]:
    """Load ExtensionNode subclasses from .remora/models/"""
    extensions = []
    if not models_dir.exists():
        return extensions
    for py_file in models_dir.glob("*.py"):
        spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for obj in module.__dict__.values():
            if (isinstance(obj, type)
                and issubclass(obj, ExtensionNode)
                and obj is not ExtensionNode):
                extensions.append(obj)
    return extensions
```

### 10c. Integration Point

In `SwarmExecutor._build_prompt()` or in the LSP handler for hydrating an `ASTAgentNode`:

```python
def apply_extensions(agent: ASTAgentNode) -> ASTAgentNode:
    extensions = load_extensions(Path(".remora/models"))
    for ext_cls in extensions:
        if ext_cls().matches(agent.node_type, agent.name):
            ext = ext_cls()
            agent.custom_system_prompt = ext.system_prompt
            agent.mounted_workspaces = ext.get_workspaces()
            agent.extra_tools = ext.get_tool_schemas()
            break
    return agent
```

---

## 11. Appendix A — File-by-File Audit

### Python Source (`src/remora/`)

| File | Lines | Status | Action Required |
|------|-------|--------|-----------------|
| `core/agent_state.py` | 84 | ⚠️ Dataclass | Convert to Pydantic `BaseModel` |
| `core/agent_runner.py` | 288 | ✅ Functional | Wire to LSP server via `EventBus` |
| `core/config.py` | 165 | ⚠️ Dataclass | Convert to Pydantic, delete `serialize_config()` |
| `core/discovery.py` | 374 | ⚠️ Dataclass `CSTNode` | Convert to Pydantic, update ID scheme to `rm_` |
| `core/event_bus.py` | 135 | ✅ Functional | No changes needed |
| `core/event_store.py` | 354 | ⚠️ Uses `asdict()` | Update serialization for Pydantic (`model_dump()`) |
| `core/events.py` | 187 | ⚠️ Dataclasses | Convert Remora events to Pydantic, keep SA re-exports |
| `core/reconciler.py` | ~200 | ✅ Functional | Minor updates for Pydantic model API |
| `core/subscriptions.py` | ~300 | ⚠️ Dataclass `SubscriptionPattern` | Convert to Pydantic |
| `core/swarm_executor.py` | 375 | ✅ Functional | Add `rewrite_self` tool response handling |
| `core/swarm_state.py` | 197 | ⚠️ Dataclass `AgentMetadata` | Convert to Pydantic |
| `core/workspace.py` | ~200 | ✅ Functional | No changes needed |
| `cli/main.py` | 274 | ⚠️ Missing `--lsp` | Add `--lsp` flag and `lsp` subcommand |
| `models/__init__.py` | 101 | ⚠️ Dataclasses | Convert to Pydantic |
| `nvim/server.py` | 265 | ✅ v1 JSON-RPC | **Keep** for backward compat, but superseded by LSP |
| **`lsp/` (entire package)** | 0 | 🔴 Missing | **Create** — 8+ new files |
| **`core/ids.py`** | 0 | 🔴 Missing | **Create** — `rm_` ID generation and injection |

### Lua Plugin

| File | Lines | Status | Action Required |
|------|-------|--------|-----------------|
| `plugin/remora_nvim.lua` | 24 | ⚠️ v1 commands | **Replace** with `plugin/remora.lua` |
| `lua/remora_nvim/.v1/init.lua` | ~50 | ❌ v1 JSON-RPC | **Delete** or archive |
| `lua/remora_nvim/.v1/bridge.lua` | ~200 | ❌ v1 transport | **Delete** or archive |
| `lua/remora_nvim/.v1/sidepanel.lua` | ~300 | ❌ v1 nui.nvim | **Rewrite** as `lua/remora/panel.lua` |
| `lua/remora_nvim/.v1/chat.lua` | ~50 | ❌ v1 chat | **Rewrite** using LSP notifications |
| `lua/remora_nvim/.v1/navigation.lua` | ~200 | ❌ v1 navigation | **Delete** — LSP code lens replaces this |
| **`lua/remora/init.lua`** | 0 | 🔴 Missing | **Create** — LSP config + handlers |
| **`lua/remora/panel.lua`** | 0 | 🔴 Missing | **Create** — nui-components sidebar |
| **`lua/remora/sse.lua`** | 0 | 🔴 Missing | **Create** — SSE event subscription |
| **`lua/remora/highlights.lua`** | 0 | 🔴 Missing | **Create** — highlight group definitions |

---

## 12. Appendix B — Dependency Check

### Python Dependencies

| Package | In `pyproject.toml`? | Used Currently? | Needed For V2.2? |
|---------|---------------------|-----------------|-------------------|
| `pygls` | ✅ Yes | ❌ No (listed but unused) | ✅ Required — LSP server |
| `lsprotocol` | ✅ Yes | ❌ No (listed but unused) | ✅ Required — LSP types |
| `pydantic` | ✅ Yes | ⚠️ Only for `AgentRunner` wrapper (stale) | ✅ Required — all models |
| `tree-sitter` | ✅ Yes | ✅ Yes (`discovery.py`) | ✅ Required — code parsing |
| `tree-sitter-python` | ✅ Yes | ✅ Yes | ✅ Required |
| `rustworkx` | ❌ No | ❌ No | 🟡 Optional — skip for MVP |

### Neovim Plugin Dependencies

| Package | Required? | Purpose |
|---------|-----------|---------|
| Neovim ≥ 0.11 | ✅ Yes | `vim.lsp.config` / `vim.lsp.enable()` API |
| `nui-components.nvim` | 🟡 Optional | Rich sidebar UI (reactive Signals) |
| `nui.nvim` | 🟡 Optional | Required by nui-components |
| `nvim-notify` | 🟡 Optional | Better notification display |

### Version Verification

```bash
# Check pygls is installed and importable
python -c "import pygls; print(pygls.__version__)"

# Check lsprotocol
python -c "import lsprotocol; print(lsprotocol.__version__)"

# Check Neovim version (need 0.11+ for vim.lsp.config)
nvim --version | head -1
```

---

*End of V2.2 Refactoring Guide*
