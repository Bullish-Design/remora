# Context

Implementation phase completed for sidebar-response-missing, following
`.scratch/projects/sidebar-response-missing/IMPLEMENTATION_GUIDE.md` end-to-end.

What was completed in this pass:
- Added typed `AgentTextResponseEvent` and registered it in core event exports/union.
- Added `agent_id` column/index to `events` schema and migration path.
- Updated EventStore writes (`append`, `batch_append`) to persist `agent_id`.
- Replaced overloaded history query with:
  - `get_agent_timeline()` / `fetch_agent_timeline_rows()`
  - `get_routed_messages()` / `fetch_routed_message_rows()`
- Updated replay dict normalization to include top-level `agent_id`.
- Updated LSP live notify to include persisted `id` for live/replay dedupe parity.
- Added `RunnerEventEmitter.emit_agent_text_response()` and switched AgentRunner callsite.
- Updated AgentRunner and TurnContext chat history assembly to include `AgentTextResponse` assistant turns.
- Updated panel/hover/bootstrap callsites to use `get_agent_timeline`.
- Added `agent_id` field on `BootstrapEvent` and populated it on `_event_write`.
- Fixed hover summary extraction for replay events (`summary` top-level fallback).
- Updated tests:
  - rewrote `tests/unit/test_event_store_queries.py` for new API semantics
  - updated `tests/unit/bootstrap/test_bedrock.py`
  - updated `tests/unit/test_execution.py` mocks to new method name
  - added `tests/unit/test_event_store_regression.py`

Validation run results:
- Passed: `tests/unit/test_event_store_queries.py -v`
- Passed: `tests/unit/bootstrap/test_bedrock.py -v`
- Passed: `tests/unit/test_event_store_regression.py -v`
- Passed (additional impacted suites): `test_execution.py`, `test_runner_loop.py`,
  `test_agent_node.py`, `test_lsp_models.py`, `test_lsp_background_scan_manifest.py`,
  `bootstrap/test_activation.py`, `bootstrap/test_runner.py`
- Full suite command (`pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`)
  still fails during collection on an existing unrelated issue:
  `ImportError: cannot import name '_lang_tag_for' from remora.core.agents.execution`
  in `tests/unit/test_swarm_executor.py`.

Key decisions locked in:
- No backward-compatibility shim for `get_recent_events`; all callsites moved to new APIs.
- `AgentTextResponseEvent` keeps `payload` sub-dict (`payload["content"]`) for panel compatibility.
- Event type literal remains `\"AgentTextResponse\"`.
- Typed response emission uses direct `emit_event`.
