# Bootstrap Refactoring Guide

**Derived from:** `CODE_REVIEW.md` (2026-03-08)
**Audience:** Junior developer implementing fixes independently
**Scope:** All issues, recommendations, structural improvements, and v3 conceptual alignment
**Test suite baseline:** 39 tests passing — all must continue to pass after each change

---

## Overview

This guide converts every finding in `CODE_REVIEW.md` into a concrete, step-by-step
implementation task. Work through the sections in order; later sections sometimes depend
on earlier ones.

For each change:
1. Read the relevant source file **before** editing it.
2. Make the change described.
3. Run the test suite: `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`
4. All 39+ bootstrap tests must still pass.

---

## Table of Contents

| Section | Priority | Description |
|---------|----------|-------------|
| [1. S1 — Rename private functions to public](#1-s1--rename-private-functions-to-public) | **Should Fix** | Drop underscore prefix from `_make_files_provider` and `_extract_workspace_tools` |
| [2. S2 — Eliminate double query in run_once](#2-s2--eliminate-double-query-in-run_once) | **Should Fix** | `run_once` and `run_for_file` each call `find_unassigned_*` twice |
| [3. S3 — BootstrapEvent type contract](#3-s3--bootstrapevent-type-contract-convert-dataclass--pydantic) | **Should Fix** | `BootstrapEvent` is a `@dataclass`; every other event is Pydantic — convert to match the convention |
| [4. N1 — Readable comprehension in _read_assigned_node_ids](#4-n1--readable-comprehension-in-_read_assigned_node_ids) | Nice to Fix | Replace optional-binding for-loop idiom with explicit if block |
| [5. N2 — Document flat listing in _make_files_provider](#5-n2--document-flat-listing-in-make_files_provider) | Nice to Fix | Add comment explaining that only root dir is listed |
| [6. N3 — Document UNION ALL duplicate behaviour](#6-n3--document-union-all-duplicate-behaviour) | Nice to Fix | Add docstring note to `graph_neighbors.pym` |
| [7. N4 — Eliminate double encode in seed_graph.py](#7-n4--eliminate-double-encode-in-seed_graphpy) | Nice to Fix | Encode source bytes once; reuse for hash and byte count |
| [8. N5 — coordinator.yaml aspirational comment](#8-n5--coordinatoryaml-aspirational-comment) | Nice to Fix | Explain that subscriptions here are never registered |
| [9. T1 — Test find_unassigned_nodes with file_path](#9-t1--test-find_unassigned_nodes-with-file_path) | Test Gap | Already exists — verify and document |
| [10. T2 — Test emit_agent_needed_events_for_nodes](#10-t2--test-emit_agent_needed_events_for_nodes) | Test Gap | Add missing test for the general API |
| [11. T3 — Execute tests for remaining 7 .pym tools](#11-t3--execute-tests-for-remaining-7-pym-tools) | Test Gap | Add real-function externals and assertions for each tool |
| [12. T4 — Test _extract_response final_message branch](#12-t4--test-_extract_response-final_message-branch) | Test Gap | Add test exercising the `final_message` code path |
| [13. T5 — Test _build_user_prompt](#13-t5--test-_build_user_prompt) | Test Gap | Add a direct unit test for the prompt builder |
| [14. T6 — Test _SKIP_DIRS exhaustiveness](#14-t6--test-_skip_dirs-exhaustiveness) | Test Gap | Assert known skip dirs are reliably excluded from seeding |
| [15. T7 — NodeStore graph method direct tests](#15-t7--nodestore-graph-method-direct-tests) | Test Gap | Note: covered transitively; no action needed |
| [16. Structural: Extract extract_response_text helper](#16-structural-extract-extract_response_text-helper) | Structural | Deduplicate identical response-extraction logic between v1 and bootstrap |
| [17. Structural: Document observer=None in TurnExecutor](#17-structural-document-observernone-in-turnexecutor) | Structural | Add comment explaining why bootstrap turns are unobserved |
| [18. Structural: Fix redundant path params in LSP wiring](#18-structural-fix-redundant-path-params-in-lsp-wiring) | Structural | Remove or document path params ignored when stores are injected |
| [19. Structural: Remove dead bootstrap/src/remora_bootstrap package](#19-structural-remove-dead-bootstrapsrcremora_bootstrap-package) | Structural | Delete archived exploration; it is dead code |
| [20. Structural: Consolidate DEFAULT_SCHEMA_YAML](#20-structural-consolidate-default_schema_yaml) | Structural | Make `bootstrap/agents/DEFAULT_SCHEMA.yaml` the single source of truth |
| [21. Structural: Add bootstrap/ directory README](#21-structural-add-bootstrap-directory-readme) | Structural | Clarify the role of the `bootstrap/` directory |
| [22. Structural: coordinator.yaml phase comment](#22-structural-coordinatoryaml-phase-comment) | Structural | Clarify in runner.py and coordinator.yaml that the Python coordinator is phase-1 scaffolding |
| [23. v3 Tension: Make node_types configurable in coordinator](#23-v3-tension-make-node_types-configurable-in-coordinator) | v3 Alignment | Hard-coded `{"file"}` leaks NodeStore convention into coordinator |
| [24. v3 Tension: Make _SKIP_DIRS configurable](#24-v3-tension-make-_skip_dirs-configurable) | v3 Alignment | Hard-coded Python project dirs in seed_graph.py |
| [25. v3 Tension: Frame bootstrap runner as phase-1 scaffolding](#25-v3-tension-frame-bootstrap-runner-as-phase-1-scaffolding) | v3 Alignment | Code comments + doc explaining the bridge nature |

---

## 1. S1 — Rename private functions to public

**Files to edit:**
- `src/remora/bootstrap/bedrock.py`
- `src/remora/bootstrap/__init__.py`
- `src/remora/bootstrap/activation.py`

**Problem:** `_make_files_provider` and `_extract_workspace_tools` use underscore-prefix
(Python convention: private) but are listed in `__all__` and imported from other modules.
This sends contradictory signals: something is simultaneously private and part of the public
API. Calling code in `activation.py` imports them with the private names, reinforcing the
confusion.

**What to do:**

### Step 1a — Rename in bedrock.py

Open `src/remora/bootstrap/bedrock.py`. You will find two functions defined with underscore
prefixes (around lines 94 and 115). Rename them by removing the underscore:

```python
# BEFORE
async def _make_files_provider(cairn_externals: CairnExternals) -> ...:
    ...

async def _extract_workspace_tools(cairn_externals: CairnExternals, tmp_dir: Path) -> Path:
    ...

__all__ = [
    "BootstrapEvent",
    "build_bedrock",
    "_make_files_provider",       # ← private name in public API
    "_extract_workspace_tools",   # ← private name in public API
]
```

```python
# AFTER
async def make_files_provider(cairn_externals: CairnExternals) -> ...:
    ...

async def extract_workspace_tools(cairn_externals: CairnExternals, tmp_dir: Path) -> Path:
    ...

__all__ = [
    "BootstrapEvent",
    "build_bedrock",
    "make_files_provider",
    "extract_workspace_tools",
]
```

### Step 1b — Update the import in activation.py

Open `src/remora/bootstrap/activation.py`. Find the import line:

```python
# BEFORE
from remora.bootstrap.bedrock import BootstrapEvent, _extract_workspace_tools, _make_files_provider, build_bedrock
```

```python
# AFTER
from remora.bootstrap.bedrock import BootstrapEvent, extract_workspace_tools, make_files_provider, build_bedrock
```

Then find the two call sites in `handle_agent_needed` and update them:

```python
# BEFORE
files_provider = await _make_files_provider(cairn_externals)
...
extracted_tools_dir = await _extract_workspace_tools(cairn_externals, Path(tmp_dir))
```

```python
# AFTER
files_provider = await make_files_provider(cairn_externals)
...
extracted_tools_dir = await extract_workspace_tools(cairn_externals, Path(tmp_dir))
```

### Step 1c — Update __init__.py

Open `src/remora/bootstrap/__init__.py`. Change the import and the `__all__` list:

```python
# BEFORE
from remora.bootstrap.bedrock import (
    BootstrapEvent,
    _extract_workspace_tools,
    _make_files_provider,
    build_bedrock,
)
...
__all__ = [
    ...
    "_make_files_provider",
    "_extract_workspace_tools",
    ...
]
```

```python
# AFTER
from remora.bootstrap.bedrock import (
    BootstrapEvent,
    extract_workspace_tools,
    make_files_provider,
    build_bedrock,
)
...
__all__ = [
    ...
    "make_files_provider",
    "extract_workspace_tools",
    ...
]
```

### Step 1d — Update any test that imports private names

Search for `_make_files_provider` and `_extract_workspace_tools` across all test files:

```bash
grep -r "_make_files_provider\|_extract_workspace_tools" tests/
```

For each occurrence, update the import and usage to use the new public name. The most likely
location is `tests/unit/bootstrap/test_activation.py`.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
```

All 39 tests must pass. If `test_activation.py` patches these by their old names you must
update the patch targets too (e.g., `mock.patch("remora.bootstrap.bedrock._make_files_provider")`
becomes `mock.patch("remora.bootstrap.bedrock.make_files_provider")`).

---

## 2. S2 — Eliminate double query in run_once

**Files to edit:**
- `src/remora/bootstrap/runner.py`

**Problem:** In `run_once`, the runner calls `find_unassigned_modules` to get a list of plans,
then calls `emit_agent_needed_events` which internally calls `find_unassigned_nodes` a second
time to find the same plans. Two graph reads for the same data per coordinator pass. The same
pattern exists in `run_for_file` / `emit_agent_needed_events_for_nodes`.

This also means there is a logical gap: the plans used to drive activation come from the
*first* read; the events emitted come from the *second* read. In theory these could diverge
under concurrent modification (though the `_activation_lock` prevents it within a single
runner instance).

**What to do:**

### Step 2a — Understand the current flow in runner.py

In `run_once` (around line 130):
```python
async def run_once(self) -> int:
    await self.initialize()
    async with self._activation_lock:
        plans = await find_unassigned_modules(self.event_store)  # read 1
        if not plans:
            return 0

        await emit_agent_needed_events(                          # read 2 happens inside here
            self.event_store,
            swarm_id=self.swarm_id,
            coordinator_id=self.coordinator_id,
        )
        return await self._activate_plans(plans, parallel=False)
```

### Step 2b — Refactor to use a shared _emit_events_for_plans helper

Add a new private helper method to `BootstrapRunner` that takes an already-computed list of
plans and emits events for them, without re-querying:

```python
async def _emit_events_for_plans(self, plans: list[AgentNeededPlan]) -> None:
    """Emit AgentNeededEvent to the store for each plan in the list."""
    for plan in plans:
        event = self._build_agent_needed_event(
            node_id=plan.node_id, agent_id=plan.agent_id
        )
        await self.event_store.append(self.swarm_id, event)
```

Add this method to `BootstrapRunner` near `_build_agent_needed_event`.

### Step 2c — Update run_once to use the helper

```python
# BEFORE
async def run_once(self) -> int:
    await self.initialize()
    async with self._activation_lock:
        plans = await find_unassigned_modules(self.event_store)
        if not plans:
            return 0

        await emit_agent_needed_events(
            self.event_store,
            swarm_id=self.swarm_id,
            coordinator_id=self.coordinator_id,
        )
        return await self._activate_plans(plans, parallel=False)
```

```python
# AFTER
async def run_once(self) -> int:
    await self.initialize()
    async with self._activation_lock:
        plans = await find_unassigned_modules(self.event_store)
        if not plans:
            return 0

        await self._emit_events_for_plans(plans)
        return await self._activate_plans(plans, parallel=False)
```

### Step 2d — Update run_for_file similarly

```python
# BEFORE
async def run_for_file(self, file_path: str) -> int:
    await self.initialize()
    async with self._activation_lock:
        plans = await find_unassigned_nodes(self.event_store, file_path=file_path)
        if not plans:
            return 0

        await emit_agent_needed_events_for_nodes(
            self.event_store,
            swarm_id=self.swarm_id,
            coordinator_id=self.coordinator_id,
            file_path=file_path,
        )
        return await self._activate_plans(plans, parallel=True)
```

```python
# AFTER
async def run_for_file(self, file_path: str) -> int:
    await self.initialize()
    async with self._activation_lock:
        plans = await find_unassigned_nodes(self.event_store, file_path=file_path)
        if not plans:
            return 0

        await self._emit_events_for_plans(plans)
        return await self._activate_plans(plans, parallel=True)
```

### Step 2e — Clean up unused imports in runner.py

After the refactor, `emit_agent_needed_events` and `emit_agent_needed_events_for_nodes`
are no longer called from runner.py. Remove them from the import:

```python
# BEFORE
from remora.bootstrap.coordinator import (
    AgentNeededPlan,
    emit_agent_needed_events,
    emit_agent_needed_events_for_nodes,
    find_unassigned_modules,
    find_unassigned_nodes,
)
```

```python
# AFTER
from remora.bootstrap.coordinator import (
    AgentNeededPlan,
    find_unassigned_modules,
    find_unassigned_nodes,
)
```

Note: `emit_agent_needed_events` and `emit_agent_needed_events_for_nodes` still exist in
`coordinator.py` and are still exported from there for external callers (e.g., tests or
other runners that want to emit events without activating). Do not delete them from
`coordinator.py`.

### Step 2f — Update test_runner.py

`test_runner.py` likely mocks `emit_agent_needed_events` at module level. After the refactor,
the runner calls `self._emit_events_for_plans` instead. You have two options:

**Option A** (simpler): Patch `BootstrapRunner._emit_events_for_plans` in the test.

**Option B**: Assert that `event_store.append` is called the right number of times.

Open `tests/unit/bootstrap/test_runner.py` and update any patches that target
`runner.emit_agent_needed_events` or `runner.emit_agent_needed_events_for_nodes` to instead
patch `BootstrapRunner._emit_events_for_plans` or assert on `event_store.append` calls.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_runner.py tests/unit/bootstrap/test_coordinator.py -v
```

---

## 3. S3 — BootstrapEvent type contract (convert @dataclass → Pydantic)

**Files to edit:**
- `src/remora/bootstrap/bedrock.py`

**Background — the code review's suggestion was wrong:**

The code review said: *"add `StructuredEvent` as base class"*. This is not possible.
`structured_agents.events.Event` (aliased as `StructuredEvent` in EventStore) is a
**Union type alias**, not a class:

```python
# structured_agents/events/__init__.py
Event = Union[KernelStartEvent, KernelEndEvent, ModelRequestEvent, ...]
```

You cannot inherit from a Union. Attempting `class BootstrapEvent(StructuredEvent)` is a
Python runtime error.

Similarly, `CoreEvent` in `remora.core.events` is also a Union type alias:
```python
CoreEvent = AgentStartEvent | AgentCompleteEvent | NodeDiscoveredEvent | ...
```

The `EventStore.append(event: StructuredEvent | CoreEvent)` type annotation is therefore
aspirational — it lists all *currently known* event types. The actual serializer handles
unknown types via duck typing:

```python
def _serialize_event(self, event):
    if hasattr(event, "model_dump"):   # Pydantic → model_dump()
        data = event.model_dump()
    elif is_dataclass(event):          # dataclass → asdict()
        data = asdict(event)
    elif hasattr(event, "__dict__"):   # fallback
        data = dict(vars(event))
```

`BootstrapEvent` currently goes through the `is_dataclass` branch. Runtime is correct.

**The real problem:** `BootstrapEvent` is the only event in the codebase that uses
`@dataclass`. Every other event — `NodeDiscoveredEvent`, `AgentStartEvent`, and all 20+
other events in `core/events/` — uses a Pydantic `BaseModel` with `frozen=True`. This
is the established project convention, and `BootstrapEvent` is inconsistent with it.

**What to do:**

Convert `BootstrapEvent` from `@dataclass` to a Pydantic `BaseModel`, matching the pattern
used by every other event. Do not import the private `_FrozenEvent` class from
`core.events.agent_events` — just apply the same pattern (`BaseModel` + `ConfigDict(frozen=True)`)
directly in `bedrock.py`.

### Step 3a — Replace the class definition in bedrock.py

```python
# BEFORE
from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from remora.core.agents.cairn_externals import CairnExternals


@dataclass
class BootstrapEvent:
    """Event envelope used by bootstrap event writes."""

    event_type: str
    node_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    from_agent: str | None = None
    to_agent: str | None = None
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)
```

```python
# AFTER
from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from remora.core.agents.cairn_externals import CairnExternals


class BootstrapEvent(BaseModel):
    """Event envelope used by bootstrap event writes.

    Uses the same Pydantic BaseModel + frozen convention as all other Remora
    events (NodeDiscoveredEvent, AgentStartEvent, etc.).

    NOTE: BootstrapEvent is intentionally not included in the CoreEvent union
    in remora.core.events — adding it there would create a layer violation
    (core importing from bootstrap). The EventStore serializer handles it via
    model_dump() since it is now a Pydantic model.
    """

    model_config = ConfigDict(frozen=True)

    event_type: str
    node_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    from_agent: str | None = None
    to_agent: str | None = None
    correlation_id: str | None = None
    tags: tuple[str, ...] = ()
    timestamp: float = Field(default_factory=time.time)
```

Remove `dataclass` and `field` from imports — they are no longer used in `bedrock.py`.

### Step 3b — Check for test code that uses dataclass-specific assertions

Open `tests/unit/bootstrap/test_bedrock.py`. Find any test that uses `dataclasses.asdict()`
or `isinstance(event, SomeDataclass)` on a `BootstrapEvent`. Update those to use
`event.model_dump()` instead (Pydantic equivalent of `asdict`).

Also search the rest of the test suite:
```bash
grep -r "BootstrapEvent\|asdict" tests/unit/bootstrap/ --include="*.py"
```

The existing test `test_event_write_appends_bootstrap_event` does:
```python
assert isinstance(emitted, BootstrapEvent)
assert emitted.event_type == "AgentNeededEvent"
assert emitted.from_agent == "agent-1"
```

These assertions all still work after the Pydantic conversion — `isinstance` still works
and attribute access is unchanged. No modification needed there.

### Step 3c — Verify EventStore serialization path

After the conversion, `BootstrapEvent` instances will have `model_dump()` method, so
`_serialize_event` will take the `model_dump()` branch instead of the `asdict` branch.
The serialized JSON will be identical in structure. No migration needed.

### Why NOT to add BootstrapEvent to CoreEvent

You might be tempted to add `BootstrapEvent` to the `CoreEvent` union in
`src/remora/core/events/__init__.py`. **Don't do this.** It would require importing
`BootstrapEvent` from `remora.bootstrap.bedrock` into `remora.core.events`, which is a
layer violation: `core` must not import from `bootstrap`. Verify this with:
```bash
devenv shell -- tach check
```

`BootstrapEvent` is a bootstrap-tier event. It serializes correctly via Pydantic's
`model_dump()` without being in the union.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
devenv shell -- tach check
```

---

## 4. N1 — Readable comprehension in _read_assigned_node_ids

**File to edit:**
- `src/remora/bootstrap/coordinator.py`

**Problem:** The set comprehension in `_read_assigned_node_ids` uses the Python "optional
binding via for-loop" idiom, which is correct but non-obvious to readers unfamiliar with it:

```python
return {
    str(attrs.get("assigned_node_id"))
    for row in agent_rows
    if isinstance(row, dict)
    for attrs in [row.get("attrs")]           # ← this is the unusual part
    if isinstance(attrs, dict) and attrs.get("assigned_node_id")
}
```

The `for attrs in [row.get("attrs")]` line creates a one-element list just to bind `attrs`
as a loop variable inside the comprehension. This is a valid Python technique to avoid a
separate `if` + assignment, but it is harder to read than an explicit block.

**What to do:**

Replace the comprehension with a plain set built in a for-loop:

```python
# BEFORE
async def _read_assigned_node_ids(event_store: EventStore) -> set[str]:
    agents_raw = await event_store.nodes.read_graph({"match": {"kind": "agent"}})
    agent_rows = json.loads(agents_raw) if agents_raw else []
    if not isinstance(agent_rows, list):
        return set()

    return {
        str(attrs.get("assigned_node_id"))
        for row in agent_rows
        if isinstance(row, dict)
        for attrs in [row.get("attrs")]
        if isinstance(attrs, dict) and attrs.get("assigned_node_id")
    }
```

```python
# AFTER
async def _read_assigned_node_ids(event_store: EventStore) -> set[str]:
    agents_raw = await event_store.nodes.read_graph({"match": {"kind": "agent"}})
    agent_rows = json.loads(agents_raw) if agents_raw else []
    if not isinstance(agent_rows, list):
        return set()

    assigned: set[str] = set()
    for row in agent_rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attrs")
        if isinstance(attrs, dict) and attrs.get("assigned_node_id"):
            assigned.add(str(attrs["assigned_node_id"]))
    return assigned
```

The logic is identical — only the style changes. No tests need to change.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_coordinator.py -v
```

---

## 5. N2 — Document flat listing in make_files_provider

**File to edit:**
- `src/remora/bootstrap/bedrock.py` (after S1 rename, this is `make_files_provider`)

**Problem:** `make_files_provider` (formerly `_make_files_provider`) only lists the root
directory of the agent's Cairn workspace. It calls `cairn_externals.list_dir(".")` which
returns immediate children only — no subdirectory recursion. This is fine for the current
bootstrap use case (agents only write to the workspace root), but if a future agent writes
structured files in subdirectories (e.g., `memory/index.md`), Grail won't see them via this
provider.

No code change is needed — just add a comment to document the limitation.

**What to do:**

Open `src/remora/bootstrap/bedrock.py`. Find `make_files_provider` (or `_make_files_provider`
if S1 hasn't been done yet). Add a comment above the function:

```python
# BEFORE
async def make_files_provider(cairn_externals: CairnExternals) -> Callable[[], Awaitable[dict[str, str | bytes]]]:
    """Create a workspace files provider for Grail runtime usage."""

    async def files_provider() -> dict[str, str | bytes]:
        try:
            paths = await cairn_externals.list_dir(".")
        except Exception:
            return {}
        ...
```

```python
# AFTER
async def make_files_provider(cairn_externals: CairnExternals) -> Callable[[], Awaitable[dict[str, str | bytes]]]:
    """Create a workspace files provider for Grail runtime usage.

    NOTE: Only lists the root of the workspace (list_dir(".") returns immediate
    children only — it is not recursive). Files in subdirectories are invisible
    to this provider. This is sufficient for the current bootstrap use case
    because all agents write their primary files (role.md, notes.md, schema.yaml)
    to the workspace root. If a future agent writes structured files into
    subdirectories (e.g., memory/index.md), extend this with recursive listing.
    """

    async def files_provider() -> dict[str, str | bytes]:
        try:
            paths = await cairn_externals.list_dir(".")
        except Exception:
            return {}
        ...
```

### Verification

No test change needed. Run the full suite to confirm no regressions:

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## 6. N3 — Document UNION ALL duplicate behaviour

**File to edit:**
- `bootstrap/tools/graph_neighbors.pym`

**Problem:** The NodeStore's "both" direction neighbor query uses `UNION ALL` which can
return the same neighbor node twice if two edges exist between the same pair of nodes (e.g.,
same from/to, different edge kinds). The `graph_neighbors.pym` tool returns whatever the
query returns, so callers (including LLM agents using this tool) may receive duplicate rows.

No code change is needed — just add a note to the tool's docstring.

**What to do:**

Open `bootstrap/tools/graph_neighbors.pym`. Locate the docstring. Add the duplicate-row
warning:

```
# BEFORE (example — your docstring may look different)
"""
Return the neighbors of a node in the graph.

Args:
    node_id: the ID of the node to find neighbors for
    direction: "in", "out", or "both" (default: "both")

Returns: JSON array of {id, kind, attrs, edge_kind} objects.
"""
```

```
# AFTER
"""
Return the neighbors of a node in the graph.

Args:
    node_id: the ID of the node to find neighbors for
    direction: "in", "out", or "both" (default: "both")

Returns: JSON array of {id, kind, attrs, edge_kind} objects.

NOTE: When direction="both", the underlying query uses UNION ALL. If node A
has two edges to node B with different edge kinds, both rows appear in the
result — the same neighbor node with different edge_kind values. Callers that
need unique neighbors by ID should deduplicate on the returned "id" field.
"""
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_system_tools.py -v
```

---

## 7. N4 — Eliminate double encode in seed_graph.py

**File to edit:**
- `src/remora/bootstrap/seed_graph.py`

**Problem:** In `seed_module_nodes_from_filesystem`, the source file content is encoded to
bytes twice — once for the SHA-1 hash and once to compute the byte count:

```python
source_hash = hashlib.sha1(source.encode("utf-8")).hexdigest()
line_count = source.count("\n") + 1
byte_count = len(source.encode("utf-8"))   # ← second encode of the same string
```

This wastes a small amount of CPU per file. The fix is to encode once and reuse.

**What to do:**

```python
# BEFORE
source = py_file.read_text(encoding="utf-8", errors="replace")
source_hash = hashlib.sha1(source.encode("utf-8")).hexdigest()
line_count = source.count("\n") + 1
byte_count = len(source.encode("utf-8"))
```

```python
# AFTER
source = py_file.read_text(encoding="utf-8", errors="replace")
source_bytes = source.encode("utf-8")
source_hash = hashlib.sha1(source_bytes).hexdigest()
line_count = source.count("\n") + 1
byte_count = len(source_bytes)
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py -v
```

---

## 8. N5 — coordinator.yaml aspirational comment

**File to edit:**
- `bootstrap/agents/coordinator.yaml`

**Problem:** `coordinator.yaml` defines event subscriptions (`AgentNeededEvent`,
`ToolSynthesizedEvent`) and a full LLM agent system prompt. But in the current codebase the
"coordinator" is the Python code in `coordinator.py` / `runner.py`, not an LLM agent. The
schema subscriptions in this YAML file are never registered because the coordinator is never
activated through the `handle_agent_needed` path. A developer reading this file would
reasonably expect these subscriptions to be active.

**What to do:**

Add a comment block at the top of `bootstrap/agents/coordinator.yaml` explaining the
current status and the intended future state:

```yaml
# BEFORE
version: "1"
name: coordinator

system: |
  You are the Remora bootstrap coordinator.
  ...
```

```yaml
# AFTER
# PHASE STATUS: ASPIRATIONAL — NOT YET ACTIVE
#
# This schema describes what the bootstrap coordinator will become in a future
# phase: a fully LLM-driven agent that responds to AgentNeededEvent and
# ToolSynthesizedEvent via this schema.
#
# In the current implementation (phase 1), coordinator logic runs as Python code
# in src/remora/bootstrap/coordinator.py and src/remora/bootstrap/runner.py.
# The coordinator node is seeded into the graph by seed_coordinator_node() but
# is never activated through handle_agent_needed(), so these subscriptions are
# never registered and the LLM system prompt is never used.
#
# When the LLM coordinator is implemented, remove this comment.
version: "1"
name: coordinator

system: |
  You are the Remora bootstrap coordinator.
  ...
```

Also add a corresponding comment in `src/remora/bootstrap/runner.py` in the `run_once`
method, briefly noting this design decision:

```python
async def run_once(self) -> int:
    """Run one coordinator pass and activate newly needed agents.

    Phase-1 note: The coordinator logic here is Python code, not an LLM agent.
    coordinator.yaml defines the future LLM coordinator schema but is not used
    yet. When the LLM coordinator is implemented, this method will be replaced
    by an event-driven activation of the coordinator agent.
    """
    ...
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_agent_schemas.py -v
```

The schema validator test should still pass — comments are stripped by YAML parsers.

---

## 9. T1 — Test find_unassigned_nodes with file_path

**Status:** Already implemented. The test exists at
`tests/unit/bootstrap/test_coordinator.py::test_find_unassigned_nodes_filters_by_file_and_assigned_targets`.

Review it to confirm it covers:
1. Filtering by `file_path` returns only nodes in that file.
2. After assigning one node, it disappears from results.
3. Nodes in other files are not included.

The existing test in the file already covers all three scenarios. No action needed beyond
confirming it passes:

```bash
devenv shell -- pytest tests/unit/bootstrap/test_coordinator.py::test_find_unassigned_nodes_filters_by_file_and_assigned_targets -v
```

---

## 10. T2 — Test emit_agent_needed_events_for_nodes

**File to add test to:**
- `tests/unit/bootstrap/test_coordinator.py`

**Problem:** `emit_agent_needed_events_for_nodes` is the general-purpose version of
`emit_agent_needed_events`. It accepts `file_path` and `node_types` filters. It is used
by `run_for_file` in the runner. It has no dedicated test.

**What to do:**

Add the following test to `tests/unit/bootstrap/test_coordinator.py`. It reuses the
existing `store` fixture (which seeds one `file` node at `src/app.py` and two `function`
nodes):

```python
from remora.bootstrap.coordinator import emit_agent_needed_events_for_nodes

@pytest.mark.asyncio
async def test_emit_agent_needed_events_for_nodes_filters_by_file(store: EventStore) -> None:
    """emit_agent_needed_events_for_nodes emits only events for the specified file."""
    count = await emit_agent_needed_events_for_nodes(
        store,
        swarm_id="swarm",
        coordinator_id="coordinator",
        file_path="src/app.py",
    )
    # src/app.py has 2 nodes: module:src/app.py and function:src/app.py:build_app
    assert count == 2

    replayed = [event async for event in store.replay("swarm")]
    needed = [e for e in replayed if e["event_type"] == "AgentNeededEvent"]
    assert len(needed) == 2
    node_ids = {e["payload"]["node_id"] for e in needed}
    assert node_ids == {"module:src/app.py", "function:src/app.py:build_app"}


@pytest.mark.asyncio
async def test_emit_agent_needed_events_for_nodes_filters_by_node_type(store: EventStore) -> None:
    """emit_agent_needed_events_for_nodes emits only events for the specified node types."""
    count = await emit_agent_needed_events_for_nodes(
        store,
        swarm_id="swarm",
        coordinator_id="coordinator",
        node_types={"function"},
    )
    # Two function nodes exist across both files
    assert count == 2

    replayed = [event async for event in store.replay("swarm")]
    needed = [e for e in replayed if e["event_type"] == "AgentNeededEvent"]
    node_ids = {e["payload"]["node_id"] for e in needed}
    # Only function nodes, not file/module nodes
    assert all("function:" in nid for nid in node_ids)
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_coordinator.py -v
```

All tests in this file should pass.

---

## 11. T3 — Execute tests for remaining 7 .pym tools

**File to add tests to:**
- `tests/unit/bootstrap/test_system_tools.py`

**Problem:** `test_system_tools.py` has full execution tests for 3 tools (`read_file`,
`graph_find_nodes`, `user_question`). The other 7 tools (`write_file`, `graph_node`,
`graph_neighbors`, `graph_add_node`, `graph_add_edge`, `read_recent_events`, `emit_event`)
are only checked to exist and compile — their runtime behaviour is untested.

**What to do:**

Read each `.pym` file first to understand what external it calls and with what arguments,
then add a corresponding test. Each test follows the same pattern as the existing ones:
real `async def` externals (not `AsyncMock`) that capture arguments or return canned values.

Add these tests to `tests/unit/bootstrap/test_system_tools.py`:

```python
@pytest.mark.asyncio
async def test_write_file_tool_calls_cairn_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "write_file.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _cairn_write(path: str, content: str) -> str:
        captured["path"] = path
        captured["content"] = content
        return "ok"

    result = await script.run(
        inputs={"path": "notes.md", "content": "hello world"},
        externals={"cairn_write": _cairn_write},
    )
    assert result == "ok"
    assert captured["path"] == "notes.md"
    assert captured["content"] == "hello world"


@pytest.mark.asyncio
async def test_graph_node_tool_calls_graph_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_node.pym", tmp_path / ".grail")
    node_data = {"id": "n1", "kind": "function", "attrs": {"name": "foo"}}
    captured: dict[str, object] = {}

    async def _graph_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps(node_data)

    result = await script.run(
        inputs={"node_id": "n1"},
        externals={"graph_read": _graph_read},
    )
    assert captured["selector"] == {"node": "n1"}
    payload = json.loads(result)
    assert payload["id"] == "n1"


@pytest.mark.asyncio
async def test_graph_neighbors_tool_calls_graph_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_neighbors.pym", tmp_path / ".grail")
    neighbors = [{"id": "n2", "kind": "function", "attrs": {}, "edge_kind": "calls"}]
    captured: dict[str, object] = {}

    async def _graph_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps(neighbors)

    result = await script.run(
        inputs={"node_id": "n1", "direction": "out"},
        externals={"graph_read": _graph_read},
    )
    assert "direction" in str(captured["selector"]) or "node_id" in str(captured["selector"])
    payload = json.loads(result)
    assert payload[0]["id"] == "n2"


@pytest.mark.asyncio
async def test_graph_add_node_tool_calls_graph_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_add_node.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_write(op: str, data: dict) -> str:
        captured["op"] = op
        captured["data"] = data
        return json.dumps({"id": "generated-uuid", "kind": "custom"})

    result = await script.run(
        inputs={"kind": "custom", "attrs": json.dumps({"label": "my-node"})},
        externals={"graph_write": _graph_write},
    )
    assert captured["op"] == "add_node"
    assert captured["data"]["kind"] == "custom"
    payload = json.loads(result)
    assert "id" in payload


@pytest.mark.asyncio
async def test_graph_add_edge_tool_calls_graph_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "graph_add_edge.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _graph_write(op: str, data: dict) -> str:
        captured["op"] = op
        captured["data"] = data
        return json.dumps({"ok": True})

    result = await script.run(
        inputs={"from_id": "n1", "to_id": "n2", "kind": "calls"},
        externals={"graph_write": _graph_write},
    )
    assert captured["op"] == "add_edge"
    assert captured["data"]["from"] == "n1"
    assert captured["data"]["to"] == "n2"
    assert captured["data"]["kind"] == "calls"


@pytest.mark.asyncio
async def test_read_recent_events_tool_calls_event_read(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "read_recent_events.pym", tmp_path / ".grail")
    events_data = [{"event_type": "AgentNeededEvent", "payload": {}}]
    captured: dict[str, object] = {}

    async def _event_read(selector: dict) -> str:
        captured["selector"] = selector
        return json.dumps(events_data)

    result = await script.run(
        inputs={"node_id": "module:src/app.py", "limit": 5},
        externals={"event_read": _event_read},
    )
    assert captured["selector"]["node_id"] == "module:src/app.py"
    assert captured["selector"]["limit"] == 5
    payload = json.loads(result)
    assert payload[0]["event_type"] == "AgentNeededEvent"


@pytest.mark.asyncio
async def test_emit_event_tool_calls_event_write(tmp_path: Path) -> None:
    script = _load_tool(TOOLS_DIR / "emit_event.pym", tmp_path / ".grail")
    captured: dict[str, object] = {}

    async def _event_write(event_type: str, payload: dict) -> str:
        captured["event_type"] = event_type
        captured["payload"] = payload
        return json.dumps({"event_id": 7})

    result = await script.run(
        inputs={
            "event_type": "CustomEvent",
            "payload": json.dumps({"key": "value"}),
        },
        externals={"event_write": _event_write},
    )
    assert captured["event_type"] == "CustomEvent"
    assert captured["payload"]["key"] == "value"
    assert json.loads(result)["event_id"] == 7
```

**Important:** If the `.pym` tool inputs don't match these exactly (e.g., `from_id` might
be `from`), open the actual `.pym` file and read the `Input(...)` declarations to see the
correct parameter names. Adjust the test `inputs={}` dict accordingly.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_system_tools.py -v
```

---

## 12. T4 — Test _extract_response final_message branch

**File to add test to:**
- `tests/unit/bootstrap/test_turn_executor.py`

**Problem:** `TurnExecutor._extract_response` has three code paths:
1. `result.final_message` exists and has `.content` → return `message.content`
2. `result.content` exists → return `result.content`
3. Fallback → `str(result)`

The existing `FakeKernel` returns `SimpleNamespace(final_message=None, content="DONE")`,
which exercises path 2. Path 1 (the `final_message` branch) is not exercised.

**What to do:**

Add a direct test for `_extract_response` as a static method. No executor setup needed:

```python
from types import SimpleNamespace
from remora.bootstrap.turn_executor import TurnExecutor


def test_extract_response_final_message_branch() -> None:
    """Uses result.final_message.content when present."""
    message = SimpleNamespace(content="The model said this.")
    result = SimpleNamespace(final_message=message, content="ignored")
    assert TurnExecutor._extract_response(result) == "The model said this."


def test_extract_response_content_branch() -> None:
    """Falls back to result.content when final_message is None."""
    result = SimpleNamespace(final_message=None, content="direct content")
    assert TurnExecutor._extract_response(result) == "direct content"


def test_extract_response_fallback_branch() -> None:
    """Falls back to str(result) when neither branch is available."""

    class NoContent:
        def __str__(self) -> str:
            return "stringified"

    assert TurnExecutor._extract_response(NoContent()) == "stringified"


def test_extract_response_final_message_without_content() -> None:
    """Falls back to str(result) when final_message exists but has no content."""
    message = SimpleNamespace(content=None)
    result = SimpleNamespace(final_message=message, content="fallback")

    # final_message exists but content is falsy → falls through to str(result)
    # Note: the current implementation falls through to str(result) from the
    # final_message branch when content is falsy. Verify this is the expected
    # behaviour before writing your assertion:
    response = TurnExecutor._extract_response(result)
    assert response == str(result)  # adjust if behaviour differs
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_turn_executor.py -v
```

---

## 13. T5 — Test _build_user_prompt

**File to add test to:**
- `tests/unit/bootstrap/test_turn_executor.py`

**Problem:** `_build_user_prompt` is a simple method but is untested. It determines what
user-turn text the LLM sees as its activation instruction.

**What to do:**

Add these tests. You can call `_build_user_prompt` directly via a minimal `TurnExecutor`
instance (or via the instance method on a real executor):

```python
from unittest.mock import MagicMock, AsyncMock
from remora.bootstrap.turn_executor import TurnExecutor


def _make_executor(**kwargs) -> TurnExecutor:
    """Create a TurnExecutor with sensible test defaults."""
    defaults = dict(
        agent_id="agent-test",
        cairn_externals=AsyncMock(),
        tools=[],
        node_attrs={},
        config=MagicMock(),
        system_agents_dir=None,
    )
    defaults.update(kwargs)
    return TurnExecutor(**defaults)


def test_build_user_prompt_with_no_event() -> None:
    executor = _make_executor()
    prompt = executor._build_user_prompt(None)
    assert prompt == "Begin your turn."


def test_build_user_prompt_with_event_type_only() -> None:
    from types import SimpleNamespace
    event = SimpleNamespace(event_type="AgentNeededEvent", node_id=None)
    executor = _make_executor()
    prompt = executor._build_user_prompt(event)
    assert "AgentNeededEvent" in prompt
    assert "Node:" not in prompt


def test_build_user_prompt_includes_node_id() -> None:
    from types import SimpleNamespace
    event = SimpleNamespace(event_type="AgentNeededEvent", node_id="module:src/app.py")
    executor = _make_executor()
    prompt = executor._build_user_prompt(event)
    assert "AgentNeededEvent" in prompt
    assert "module:src/app.py" in prompt
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_turn_executor.py -v
```

---

## 14. T6 — Test _SKIP_DIRS exhaustiveness

**File to add test to:**
- `tests/unit/bootstrap/test_seed_graph.py`

**Problem:** `seed_module_nodes_from_filesystem` skips directories listed in `_SKIP_DIRS`
(`{".venv", ".devenv", "__pycache__", "dist", "build", ".git"}`). The existing tests confirm
that `.venv` is skipped, but don't systematically verify all members of the set. Adding a
test that creates a file inside each skip dir and confirms zero nodes are seeded provides
a regression guard.

**What to do:**

Add this parametrized test to `tests/unit/bootstrap/test_seed_graph.py`:

```python
import pytest
from pathlib import Path
from remora.bootstrap.seed_graph import seed_module_nodes_from_filesystem
from remora.core.code.projections import NodeProjection
from remora.core.store.event_store import EventStore

SKIP_DIRS = [".venv", ".devenv", "__pycache__", "dist", "build", ".git"]


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_dir", SKIP_DIRS)
async def test_skip_dirs_are_excluded(tmp_path: Path, skip_dir: str) -> None:
    """Files inside skip directories must not be seeded as module nodes."""
    # Create a Python file inside the skip directory
    skip_path = tmp_path / skip_dir
    skip_path.mkdir()
    (skip_path / "module_that_should_be_skipped.py").write_text(
        "x = 1\n", encoding="utf-8"
    )
    # Also create a legitimate file at root to confirm seeding works at all
    (tmp_path / "real_module.py").write_text("y = 2\n", encoding="utf-8")

    db_path = tmp_path / "events.db"
    event_store = EventStore(db_path, projection=NodeProjection())
    await event_store.initialize()
    try:
        count = await seed_module_nodes_from_filesystem(
            event_store, tmp_path, swarm_id="swarm"
        )
        # Only the real_module.py should be seeded — not the skip dir file
        assert count == 1, (
            f"Expected 1 node (real_module.py) but got {count}. "
            f"Files in '{skip_dir}/' should be excluded."
        )
    finally:
        await event_store.close()
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py -v
```

---

## 15. T7 — NodeStore graph method direct tests

**Status: No action needed.**

The review notes that `NodeStore.read_graph` and `NodeStore.write_graph` graph methods are
not directly tested but are covered transitively through:
- `test_coordinator.py` — which exercises `read_graph({"match": {"kind": "agent"}})` via
  `find_unassigned_modules` / `_read_assigned_node_ids`
- `test_bootstrap_loop.py` — the integration test exercises `write_graph("add_node")` and
  `write_graph("add_edge")` via the full activation path

The transitive coverage is sufficient for a module that serves as an infrastructure adapter.
Direct unit tests would either duplicate the integration test logic or test the SQLite adapter
in isolation (which is already tested within NodeStore's own test suite, if it has one).

No action needed here. Move on to the structural issues.

---

## 16. Structural: Extract extract_response_text helper

**Files to edit:**
- `src/remora/core/agents/kernel_factory.py` (add the helper here)
- `src/remora/bootstrap/turn_executor.py` (use the helper)
- The v1 agent execution path that contains the same logic (find it as described below)

**Problem:** `TurnExecutor._extract_response` in bootstrap and the response-extraction block
in the v1 `execute_agent_turn` function contain identical code:

```python
# Both have this exact logic:
if hasattr(result, "final_message") and result.final_message:
    msg = result.final_message
    if hasattr(msg, "content") and msg.content:
        return msg.content
    return str(result)
if hasattr(result, "content") and result.content:
    return result.content
return str(result)
```

This duplication means a bug fix or behaviour change must be applied in two places. The
correct fix is to extract this into a shared function.

**What to do:**

### Step 16a — Find the v1 extract_response location

Search for the v1 call site:
```bash
grep -rn "final_message" src/remora/ --include="*.py" | grep -v bootstrap | grep -v test
```

This will show you the file and line where the identical logic exists in the v1 path.
Common location: `src/remora/runner/agent_runner.py` or a similar agent execution module.

### Step 16b — Add the shared helper to kernel_factory.py

Open `src/remora/core/agents/kernel_factory.py`. Add the following function **at the bottom
of the file**, before `__all__`:

```python
def extract_response_text(result: Any) -> str:
    """Extract text from a kernel run result.

    Handles the three result shapes returned by structured_agents AgentKernel:
    1. result.final_message.content  — preferred; carries the final model message
    2. result.content                — fallback for simpler result shapes
    3. str(result)                   — last resort
    """
    if hasattr(result, "final_message") and result.final_message:
        message = result.final_message
        if hasattr(message, "content") and message.content:
            return message.content
        return str(result)

    if hasattr(result, "content") and result.content:
        return result.content

    return str(result)
```

Update `__all__` in `kernel_factory.py`:
```python
__all__ = ["create_kernel", "extract_response_text"]
```

### Step 16c — Replace _extract_response in TurnExecutor

Open `src/remora/bootstrap/turn_executor.py`. Add the import at the top:

```python
from remora.core.agents.kernel_factory import create_kernel, extract_response_text
```

Delete the `_extract_response` static method from `TurnExecutor`:

```python
# DELETE THIS:
@staticmethod
def _extract_response(result: Any) -> str:
    if hasattr(result, "final_message") and result.final_message:
        message = result.final_message
        if hasattr(message, "content") and message.content:
            return message.content
        return str(result)

    if hasattr(result, "content") and result.content:
        return result.content

    return str(result)
```

Update the call site in `TurnExecutor.run`:

```python
# BEFORE
return TurnResult(
    response_text=self._extract_response(result),
    context_values=context_values,
)
```

```python
# AFTER
return TurnResult(
    response_text=extract_response_text(result),
    context_values=context_values,
)
```

### Step 16d — Replace the v1 extract_response block

Open the v1 file you found in step 16a. Find the identical code block. Replace it with a
call to `extract_response_text`, importing it from `remora.core.agents.kernel_factory`.

### Step 16e — Update tests

If `test_turn_executor.py` tested `TurnExecutor._extract_response` directly (from T4 above),
update those tests to instead test `extract_response_text` from `kernel_factory`:

```python
from remora.core.agents.kernel_factory import extract_response_text

def test_extract_response_final_message_branch() -> None:
    message = SimpleNamespace(content="The model said this.")
    result = SimpleNamespace(final_message=message)
    assert extract_response_text(result) == "The model said this."
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ tests/unit/runner/ -q
```

Run tach to confirm no new dependency violations:
```bash
devenv shell -- tach check
```

`remora.bootstrap.turn_executor` already imports from `remora.core.agents.kernel_factory`
so this does not introduce a new layer violation.

---

## 17. Structural: Document observer=None in TurnExecutor

**File to edit:**
- `src/remora/bootstrap/turn_executor.py`

**Problem:** In `TurnExecutor.run`, the kernel is created with `observer=None`:

```python
kernel = create_kernel(
    ...,
    observer=None,  # ← this is intentional, not an oversight
    client=self._client,
)
```

In the v1 agent execution path, `observer` is set to a `_CompositeObserver` that records
every kernel event (tool calls, model responses, errors) to the EventStore. Bootstrap
intentionally passes `None` — bootstrap LLM activations leave no per-turn trace in the
event store. The only record is the `AgentNeededEvent` and `ToolSynthesizedEvent` that
surround the turn, not the model's internal reasoning.

A future developer might see `observer=None` and think it's a missing feature rather than
a deliberate design decision.

**What to do:**

Add a comment at the `observer=None` line explaining the decision:

```python
kernel = create_kernel(
    model_name=self._config.model_default,
    base_url=self._config.model_base_url,
    api_key=self._config.model_api_key or "EMPTY",
    timeout=self._config.timeout_s,
    tools=active_tools,
    # Bootstrap turns are intentionally unobserved. Unlike v1 agent turns,
    # bootstrap activations are setup-time operations; their LLM reasoning
    # and tool call sequences are not recorded to the EventStore. The
    # surrounding AgentNeededEvent and ToolSynthesizedEvent provide the
    # observable record of what bootstrap accomplished. To add observability,
    # pass a CompositeObserver instance here.
    observer=None,
    client=self._client,
)
```

No code change — comment only. No tests need to change.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_turn_executor.py -q
```

---

## 18. Structural: Fix redundant path params in LSP wiring

**File to edit:**
- The file that creates `BootstrapRunner` during LSP startup (search for `BootstrapRunner(`)

**Problem:** When `BootstrapRunner` is created in the LSP startup with pre-built stores
injected, the path parameters (`event_store_path`, `subscriptions_path`) are also passed.
But when a store is injected, the runner sets `_owns_<store> = False` and never creates its
own store — so the paths are computed and stored but never used:

```python
bootstrap_runner = BootstrapRunner(
    config,
    project_root=runtime_paths.project_root,
    bootstrap_root=runtime_paths.bootstrap_root,
    event_store_path=runtime_paths.event_store_path,      # ← computed but ignored
    subscriptions_path=runtime_paths.subscriptions_path,  # ← computed but ignored
    event_store=event_store,          # ← used; makes event_store_path irrelevant
    subscriptions=subscriptions,      # ← used; makes subscriptions_path irrelevant
    workspace_service=cairn_service,
)
```

**What to do:**

### Option A (Preferred) — Remove the redundant paths

Open the LSP startup file. Remove `event_store_path` and `subscriptions_path` from the
`BootstrapRunner(...)` call:

```python
bootstrap_runner = BootstrapRunner(
    config,
    project_root=runtime_paths.project_root,
    bootstrap_root=runtime_paths.bootstrap_root,
    event_store=event_store,
    subscriptions=subscriptions,
    workspace_service=cairn_service,
)
```

This is cleaner — when stores are injected, their paths are irrelevant.

### Option B — Document the behaviour in BootstrapRunner.__init__

If removing the paths causes tests to fail (because tests assert they're passed), add a
docstring note to `BootstrapRunner.__init__` instead:

```python
def __init__(
    self,
    config: Config,
    *,
    ...
    event_store_path: Path | None = None,
    subscriptions_path: Path | None = None,
    ...
    event_store: EventStore | None = None,
    subscriptions: SubscriptionRegistry | None = None,
    ...
) -> None:
    """
    ...
    Note: When `event_store` or `subscriptions` are provided (injected), the
    corresponding `event_store_path` / `subscriptions_path` parameters are
    stored but not used — the runner does not create its own stores. The path
    parameters are only relevant when the runner creates stores itself (i.e.,
    when the store parameters are None).
    """
```

Prefer Option A as it removes the misleading parameters from call sites.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_runner.py -v
```

Also check that the LSP starts correctly (if you have a way to smoke-test the LSP startup).

---

## 19. Structural: Remove dead bootstrap/src/remora_bootstrap package

**Directory to delete:**
- `bootstrap/src/remora_bootstrap/` (entire directory tree)

**Problem:** A separate Python package exists at `bootstrap/src/remora_bootstrap/` containing
`primitives.py`, `runtime.py`, `bootstrap.py`, `contracts.py`, `registry.py`, and subpackages.
This appears to be an earlier exploration/prototype. Nothing in the current codebase imports
from it. It is dead code.

The hazard: a developer exploring the codebase encounters this package and spends time
wondering about its relationship to `src/remora/bootstrap/`. The presence of both creates
cognitive overhead and ambiguity about which is authoritative.

**What to do:**

### Step 19a — Confirm nothing imports from it

```bash
grep -r "remora_bootstrap" src/ tests/ --include="*.py"
```

This must return **zero results**. If anything imports from `remora_bootstrap`, do not
delete it until those imports are updated.

### Step 19b — Confirm it is not referenced in configuration files

```bash
grep -r "remora_bootstrap" pyproject.toml tach.toml setup.cfg
```

Again, must return zero results.

### Step 19c — Delete the directory

```bash
rm -rf bootstrap/src/remora_bootstrap/
```

If `bootstrap/src/` becomes empty after the deletion, remove it too:
```bash
rmdir bootstrap/src/ 2>/dev/null || true
```

### Step 19d — Verify no test or import broke

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
devenv shell -- tach check
```

### Verification

Both commands must pass with no new failures or violations.

---

## 20. Structural: Consolidate DEFAULT_SCHEMA_YAML

**Files involved:**
- `src/remora/bootstrap/schema_loader.py` (contains the string constant)
- `bootstrap/agents/DEFAULT_SCHEMA.yaml` (contains the file version)

**Problem:** The default bootstrap schema exists in two places that must be manually kept
in sync:
1. `schema_loader.py` — as `DEFAULT_SCHEMA_YAML` string constant, used when an agent's
   workspace has no `schema.yaml`
2. `bootstrap/agents/DEFAULT_SCHEMA.yaml` — as a file, validated by the agent schema test

If they diverge, new agents get different behaviour depending on whether their workspace was
ever written (falls through to the constant) vs. an agent that somehow got an explicit default
installed (reads the file). The file should be the single source of truth.

**What to do:**

### Step 20a — Update load_schema to read the default from the filesystem

Open `src/remora/bootstrap/schema_loader.py`. Update `load_schema` to use the filesystem
default when `system_agents_dir` is available:

```python
# BEFORE
async def load_schema(
    cairn_externals: CairnExternals,
    *,
    system_agents_dir: Path | None = None,
) -> TurnSchema:
    """Load schema.yaml from the agent's Cairn workspace."""
    content = await cairn_externals.read_file("schema.yaml")

    if not content:
        return TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))
    ...
```

```python
# AFTER
async def load_schema(
    cairn_externals: CairnExternals,
    *,
    system_agents_dir: Path | None = None,
) -> TurnSchema:
    """Load schema.yaml from the agent's Cairn workspace.

    If the agent's workspace has no schema.yaml, the default schema is loaded
    from bootstrap/agents/DEFAULT_SCHEMA.yaml (via system_agents_dir). The
    DEFAULT_SCHEMA_YAML string constant is a last-resort fallback for contexts
    where system_agents_dir is not available (e.g., tests without a filesystem).
    """
    content = await cairn_externals.read_file("schema.yaml")

    if not content:
        # Prefer loading default from filesystem — single source of truth.
        if system_agents_dir is not None:
            default_path = system_agents_dir / "DEFAULT_SCHEMA.yaml"
            if default_path.exists():
                return TurnSchema.model_validate(
                    _load_yaml(default_path.read_text(encoding="utf-8"))
                )
        # Fallback to embedded constant for environments without a bootstrap root.
        return TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))
    ...
```

### Step 20b — Keep DEFAULT_SCHEMA_YAML as a documented fallback

Do NOT remove `DEFAULT_SCHEMA_YAML` from `schema_loader.py`. It serves as the last-resort
fallback for:
- Tests that don't provide `system_agents_dir`
- Environments where the bootstrap files are not installed

Add a comment to the constant explaining its role:

```python
# Fallback default schema used when:
#   (a) The agent workspace has no schema.yaml, AND
#   (b) system_agents_dir is not provided or DEFAULT_SCHEMA.yaml does not exist.
# The authoritative default is bootstrap/agents/DEFAULT_SCHEMA.yaml. If you
# change the default schema, update that file; this constant will be overridden
# whenever system_agents_dir is available.
DEFAULT_SCHEMA_YAML = """
...
""".strip()
```

### Step 20c — Add a test asserting they match

Add a test in `tests/unit/bootstrap/test_schema_loader.py` that reads both and asserts
they parse to equivalent `TurnSchema` objects:

```python
from pathlib import Path
from remora.bootstrap.schema_loader import DEFAULT_SCHEMA_YAML, TurnSchema, _load_yaml

def test_default_schema_yaml_matches_file() -> None:
    """The embedded constant and the file must represent the same schema."""
    agents_dir = Path("bootstrap/agents")
    default_file = agents_dir / "DEFAULT_SCHEMA.yaml"
    assert default_file.exists(), "bootstrap/agents/DEFAULT_SCHEMA.yaml must exist"

    from_constant = TurnSchema.model_validate(_load_yaml(DEFAULT_SCHEMA_YAML))
    from_file = TurnSchema.model_validate(
        _load_yaml(default_file.read_text(encoding="utf-8"))
    )
    assert from_constant == from_file, (
        "DEFAULT_SCHEMA_YAML constant and bootstrap/agents/DEFAULT_SCHEMA.yaml "
        "have diverged. Update one to match the other."
    )
```

This test will fail if someone edits one but not the other, catching drift early.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_agent_schemas.py -v
```

---

## 21. Structural: Add bootstrap/ directory README

**File to create:**
- `bootstrap/README.md`

**Problem:** The `bootstrap/` directory contains both runtime data files (`tools/*.pym`,
`agents/*.yaml`) and the now-removed dead package (`src/remora_bootstrap/`). A new developer
exploring the codebase would be confused about:
- What `bootstrap/` is vs. `src/remora/bootstrap/`
- Whether `bootstrap/tools/*.pym` and `bootstrap/agents/*.yaml` are code or config
- Whether they need to be edited or are auto-generated

**What to do:**

Create `bootstrap/README.md` with the following content (adjust paths if they differ):

```markdown
# bootstrap/ — Runtime Data for the Bootstrap System

This directory contains **runtime data files** used by the bootstrap system at runtime.
These are not Python source code — they are configuration and script files read by the
bootstrap runtime from `src/remora/bootstrap/`.

## Contents

### tools/ — Grail tool scripts (.pym files)

These are Grail DSL scripts that define the "bedrock" tools available to bootstrap agents.
Each file exposes one tool to the LLM via the Grail runtime:

| File | Tool name | What it does |
|------|-----------|--------------|
| `read_file.pym` | `read_file` | Read a file from the agent's Cairn workspace |
| `write_file.pym` | `write_file` | Write a file to the agent's Cairn workspace |
| `graph_node.pym` | `graph_node` | Read a single node from the graph |
| `graph_neighbors.pym` | `graph_neighbors` | Read neighbors of a node |
| `graph_find_nodes.pym` | `graph_find_nodes` | Find nodes matching a kind/attrs filter |
| `graph_add_node.pym` | `graph_add_node` | Add a new node to the graph |
| `graph_add_edge.pym` | `graph_add_edge` | Add an edge between two graph nodes |
| `read_recent_events.pym` | `read_recent_events` | Read recent events for a node |
| `emit_event.pym` | `emit_event` | Emit an event to the event bus |
| `user_question.pym` | `user_question` | Request human input |

These tools are loaded by `discover_grail_tools()` during `handle_agent_needed()`.
They call into the "bedrock" external functions defined in `src/remora/bootstrap/bedrock.py`.

### agents/ — Agent schema files (.yaml files)

These define LLM agent "schemas" — the system prompt, context pipeline, available tools,
and subscriptions for a category of bootstrap agent:

| File | Description |
|------|-------------|
| `DEFAULT_SCHEMA.yaml` | Fallback schema for new agents with empty workspaces. Instructs the agent to write role.md, notes.md, schema.yaml. |
| `base_code_agent.yaml` | Schema for agents assigned to analyse code nodes. Uses context pipeline to load role.md, notes.md, and the source file. |
| `coordinator.yaml` | **Aspirational.** Defines the future LLM coordinator. Currently, coordinator logic runs as Python code in `src/remora/bootstrap/runner.py`. |

An agent's **workspace-resident** `schema.yaml` (stored in the Cairn VFS) overrides these
system defaults. Agents write their own schema during their first activation.

## Relationship to src/remora/bootstrap/

`src/remora/bootstrap/` is the Python implementation of the bootstrap system.
`bootstrap/` (this directory) provides the data files that the Python code reads at runtime.

Think of it this way:
- `src/remora/bootstrap/` = the engine
- `bootstrap/` = the engine's fuel
```

### Verification

No code change — documentation only. Confirm it exists:

```bash
test -f bootstrap/README.md && echo "OK"
```

---

## 22. Structural: coordinator.yaml phase comment

This was addressed as part of **Section 8 (N5)**. Ensure you have:

1. Added the `# PHASE STATUS: ASPIRATIONAL` comment block at the top of
   `bootstrap/agents/coordinator.yaml`.
2. Added the phase-1 note to the `BootstrapRunner.run_once` docstring in
   `src/remora/bootstrap/runner.py`.

No additional work needed here.

---

---

## v3 Conceptual Alignment Tensions

The following three sections address tensions between the current implementation and the
v3 philosophy: *"specify the substrate (cairn workspace, graph, event bus), let structure
emerge from bootstrapping. Do NOT pre-specify node kinds, edge kinds, protocol state
machines, or memory models."*

These are not bugs. They are pragmatic decisions made for a working phase-1 system. The
goal of these sections is to either make them configurable (removing the hard-coded
assumption) or explicitly frame them as intentional phase-1 constraints.

---

## 23. v3 Tension: Make node_types configurable in coordinator

**Files to edit:**
- `src/remora/bootstrap/coordinator.py`
- `src/remora/bootstrap/runner.py`

**Problem:** `find_unassigned_modules` hard-codes `node_types={"file"}`. From a v3
perspective, "what type of node gets an agent" is a policy decision that should not be
embedded in the substrate coordinator. It leaks the NodeStore convention (`node_type="file"`
maps to module nodes) into the coordinator logic.

**What to do:**

### Step 23a — Update BootstrapRunner to own the node_types policy

Make `node_types` a constructor parameter of `BootstrapRunner` with `{"file"}` as the
default. This makes the default behaviour identical to today but allows callers to change it.

```python
# In BootstrapRunner.__init__, add:
def __init__(
    self,
    config: Config,
    *,
    ...
    node_types: set[str] | None = None,  # ← add this parameter
    ...
) -> None:
    ...
    # What node types are considered "need an agent". Defaults to file/module nodes.
    # Override to expand bootstrap coverage to other node types.
    self.node_types: set[str] = node_types if node_types is not None else {"file"}
    ...
```

### Step 23b — Use self.node_types in run_once and run_for_file

Update `run_once` to pass `node_types` to `find_unassigned_nodes`:

```python
# BEFORE
plans = await find_unassigned_modules(self.event_store)
```

```python
# AFTER
plans = await find_unassigned_nodes(
    self.event_store,
    node_types=self.node_types,
)
```

Since `find_unassigned_modules` now becomes unused by the runner (if you make this change),
it is still useful as a public convenience function — keep it in `coordinator.py` but the
runner no longer calls it.

Update `run_for_file` similarly:

```python
# BEFORE
plans = await find_unassigned_nodes(self.event_store, file_path=file_path)
```

```python
# AFTER
plans = await find_unassigned_nodes(
    self.event_store,
    file_path=file_path,
    node_types=self.node_types,
)
```

### Step 23c — Update the docstring

Add a docstring note to `find_unassigned_modules` explaining why it still exists:

```python
async def find_unassigned_modules(event_store: EventStore) -> list[AgentNeededPlan]:
    """Find file/module nodes (node_type='file') that have no assigned agent.

    Convenience wrapper around find_unassigned_nodes with node_types={"file"}.
    Callers that need broader coverage should use find_unassigned_nodes directly
    or configure BootstrapRunner with a custom node_types set.
    """
    return await find_unassigned_nodes(event_store, node_types={"file"})
```

### Step 23d — Add a test for configurable node_types in the runner

In `tests/unit/bootstrap/test_runner.py`, add a test that creates a `BootstrapRunner`
with `node_types={"function"}` and asserts that `find_unassigned_nodes` is called with
the custom set (using mocking or by checking what plans are returned in a real event store).

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## 24. v3 Tension: Make _SKIP_DIRS configurable

**Files to edit:**
- `src/remora/bootstrap/seed_graph.py`

**Problem:** `_SKIP_DIRS` is a module-level constant hard-coded with Python project
conventions (`.venv`, `__pycache__`, `dist`, `build`, `.git`, `.devenv`). A v3-pure
seeder would read these from config. For now, the right fix is to make the skip set
injectable — pass it as a parameter with the current set as default.

**What to do:**

### Step 24a — Update seed_module_nodes_from_filesystem signature

```python
# BEFORE
async def seed_module_nodes_from_filesystem(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
) -> int:
```

```python
# AFTER
async def seed_module_nodes_from_filesystem(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
    skip_dirs: frozenset[str] | None = None,
) -> int:
    """Create file/module nodes in `nodes` via NodeDiscoveredEvent projection.

    Args:
        skip_dirs: Directory names to skip during traversal. Defaults to
            _SKIP_DIRS (Python project conventions). Pass a custom set to
            override for non-Python projects or different layouts.
    """
    effective_skip = skip_dirs if skip_dirs is not None else _SKIP_DIRS
    ...
```

### Step 24b — Update the traversal loop to use effective_skip

```python
# BEFORE
if _SKIP_DIRS.intersection(rel_path_obj.parts):
    continue
```

```python
# AFTER
if effective_skip.intersection(rel_path_obj.parts):
    continue
```

### Step 24c — Update seed_modules_if_empty to accept skip_dirs

Pass `skip_dirs` through:

```python
async def seed_modules_if_empty(
    event_store: EventStore,
    project_root: Path,
    *,
    swarm_id: str,
    skip_dirs: frozenset[str] | None = None,
) -> int:
    """Seed module nodes only when no module/file nodes currently exist."""
    existing = await event_store.nodes.read_graph({"match": {"kind": "module"}})
    if existing and existing != "[]":
        logger.info("Module nodes already exist; skipping filesystem seeding")
        return 0
    return await seed_module_nodes_from_filesystem(
        event_store, project_root, swarm_id=swarm_id, skip_dirs=skip_dirs
    )
```

### Step 24d — Add a comment documenting _SKIP_DIRS

```python
# Default skip directories for Python project layouts. Pass skip_dirs= to
# seed_module_nodes_from_filesystem() or seed_modules_if_empty() to override.
_SKIP_DIRS = frozenset({".venv", ".devenv", "__pycache__", "dist", "build", ".git"})
```

Note the change from `set` to `frozenset` — since this is a module-level constant it
should be immutable. Update the type annotation on `_SKIP_DIRS` too.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py -v
```

The T6 test (Section 14) should still pass with the default skip set.

---

## 25. v3 Tension: Frame bootstrap runner as phase-1 scaffolding

**Files to edit:**
- `src/remora/bootstrap/runner.py`
- `src/remora/bootstrap/coordinator.py`
- `bootstrap/agents/coordinator.yaml` (already addressed in Section 8)

**Problem:** The v3 philosophy calls for structure to emerge from bootstrapping. But the
bootstrap runner itself runs as hard-coded Python (`run_once`, `run_forever`). This is
intentionally pragmatic — the system needs to bootstrap before it can be agent-driven —
but this design intent is not documented. A developer could mistake the Python coordinator
for the *intended final form*, when it is actually scaffolding that will eventually be
replaced by the LLM-driven coordinator defined in `coordinator.yaml`.

**What to do:**

### Step 25a — Add a module docstring to runner.py

At the very top of `src/remora/bootstrap/runner.py`, update or add the module docstring:

```python
"""Bootstrap runtime loop for module-to-agent assignment.

PHASE-1 SCAFFOLDING
-------------------
This module implements the coordinator loop in Python code. It is intentionally
temporary. The v3 design calls for the coordinator itself to be an LLM agent
(see bootstrap/agents/coordinator.yaml for the target schema). The Python
coordinator exists here because the system must be able to bootstrap before it
can run LLM agents — you cannot use an agent to start the system that starts
agents.

Phase-1 responsibilities of this module:
  1. Seed the graph with module nodes (via seed_graph.py).
  2. Detect unassigned nodes (via coordinator.py).
  3. Emit AgentNeededEvent for each (written to the event store).
  4. Directly activate each agent via handle_agent_needed (without going
     through the event bus — this is the "fast path" for local activation).

Phase-2 transition plan:
  - The BootstrapRunner.run_once() loop will be replaced by an event-driven
    coordinator agent that subscribes to AgentNeededEvent and ToolSynthesizedEvent.
  - The agent will use the tools defined in bootstrap/tools/ to survey the graph
    and emit its own AgentNeededEvent events.
  - When this transition is complete, BootstrapRunner becomes a thin wrapper that
    seeds the graph and starts the coordinator agent's first activation.
"""
```

### Step 25b — Add a module docstring to coordinator.py

Similarly, update `src/remora/bootstrap/coordinator.py`:

```python
"""Coordinator helpers for bootstrap self-assignment flow.

PHASE-1 NOTE: This module provides the Python implementation of coordinator
logic — finding unassigned nodes and emitting AgentNeededEvent. In phase 2,
this logic will be replaced by an LLM-driven coordinator agent (see
bootstrap/agents/coordinator.yaml). The functions here will remain as utilities
but the coordinator agent will call them via the graph and event bedrock
primitives rather than via direct Python imports.
"""
```

### Step 25c — No code changes

These are documentation-only changes. The code behaviour stays identical.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
```

All tests must still pass.

---

## Implementation Order

Work through the sections in this order to minimize conflicts and test failures:

| Order | Section | Reason |
|-------|---------|--------|
| 1 | S1 (Section 1) | Renames functions; must be done before any test updates that reference private names |
| 2 | N4 (Section 7) | Small, safe, no dependencies |
| 3 | N1 (Section 4) | Small, safe, no dependencies |
| 4 | S2 (Section 2) | Depends on the rename being done; refactors runner |
| 5 | S3 (Section 3) | Isolated to bedrock.py |
| 6 | N2 (Section 5) | Comment only; any order |
| 7 | N5 / Section 8 | Comment only; any order |
| 8 | Section 17 | Comment only; any order |
| 9 | Section 22 | Covered by Section 8; confirm done |
| 10 | Section 25 | Doc only; any order |
| 11 | N3 (Section 6) | Comment on .pym file; any order |
| 12 | T4 (Section 12) | Add tests after S1 to use correct function names |
| 13 | T5 (Section 13) | Add tests |
| 14 | T6 (Section 14) | Add tests |
| 15 | T2 (Section 10) | Add tests |
| 16 | T3 (Section 11) | Add tests; most work |
| 17 | Section 16 | Structural refactor — extract shared helper; do after tests pass |
| 18 | Section 18 | LSP wiring cleanup |
| 19 | Section 19 | Delete dead package |
| 20 | Section 20 | Consolidate DEFAULT_SCHEMA_YAML |
| 21 | Section 21 | Write README |
| 22 | Section 23 | v3: configurable node_types |
| 23 | Section 24 | v3: configurable skip_dirs |

---

## Running the Full Test Suite

After completing all changes, run the full suite once to verify no regressions:

```bash
devenv shell -- uv sync --extra dev
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
devenv shell -- tach check
```

Expected: 39+ tests passing, 0 tach violations.

The known pre-existing failures (unrelated to bootstrap) are:
- `test_lsp_handlers_register_and_advertise_capabilities`
- 2 cairn merge-ops integration tests

These are expected failures and do not indicate a regression from bootstrap changes.
