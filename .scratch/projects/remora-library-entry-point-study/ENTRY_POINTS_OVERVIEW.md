# Remora Entry Points Overview (Study-First Map)

This guide is a practical reading order for understanding Remora quickly and correctly.

## 0) Start With Concept + Surface

1. `docs/overview.md`
Why first:
- Fast mental model of discovery -> events -> reactions.

2. `docs/ARCHITECTURE.md`
Why second:
- Defines core boundaries (EventStore, projection, runner, LSP adapter).

3. `pyproject.toml` (`[project.scripts]`)
Why third:
- Shows all executable entry surfaces and their module targets.

## 1) External Runtime Entry Points (Actual Process Starts)

4. `src/remora/__main__.py`
What it is:
- `python -m remora` module entrypoint; delegates to CLI.

5. `src/remora/cli/main.py`
What it is:
- Main command surface: `swarm` and `serve`.
- Key handoffs:
  - `swarm start` -> prepares EventStore/subscriptions/projection/reconcile, then starts runner.
  - `swarm start --lsp` -> same preparation, then hands off to `remora.lsp.__main__.main`.
  - `serve` -> builds `RemoraService` and starts Starlette/Uvicorn.

6. `src/remora/lsp/__main__.py`
What it is:
- LSP process bootstrap with workspace lock, DB/event setup, runner wiring, and IO transport.
- This is the highest-value runtime entry point for editor-driven usage.

7. `src/remora/service/api.py`
8. `src/remora/adapters/starlette.py`
What they are:
- Framework-agnostic service API + HTTP adapter routes/lifespan wiring.

## 2) Core Runtime Handoffs (Read Immediately After Entrypoints)

9. `src/remora/core/config.py`
10. `src/remora/core/runtime_paths.py`
Why now:
- These define how all entry points resolve workspace, swarm, events, and model config.

11. `src/remora/core/code/discovery.py`
Why now:
- Discovery is the source of node identity and node events.

12. `src/remora/core/code/reconciler.py`
Why now:
- Startup sync logic: discovered nodes vs projected nodes, plus subscription defaults.

13. `src/remora/core/store/event_store.py`
14. `src/remora/core/code/projections.py`
15. `src/remora/core/store/node_store.py`
Why now:
- This trio is the center of the architecture:
  - append-only events
  - materialized node read model
  - query/update surface for agents

16. `src/remora/core/events/subscriptions.py`
17. `src/remora/core/events/event_bus.py`
Why now:
- Explains routing from events to triggered agent execution.

## 3) Agent Execution Path (What Actually Runs on Trigger)

18. `src/remora/runner/agent_runner.py`
19. `src/remora/runner/turn_logic.py`
20. `src/remora/core/agents/execution.py`
21. `src/remora/core/agents/agent_node.py`
Why this block:
- Queue + trigger controls (cooldown/depth/concurrency), then unified turn execution, then AgentNode behavior and LSP render helpers.

## 4) LSP Behavior Layer (Editor UX Wiring)

22. `src/remora/lsp/server.py`
23. `src/remora/lsp/server_setup.py`
24. `src/remora/lsp/handlers/documents.py`
25. `src/remora/lsp/handlers/commands.py`
26. `src/remora/lsp/background_scanner.py`
27. `src/remora/lsp/db.py`
Why this block:
- Shows how editing operations, commands, and background scans generate events and interact with the runner/event store.
- `lsp/db.py` clarifies what state is LSP-local vs event-sourced core.

## 5) Bootstrap + Extension Layer (Advanced, But Important)

28. `src/remora/bootstrap/runner.py`
29. `src/remora/bootstrap/coordinator.py`
30. `src/remora/bootstrap/activation.py`
31. `src/remora/extensions.py`
Why here:
- Covers dynamic assignment/activation of bootstrap agents and extension matching from `.remora/models/`.

## End-to-End Call Chains To Trace

### A) Headless Swarm
`remora` script -> `src/remora/cli/main.py` (`swarm start`) -> config/runtime paths -> EventStore + SubscriptionRegistry + NodeProjection -> `reconcile_on_startup()` -> `AgentRunner.run_forever()` + `run_from_event_store()`.

### B) Editor LSP
`remora-lsp` script -> `src/remora/lsp/__main__.py` (`main/_prepare/_run_server`) -> `register_handlers()` -> `RemoraLanguageServer` + `AgentRunner` + `BackgroundScanner` -> document handlers append events -> subscriptions trigger runner.

### C) HTTP Service
`remora` script -> `src/remora/cli/main.py` (`serve`) -> `RemoraService.create_default()` -> `create_app()` (Starlette routes/lifespan) -> service handlers consume event/projector state.

## Suggested Study Sessions

1. Session 1: Docs + scripts + CLI/LSP bootstrap (`overview`, `architecture`, `pyproject`, `cli/main`, `lsp/__main__`)
2. Session 2: Core data loop (`discovery`, `reconciler`, `event_store`, `projections`, `subscriptions`)
3. Session 3: Execution loop (`agent_runner`, `turn_logic`, `execution`, `agent_node`)
4. Session 4: Adapter specifics (`lsp/server + handlers + scanner + db`, `service/api + starlette`)
5. Session 5: Advanced behavior (`bootstrap/*`, `extensions.py`, then selected tests)

## Tests Worth Reading Alongside

- `tests/unit/test_lsp_entrypoint.py`
- `tests/unit/test_cli_commands.py`
- `tests/unit/test_event_store_projection.py`
- `tests/unit/test_event_store_queries.py`
- `tests/unit/test_subscriptions.py`
- `tests/integration/test_event_store_integration.py`
- `tests/integration/test_bootstrap_loop.py`

## Noted Repository Detail

- `pyproject.toml` defines `remora-index = "remora.indexer.cli:main"` but this repository snapshot does not include `src/remora/indexer/`. Treat this as a potential stale script target unless defined externally.
