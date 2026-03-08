# Demo Alignment Refactoring Guide

**Created:** 2026-03-07
**Status:** Analysis complete (Phase 1 + 2 done), Phase 3 implementation pending
**Goal:** Align all functional areas to the refactored Remora architecture (post-`architecture_refactor` + `architecture-mental-model-simplification`).

---

## Context

Two major architecture refactors completed on 2026-03-07:

1. **`architecture_refactor`** — Severed `core → outer-layer` deps, broke LSP circular startup deps, decomposed large modules, introduced `remora.runner` package, removed compat shims.

2. **`architecture-mental-model-simplification`** — Enforced layering in `tach.toml`, moved `RewriteProposal` to `runner.models`, moved `NodeDiscoveredEvent.from_cst_node()` to `discovery.node_to_event()`, split `core.events.events` into 4 bounded modules, thinned hotspot orchestrators, barrel-import audit.

**Result:** `tach check` passes, 0 cycles, Architecture SLOs OK, all tests pass.

---

## Functional Areas

Four areas require alignment review. These are real functional implementations — not demo harnesses.

| Area | Primary Files | Primary Issues |
|------|--------------|----------------|
| [1. Web UI / Graph Viewer](#1-web-ui--graph-viewer) | `remora_demo/web/graph/` | **Critical**: Wrong DB path + stale column names → runtime SQL errors |
| [2. Neovim Integration](#2-neovim-integration) | `src/remora/lsp/nvim/lua/remora/` | **High**: Live AgentMessageEvent invisible; direction "unknown" |
| [3. Companion](#3-companion) | `src/remora/companion/` + `remora_demo/companion/` | **Critical**: Companion pipeline never runs — start_companion() never called |
| [4. Agent Chat Service](#4-agent-chat-service) | `src/remora/service/chat_service.py` | Module-level singleton, broken DI |

See per-area guides:
- [`GUIDE_WEB_UI.md`](GUIDE_WEB_UI.md) — Two-DB architecture + schema fixes
- [`GUIDE_NEOVIM.md`](GUIDE_NEOVIM.md) — Event wire protocol bugs
- [`GUIDE_COMPANION.md`](GUIDE_COMPANION.md) — Companion pipeline integration (complete rewrite)
- [`GUIDE_AGENT_CHAT.md`](GUIDE_AGENT_CHAT.md) — Singleton + DI fixes

---

## Architecture Layer Reference

```
core  →  runner  →  adapters (lsp, service, companion, ui, cli)  →  utils
```

- `core` is never allowed to depend on any adapter layer module.
- `runner` must NOT import `lsp.*`.
- Adapters import from `core` and `runner` — not from each other (except where tach explicitly allows).

### Canonical Event Import Paths (post-W4)

Old (deleted): `from remora.core.events.events import X`

New bounded modules:
```python
from remora.core.events.agent_events import (
    AgentStartEvent, AgentCompleteEvent, AgentErrorEvent,
    AgentEvent, HumanChatEvent,
    RewriteProposalEvent, RewriteAppliedEvent, RewriteRejectedEvent,
    HumanInputRequestEvent, HumanInputResponseEvent,
    _FrozenEvent,
)
from remora.core.events.interaction_events import (
    AgentMessageEvent, FileSavedEvent, ContentChangedEvent,
    CursorFocusEvent, ManualTriggerEvent,
)
from remora.core.events.code_events import (
    NodeDiscoveredEvent, ScaffoldRequestEvent, NodeRemovedEvent,
)
from remora.core.events.kernel_events import (
    ToolCallEvent, ToolResultEvent, KernelStartEvent, KernelEndEvent,
    ModelRequestEvent, ModelResponseEvent, TurnCompleteEvent,
)
```

### Canonical Model Import Paths (post-W2)

```python
# RewriteProposal now lives in runner.models (NOT lsp.models)
from remora.runner.models import RewriteProposal, generate_id
```

`lsp.models` has been deleted — any remaining imports from it will fail.

### Production Companion Entry Point (post-analysis)

```python
# This is the correct way to start the companion pipeline:
from remora.companion.startup import start_companion
from remora.companion.config import CompanionConfig

dispatcher = await start_companion(
    event_store=event_store,
    event_bus=event_bus,
    cairn_service=None,
    config=CompanionConfig(workspace_path=Path.cwd()),
)
```

`remora_demo/companion/runtime.py` and `lsp/server.py` are obsolete — the production companion integrates directly into the main LSP server via `start_companion()`.

### Event Wire Protocol

**Live events** (`$/remora/event` notification):
```
AgentEvent subclasses → {event_type, agent_id, payload={...}, summary, timestamp}
AgentMessageEvent     → {from_agent, to_agent, content, ...}  ← NO event_type! (Bug 1)
```

Fix (see GUIDE_NEOVIM.md): wrap `AgentMessageEvent` in `AgentEvent` envelope in `emit_agent_message_event()`.

**Historical events** (`row_to_event_dict()`):
```
All types → {id, event_type, from_agent, to_agent, payload={non-meta fields}, summary, timestamp}
```

### Two-Database Architecture

```
.remora/
├── events/
│   └── events.db    ← EventStore: tables: events, nodes
├── indexer.db       ← RemoraDB: tables: edges, proposals, cursor_focus, command_queue, activation_chain
├── subscriptions.db ← SubscriptionRegistry
├── lsp.lock
└── lsp.pid
```

`GraphState` (web UI) must open BOTH databases — see GUIDE_WEB_UI.md.

### Current EventStore Schema

```sql
events: id INTEGER PK AUTOINCREMENT, graph_id, event_type, payload TEXT, timestamp, created_at,
        from_agent, to_agent, correlation_id, tags
nodes:  node_id TEXT PK, node_type, name, full_name, file_path, start_line, end_line,
        source_code, source_hash, parent_id, status DEFAULT 'idle', ...
```

**Stale names (do not use):** `event_id`, `agent_id`, `nodes.id`

---

## Priority Order

Recommended work order:

1. **Companion** — pipeline never runs (start_companion() not called); complete rewrite needed
2. **Web UI** — wrong DB path causes complete failure at runtime; fix immediately
3. **Neovim** — AgentMessageEvent live events invisible; affects core demo value
4. **Agent Chat** — Singleton is a test-isolation issue; functional but fragile

---

## Acceptance Criteria (all areas)

- [ ] No `from remora.core.events.events import` anywhere (module deleted)
- [ ] No `from remora.lsp.models import` anywhere (module deleted)
- [ ] `start_companion()` called in `lsp/__main__.py` — companion pipeline active
- [ ] `state.py` queries nodes/events from EventStore (`.remora/events/events.db`)
- [ ] `state.py` SQL queries use current column names (`id`, `from_agent`, `to_agent`, `node_id`)
- [ ] `tests/test_bridge.py` creates both production schemas (EventStore + RemoraDB)
- [ ] Live `AgentMessageEvent` visible in panel.lua
- [ ] `companion.getSidebar` workspace/executeCommand registered in main LSP
- [ ] Old `remora_demo/companion/lsp/server.py` and `runtime.py` deleted
- [ ] `devenv shell -- tach check` continues to pass
- [ ] Full test suite passes: `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
