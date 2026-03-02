# CONTEXT — Launch Plan Execution

## Current State
- **Active batch:** Batch 2 (Track B Medium Items) — item 2.7 COMPLETE, moving to 2.8
- **Next action:** Item 2.8 (Parameterize language in system prompt)

## What Just Happened
- Completed item 2.7: Added `start_byte`/`end_byte` to `NodeDiscoveredEvent`
  - Added fields with default=0 to `NodeDiscoveredEvent` (events.py)
  - Added columns to nodes table schema (event_store.py)
  - Added migration for existing DBs in `_migrate_routing_fields()`
  - Updated `NodeProjection` row dict + ON CONFLICT upsert clause
  - Added `start_byte`/`end_byte` to `AgentNode` Pydantic model
  - Updated watcher to emit byte offsets (tree-sitter nodes provide them; fallback uses 0)
  - Updated all 3 LSP handler call sites to pass `nd.get("start_byte", 0)`
  - Wrote TDD tests in test_node_events.py and test_projections.py
  - Full test suite passes (only failure: `test_real_vllm_grail_tool_execution` — needs running vLLM server)

## Key Context for Resumption
- Master task list: `REMORA_LAUNCH_PLAN.md` (root)
- Execution plan: `.scratch/projects/launch-plan-execution/PLAN.md`
- Progress tracker: `.scratch/projects/launch-plan-execution/PROGRESS.md`
- Test command: `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py -q`
- All work is in `src/remora/` — `remora_demo/` is out of scope
- Tests in `tests/unit/test_graph_*.py` and `tests/unit/test_web_layout.py` depend on `remora_demo` — ignore them

## Batch 2 Remaining Items (suggested order)
- **2.8**: Parameterize language in system prompt (`agent_node.py:128` hardcodes "Python")
- **2.3**: Hardcoded LLM configs — short-term fix (make `lsp/__main__.py` read from Config)
- **2.6**: Populate or remove `last_trigger_event` dead schema
- **2.2**: SubscribeTool self-referencing bug (needs design decision)
- **2.5**: Widen `AgentExtension.matches()` API
- **2.4**: Reconciler stale metadata bug
- **2.9**: Subscription index for O(1) lookup
- **2.1**: RemoraDB dual-write elimination (largest item, ~1 day)
- **2.10–2.12**: Test writing (ChatSession, service/, Phase 1 gaps)

## How to Resume
1. Read `.scratch/CRITICAL_RULES.md`
2. Read `.scratch/REPO_RULES.md`
3. Read this file
4. Continue with next Batch 2 item (2.8)
