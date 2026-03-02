# tests/ — Shadow Tree Notes

## Status: MODIFY (clean up old tests, keep EventBased tests)

### Unit tests (tests/unit/) — KEEP + MODIFY:
- `test_agent_node.py` — Phase 1 AgentNode tests. KEEP.
- `test_event_store.py` — Phase 1 EventStore tests. KEEP.
- `test_event_store_projection.py` — Phase 1 projection tests. KEEP.
- `test_event_store_nodes_query.py` — Phase 1 nodes query tests. KEEP.
- `test_node_events.py` — Phase 1 event tests. KEEP.
- `test_nodes_table.py` — Phase 1 nodes table tests. KEEP.
- `test_extensions.py` — Phase 1 extensions tests. KEEP.
- `test_projections.py` — Phase 1 projections tests. KEEP.
- `test_event_bus.py` — EventBus tests. KEEP.
- `test_subscriptions.py` — Subscription tests. KEEP.
- `test_swarm_state.py` — SwarmState tests. REMOVE after Option A completes.
- `test_lsp_*.py` — LSP tests. MODIFY during Option A.
- `test_graph_*.py` — Graph viewer tests. KEEP (for remora_demo).
- `test_web_layout.py` — Web layout tests. KEEP.
- `test_command_*.py` — Command queue tests. KEEP (LSP feature).

### Integration tests (tests/integration/) — MODIFY:
- `test_agent_node_pipeline.py` — Phase 1 integration test. KEEP.
- `test_event_store_integration.py` — EventStore integration. KEEP.
- `test_lsp_integration.py` — LSP integration. MODIFY during Option A.
- `cairn/` — 10 cairn integration tests. KEEP for now (cairn dependency).
- `test_agent_runner.py`, `test_reconcile_real.py`, `test_swarm_store.py` — MODIFY.
- `test_cli_real.py`, `test_vllm_real.py`, `test_multilanguage_discovery_real.py`, `test_real_code_discovery_real.py` — KEEP.

### Root-level tests:
- `test_discovery.py` — KEEP.
- `test_main.py` — KEEP.
- `test_tool_script_fuzzing.py` — Grail script fuzzing. KEEP for now.

### Test infrastructure:
- `conftest.py` — KEEP, update.
- `helpers.py` — KEEP.
- `fixtures/` — KEEP.
- `utils/` — KEEP.
- `roundtrip/` — Roundtrip test harness. KEEP.
- `benchmarks/` — Discovery performance. KEEP.
- `snapshots/` — Syrupy snapshots. KEEP.
