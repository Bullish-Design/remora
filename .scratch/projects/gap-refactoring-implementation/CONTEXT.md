# Gap Refactoring Implementation — CONTEXT

## Current State (Updated after Workstream B completion)

Workstream A is COMPLETE. Workstream B is COMPLETE. Starting Workstream C.

### Workstream B Summary
- `execute_agent_turn()` in `src/remora/core/execution.py` is the ONE shared execution path
- `SwarmExecutor.run_agent()` delegates to it (~104 lines)
- `AgentRunner.execute_turn()` delegates to it, no more LLMClient
- LSP tools factored into `src/remora/core/tools/lsp.py`
- Full test suite: 5 pre-existing failures, zero new regressions

### What's Next: Workstream C — Unify Discovery (Gaps #3, #4, #5)
Read the GAP_REFACTORING_PLAN.md for Workstream C details. Key goals:
- Add `parse_content()` to `core/discovery.py` — a pure function that takes (uri, text, lang) and returns node dicts
- Create .scm query files for tree-sitter queries
- Refactor `ASTWatcher` in `lsp/watcher.py` to delegate to `parse_content()`
- This unifies discovery so both LSP and core paths share the same parsing logic

### Then: Workstream E (Gap #11 — trivial), then Workstream D (Gaps #12, #13)

## Key Files
- `src/remora/core/execution.py` — Shared `execute_agent_turn()` + helpers
- `src/remora/core/tools/lsp.py` — LSP tool classes
- `src/remora/core/swarm_executor.py` — Delegates to execution.py
- `src/remora/lsp/runner.py` — Delegates to execution.py, no LLMClient
- `src/remora/core/discovery.py` — NEXT TARGET for Workstream C
- `src/remora/lsp/watcher.py` — NEXT TARGET for Workstream C

## Known Pre-existing Test Failures (IGNORE)
- `test_service_cli_serve_serves_http` — uvicorn connection refused
- `test_real_vllm_tool_calling` / `test_real_vllm_grail_tool_execution` — ConstraintPipeline
- `test_event_store_append_and_replay` — KeyError in payload
- `TestCLI::test_help_flag` — `remora_demo.graph` not installed
- 6 collection errors (graph UI tests)
- 2 skips
