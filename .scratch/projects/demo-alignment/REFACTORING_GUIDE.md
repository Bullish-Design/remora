# Demo Alignment Refactoring Guide

**Created:** 2026-03-07
**Status:** Analysis complete, fixes pending
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
| [1. Web UI / Graph Viewer](#1-web-ui--graph-viewer) | `remora_demo/web/graph/` | **Critical**: DB schema drift → runtime SQL errors |
| [2. Agent Chat Service](#2-agent-chat-service) | `src/remora/service/chat_service.py` | Module-level singleton, broken DI |
| [3. Neovim Integration](#3-neovim-integration) | `src/remora/lsp/nvim/lua/remora/` | **High**: Live AgentMessageEvent invisible; event wire format bugs |
| [4. Companion](#4-companion) | `remora_demo/companion/` | Protocol mismatch, dead push code, pattern divergence |

See per-area guides:
- [`GUIDE_WEB_UI.md`](GUIDE_WEB_UI.md) — Critical DB schema fixes
- [`GUIDE_AGENT_CHAT.md`](GUIDE_AGENT_CHAT.md) — Singleton + DI fixes
- [`GUIDE_NEOVIM.md`](GUIDE_NEOVIM.md) — Event wire protocol bugs
- [`GUIDE_COMPANION.md`](GUIDE_COMPANION.md) — Protocol alignment, push model

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

### Event Wire Protocol

**Live events** (`$/remora/event` notification):
```
AgentEvent subclasses → {event_type, agent_id, payload={...}, summary, timestamp}
AgentMessageEvent     → {from_agent, to_agent, content, ...}  ← NO event_type! (Bug)
```

**Historical events** (`row_to_event_dict()`):
```
All types → {id, event_type, from_agent, to_agent, payload={non-meta fields}, summary, timestamp}
```

### Current EventStore Schema

```sql
events: id INTEGER PK, graph_id, event_type, payload TEXT, timestamp, created_at,
        from_agent, to_agent, correlation_id, tags
nodes:  node_id TEXT PK, node_type, name, full_name, file_path, start_line, end_line,
        source_code, source_hash, parent_id, status DEFAULT 'idle', ...
```

**Stale names (do not use):** `event_id`, `agent_id`, `nodes.id`

---

## Priority Order

Recommended work order:

1. **Web UI** — Critical SQL errors cause complete failure at runtime; fix immediately
2. **Neovim Integration** — `AgentMessageEvent` live events invisible; affects core demo value
3. **Agent Chat** — Singleton is a test-isolation issue; functional but fragile
4. **Companion** — Protocol improvements are medium-term; mostly works today

---

## Acceptance Criteria (all areas)

- [ ] No `from remora.core.events.events import` anywhere (module deleted)
- [ ] No `from remora.lsp.models import` anywhere (module deleted)
- [ ] `state.py` SQL queries match current EventStore column names
- [ ] `tests/test_bridge.py` schema matches production EventStore schema
- [ ] Live `AgentMessageEvent` visible in panel.lua
- [ ] `devenv shell -- tach check` continues to pass
- [ ] Full test suite passes: `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
