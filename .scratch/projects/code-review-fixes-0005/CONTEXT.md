# CONTEXT: Code Review 0005 Fixes

All planned fixes for code-review-fixes-0005 are now implemented.

## Current State
- Phase 1 completed earlier (critical import/dispatcher/discovery fixes).
- Phase 2 completed:
  1. `EventStore`/`NodeStore` split finalized; node mutations moved to `event_store.nodes.*` and wrapper methods removed from `EventStore`.
  2. `AgentRunner` emission helpers extracted to `src/remora/runner/event_emitter.py`.
  3. Event hierarchy unified in `core.events.events`; `src/remora/runner/events.py` deleted.
- Phase 3 completed:
  - Simplified `EventStore.batch_append` instrumentation (removed excessive inline logging noise).
  - Extracted workspace scan logic into `src/remora/lsp/background_scanner.py`.
  - Unified skip-dir configuration through `Config.workspace_ignore_patterns`.
  - Removed timestamp sentinel pattern (`timestamp=0.0`) and deprecated `asyncio.get_event_loop()` calls.
  - Added type hints / declared server runtime attributes.
  - Removed unused imports and dead hook (`model_post_init` no-op).
  - Optimized `EventBus` dispatch with MRO/cache-based handler resolution.
  - Replaced dynamic f-string node INSERT SQL with a constant statement.
  - Added explicit `__all__` exports where called out in review.

## Validation
- `devenv shell -- ruff check` on all touched Python modules passed.
- Targeted regression tests for runner/LSP/events/store passed:
  - `tests/unit/test_event_store_nodes_query.py`
  - `tests/unit/test_lsp_notifications.py`
  - `tests/unit/test_lsp_models.py`
  - `tests/unit/test_unified_events.py`
  - `tests/unit/test_unified_runner.py`
  - `tests/unit/test_event_bus.py`
  - `tests/unit/test_batch8_fixes.py`
