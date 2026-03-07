# Context: Architecture Refactor

## Current State (2026-03-06)
Architecture refactor guide phases are implemented, and the two remaining structural issues identified from `tach_module_graph.dot` have now been addressed:

1. Handlers/notifications no longer import `remora.lsp.server` directly.
2. `remora.runner.agent_runner` no longer imports from `remora.lsp.*`.

Compatibility aliases remain for moved modules (`core/*`, `lsp/models.py`, `lsp/tools.py`) to preserve import compatibility while keeping boundaries cleaner.

## What Changed in This Session
- Added `src/remora/lsp/protocols.py` and retargeted handler/notification type references to protocol-based typing.
- Added `src/remora/runner/events.py` and `src/remora/runner/tools.py` as runner-owned modules.
- Converted `src/remora/lsp/models.py` and `src/remora/lsp/tools.py` to compatibility aliases.
- Refactored `AgentRunner` to call server-side interface methods with fallback compatibility paths, removing direct imports of `remora.lsp.*`.
- Added server helper methods in `src/remora/lsp/server.py` for proposal acceptance and LSP event emission.
- Added #3 planning-gap analysis doc:
  - `.scratch/projects/architecture_refactor/PHASE3_PLAN_GAP_ANALYSIS.md`

## Verification Performed
- Targeted LSP/runner tests passed:
  - `tests/unit/test_lsp_runner.py`
  - `tests/unit/test_runner_loop.py`
  - `tests/unit/test_llm_config.py`
  - `tests/unit/test_lsp_background_scan_manifest.py`
  - `tests/unit/test_lsp_tools.py`
  - `tests/unit/test_lsp_server.py`
  - `tests/integration/test_lsp_integration.py`

## Remaining Work
- Re-run full non-cairn suite before final merge.
- Concurrency failures in cairn safety tests remain intentionally deferred per user instruction.

## Additional Findings (2026-03-07)
- User-reported LiteLLM warning was noise from offline remote price-map fetch; now suppressed by default via:
  - `src/remora/__init__.py` sets `LITELLM_LOCAL_MODEL_COST_MAP=true` using `os.environ.setdefault`.
- Background scan manifest timeout was reproduced with real sample data and traced to scan internals:
  - `asyncio.to_thread(...)` calls in `_background_scan` can hang in this runtime path.
  - This caused test waits on `db.entered_block` to timeout, making failures look like generic async timeouts.
- Implemented mitigation in `src/remora/lsp/__main__.py`:
  - use synchronous file read + `parse_content` inside `_background_scan` loop (no `to_thread` for these steps).
  - keep preemption checkpoints/yields already present for scan fairness.
- Targeted previously failing unit tests now pass for llm-config + background-scan cases.
