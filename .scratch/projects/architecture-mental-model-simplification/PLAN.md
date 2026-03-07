# PLAN — Architecture Mental Model Simplification

## Objective

Reduce architectural cognitive load by eliminating coupling hotspots, enforcing strict layer
boundaries, and decomposing overloaded modules so that each can be understood in isolation.

## Target Mental Model

```
                        ┌─────────────┐
                        │    utils    │  ← leaf: no dependencies on anything in remora
                        └─────────────┘
                               ▲
                        ┌─────────────┐
                        │    core     │  ← domain: events, agents, store, code, config
                        └─────────────┘
                               ▲
                        ┌─────────────┐
                        │   runner    │  ← orchestration: agent execution, triggers
                        └─────────────┘
                               ▲
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌─────────────┐    ┌─────────────────┐   ┌─────────────┐
   │     lsp     │    │    service/ui   │   │  companion  │  ← adapters: wire-protocol specific
   └─────────────┘    └─────────────────┘   └─────────────┘
```

**One rule:** dependencies flow inward only. Adapters depend on runner and core. Runner depends on
core. Core depends on utils. Nothing flows outward.

---

## Baseline (W0 confirmed — 2026-03-07)

- Modules: 106 | Edges: 305 | Cycles: 0 | `tach check`: PASSES
- Top hotspot degrees:
  - `core.events.events`: degree 34 (in 33 / out 1)  ← PRIMARY TARGET
  - `core` (barrel):      degree 19 (in  0 / out 19)
  - `lsp.server`:         degree 17 (in  2 / out 15)
  - `store.event_store`:  degree 16 (in 10 / out  6)
  - `service.api`:        degree 16 (in  3 / out 13)
  - `agents.execution`:   degree 16 (in  3 / out 13)
  - `runner.agent_runner`:degree 16 (in  4 / out 12)
  - `cli.main`:           degree 15 (in  2 / out 13)
- Confirmed violations:
  - `runner.agent_runner → lsp.models` (W2)
  - `core.events.events → core.code.discovery` (W3)
- W5 (LSP barrel/handler cycle): **Already resolved** — skipped

---

## Workstreams

### W0 — Diagnostic: Identify remaining cycles ✅ COMPLETE

**Run:** 2026-03-07. Commands used:
```bash
devenv shell -- tach check          # passes — all modules validated
devenv shell -- tach show -o /tmp/remora_current.dot
# then Kosaraju SCC analysis on the DOT file in Python
```

**Findings:**

**0 cycles remain.** Both cycles predicted from the baseline are already resolved.

The old baseline (from the prior architecture_refactor session) included flat compatibility shim
modules (`remora.core.agent_context`, `remora.core.agent_node`, etc.) that were removed when the
nested module structure was finalised. Those shims contained the edges that formed the cycles.

**Cycle A (historical — now resolved):**
`remora.lsp` ↔ `remora.lsp.server` ↔ `remora.lsp.handlers.*` ← all handlers now import
`remora.lsp.protocols` instead of the barrel; cycle is gone.

**Cycle B (historical — now resolved):**
`remora.runner` ↔ `remora.runner.agent_runner` ← agent_runner no longer imports the runner
barrel; cycle is gone.

**Confirmed violations still present (layer rule breaches, not cycles):**
- `remora.runner.agent_runner → remora.lsp.models` — addressed by W2
- `remora.core.events.events → remora.core.code.discovery` — addressed by W3

**No core → adapter violations** found. Core is clean with respect to lsp/service/ui/companion/cli.

**Impact on plan:**
- W5 is skipped (already done).
- Baseline updated to current numbers (106 nodes, 305 edges, 0 cycles).
- `core.events.events` in-degree is 33 — worse than old baseline of 29, confirming W4 urgency.

---

### W1 — Enforce dependency policy in `tach.toml`

**Why first among implementation work:** Rules prevent regressions while you refactor. Adding them
before any code moves means you can verify each step is clean.

**Steps:**

1. Open `tach.toml`. The `[[modules]]` entries currently describe what each module *is allowed* to
   import. Add the following forbidden dependency rules. Tach enforces these as `depends_on` lists —
   any import not in the list will fail `tach check`.

2. **Lock down `core` so it cannot import from adapters.** Find these module entries in `tach.toml`
   and verify their `depends_on` lists do NOT include any of:
   `remora.lsp`, `remora.service`, `remora.ui`, `remora.companion`, `remora.cli`, `remora.extensions`

   Specifically check these core submodules (they had violations in the prior refactor):
   - `remora.core.events.events` — currently allowed to depend on `remora.core.code.discovery`.
     This dependency is addressed in **W3** and should be removed from `depends_on` then.
   - `remora.core` (barrel) — scan its `depends_on` list and confirm no adapter paths are present.

3. **Lock down `runner` so it cannot import from `lsp`.** Find the entry for
   `remora.runner.agent_runner` in `tach.toml`. Its current `depends_on` list includes:
   ```toml
   "remora.lsp.models"
   ```
   This is the violation addressed in **W2**. For now, leave it but add a comment:
   ```toml
   # VIOLATION — to be removed in W2: remora.lsp.models
   ```
   Do not actually remove it yet — removing it from `tach.toml` before fixing the source import
   will cause `tach check` to fail loudly and break CI.

4. **Add a CI command.** If a CI configuration file exists (e.g., `.github/workflows/*.yml` or
   a `Makefile`), add:
   ```
   tach check
   ```
   as a required step. If no CI exists, add a `Makefile` target:
   ```makefile
   .PHONY: check-arch
   check-arch:
       tach check
   ```

5. Run `tach check` now to establish the current baseline pass/fail state. Record the result in
   `PROGRESS.md`. This is the starting line — every subsequent workstream should leave `tach check`
   passing or no worse than this baseline.

**Acceptance:** `tach check` runs without error (or the exact set of existing violations is
documented in `PROGRESS.md` so regressions are detectable).

---

### W2 — Fix `runner.agent_runner → lsp.models` (the concrete layer violation)

**Why this is critical:** `runner` is the orchestration layer. It must not know about `lsp`, which
is an adapter. Currently `remora.runner.agent_runner` imports `RewriteProposal` and `generate_id`
from `remora.lsp.models`. These are proposal types owned by the runner's domain, not by the LSP
wire protocol.

**Problem location:** `src/remora/runner/agent_runner.py`, line 14:
```python
from remora.lsp.models import RewriteProposal, generate_id
```

**Steps:**

1. **Create `src/remora/runner/models.py`** (new file). Move `RewriteProposal` and `generate_id`
   here. Copy the full content of both from `lsp/models.py`:

   ```python
   """Runner-owned proposal and ID models.

   RewriteProposal describes a pending code change that the runner creates
   and the server (LSP or headless) stores and dispatches.
   """
   from __future__ import annotations

   import difflib
   import random
   import string

   from lsprotocol import types as lsp
   from pydantic import BaseModel, computed_field


   def generate_id() -> str:
       body = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
       return f"rm_{body}"


   class RewriteProposal(BaseModel):
       proposal_id: str
       agent_id: str
       file_path: str
       old_source: str
       new_source: str
       start_line: int
       end_line: int
       reasoning: str = ""
       correlation_id: str = ""

       @computed_field
       @property
       def diff(self) -> str:
           return "\n".join(
               difflib.unified_diff(
                   self.old_source.splitlines(),
                   self.new_source.splitlines(),
                   lineterm="",
               )
           )

       def to_workspace_edit(self) -> lsp.WorkspaceEdit: ...
       def to_diagnostic(self) -> lsp.Diagnostic: ...
       def to_code_actions(self) -> list[lsp.CodeAction]: ...
   ```

   Copy the full method bodies from `lsp/models.py` — do not summarize them.

2. **Update `src/remora/runner/agent_runner.py`**: Change line 14 from:
   ```python
   from remora.lsp.models import RewriteProposal, generate_id
   ```
   to:
   ```python
   from remora.runner.models import RewriteProposal, generate_id
   ```

3. **Update `src/remora/lsp/models.py`**: The LSP aliases (`LspRewriteProposalEvent`, etc.) are
   just re-exports from `core.events.events`. Remove them entirely — they add no value and create
   a re-export chain that confuses import tracking. The remaining content of `lsp/models.py` after
   the move should be only:
   - The `lsprotocol`-specific LSP wire types (if any exist beyond `RewriteProposal`)
   - An import of `RewriteProposal` from `remora.runner.models` for backwards compatibility via
     the `lsp` barrel (see step 4)

   Concretely, `lsp/models.py` becomes:
   ```python
   """LSP-facing models.

   Wire-protocol specific models for the Neovim LSP adapter.
   RewriteProposal and generate_id now live in remora.runner.models.
   """
   from remora.runner.models import RewriteProposal, generate_id  # re-export for barrel compat

   __all__ = ["RewriteProposal", "generate_id"]
   ```
   And remove all the `LspAgentEvent`, `LspHumanChatEvent`, etc. aliases — callers should import
   from `remora.core.events.events` directly.

4. **Update `src/remora/lsp/__init__.py`**: Remove the `LspAgent*` re-exports from `__all__` since
   those aliases are being deleted. Keep `RewriteProposal`, `generate_id`, `RemoraDB`, `LazyGraph`,
   `RemoraLanguageServer`.

5. **Grep for any other import sites** that import the old LSP aliases:
   ```
   grep -r "LspAgentEvent\|LspHumanChatEvent\|LspRewriteProposalEvent\|LspAgentMessageEvent\|LspRewriteAppliedEvent\|LspRewriteRejectedEvent\|LspAgentErrorEvent" src/
   ```
   Update each to import the underlying type directly from `remora.core.events.events`.

6. **Update `tach.toml`**:
   - Remove `"remora.lsp.models"` from `remora.runner.agent_runner`'s `depends_on` list.
   - Add a new entry for `remora.runner.models`:
     ```toml
     [[modules]]
     path = "remora.runner.models"
     depends_on = ["remora.runner.protocols"]
     ```
     Note: `runner.models` needs `lsprotocol` (external) but no internal remora dependencies
     beyond `runner.protocols` if any. If `to_workspace_edit` / `to_diagnostic` only use
     `lsprotocol.types`, then `depends_on = []` is correct.
   - Update `remora.lsp.models` depends_on to:
     ```toml
     [[modules]]
     path = "remora.lsp.models"
     depends_on = ["remora.runner.models"]
     ```

7. Run `tach check`. It must pass. Run the test suite and confirm no import errors.

**Acceptance:**
- `grep -r "from remora.lsp.models import" src/remora/runner/` returns no results.
- `tach check` passes.
- `python -c "from remora.runner.agent_runner import AgentRunner"` succeeds.

---

### W3 — Fix `core.events.events → core.code.discovery`

**Why:** Event type definitions are pure data. They should have zero knowledge of domain services
like code discovery. The sole cause of this dependency is `NodeDiscoveredEvent.from_cst_node()`,
a factory method that converts a `CSTNode` (from discovery) into an event. Factory methods that
depend on domain objects have no business living on the event type itself.

**Problem location:** `src/remora/core/events/events.py`, lines 236–252:
```python
@classmethod
def from_cst_node(cls, node: CSTNode) -> NodeDiscoveredEvent:
    from remora.core.code.discovery import compute_source_hash
    return cls(
        node_id=node.node_id,
        ...
        source_hash=compute_source_hash(node.text),
        ...
    )
```
And lines 21–23 (TYPE_CHECKING guard):
```python
if TYPE_CHECKING:
    from remora.core.code.discovery import CSTNode
```

**Steps:**

1. **Add a factory function to `src/remora/core/code/discovery.py`**. At the bottom of the file,
   add:
   ```python
   def node_to_event(node: CSTNode) -> "NodeDiscoveredEvent":
       """Convert a CSTNode to a NodeDiscoveredEvent.

       This factory lives in discovery (not on the event type) because
       event definitions must not depend on discovery internals.
       """
       from remora.core.events.events import NodeDiscoveredEvent  # avoid circular import

       return NodeDiscoveredEvent(
           node_id=node.node_id,
           node_type=node.node_type,
           name=node.name,
           full_name=node.full_name,
           file_path=node.file_path,
           start_line=node.start_line,
           end_line=node.end_line,
           start_byte=node.start_byte,
           end_byte=node.end_byte,
           source_code=node.text,
           source_hash=compute_source_hash(node.text),
           parent_id=node.parent_id,
       )
   ```
   The deferred import inside the function body is intentional: `discovery` imports `events` (which
   is fine — downstream can import upstream), but this function body uses a deferred import to
   avoid a module-level circular dependency during the transition.

   Once **W4** is complete (events split into bounded modules), the deferred import becomes a clean
   top-level import of only `NodeDiscoveredEvent` from `core.events.code_events` with no risk of
   cycles.

2. **Find every call site of `NodeDiscoveredEvent.from_cst_node`**:
   ```
   grep -rn "from_cst_node" src/
   ```
   For each result, change:
   ```python
   event = NodeDiscoveredEvent.from_cst_node(node)
   ```
   to:
   ```python
   from remora.core.code.discovery import node_to_event
   event = node_to_event(node)
   ```
   (If the file already imports from `remora.core.code.discovery`, just add `node_to_event` to the
   existing import line.)

3. **Edit `src/remora/core/events/events.py`**:
   - Delete the `TYPE_CHECKING` block (lines 21–23) that imported `CSTNode`.
   - Delete the `from_cst_node` classmethod from `NodeDiscoveredEvent` (lines 236–252).
   - Remove the `from __future__ import annotations` guard if it was only needed for the
     TYPE_CHECKING annotation. (Check if other annotations in the file need it — if `CSTNode`
     was the only forward ref, it can be removed.)

4. **Update `tach.toml`**: Remove `"remora.core.code.discovery"` from `remora.core.events.events`
   `depends_on`. After this change, `remora.core.events.events` should have `depends_on = []`
   (it only depends on `pydantic` and `structured_agents`, which are external packages Tach
   doesn't track).

5. Run `tach check`. The edge `core.events.events → core.code.discovery` must be gone.

**Acceptance:**
- `grep -n "from remora.core.code" src/remora/core/events/events.py` returns nothing.
- `grep -n "from_cst_node" src/remora/core/events/events.py` returns nothing.
- `tach check` passes.

---

### W4 — Decompose `core.events.events` into bounded modules

**Why this is the highest-impact workstream:** `core.events.events` has in-degree 29 — nearly
every module in the system imports it. This means no module can be understood in isolation because
developers must mentally load the entire event vocabulary to understand any part of the codebase.
Splitting into bounded event modules lets each subsystem import only the 2–5 events it actually
uses.

**Target file layout** (all under `src/remora/core/events/`):

| New file | Contents |
|---|---|
| `agent_events.py` | Agent lifecycle + proposal + chat + HITL events |
| `interaction_events.py` | Swarm/reactive events (messages, file, cursor, trigger) |
| `code_events.py` | Node lifecycle events |
| `kernel_events.py` | Re-exports from `structured_agents` |
| `events.py` | **Thin re-export barrel** pointing to all four above (backward compat) |

**Steps:**

1. **Create `src/remora/core/events/agent_events.py`**:
   ```python
   """Agent lifecycle, proposal, chat, and human-in-the-loop events."""
   from __future__ import annotations

   import time
   from typing import Any

   from pydantic import BaseModel, ConfigDict, Field, model_validator


   class _FrozenEvent(BaseModel):
       model_config = ConfigDict(frozen=True)


   class AgentStartEvent(_FrozenEvent): ...
   class AgentCompleteEvent(_FrozenEvent): ...
   class AgentErrorEvent(_FrozenEvent): ...
   class AgentEvent(_FrozenEvent): ...
   class HumanChatEvent(AgentEvent): ...
   class RewriteProposalEvent(AgentEvent): ...
   class RewriteAppliedEvent(AgentEvent): ...
   class RewriteRejectedEvent(AgentEvent): ...
   class HumanInputRequestEvent(_FrozenEvent): ...
   class HumanInputResponseEvent(_FrozenEvent): ...
   ```
   Copy the full class bodies verbatim from `events.py`. Do not summarise.

   `depends_on = []` in tach.toml — this file has no remora imports.

2. **Create `src/remora/core/events/interaction_events.py`**:
   ```python
   """Reactive swarm and editor-interaction events."""
   from __future__ import annotations

   import time
   from pydantic import BaseModel, ConfigDict, Field

   # Import _FrozenEvent from agent_events to share the base without a new module
   from remora.core.events.agent_events import _FrozenEvent


   class AgentMessageEvent(_FrozenEvent): ...
   class FileSavedEvent(_FrozenEvent): ...
   class ContentChangedEvent(_FrozenEvent): ...
   class CursorFocusEvent(_FrozenEvent): ...
   class ManualTriggerEvent(_FrozenEvent): ...
   ```
   Copy full class bodies verbatim.

   `depends_on = ["remora.core.events.agent_events"]` in tach.toml.

3. **Create `src/remora/core/events/code_events.py`**:
   ```python
   """Node lifecycle events (discovery, scaffold, removal)."""
   from __future__ import annotations

   import time
   from pydantic import BaseModel, ConfigDict, Field

   from remora.core.events.agent_events import _FrozenEvent


   class NodeDiscoveredEvent(_FrozenEvent): ...
   class ScaffoldRequestEvent(_FrozenEvent): ...
   class NodeRemovedEvent(_FrozenEvent): ...
   ```
   Copy full class bodies verbatim. `from_cst_node` was removed in **W3** so do not include it.

   `depends_on = ["remora.core.events.agent_events"]` in tach.toml.

4. **Create `src/remora/core/events/kernel_events.py`**:
   ```python
   """Re-exports of structured_agents kernel events."""
   from structured_agents.events import (
       KernelEndEvent,
       KernelStartEvent,
       ModelRequestEvent,
       ModelResponseEvent,
       ToolCallEvent,
       ToolResultEvent,
       TurnCompleteEvent,
   )

   __all__ = [
       "KernelEndEvent",
       "KernelStartEvent",
       "ModelRequestEvent",
       "ModelResponseEvent",
       "ToolCallEvent",
       "ToolResultEvent",
       "TurnCompleteEvent",
   ]
   ```
   `depends_on = []` in tach.toml (structured_agents is external).

5. **Rewrite `src/remora/core/events/events.py`** as a thin re-export barrel:
   ```python
   """Backward-compatible re-export barrel.

   Import from the specific submodules instead:
     remora.core.events.agent_events
     remora.core.events.interaction_events
     remora.core.events.code_events
     remora.core.events.kernel_events

   This barrel exists only to avoid breaking existing imports during the
   transition. It will be deprecated once all internal imports are updated.
   """
   from remora.core.events.agent_events import (
       AgentStartEvent, AgentCompleteEvent, AgentErrorEvent,
       AgentEvent, HumanChatEvent, RewriteProposalEvent,
       RewriteAppliedEvent, RewriteRejectedEvent,
       HumanInputRequestEvent, HumanInputResponseEvent,
   )
   from remora.core.events.interaction_events import (
       AgentMessageEvent, FileSavedEvent, ContentChangedEvent,
       CursorFocusEvent, ManualTriggerEvent,
   )
   from remora.core.events.code_events import (
       NodeDiscoveredEvent, ScaffoldRequestEvent, NodeRemovedEvent,
   )
   from remora.core.events.kernel_events import (
       KernelEndEvent, KernelStartEvent, ModelRequestEvent,
       ModelResponseEvent, ToolCallEvent, ToolResultEvent, TurnCompleteEvent,
   )

   CoreEvent = (
       AgentStartEvent | AgentCompleteEvent | AgentErrorEvent
       | AgentEvent | HumanChatEvent | RewriteProposalEvent
       | RewriteAppliedEvent | RewriteRejectedEvent
       | HumanInputRequestEvent | HumanInputResponseEvent
       | AgentMessageEvent | FileSavedEvent | ContentChangedEvent
       | CursorFocusEvent | ManualTriggerEvent
       | NodeDiscoveredEvent | ScaffoldRequestEvent | NodeRemovedEvent
       | KernelStartEvent | KernelEndEvent | ToolCallEvent | ToolResultEvent
       | ModelRequestEvent | ModelResponseEvent | TurnCompleteEvent
   )

   __all__ = [
       # (same __all__ as before)
   ]
   ```
   Update `depends_on` in tach.toml:
   ```toml
   [[modules]]
   path = "remora.core.events.events"
   depends_on = [
       "remora.core.events.agent_events",
       "remora.core.events.interaction_events",
       "remora.core.events.code_events",
       "remora.core.events.kernel_events",
   ]
   ```

6. **Update internal imports selectively.** The re-export barrel means nothing breaks. Now go
   through the 29 importing modules and switch them to narrow imports. Priority order (highest
   value first):

   For each file, run:
   ```
   grep -n "from remora.core.events.events import" src/remora/PACKAGE/SUBMODULE.py
   ```
   Look at which symbols are imported and switch to the appropriate bounded module:

   | Old import | New import |
   |---|---|
   | `AgentStartEvent, AgentCompleteEvent, AgentErrorEvent` | `from remora.core.events.agent_events import ...` |
   | `AgentEvent, HumanChatEvent, RewriteProposalEvent, ...` | `from remora.core.events.agent_events import ...` |
   | `AgentMessageEvent, FileSavedEvent, ContentChangedEvent, ...` | `from remora.core.events.interaction_events import ...` |
   | `NodeDiscoveredEvent, ScaffoldRequestEvent, NodeRemovedEvent` | `from remora.core.events.code_events import ...` |
   | `KernelStartEvent, ToolCallEvent, ...` | `from remora.core.events.kernel_events import ...` |

   Files to migrate (run grep to find all 29 and confirm):
   ```
   grep -rl "from remora.core.events.events import" src/
   ```
   Work through the list. For each file, update its `depends_on` entry in `tach.toml` to replace
   `"remora.core.events.events"` with the specific bounded module(s) it actually uses.

7. **Update `remora.core.events.__init__.py`** to re-export from the new bounded modules
   (same symbols as before, but sourced from the bounded files).

8. Run the full test suite. Fix any import errors.

9. Run `tach check`. The `remora.core.events.events` barrel's in-degree should now be ~4
   (one from each bounded module). All 29 former importers should now point to the specific
   bounded modules.

**Acceptance:**
- `tach check` passes.
- `grep -rl "from remora.core.events.events import" src/` returns only the barrel itself and
  any test files (no production modules).
- The four new bounded event modules exist and are importable independently.

---

### W5 — Break the LSP barrel/server/handlers cycle ✅ ALREADY DONE

**W0 diagnostic confirmed: no lsp.handlers → lsp barrel edges exist in the current graph.
No work needed here. This section is retained for historical reference only.**

**Background (historical):** Two cycles involved the `lsp` package:

**Cycle A:** `remora.lsp` (barrel) → `remora.lsp.server` → `remora.lsp.handlers.*` → `remora.lsp`
(barrel) → ...

The handlers import the `lsp` barrel to access `RemoraLanguageServer` type, but the barrel imports
the server, which imports the handlers.

**Cycle B:** Same path through `remora.lsp.notifications` → `remora.lsp` (barrel).

**Steps:**

1. **Identify what each handler imports from the barrel.** Run:
   ```
   grep -n "from remora.lsp import\|import remora.lsp$" src/remora/lsp/handlers/*.py src/remora/lsp/notifications.py
   ```
   Typically handlers import `RemoraLanguageServer` (the server class) to use as a type annotation
   or to call methods on the server object they receive.

2. **Move `RemoraLanguageServer` to `lsp.protocols` (or a new `lsp.types` module).** The
   handlers and notifications need the type, not the full server implementation. If
   `remora.lsp.protocols` already exists, check what it contains:
   ```
   cat src/remora/lsp/protocols.py
   ```
   Add a `ServerProtocol` (or use `RemoraLanguageServer` directly) that handlers can type-annotate
   against. The key is that this protocol/type file has no imports from `lsp.server` or the barrel.

3. **Update each handler file** to replace:
   ```python
   from remora.lsp import RemoraLanguageServer
   ```
   with:
   ```python
   from remora.lsp.protocols import RemoraLanguageServer  # or ServerProtocol
   ```

4. **Update `notifications.py`** similarly — replace any barrel imports with direct imports from
   `lsp.protocols` or specific sibling modules.

5. **Slim down `lsp/__init__.py`** (the barrel). Its job is to provide a convenient public API.
   It should NOT import from `lsp.server` directly if that creates a cycle. Instead:
   - Keep re-exports of `RemoraDB`, `LazyGraph`, `RewriteProposal`, `generate_id`.
   - Move `RemoraLanguageServer` to be imported from `lsp.server` only at module level in
     `__init__` (which is fine — barrel importing server is expected).
   - The cycle only exists because handlers also import the barrel. Once handlers use
     `lsp.protocols` instead, the cycle is broken.

6. Update `tach.toml` for each affected handler and `notifications`:
   - Replace `"remora.lsp"` in their `depends_on` with `"remora.lsp.protocols"`.

7. Run `tach check --circular`. The LSP cycles must no longer appear.

**Acceptance:**
- `tach check --circular` reports 0 cycles (or fewer than the W0 baseline, per the documented
  remaining SCCs).
- `python -m remora.lsp` starts without import errors.

---

### W6 — Decompose orchestration hotspots

This workstream reduces out-degree on the 4 modules doing too much. High out-degree means the
module is coordinating too many concerns; the fix is to extract use-case services and leave the
entry-point module as pure wiring/composition.

**Priority order:** tackle highest out-degree first.

#### W6a — Thin `remora.lsp.server` (out-degree 15 → target ≤ 8)

`lsp.server` currently imports: `lsp.db`, `core.config`, `lsp.notifications`, `lsp.graph`,
`core.agents.agent_node`, `core.code.discovery`, `core.events.events`, all 6 handler modules,
`lsp.models`, and `core.tools.grail`.

**The fix:** `lsp.server` should own only *wiring* — receiving requests and dispatching them. Move
protocol-specific logic into the handlers where it belongs.

Steps:
1. Audit `lsp.server` for any logic that belongs in a specific handler (e.g., code lens
   computation, document synchronization). Move it to the appropriate handler file.
2. Handler registration (the calls that register each handler with the server) should live in a
   `lsp.server_setup` module or in `lsp.__main__`, not in the server class body itself.
3. After moving, the server should only import: `lsp.db`, `lsp.graph`, `lsp.notifications`,
   `core.config`, `core.agents.agent_node`, and `runner.protocols`. The handler imports should
   be removed from the server and replaced by a registration pattern (handlers register themselves
   or are registered in setup code).
4. Update `tach.toml` for `remora.lsp.server` to reflect the narrowed `depends_on`.

#### W6b — Thin `remora.core.agents.execution` (out-degree 13 → target ≤ 8)

`core.agents.execution` currently coordinates: event_store, events, workspace, kernel_factory,
utils, code.discovery, agent_node, manifest, agent_context, cairn_bridge, subscriptions,
and tools.grail.

**The fix:** Extract a `core.agents.turn_context` module that assembles the context object
(`workspace_service`, `tool_list`, `subscription_snapshot`) needed for a single agent turn.
`execution.py` itself then only calls `turn_context.build(...)` and `kernel.run(...)`.

Steps:
1. Identify which imports in `execution.py` are used only to assemble context (not to execute).
2. Create `src/remora/core/agents/turn_context.py` with a `build_turn_context()` function that
   owns those imports and returns a structured context object.
3. `execution.py` imports only `turn_context.build_turn_context` and the kernel runner.
4. Update `tach.toml`.

#### W6c — Thin `remora.service.api` (out-degree 13 → target ≤ 8)

`service.api` currently imports: `ui.view`, `service.datastar`, `utils`, `ui.projector`,
`service.handlers`, `models`, `core.config`, `core.events.event_bus`, `core.events.subscriptions`,
`core.agents.cairn_bridge`, `core.code.projections`, `extensions`, `core.store.event_store`.

**The fix:** `service.api` is the route definition file. Route *handler logic* should live in
`service.handlers`. Move any business logic in `api.py` that isn't pure HTTP routing into
`service.handlers`. `api.py` should only: define routes, inject dependencies, and call handlers.

After the move, `api.py` should import: `service.handlers`, `core.config`, `core.events.event_bus`,
and `core.store.event_store` (for the dependency injection container). All domain logic (projections,
cairn_bridge, subscriptions) should be accessed through handler functions.

Steps:
1. Go through each route handler function in `service/api.py`. If it contains more than ~5 lines
   of logic, extract it to a named function in `service/handlers.py`.
2. The route in `api.py` becomes a 1–3 line wrapper that calls the handler.
3. Update `tach.toml`.

**Acceptance for W6:**
- All four hotspot modules have out-degree ≤ 8 as verified by a fresh Tach graph.
- `tach check` passes.
- The test suite passes.

---

### W7 — Import hygiene and CI architecture SLO gates

**Steps:**

1. **Barrel import audit.** Internal code (non-`__init__.py` files) must not import from top-level
   barrel packages where a specific submodule import is available. Run:
   ```
   grep -rn "from remora.core import\|from remora.lsp import\|from remora.runner import" src/remora/
   ```
   Exclude `__init__.py` files from results. For each hit, replace the barrel import with the
   concrete submodule import (e.g., `from remora.core import X` → `from remora.core.agents.X import X`).
   Update `tach.toml` to match.

2. **Add architecture SLO checks.** Add a script `scripts/check_arch_slo.py`:
   ```python
   """Verify architecture degree SLOs against the Tach module graph."""
   import sys
   import subprocess
   import json

   MAX_OUT_DEGREE = 8
   MAX_IN_DEGREE = 12

   # Run tach and parse output (adjust command for your tach version)
   result = subprocess.run(["tach", "show", "--json"], capture_output=True, text=True)
   graph = json.loads(result.stdout)

   violations = []
   for mod, deps in graph.items():
       out_degree = len(deps.get("depends_on", []))
       in_degree = len(deps.get("depended_on_by", []))
       if out_degree > MAX_OUT_DEGREE:
           violations.append(f"OUT-DEGREE: {mod} = {out_degree} (max {MAX_OUT_DEGREE})")
       if in_degree > MAX_IN_DEGREE:
           violations.append(f"IN-DEGREE:  {mod} = {in_degree} (max {MAX_IN_DEGREE})")

   if violations:
       print("Architecture SLO violations:")
       for v in violations:
           print(f"  {v}")
       sys.exit(1)
   else:
       print("Architecture SLOs: OK")
   ```

   Note: Tach's exact JSON output format may differ — verify with `tach show --help` and adjust
   the parsing accordingly.

3. **Add to CI / Makefile**:
   ```makefile
   .PHONY: check-arch-slo
   check-arch-slo:
       python scripts/check_arch_slo.py

   .PHONY: check
   check: check-arch check-arch-slo
   ```

4. **Generate a final architecture diagram** after all workstreams complete:
   ```
   tach show --mermaid > docs/architecture.mmd
   ```
   Or using graphviz if tach supports it. Commit this as a living architecture diagram updated
   in CI.

**Acceptance:**
- `make check` passes end-to-end.
- The architecture diagram in `docs/` reflects the clean 4-layer model.
- No internal module imports from barrel packages.

---

## Execution Order

```
W0 (diagnostic) ✅ DONE
  └── W1 (policy in tach.toml)
        ├── W2 (fix runner→lsp.models)
        │     └── W3 (fix events→discovery)
        │           └── W4 (decompose event hub)  ← highest value
        ├── [W5 SKIPPED — already resolved]
        ├── W6 (thin orchestration hotspots)
        └── W7 (import hygiene + CI SLOs)
```

W2 and the early steps of W6 can be done in parallel once W1 is in place.
W3 must precede W4. W7 is always last.

---

## Acceptance Criteria (full plan)

- [x] `tach check` passes with zero violations.
- [x] Module graph SCC analysis reports 0 cycles.
- [x] `runner` does not depend on `lsp` at any level.
- [x] Legacy compatibility event barrel (`core.events.events`) has been removed from production.
- [x] Four bounded event modules exist and are independently importable.
- [x] No targeted orchestration hotspot module has out-degree > 8.
- [x] `just check` (tach + SLO gate) is wired for CI/local checks.
- [x] All existing tests pass.
