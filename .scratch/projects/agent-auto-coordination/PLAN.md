# Plan — Agent Auto-Coordination

**Goal:** Fully autonomous, event-driven bootstrap. A `NodeDiscoveredEvent`
automatically triggers agent assignment. No polling. No LLM coordinator.
Everything flows through the EventStore trigger queue.

**NO SUBAGENTS. NEVER USE THE TASK TOOL. ALL WORK DIRECTLY.**

---

## Table of Contents

| Section | Description |
|---------|-------------|
| [Overview](#overview) | Architecture summary and the "bootstrap-system" mechanism |
| [M0 — Fix URI Path Normalization](#m0--fix-uri-path-normalization) | Bug fix: `run_for_file` gets raw URI, nodes stored as relative paths |
| [M1 — Add node_id to SubscriptionPattern](#m1--add-node_id-to-subscriptionpattern) | Prerequisite: scoped subscriptions so only the right agent fires on file change |
| [M2 — Add stable_workspace property](#m2--add-stable_workspace-property) | Small cleanup: remove private attribute access in activation.py |
| [M3 — run_from_event_store with system dispatch](#m3--run_from_event_store-with-system-dispatch) | Core: the event-driven loop that routes NodeDiscoveredEvent → AgentNeededEvent → handle_agent_needed |
| [M4 — Register bootstrap-system at startup](#m4--register-bootstrap-system-at-startup) | Wire: register "bootstrap-system" subscriptions before seeding, ensuring ordering is correct |
| [M5 — Seed root directory node](#m5--seed-root-directory-node) | Structural: "directory:." node with parent→child edges to file nodes |
| [M6 — Wire run_from_event_store in LSP](#m6--wire-run_from_event_store-in-lsp) | LSP integration: start the re-activation bridge alongside run_forever |
| [M7 — Deprecate Python polling coordinator](#m7--deprecate-python-polling-coordinator) | Phase-out: run_once() becomes a fallback, not the primary path |
| [M8 — Integration test](#m8--integration-test) | End-to-end validation: seeding → auto-activation → re-activation on change |
| [Acceptance Criteria](#acceptance-criteria) | Definition of "done" |

---

## Overview

The central mechanism is the **`"bootstrap-system"` pseudo-agent**:

- A synthetic agent ID registered in `SubscriptionRegistry` (not an LLM)
- Subscribed to `NodeDiscoveredEvent` and `AgentNeededEvent`
- When either event fires, `EventStore.append()` queues a trigger for it
- `run_from_event_store()` dispatches to Python handlers instead of an LLM

The routing logic:

```
trigger: ("bootstrap-system", NodeDiscoveredEvent)
  → node already has agent?  → skip
  → else                     → append AgentNeededEvent to EventStore

trigger: ("bootstrap-system", AgentNeededEvent)
  → call handle_agent_needed() → file agent LLM runs

trigger: (any_other_agent_id, any_BootstrapEvent)
  → resolve node_id from graph
  → call handle_agent_needed() → file agent re-runs
```

**Startup ordering constraint:** register "bootstrap-system" subscriptions
**before** seeding files. Events from seeding must match the subscription or
they'll be lost (the trigger queue is not retroactively replayed).

The **directory node** (`node_id="directory:."`) is structural only in this
project: it gives the graph a hierarchical root and parent→child edges to
file nodes. It does not run an LLM agent here. That is deferred to a future
phase when `FileCreatedEvent` integration (inotify/watchdog) is ready.

---

## M0 — Fix URI Path Normalization

**Files:** `src/remora/lsp/handlers/documents.py`

**Why first:** Every other milestone assumes `run_for_file` works correctly.
The on-file-open activation path is silently broken until this is fixed.

**Problem:** `did_open` calls `bootstrap_runner.run_for_file(uri)` where
`uri = "file:///home/user/project/src/app.py"`. Inside, this queries
`WHERE file_path = 'file:///...'` but seeded nodes use `'src/app.py'`.
Zero rows returned. Silent no-op.

### Steps

**M0a** — Add `_uri_to_rel_path` helper after the existing `_uri_to_path`:

```python
def _uri_to_rel_path(uri: str, root_path: str | None) -> str:
    """Convert a file URI to a project-relative POSIX path.
    Returns the absolute path if root_path is None or path is outside root.
    """
    abs_path = _uri_to_path(uri)
    if not root_path:
        return abs_path
    try:
        return Path(abs_path).relative_to(root_path).as_posix()
    except ValueError:
        return abs_path
```

**M0b** — Apply normalization in `did_open`:

```python
# Before: await bootstrap_runner.run_for_file(uri)
root_path = getattr(ls.workspace, "root_path", None)
file_rel_path = _uri_to_rel_path(uri, root_path)
await bootstrap_runner.run_for_file(file_rel_path)
```

**M0c** — Add three tests in `tests/unit/bootstrap/` (new file
`test_uri_normalization.py` or append to `test_runner.py`):
- `test_uri_to_rel_path_normalizes_file_uri`
- `test_uri_to_rel_path_returns_abs_when_outside_root`
- `test_uri_to_rel_path_handles_none_root`

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## M1 — Add node_id to SubscriptionPattern

**Files:** `src/remora/core/events/subscriptions.py`,
`src/remora/bootstrap/activation.py`

**Why now:** Without scoped subscriptions, when `run_from_event_store` is
added in M3, every agent subscribed to `ContentChangedEvent` fires on any
file change. This would re-run all agents on every keystroke — incorrect and
expensive.

**Problem:** `SubscriptionPattern` has no `node_id` field. Schema
subscriptions like `node_id: "{node.id}"` are silently dropped in
`_register_schema_subscriptions`.

### Steps

**M1a** — Add field to `SubscriptionPattern` in `subscriptions.py`:

```python
# Optional node_id filter. When set, only events whose node_id
# matches (checked via event.node_id or event.payload["node_id"])
# are delivered to this subscriber.
node_id: str | None = None
```

**M1b** — Add matching logic in `SubscriptionPattern.matches()`:

```python
if self.node_id is not None:
    event_node_id = (
        getattr(event, "node_id", None)
        or (getattr(event, "payload", None) or {}).get("node_id")
    )
    if str(event_node_id) != self.node_id:
        return False
```

**M1c** — Update `_register_schema_subscriptions` in `activation.py`:
- Remove the "Ignoring schema node_id subscription filter" log + noop
- Resolve `spec.node_id` template via `_resolve_node_vars(spec.node_id, node_attrs)`
- If the template is unresolved (still contains `{node.`), log warning + skip filter
- Pass `node_id=resolved_value` to `SubscriptionPattern(...)`

**M1d** — Update `_pattern_key` in `activation.py` to include `pattern.node_id`:

```python
return (..., pattern.node_id)  # add at end of existing tuple
```

**M1e** — Add/update tests in `test_activation.py`:
- Verify `ContentChangedEvent` subscription is registered WITH resolved `node_id`
- Add `test_register_schema_subscriptions_includes_node_id`

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
devenv shell -- tach check
```

---

## M2 — Add stable_workspace Property

**Files:** `src/remora/core/agents/cairn_bridge.py`,
`src/remora/bootstrap/activation.py`

**Why now:** Small prerequisite cleanup before writing more activation code.
Private attribute access is a fragile coupling.

### Steps

**M2a** — Add public property to `CairnWorkspaceService`:

```python
@property
def stable_workspace(self):
    """Shared Cairn workspace. Raises RuntimeError if not initialized."""
    ws = self._stable_workspace
    if ws is None:
        raise RuntimeError(
            "CairnWorkspaceService.stable_workspace accessed before initialize()"
        )
    return ws
```

**M2b** — Update `activation.py`:

```python
# Before: getattr(workspace_service, "_stable_workspace", None) + guard
stable_workspace = workspace_service.stable_workspace
# RuntimeError raised by property if uninitialized — no extra guard needed
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## M3 — run_from_event_store with System Dispatch

**Files:** `src/remora/bootstrap/runner.py`

**Why this is the core:** This is the event loop that closes the circuit.
Without it, events go into the trigger queue and die there.

### Design

`run_from_event_store` consumes `event_store.get_triggers()` and dispatches:

```python
_BOOTSTRAP_SYSTEM_AGENT_ID = "bootstrap-system"

async for agent_id, event_id, event in store.get_triggers():
    if not self._running:
        break
    if agent_id == _BOOTSTRAP_SYSTEM_AGENT_ID:
        await self._handle_system_trigger(event)
    else:
        await self._handle_agent_reactivation(agent_id, event, store)
```

### Steps

**M3a** — Add module-level constant:

```python
_BOOTSTRAP_SYSTEM_AGENT_ID = "bootstrap-system"
```

**M3b** — Add `run_from_event_store(self, event_store=None)`:
- Wait for `_initialized` before consuming (brief `asyncio.sleep(0.05)` poll)
- Consume `store.get_triggers()` async generator
- Dispatch to `_handle_system_trigger` or `_handle_agent_reactivation`
- Wrap each dispatch in try/except; log but don't terminate the loop

**M3c** — Add `_handle_system_trigger(self, event)`:

```python
async def _handle_system_trigger(self, event: Any) -> None:
    event_type = getattr(event, "event_type", None) or type(event).__name__
    if event_type == "NodeDiscoveredEvent":
        await self._emit_agent_needed_if_unassigned(event)
    elif event_type == "AgentNeededEvent":
        await self._activate_from_event(event)
```

**M3d** — Add `_emit_agent_needed_if_unassigned(self, event)`:
- Extract `node_id` from event (`event.node_id` or `event.payload["node_id"]`)
- Check if already assigned: call `_read_assigned_node_ids()` (from coordinator.py)
- If unassigned: `await self.event_store.append(swarm_id, BootstrapEvent(event_type="AgentNeededEvent", ...))`

**M3e** — Add `_activate_from_event(self, event)`:
- Extract `node_id` from event
- Build `AgentNeededEvent` BootstrapEvent with coordinator as `from_agent`
- Call `handle_agent_needed(event, workspace_service=..., ...)`
- Acquire `_activation_lock` to prevent concurrent activation of same node

**M3f** — Add `_handle_agent_reactivation(self, agent_id, event, store)`:
- Look up `node_id` from graph via `_resolve_agent_node_id(agent_id, store)`
- If not found: log warning, skip
- Build re-activation `BootstrapEvent` preserving triggering event's payload
- Call `handle_agent_needed(...)`

**M3g** — Add `_resolve_agent_node_id(self, agent_id, store)`:
- Query `store.nodes.read_graph({"node": agent_id})`
- Parse JSON → extract `attrs.assigned_node_id`
- Return `str(node_id)` or `None`

**M3h** — Add tests in `tests/unit/bootstrap/test_runner.py`:
- `test_run_from_event_store_routes_node_discovered_to_agent_needed`
- `test_run_from_event_store_routes_agent_needed_to_handle_agent_needed`
- `test_run_from_event_store_reactivates_file_agent_on_content_changed`
- `test_run_from_event_store_skips_already_assigned_nodes`

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_runner.py -v
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## M4 — Register bootstrap-system at Startup

**Files:** `src/remora/bootstrap/runner.py`

**Why ordering matters:** Subscriptions must be registered BEFORE seeding.
Events from `seed_module_nodes_from_filesystem` will match the subscription
and queue triggers. If registered after, those events are lost forever.

### Steps

**M4a** — Add `_register_system_subscriptions(self)` to `BootstrapRunner`:

```python
async def _register_system_subscriptions(self) -> None:
    """Register the bootstrap-system routing subscriptions if not already present."""
    existing = await self.subscriptions.get_subscriptions(_BOOTSTRAP_SYSTEM_AGENT_ID)
    existing_types = {
        et
        for sub in existing
        for et in (sub.pattern.event_types or [])
    }
    if "NodeDiscoveredEvent" not in existing_types:
        await self.subscriptions.register(
            _BOOTSTRAP_SYSTEM_AGENT_ID,
            SubscriptionPattern(event_types=["NodeDiscoveredEvent"]),
        )
    if "AgentNeededEvent" not in existing_types:
        await self.subscriptions.register(
            _BOOTSTRAP_SYSTEM_AGENT_ID,
            SubscriptionPattern(event_types=["AgentNeededEvent"]),
        )
```

**M4b** — Update `initialize()` to call `_register_system_subscriptions()`
**before** the seeding calls. New ordering:

```python
async def initialize(self) -> None:
    # ... setup subscriptions, event_store, workspace_service ...
    await self._register_system_subscriptions()  # FIRST
    await seed_root_directory_node(event_store)   # then structure
    await seed_modules_if_empty(...)              # then file nodes → triggers queued
    self._initialized = True
```

**M4c** — Add tests in `test_runner.py`:
- `test_initialize_registers_system_subscriptions_before_seeding`
- `test_initialize_does_not_duplicate_system_subscriptions_on_restart`

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_runner.py -v
```

---

## M5 — Seed Root Directory Node

**Files:** `src/remora/bootstrap/seed_graph.py`,
`tests/unit/bootstrap/test_seed_graph.py`

**Purpose:** Structural foundation. The graph gets a hierarchical root.
Agents can query their directory context. Future: `FileCreatedEvent` target.

### Node shape

```python
{
    "id": "directory:.",
    "kind": "directory",     # not "agent" — this node has no LLM
    "node_type": "directory",
    "attrs": {
        "name": "project-root",
        "path": ".",
        "role": "Root directory. Structural parent of all file nodes.",
    }
}
```

### Steps

**M5a** — Add `seed_root_directory_node(event_store, *, root_id="directory:")`:

```python
async def seed_root_directory_node(
    event_store: EventStore,
    *,
    root_id: str = "directory:.",
) -> None:
    """Ensure the root directory structural node exists in the graph."""
    await event_store.nodes.write_graph("add_node", {
        "id": root_id,
        "kind": "directory",
        "node_type": "directory",
        "attrs": {"name": "project-root", "path": ".", "role": "..."},
    })
```

**M5b** — After seeding file nodes in `seed_module_nodes_from_filesystem`,
add parent→child edges: for each seeded node, call `write_graph("add_edge", ...)`
to connect `directory:.` → `module:src/app.py`. Extract this into a helper
`_add_directory_edges(event_store, root_id, node_ids)`.

**M5c** — Update `__all__` in `seed_graph.py`.

**M5d** — Add tests in `test_seed_graph.py`:
- `test_seed_root_directory_node_creates_directory_node`
- `test_seed_root_directory_node_is_idempotent`
- `test_seed_module_nodes_adds_directory_edges`

**M5e** — Update `initialize()` in `runner.py`: replace
`seed_coordinator_node(event_store)` with `seed_root_directory_node(event_store)`.
Keep `seed_coordinator_node` in the codebase for backwards compat but stop
calling it by default (add `keep_legacy_coordinator: bool = False` flag).

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py -v
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## M6 — Wire run_from_event_store in LSP

**Files:** `src/remora/lsp/__main__.py`

**Why:** The event loop must run as a concurrent asyncio task alongside the
LSP server. Without this wiring, `run_from_event_store` exists but is never
started.

### Steps

**M6a** — In `_on_initialized` handler, after starting `run_forever`:

```python
# Start event-driven re-activation bridge
reactivation_task = getattr(ls, "_remora_bootstrap_reactivation_task", None)
if reactivation_task is None or reactivation_task.done():
    startup_log.info("Starting bootstrap re-activation bridge...")
    ls._remora_bootstrap_reactivation_task = asyncio.ensure_future(
        bootstrap_runner.run_from_event_store()
    )
```

**M6b** — In shutdown `finally` block, cancel the reactivation task:

```python
reactivation_task = getattr(ls, "_remora_bootstrap_reactivation_task", None)
if reactivation_task and not reactivation_task.done():
    reactivation_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reactivation_task
```

**M6c** — Add `N2` comment near `BootstrapEvent` EventBus subscription:

```python
# BootstrapEvent is not in the CoreEvent union (that would be a layer violation).
# EventBus dispatches via MRO, so subscribing to BootstrapEvent class works at runtime.
event_bus_local.subscribe(BootstrapEvent, _forward_user_question)
```

### Verification

```bash
devenv shell -- pytest tests/unit/test_lsp_startup_sequence.py -v
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## M7 — Deprecate Python Polling Coordinator

**Files:** `src/remora/bootstrap/runner.py`

**Goal:** Make `run_from_event_store` the primary activation path. Keep
`run_once()` as a fallback controlled by a flag.

### Steps

**M7a** — Add `use_python_coordinator: bool = False` to `BootstrapRunner.__init__`.

**M7b** — Update `run_forever()`:

```python
async def run_forever(self, *, poll_interval_s: float = 0.5) -> None:
    await self.initialize()
    self._running = True
    try:
        while self._running:
            if self.use_python_coordinator:
                await self.run_once()
            await asyncio.sleep(max(0.0, poll_interval_s))
    finally:
        self._running = False
```

When `use_python_coordinator=False` (default), `run_forever` just keeps the
loop alive; the real work happens in `run_from_event_store`.

**M7c** — Update `run_once()` docstring:

```
PHASE-1 FALLBACK: This method is the Python polling coordinator.
It is no longer the primary activation path. Set use_python_coordinator=True
on BootstrapRunner to enable it. The primary path is run_from_event_store()
via the "bootstrap-system" subscription mechanism.
```

**M7d** — Update `run_bootstrap()` convenience function to start both
`run_forever` and `run_from_event_store` as concurrent tasks.

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_runner.py -v
devenv shell -- pytest tests/unit/bootstrap/ -q
```

---

## M8 — Integration Test: End-to-End Event Flow

**Files:** `tests/integration/test_auto_coordination.py`

**Validates the full self-activating loop:**
1. `initialize()` registers "bootstrap-system" subscriptions
2. File nodes are seeded → `NodeDiscoveredEvent` → triggers queued
3. `run_from_event_store` emits `AgentNeededEvent` per unassigned node
4. `run_from_event_store` calls `handle_agent_needed` per `AgentNeededEvent`
5. File agents register `ContentChangedEvent` subscriptions (scoped by `node_id`)
6. Appending a `ContentChangedEvent` for a file → triggers queued → agent re-activates

### Verification

```bash
devenv shell -- pytest tests/integration/test_auto_coordination.py -v
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
devenv shell -- tach check
```

---

## Acceptance Criteria

The system is complete when ALL of these hold:

- [ ] `BootstrapRunner.initialize()` registers "bootstrap-system" BEFORE seeding
- [ ] Seeding files emits `NodeDiscoveredEvent` → triggers route to "bootstrap-system"
- [ ] `run_from_event_store` emits `AgentNeededEvent` for each unassigned node
- [ ] `run_from_event_store` calls `handle_agent_needed` for each `AgentNeededEvent`
- [ ] File agents subscribe to `ContentChangedEvent` scoped to their `node_id`
- [ ] Appending `ContentChangedEvent` for `src/app.py` only re-activates that file's agent
- [ ] `run_for_file(file_rel_path)` correctly finds nodes (URI normalization fixed)
- [ ] Directory node `"directory:."` exists in graph with edges to file nodes
- [ ] All 66+ bootstrap tests pass
- [ ] `tach check` passes
- [ ] `run_once()` still works as an optional fallback (`use_python_coordinator=True`)

---

**NO SUBAGENTS. NEVER USE THE TASK TOOL. ALL WORK DIRECTLY.**
