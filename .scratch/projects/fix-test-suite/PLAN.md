# PLAN — Fix Failing Tests & Improve Test Suite

**ABSOLUTE RULE: NO SUBAGENTS — NEVER use the Task tool. Do ALL work directly.**

---

## Phase 1: Analysis & Documentation
1. Write `TEST_SUITE_ANALYSIS.md` — comprehensive document covering suite structure, all failures with root causes, Hypothesis audit, coverage gaps.

## Phase 2: Fix Failing Tests (6 fixable failures)

### 2a. vLLM Integration Tests (2 failures)
- **Files:** `tests/integration/test_vllm_real.py`, `tests/integration/helpers.py`
- **Fix:** Replace `ConstraintPipeline.no_constraints()` with `constraint_pipeline=None`
- Both `test_real_vllm_tool_calling` and `test_real_vllm_grail_tool_execution` share the same root cause.

### 2b. Hypothesis Flaky Test (1 failure)
- **File:** `tests/test_tool_script_fuzzing.py`
- **Fix:** Add `deadline=None` to `@settings(...)` decorator (subprocess tests are inherently slow).

### 2c. EventStore Test (1 failure)
- **File:** `tests/unit/test_event_store.py`
- **Fix:** Change `records[0]["payload"]["graph_id"]` to `records[0]["graph_id"]` (meta keys are top-level, not in payload).

### 2d. Graph CLI Test (1 failure)
- **File:** `tests/unit/test_graph_cli.py`
- **Fix:** Change `remora_demo.graph` to `remora_demo.web.graph`.

### 2e. Service CLI Test (1 failure)
- **File:** `tests/integration/test_cli_real.py`
- **Fix:** Investigate why `remora serve` doesn't respond within 10s. May need config, longer timeout, or different health endpoint.

## Phase 3: Verify All Fixes
- Run full test suite (excluding benchmarks, cairn, known graph UI tests).
- Target: 0 non-companion failures.

## Phase 4: Expand Hypothesis Usage
- Add property-based tests to high-value areas:
  - Event serialization/deserialization roundtrips
  - EventStore append/replay invariants
  - Subscription filtering logic
  - Discovery/workspace operations
  - Node projection consistency

## Phase 5: Final Verification & Documentation
- Run full suite one more time.
- Update PROGRESS.md with final results.
- Update CONTEXT.md with completion summary.

---

**ABSOLUTE RULE: NO SUBAGENTS — NEVER use the Task tool. Do ALL work directly.**
