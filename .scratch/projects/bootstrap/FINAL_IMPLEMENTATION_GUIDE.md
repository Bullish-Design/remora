# Bootstrap Final Implementation Guide

**Derived from:** `FINAL_CODE_REVIEW.md` (2026-03-09)
**Goal:** Close all remaining gaps so the bootstrap system operates as a
fully functional, real-world running system. No aspirational placeholders.
No silent no-ops. Every activation path works end-to-end.
**Test baseline:** 66 tests passing — all must continue to pass after each change.

---

## Overview

The implementation is sound and mostly complete. Two gaps prevent it from
functioning in production:

1. **M1 — URI/path mismatch**: `run_for_file(uri)` is called with a raw LSP
   URI; the database stores relative paths; the query silently matches nothing.
2. **M2 — Event-driven re-activation**: Bootstrap agents declare subscriptions
   but there is no loop that watches those subscriptions and re-activates the
   agent when a matching event fires.

Beyond these, one "Should Fix" architectural issue (S1) must be addressed
before the re-activation loop (M2) can work correctly:

3. **S1 — `SubscriptionPattern.node_id`**: Without node-scoped subscriptions,
   every agent subscribed to `ContentChangedEvent` fires on any file change.

Work in this order:

| Order | Section | Priority |
|-------|---------|----------|
| 1 | [M1 — Fix URI path normalization](#1-m1--fix-uri-path-normalization) | Must Fix |
| 2 | [S1 — Add node_id to SubscriptionPattern](#2-s1--add-node_id-to-subscriptionpattern) | Should Fix (prerequisite for M2) |
| 3 | [M2 — Event-driven re-activation loop](#3-m2--event-driven-re-activation-loop) | Must Fix |
| 4 | [S2 — Eliminate _stable_workspace private access](#4-s2--eliminate-_stable_workspace-private-access) | Should Fix |
| 5 | [N1 — Retire coordinator.yaml aspirational status](#5-n1--retire-coordinatoryaml-aspirational-status) | Nice to Fix |
| 6 | [N2/N3 — Minor cleanup](#6-n2n3--minor-cleanup) | Nice to Fix |

---

## 1. M1 — Fix URI path normalization

**Files to edit:**
- `src/remora/lsp/handlers/documents.py`

**Problem:** `did_open` calls:
```python
await bootstrap_runner.run_for_file(uri)
```
where `uri = "file:///home/user/project/src/app.py"`. Inside `run_for_file`,
this becomes `find_unassigned_nodes(event_store, file_path=uri)` which runs
`WHERE file_path = 'file:///home/user/project/src/app.py'`. But nodes seeded
by `seed_module_nodes_from_filesystem` are stored with relative paths like
`'src/app.py'`. The query returns zero rows. The on-file-open activation path
is silently broken.

The fix is to normalize the URI to a project-relative path before calling
`run_for_file`. The workspace root path is available from the LSP server's
`workspace.root_path`.

### Step 1a — Add a path-normalization helper to documents.py

Open `src/remora/lsp/handlers/documents.py`. A `_uri_to_path` helper already
exists (line 19). Add a `_uri_to_rel_path` helper below it:

```python
# BEFORE (existing helper only)
def _uri_to_path(uri: str) -> str:
    try:
        return to_fs_path(uri)
    except Exception:
        return uri
```

```python
# AFTER (add a companion normalizer)
def _uri_to_path(uri: str) -> str:
    try:
        return to_fs_path(uri)
    except Exception:
        return uri


def _uri_to_rel_path(uri: str, root_path: str | None) -> str:
    """Convert a file URI to a project-relative POSIX path.

    Returns the original URI unchanged if normalization fails or if the
    resolved path is not inside the project root.
    """
    abs_path = _uri_to_path(uri)
    if not root_path:
        return abs_path
    try:
        rel = Path(abs_path).relative_to(root_path)
        return rel.as_posix()
    except ValueError:
        # Path is not under root — return the abs path; let the caller filter it
        return abs_path
```

### Step 1b — Apply normalization before run_for_file

In `did_open`, find the `run_for_file(uri)` call (around line 61) and change it:

```python
# BEFORE
if bootstrap_runner is not None:
    async def _activate_bootstrap_for_file() -> None:
        try:
            await bootstrap_runner.run_for_file(uri)
        except Exception:
            logger.exception("did_open: bootstrap file activation failed for %s", uri)

    asyncio.create_task(_activate_bootstrap_for_file())
```

```python
# AFTER
if bootstrap_runner is not None:
    root_path = getattr(ls.workspace, "root_path", None)
    file_rel_path = _uri_to_rel_path(uri, root_path)

    async def _activate_bootstrap_for_file() -> None:
        try:
            await bootstrap_runner.run_for_file(file_rel_path)
        except Exception:
            logger.exception(
                "did_open: bootstrap file activation failed for %s (rel=%s)",
                uri,
                file_rel_path,
            )

    asyncio.create_task(_activate_bootstrap_for_file())
```

### Step 1c — Apply the same normalization in did_save and did_change

Search `documents.py` for any other `run_for_file` calls. Apply the same
normalization pattern to each. Look especially at the `did_save` handler if
one exists.

### Step 1d — Add a test

Add to `tests/unit/bootstrap/test_runner.py` or a new integration test:

```python
from remora.lsp.handlers.documents import _uri_to_rel_path
from pathlib import Path

def test_uri_to_rel_path_normalizes_file_uri() -> None:
    result = _uri_to_rel_path(
        "file:///home/user/project/src/app.py",
        "/home/user/project",
    )
    assert result == "src/app.py"


def test_uri_to_rel_path_returns_abs_when_outside_root() -> None:
    result = _uri_to_rel_path(
        "file:///tmp/external/file.py",
        "/home/user/project",
    )
    assert result == "/tmp/external/file.py"


def test_uri_to_rel_path_handles_none_root() -> None:
    result = _uri_to_rel_path("file:///home/user/project/src/app.py", None)
    # Returns absolute path — not relative — when root is not available
    assert result == "/home/user/project/src/app.py"
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q --no-cov
devenv shell -- pytest tests/integration/test_bootstrap_loop.py -q --no-cov
```

---

## 2. S1 — Add node_id to SubscriptionPattern

**Files to edit:**
- `src/remora/core/events/subscriptions.py`
- `src/remora/bootstrap/activation.py`

**Problem:** `SubscriptionPattern` has no `node_id` field. Bootstrap agent
schemas declare subscriptions like:

```yaml
subscriptions:
  - event_type: ContentChangedEvent
    node_id: "{node.id}"
```

In `_register_schema_subscriptions`, the `spec.node_id` field is logged and
then silently dropped:

```python
if spec.node_id:
    logger.debug("Ignoring schema node_id subscription filter ...")

pattern = SubscriptionPattern(event_types=[event_type])  # node_id dropped
```

Without `node_id` filtering, every agent subscribed to `ContentChangedEvent`
will receive events for every file change. When the re-activation loop (M2) is
added, this causes all bootstrap agents to be re-activated on every save —
which is incorrect and expensive.

This section requires understanding the existing `SubscriptionPattern` and
`SubscriptionRegistry` implementation. Read both files before editing.

### Step 2a — Read the existing subscription infrastructure

```bash
cat src/remora/core/events/subscriptions.py
```

Understand:
- What fields `SubscriptionPattern` has currently
- How `SubscriptionRegistry.match` or `EventStore` uses patterns to find
  matching agents
- Whether subscription matching is done in Python or SQL

### Step 2b — Add node_id to SubscriptionPattern

Open `src/remora/core/events/subscriptions.py`. Find `SubscriptionPattern`
(likely a dataclass or Pydantic model). Add a `node_id` field:

```python
# BEFORE
@dataclass
class SubscriptionPattern:
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None
```

```python
# AFTER
@dataclass
class SubscriptionPattern:
    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None
    # Optional node_id filter. When set, only events with a matching node_id
    # (checked via event.node_id, event.payload["node_id"], or similar) are
    # delivered to this subscriber. Supports "{node.xxx}" template substitution
    # when registered via schema subscriptions.
    node_id: str | None = None
```

### Step 2c — Update subscription matching to filter by node_id

Find where subscription matching happens (likely in `EventStore.append` or
the `SubscriptionRegistry.match` method, or a trigger queue fill). Add logic
to skip events where `pattern.node_id` is set but the event's node_id does
not match.

The event node_id can come from:
- `event.node_id` (for `BootstrapEvent`, `NodeDiscoveredEvent`, etc.)
- `event.payload.get("node_id")` (for generic events with payload dicts)

```python
# Pseudocode for matching logic — locate the actual match implementation
def _matches_pattern(event: Any, pattern: SubscriptionPattern) -> bool:
    ...
    # Existing checks (event_type, from_agent, to_agent, tags, path_glob)
    ...
    if pattern.node_id is not None:
        event_node_id = (
            getattr(event, "node_id", None)
            or (getattr(event, "payload", {}) or {}).get("node_id")
        )
        if str(event_node_id) != str(pattern.node_id):
            return False
    return True
```

### Step 2d — Update _register_schema_subscriptions in activation.py

Remove the "Ignoring schema node_id subscription filter" log line and instead
use the resolved `node_id` in the pattern:

```python
# BEFORE
if spec.node_id:
    logger.debug(
        "Ignoring schema node_id subscription filter for %s: %s",
        agent_id,
        _resolve_node_vars(spec.node_id, node_attrs),
    )

pattern = SubscriptionPattern(event_types=[event_type])
```

```python
# AFTER
node_id_filter: str | None = None
if spec.node_id:
    node_id_filter = _resolve_node_vars(spec.node_id, node_attrs)
    # Note: node_id may contain "{node.id}" which resolves to the actual node_id
    # from node_attrs. If resolution returns the original template (node not in
    # attrs), log a warning and skip the node_id filter rather than registering
    # an unmatchable subscription.
    if "{node." in node_id_filter:
        logger.warning(
            "Schema node_id template unresolved for agent %s: %r — registering without node_id filter",
            agent_id,
            node_id_filter,
        )
        node_id_filter = None

pattern = SubscriptionPattern(event_types=[event_type], node_id=node_id_filter)
```

### Step 2e — Update _pattern_key to include node_id

The deduplication key must include `node_id` to avoid treating patterns with
different node_id filters as identical:

```python
# BEFORE
def _pattern_key(pattern: SubscriptionPattern) -> tuple[Any, ...]:
    return (
        tuple(pattern.event_types or []),
        tuple(pattern.from_agents or []),
        pattern.to_agent,
        pattern.path_glob,
        tuple(pattern.tags or []),
    )
```

```python
# AFTER
def _pattern_key(pattern: SubscriptionPattern) -> tuple[Any, ...]:
    return (
        tuple(pattern.event_types or []),
        tuple(pattern.from_agents or []),
        pattern.to_agent,
        pattern.path_glob,
        tuple(pattern.tags or []),
        pattern.node_id,  # ← add this
    )
```

### Step 2f — Add tests

In `tests/unit/bootstrap/test_activation.py`, update the orchestration test
to verify `ContentChangedEvent` subscriptions are registered WITH the resolved
`node_id`:

```python
# In test_handle_agent_needed_bootstraps_agent, after the current assertions:
second_pattern = subscriptions.register.await_args_list[1].args[1]
assert isinstance(second_pattern, SubscriptionPattern)
assert second_pattern.event_types == ["ContentChangedEvent"]
# Verify node_id is scoped to the actual node
assert second_pattern.node_id == "module:src/app.py"
```

Add a direct test for `_register_schema_subscriptions` with node_id:

```python
@pytest.mark.asyncio
async def test_register_schema_subscriptions_includes_node_id() -> None:
    from remora.bootstrap.activation import _register_schema_subscriptions
    from remora.bootstrap.schema_loader import SubscriptionSpec, TurnSchema

    subscriptions = SimpleNamespace(
        get_subscriptions=AsyncMock(return_value=[]),
        register=AsyncMock(),
    )
    schema = TurnSchema(
        subscriptions=[SubscriptionSpec(event_type="ContentChangedEvent", node_id="{node.id}")]
    )
    node_attrs = {"id": "module:src/app.py", "node_id": "module:src/app.py"}

    await _register_schema_subscriptions(
        subscriptions,
        agent_id="agent-app",
        schema=schema,
        node_attrs=node_attrs,
    )

    subscriptions.register.assert_awaited_once()
    registered_pattern = subscriptions.register.await_args.args[1]
    assert registered_pattern.event_types == ["ContentChangedEvent"]
    assert registered_pattern.node_id == "module:src/app.py"
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q --no-cov
devenv shell -- tach check
```

Pay attention to any test that checks `SubscriptionPattern` equality or
deduplication — the `_pattern_key` change may require test updates.

---

## 3. M2 — Event-driven re-activation loop

**Files to edit:**
- `src/remora/bootstrap/runner.py`
- `src/remora/lsp/__main__.py`

**Problem:** Bootstrap agents write schema subscriptions (e.g., to
`ContentChangedEvent`, `CursorFocusEvent`, `HumanInputResponseEvent`). These
are registered in `SubscriptionRegistry`. But nothing monitors the trigger
queue and re-activates the agent when a matching event fires.

The v1 `AgentRunner.run_from_event_store(event_store)` does exactly this for
v1 agents: it consumes triggers from `event_store.get_triggers()` and calls
`trigger(agent_id, ...)`. The bootstrap runner needs an analogous loop.

### Design

When an event is appended to the `EventStore`:
1. `EventStore.append` checks the `SubscriptionRegistry` for agents matching
   the event.
2. Matching agents are placed in the `_trigger_queue` as `(agent_id, event_id, event)`.
3. The `get_triggers()` async generator yields these tuples.

The bootstrap runner needs to:
1. Consume from `get_triggers()`
2. Look up the matching agent's `node_id` from the graph (agent node has
   `attrs.assigned_node_id`)
3. Re-activate the agent by calling `handle_agent_needed` with the triggering
   event

### Step 3a — Add run_from_event_store to BootstrapRunner

Open `src/remora/bootstrap/runner.py`. Add a new method after `run_forever`:

```python
async def run_from_event_store(self, event_store: EventStore | None = None) -> None:
    """Watch EventStore triggers and re-activate the matching bootstrap agent.

    This is the re-activation bridge: it consumes subscription-matched
    triggers from the EventStore trigger queue and calls handle_agent_needed
    with the triggering event so the agent can respond to content changes,
    cursor focus events, and human input responses.

    Runs until the runner is stopped or the event_store trigger generator
    terminates.
    """
    store = event_store or self.event_store
    # Wait for run_forever() or initialize() to complete
    while not self._initialized:
        await asyncio.sleep(0.05)

    async for agent_id, _event_id, event in store.get_triggers():
        if not self._running:
            break

        # Only process BootstrapEvent triggers (not v1 CoreEvent triggers)
        from remora.bootstrap.bedrock import BootstrapEvent
        if not isinstance(event, BootstrapEvent):
            continue

        # Resolve the agent's assigned node_id from the graph
        node_id = await self._resolve_agent_node_id(agent_id, store)
        if node_id is None:
            logger.warning(
                "run_from_event_store: no assigned node_id for agent=%s, skipping",
                agent_id,
            )
            continue

        logger.debug(
            "run_from_event_store: re-activating agent=%s node=%s event=%s",
            agent_id,
            node_id,
            getattr(event, "event_type", type(event).__name__),
        )

        # Build a re-activation event preserving the triggering event's payload
        activation_event = BootstrapEvent(
            event_type=getattr(event, "event_type", "ReactivationEvent"),
            node_id=node_id,
            payload={
                "node_id": node_id,
                "agent_id": agent_id,
                **(getattr(event, "payload", {}) or {}),
            },
            from_agent=getattr(event, "from_agent", None),
            to_agent=agent_id,
        )

        try:
            await handle_agent_needed(
                activation_event,
                workspace_service=self.workspace_service,
                subscriptions=self.subscriptions,
                event_store=store,
                config=self.config,
                swarm_id=self.swarm_id,
                bootstrap_root=self.bootstrap_root,
            )
        except Exception:
            logger.exception(
                "run_from_event_store: activation failed agent=%s node=%s",
                agent_id,
                node_id,
            )
```

### Step 3b — Add _resolve_agent_node_id helper

Add this private helper to `BootstrapRunner`:

```python
async def _resolve_agent_node_id(self, agent_id: str, event_store: EventStore) -> str | None:
    """Look up the node_id assigned to an agent from the graph."""
    try:
        import json
        raw = await event_store.nodes.read_graph({"node": agent_id})
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        attrs = data.get("attrs")
        if not isinstance(attrs, dict):
            return None
        node_id = attrs.get("assigned_node_id")
        return str(node_id) if node_id else None
    except Exception:
        logger.debug("_resolve_agent_node_id: lookup failed for %s", agent_id, exc_info=True)
        return None
```

### Step 3c — Wire run_from_event_store in the LSP __main__.py

Open `src/remora/lsp/__main__.py`. In the `_on_initialized` handler, after
`asyncio.ensure_future(bootstrap_runner.run_forever(...))`:

```python
if bootstrap_runner is not None:
    bootstrap_task = getattr(ls, "_remora_bootstrap_task", None)
    if bootstrap_task is None or bootstrap_task.done():
        poll_interval = max(0.0, float(getattr(ls, "_remora_bootstrap_poll_interval_s", 0.5)))
        startup_log.info("Starting bootstrap runner loop...")
        ls._remora_bootstrap_task = asyncio.ensure_future(
            bootstrap_runner.run_forever(poll_interval_s=poll_interval)
        )

# ADD: Start the event-driven re-activation bridge
if bootstrap_runner is not None and ls.event_store is not None:
    reactivation_task = getattr(ls, "_remora_bootstrap_reactivation_task", None)
    if reactivation_task is None or reactivation_task.done():
        startup_log.info("Starting bootstrap re-activation bridge...")
        ls._remora_bootstrap_reactivation_task = asyncio.ensure_future(
            bootstrap_runner.run_from_event_store(ls.event_store)
        )
```

Also cancel `_remora_bootstrap_reactivation_task` in the `finally` cleanup
block alongside `_remora_bootstrap_task`.

### Step 3d — Add a test for run_from_event_store

In `tests/unit/bootstrap/test_runner.py`:

```python
@pytest.mark.asyncio
async def test_run_from_event_store_reactivates_agent_on_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Triggers from EventStore re-activate the corresponding bootstrap agent."""
    import asyncio
    from remora.bootstrap.bedrock import BootstrapEvent

    config = _make_config(tmp_path)
    monkeypatch.setattr("remora.bootstrap.runner.CairnWorkspaceService", _FakeWorkspaceService)
    monkeypatch.setattr("remora.bootstrap.runner.seed_coordinator_node", AsyncMock())
    monkeypatch.setattr("remora.bootstrap.runner.seed_modules_if_empty", AsyncMock(return_value=0))

    handle_mock = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr("remora.bootstrap.runner.handle_agent_needed", handle_mock)

    trigger_event = BootstrapEvent(
        event_type="ContentChangedEvent",
        node_id="module:src/app.py",
        payload={"node_id": "module:src/app.py"},
    )

    # Event store that yields one trigger then stops
    trigger_queue: asyncio.Queue = asyncio.Queue()
    await trigger_queue.put(("agent-app", 42, trigger_event))

    async def _fake_get_triggers():
        while True:
            item = await trigger_queue.get()
            yield item

    event_store = SimpleNamespace(
        get_triggers=_fake_get_triggers,
        nodes=SimpleNamespace(
            read_graph=AsyncMock(return_value='{"kind": "agent", "attrs": {"assigned_node_id": "module:src/app.py"}}')
        ),
    )

    runner = BootstrapRunner(config, event_store=event_store, subscriptions=SimpleNamespace(), workspace_service=_FakeWorkspaceService())
    runner._initialized = True
    runner._running = True

    # Run the bridge for just long enough to process one trigger
    task = asyncio.ensure_future(runner.run_from_event_store(event_store))
    await asyncio.sleep(0.1)
    runner.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    handle_mock.assert_awaited_once()
    activation_event = handle_mock.await_args.args[0]
    assert isinstance(activation_event, BootstrapEvent)
    assert activation_event.to_agent == "agent-app"
    assert activation_event.payload["node_id"] == "module:src/app.py"
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/test_runner.py -v --no-cov
devenv shell -- pytest tests/integration/test_bootstrap_loop.py -v --no-cov
```

---

## 4. S2 — Eliminate _stable_workspace private access

**Files to edit:**
- `src/remora/core/agents/cairn_bridge.py` (add public property)
- `src/remora/bootstrap/activation.py` (use public property)

**Problem:** `activation.py` accesses:

```python
stable_workspace = getattr(workspace_service, "_stable_workspace", None)
if stable_workspace is None:
    raise RuntimeError("Workspace service stable workspace is not initialized")
```

This accesses a private attribute and creates a fragile coupling.

### Step 4a — Add a public property to CairnWorkspaceService

Open `src/remora/core/agents/cairn_bridge.py`. Find `CairnWorkspaceService`.
Add a public property:

```python
@property
def stable_workspace(self):
    """The shared (stable) Cairn workspace for the current project.

    Raises RuntimeError if the service has not been initialized yet.
    """
    ws = self._stable_workspace
    if ws is None:
        raise RuntimeError(
            "CairnWorkspaceService.stable_workspace is not initialized. "
            "Call initialize() before accessing it."
        )
    return ws
```

### Step 4b — Update activation.py to use the public property

```python
# BEFORE
stable_workspace = getattr(workspace_service, "_stable_workspace", None)
if stable_workspace is None:
    raise RuntimeError("Workspace service stable workspace is not initialized")
```

```python
# AFTER
stable_workspace = workspace_service.stable_workspace
# (RuntimeError is raised by the property if uninitialized)
```

### Verification

```bash
devenv shell -- pytest tests/unit/bootstrap/ -q --no-cov
devenv shell -- tach check
```

---

## 5. N1 — Retire coordinator.yaml aspirational status

**Context:** `coordinator.yaml` currently carries the comment `# PHASE STATUS:
ASPIRATIONAL — NOT YET ACTIVE`. This is accurate but does not resolve the
aspiration. Two options:

### Option A — Keep aspirational (recommended for near-term)

The coordinator schema is a design artifact. Keep it as-is with the aspirational
comment. Add a single task to the backlog: "Implement LLM coordinator to replace
Python coordinator in runner.py." When that work begins, the YAML provides the
target schema.

No code change needed now.

### Option B — Fully implement the LLM coordinator

This is substantial work: the Python `run_once` loop in `BootstrapRunner` would
be replaced by:
1. Seeding the coordinator agent (already done by `seed_coordinator_node`)
2. Activating the coordinator agent via `handle_agent_needed` using
   `coordinator.yaml` as its schema
3. The coordinator LLM surveys the graph and emits `AgentNeededEvent` for
   unassigned nodes
4. Those events trigger `run_from_event_store` which activates the target agents

This is deferred. The Python coordinator is functionally correct; the LLM
coordinator adds autonomy. Do Option A now, Option B when the LLM coordinator
becomes a project priority.

---

## 6. N2/N3 — Minor cleanup

### N2 — BootstrapEvent EventBus subscription comment

Open `src/remora/lsp/__main__.py`. Find the line:

```python
event_bus_local.subscribe(BootstrapEvent, _forward_user_question)
```

Add a comment:

```python
# BootstrapEvent is not in the CoreEvent union (that would create a layer
# violation: core importing from bootstrap). EventBus dispatches via MRO,
# so subscribing to the BootstrapEvent class works correctly at runtime.
event_bus_local.subscribe(BootstrapEvent, _forward_user_question)
```

### N3 — Remove unreachable getattr guards

Open `src/remora/bootstrap/activation.py`. In
`_ensure_subject_matter_expert_workspace`:

```python
# BEFORE
read_file = getattr(cairn_externals, "read_file", None)
write_file = getattr(cairn_externals, "write_file", None)
if not callable(read_file) or not callable(write_file):
    return
```

```python
# AFTER
# CairnExternals always provides read_file and write_file — no guard needed.
```

Then update the try/except blocks to call `cairn_externals.read_file(...)` and
`cairn_externals.write_file(...)` directly (the exception guards for individual
reads/writes are still correct and useful).

---

## Running the Complete Test Suite

After completing all changes, run the full suite:

```bash
devenv shell -- uv sync --extra dev
devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q --no-cov
devenv shell -- tach check
```

Expected: 70+ tests passing, 0 tach violations.

Known pre-existing failures (unrelated to bootstrap):
- `test_lsp_handlers_register_and_advertise_capabilities`
- 2 cairn merge-ops integration tests

---

## End State: What "Fully Functional" Looks Like

After this guide is complete, the bootstrap system operates as follows:

**On LSP startup:**
1. `seed_coordinator_node` → coordinator agent node appears in graph
2. `seed_modules_if_empty` → one `module:...` node per `.py` file in the graph
3. `run_forever()` starts polling; `run_from_event_store()` starts listening

**On first `run_once` pass:**
1. `find_unassigned_nodes` finds all seeded module nodes without agents
2. `_emit_events_for_plans` → `AgentNeededEvent` per node written to EventStore
3. `_activate_plans` → `handle_agent_needed` per node:
   - Pre-seeds `schema.yaml` (extends: subject_matter_expert) + `summary.md`
   - Loads `subject_matter_expert.yaml` schema (via `extends` merge)
   - Runs LLM with full context pipeline (existing_summary, source_file, graph_node, etc.)
   - LLM updates `summary.md` with accurate documentation
   - Registers `ContentChangedEvent` + `CursorFocusEvent` subscriptions scoped to the node
   - Writes agent node to graph with `assigned_node_id`

**On file open (editor):**
1. `did_open` → `parse_content` → `NodeDiscoveredEvent` → nodes in EventStore
2. `run_for_file(file_rel_path)` → finds any newly-appeared function/class nodes
3. Activates agents for nodes discovered during this parse pass

**On file save / content change:**
1. `ContentChangedEvent` appended to EventStore
2. SubscriptionRegistry matches it to agents subscribed to `ContentChangedEvent`
   WHERE `node_id = 'module:src/app.py'` (with S1 fix applied)
3. Trigger pushed to queue → `run_from_event_store` picks it up
4. `handle_agent_needed` with the `ContentChangedEvent` as activation event
5. LLM reads updated source, updates `summary.md`

**On user question from agent:**
1. Agent calls `user_question` tool → `HumanInputRequestEvent` emitted
2. EventBus `_forward_user_question` → `$/remora/requestInput` to editor
3. Editor shows UI prompt; user responds
4. `$/remora/submitInput` → `notifications.on_input_submitted`
5. `bootstrap_runner.handle_human_input_response` → `HumanInputResponseEvent`
6. `_append_correction_notes` → updates `notes.md` + `summary.md`
7. `handle_agent_needed` → LLM runs with correction context

Every activation path is functional. No aspirational placeholders block
production use.

---

## Implementation Order Summary

| Step | Change | Test Command |
|------|--------|--------------|
| 1 | URI path normalization in `documents.py` | `pytest tests/unit/bootstrap/ tests/integration/test_bootstrap_loop.py` |
| 2 | `SubscriptionPattern.node_id` field + matching | `pytest tests/unit/bootstrap/ && tach check` |
| 3 | `_register_schema_subscriptions` uses node_id | `pytest tests/unit/bootstrap/test_activation.py` |
| 4 | `run_from_event_store` on BootstrapRunner | `pytest tests/unit/bootstrap/test_runner.py` |
| 5 | Wire re-activation in LSP `__main__.py` | Manual LSP integration test |
| 6 | `stable_workspace` public property | `pytest tests/unit/bootstrap/ && tach check` |
| 7 | Minor cleanup (N2/N3) | `pytest tests/unit/bootstrap/ -q` |
