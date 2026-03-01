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

