# Remora V2 Testing Guidelines

Remora V2 ships with phase-aligned unit suites and a focused integration signal. The primary goals:

1. Validate the **event bus** (pub/sub, wildcards, serialization, streams).
2. Verify the **AgentGraph** and **AgentInbox** (declarative dependencies, blocking, resuming).
3. Exercise **workspace helpers** (per-agent dirs, snapshot/merge, cleanup).
4. Ensure the **interactive coordinator** and **dashboard** respond to blocked questions and answers.
5. Confirm serialization/persistence via **AgentKVStore** and **CheckpointManager**.

## Unit Testing

| Phase | Targeted Module | Focus |
|-------|----------------|-------|
| 1 | `tests/unit/test_event_bus.py` | pub/sub, wildcard matching, SSE stream iteration, JSON serialization
| 2 | `tests/unit/test_agent_graph.py` | `AgentNode`, `AgentGraph`, inbox blocking + user messages, execution events
| 3 | `tests/unit/test_workspace_ipc.py` | `WorkspaceInboxCoordinator` emits `agent:block`/`resumed`
| 5 | `tests/unit/test_agent_state.py` | `AgentKVStore` message/tool/metadata CRUD + snapshot/restore
| 6 | `tests/unit/test_workspace.py` | `GraphWorkspace` directories, snapshots, shared space, merge helpers

Run the full unit suite with `pytest tests/unit/ -v`. Each unit test should avoid private fields and focus on observable behavior via the event bus, KV state, or workspace filesystem.

## Integration Testing

Integration tests should stitch discovery → graph → execution → interaction, asserting that event subscriptions see the expected lifecycle. The reference test is `tests/integration/test_workspace_ops.py`, which exercises `AgentGraph`, `GraphExecutor`, and workspace checkpointing. Additional integration scenarios live under `tests/acceptance/`.

## Monitoring & Dashboards

Since the UI now subscribes to `EventBus.stream()`, regression tests should prefer assertions on events rather than internals. For example, instead of inspecting `_running_tasks`, assert that an `Event` with `category="agent"` and `action="completed"` was emitted. This keeps the suite resilient as implementation details evolve.
