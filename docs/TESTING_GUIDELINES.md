Remora V2 ships with phase-aligned unit suites and a focused integration signal. The primary goals:

1. Validate the **event bus** (pub/sub, filtering, streams, `wait_for`).
2. Confirm the **graph builder + executor** choose bundles deterministically and emit lifecycle events.
3. Verify the **workspace helpers** (per-agent Cairn workspaces, shared snapshots, cleanup).
4. Exercise the **context builder** (short/long tracks, knowledge ingestion, prompt sections).
5. Ensure dashboards and CLI consumers can replay the same **EventBus** stream.

## Unit Testing

| Phase | Targeted Module | Focus |
|-------|----------------|-------|
| 1 | `tests/unit/test_event_bus.py` | pub/sub, wildcard matching, SSE stream iteration, JSON serialization |
| 2 | `tests/test_context_manager.py` | `ContextBuilder` tracks recent actions and knowledge summaries |
| 3 | `tests/unit/test_workspace.py` | cairn workspace creation, snapshot/restore, and shared directories |

Run the full unit suite with `pytest tests/unit/ -v`. Each test should focus on observable behavior through events, workspace state, or context summaries rather than private helpers.

## Integration Testing

Integration tests should stitch discovery → metadata-driven graph → execution → dashboard events, asserting that the EventBus produces the expected lifecycle. The future integration suite will exercise `GraphExecutor`, the dashboard SSE endpoints, and `ResultSummary` propagation.

Run the integration suite with `pytest tests/integration/ -v`. These tests expect a real vLLM server (see `tests/config/vllm_server.yaml` for defaults) and will skip when the server is unavailable.
Integration tests also depend on AgentFS (Cairn workspace backing). When AgentFS is unavailable, vLLM-backed integration tests will skip.

The concurrent agent workflow test (`tests/integration/test_agent_workflow_real.py`) uses these env vars to tune load:
- `REMORA_WORKFLOW_RUNS` (default 20)
- `REMORA_WORKFLOW_CONCURRENCY` (default 8)
- `REMORA_WORKFLOW_MIN_SUCCESS` (default 0.8)

## Monitoring & Dashboards

Since every UI consumer subscribes to `EventBus.stream()`, regression tests should assert on emitted events (e.g., `agent_completed`, `tool_result`). Keeping assertions at the public event level makes the suite resilient as internal plumbing evolves.
