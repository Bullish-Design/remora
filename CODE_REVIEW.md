# Remora Refactor Review

**Findings**
- Critical: Swarm execution never actually runs because `swarm start` never instantiates an `AgentRunner`, and `EventStore.set_subscriptions()` does not create a trigger queue when subscriptions are attached post-initialize; `EventStore.get_triggers()` then returns `None`, so no triggers are delivered. See `src/remora/cli/main.py:34`, `src/remora/core/event_store.py:39`, `src/remora/core/event_store.py:167`, `src/remora/core/agent_runner.py:74`.
- Critical: Neovim JSON-RPC requests will fail because handler functions are stored as unbound methods and invoked without binding; additionally, `_broadcast_event` is never subscribed to any EventBus so Neovim never receives event notifications. See `src/remora/nvim/server.py:100`, `src/remora/nvim/server.py:224`, `src/remora/nvim/server.py:241`.
- High: `AgentRunner` is a stub that never runs real agent logic and emits lifecycle events only on `EventBus`, bypassing `EventStore.append()` so downstream subscriptions never trigger; it also ignores `config.swarm` and uses `config.execution` instead. See `src/remora/core/agent_runner.py:63`, `src/remora/core/agent_runner.py:160`, `src/remora/core/agent_runner.py:208`.
- High: Graph-era execution remains the primary interface (CLI `run`, service `/run`/`/plan`, graph events/exports), which violates the “no backwards compatibility” requirement. See `src/remora/cli/main.py:225`, `src/remora/service/handlers.py:47`, `src/remora/core/events.py:30`, `src/remora/__init__.py`.
- High: Config + workspace layout are still graph-oriented (nested `RemoraConfig`, YAML examples with indexer/checkpoint fields, graph-scoped workspace services), so the per-agent persistent `workspace.db` and flat config described in the refactor docs are not implemented. See `src/remora/core/config.py:38`, `remora.yaml`, `remora.yaml.example`, `src/remora/core/cairn_bridge.py:24`, `src/remora/core/workspace.py:107`.
- Medium: Reconciliation only handles create/delete, not changed nodes or `ContentChangedEvent` emission; default subscriptions use absolute paths from discovery, but CLI/Nvim emit raw paths, so `path_glob` matching will likely never fire. This is compounded by docs/tests still referencing removed systems (indexer/checkpoint) and no swarm integration tests. See `src/remora/core/reconciler.py:62`, `src/remora/cli/main.py:202`, `src/remora/nvim/server.py:143`, `tests/integration/test_indexer_daemon_real.py`, `tests/integration/test_checkpoint_roundtrip.py`, `README.md`.

**Open Questions / Assumptions**
- Should all graph execution surfaces (`GraphExecutor`, CLI `run`, service `/run`, graph events) be removed entirely to enforce the new swarm-only model?
- Is `graph_id` meant to be removed from the event schema, or should it be replaced with a single swarm/session identifier?
- What is the canonical format for `ContentChangedEvent.path` (absolute vs project-relative) so subscriptions can match deterministically?

**Change Summary**
- No code changes made; analysis only.
