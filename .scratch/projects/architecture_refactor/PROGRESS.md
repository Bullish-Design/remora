# Progress: Architecture Refactor

## Phase Status (Guide V2)
- [x] Phase 1: Sever core -> outer-layer dependencies
- [x] Phase 2: Break LSP circular startup/registration dependencies (functional)
- [x] Phase 3: Decompose large modules
- [x] Phase 4: Reorganize core into subpackages
- [x] Phase 5: Introduce `remora.runner` package + protocol
- [x] Phase 6: Cleanup/polish items (language map + query dir rename + compatibility)

## Follow-up Gap Closure (2026-03-06)
- [x] #1 Remove remaining `handlers/notifications -> lsp.server` imports
- [x] #2 Remove remaining `runner.agent_runner -> remora.lsp.*` imports
- [x] Added analysis document for #3 design/planning gap:
  - `PHASE3_PLAN_GAP_ANALYSIS.md`

## Test Status
- Targeted LSP/runner suite: passing
  - `tests/unit/test_lsp_runner.py`
  - `tests/unit/test_runner_loop.py`
  - `tests/unit/test_llm_config.py`
  - `tests/unit/test_lsp_background_scan_manifest.py`
  - `tests/unit/test_lsp_tools.py`
  - `tests/unit/test_lsp_server.py`
  - `tests/integration/test_lsp_integration.py`

## Deferred
- Concurrency failures in `tests/integration/cairn/test_concurrent_safety.py` remain intentionally deferred per user instruction.

## Post-Refactor Follow-up (2026-03-07)
- [x] Suppressed offline LiteLLM startup warning by defaulting:
  - `LITELLM_LOCAL_MODEL_COST_MAP=true` in `src/remora/__init__.py`.
- [x] Reproduced background scan timeout against real sample data (not just unit test doubles).
- [x] Identified root cause:
  - `asyncio.to_thread(...)` usage in `_background_scan` hangs in this runtime path, preventing progress to `update_edges` call 11 within 5s.
- [x] Fixed `_background_scan` by switching sample-file read/parse to synchronous calls in the scan task.
- [x] Re-verified targeted failing tests now pass:
  - `tests/unit/test_lsp_background_scan_manifest.py::test_background_scan_saves_partial_manifest_before_completion`
  - `tests/unit/test_lsp_background_scan_manifest.py::test_background_scan_uses_aggressive_preemption_settings`
  - `tests/unit/test_llm_config.py::TestLspMainUsesConfig::test_lsp_main_reads_config`
