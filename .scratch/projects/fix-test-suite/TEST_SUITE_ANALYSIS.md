# TEST SUITE ANALYSIS — Remora

**Date:** 2026-03-03
**Baseline:** 1322 passed, 9 failed, 76% code coverage (5598 statements, 1368 missed)

---

## Table of Contents

1. **Suite Structure & Statistics** — Test organization, counts by directory, overall health metrics
2. **Failure Analysis** — All 9 failures categorized: 3 companion (excluded), 6 fixable with root causes and fixes
3. **Hypothesis Audit** — Current usage assessment, flakiness issues, expansion recommendations
4. **Code Coverage Gap Analysis** — Modules under 50% coverage, prioritized remediation plan
5. **Recommendations** — Prioritized action items for improving test quality and coverage

---

## 1. Suite Structure & Statistics

### Test Organization

```
tests/
├── companion/           # Companion runtime tests (under active dev — excluded from targets)
├── integration/
│   ├── cairn/           # Cairn integration tests (excluded via --ignore)
│   ├── test_cli_real.py # CLI integration tests (service startup)
│   └── test_vllm_real.py # vLLM integration tests (requires running vLLM server)
├── unit/                # Unit tests for core modules (event store, subscriptions, etc.)
├── conftest.py          # Shared fixtures + real-time test progress logging hooks
└── test_tool_script_fuzzing.py  # Hypothesis-based fuzzing test
```

### Health Metrics

| Metric | Value |
|--------|-------|
| Total tests | 1331 (1322 pass + 9 fail) |
| Pass rate | 99.3% |
| Failures | 9 (3 companion + 6 fixable) |
| Code coverage | 76% (5598 stmts, 1368 missed) |
| Hypothesis tests | 1 file, 1 test |
| Test timeout | 30s per test |

### Excluded from Test Runs

- `tests/benchmarks/` — performance benchmarks, not part of CI
- `tests/integration/cairn/` — cairn is under active development
- `tests/unit/test_graph_app.py`, `test_graph_integration.py`, `test_graph_shell.py`, `test_graph_sidebar.py`, `test_graph_state.py`, `test_web_layout.py` — graph UI tests (pre-existing exclusions)

### Test Command

```bash
devenv shell -- python -m pytest tests/ \
  --ignore=tests/benchmarks \
  --ignore=tests/integration/cairn \
  --ignore=tests/unit/test_graph_app.py \
  --ignore=tests/unit/test_graph_integration.py \
  --ignore=tests/unit/test_graph_shell.py \
  --ignore=tests/unit/test_graph_sidebar.py \
  --ignore=tests/unit/test_graph_state.py \
  --ignore=tests/unit/test_web_layout.py \
  -q --timeout=30 -s
```

---

## 2. Failure Analysis

### Summary

| # | Test | Category | Root Cause | Fix |
|---|------|----------|-----------|-----|
| 1 | `companion/test_harness.py::test_run_scenario_calls_runtime_lifecycle` | Companion | `CompanionRuntime` missing from module | Skip (under dev) |
| 2 | `companion/test_harness.py::test_run_scenario_updates_renderer_state` | Companion | Same as #1 | Skip (under dev) |
| 3 | `companion/test_renderer.py::test_all_lines_same_width` | Companion | Off-by-one: 99 vs 100 width | Skip (under dev) |
| 4 | `integration/test_vllm_real.py::test_real_vllm_tool_calling` | vLLM API | `ConstraintPipeline.no_constraints()` removed | Use `None` |
| 5 | `integration/test_vllm_real.py::test_real_vllm_grail_tool_execution` | vLLM API | Same as #4 | Use `None` |
| 6 | `test_tool_script_fuzzing.py::test_tool_script_handles_malformed_json` | Hypothesis | Deadline exceeded (286ms > 200ms) | `deadline=None` |
| 7 | `unit/test_event_store.py::test_event_store_append_and_replay` | EventStore | `graph_id` is top-level, not in payload | Fix assertion path |
| 8 | `unit/test_graph_cli.py::TestCLI::test_help_flag` | Module path | `remora_demo.graph` moved to `remora_demo.web.graph` | Update path |
| 9 | `integration/test_cli_real.py::test_service_cli_serve_serves_http` | Service | Connection refused within 10s timeout | Investigate startup |

### Companion Failures (Excluded — Under Active Development)

These 3 tests fail because the companion module is being actively rewritten. They are documented here for completeness but are **not targets for this project**.

**#1 & #2: `test_harness.py`** — `AttributeError: module 'remora.companion' has no attribute 'CompanionRuntime'`. The `CompanionRuntime` class has been removed or renamed during the companion rewrite.

**#3: `test_renderer.py`** — `test_all_lines_same_width` asserts all rendered lines are the same width, but gets 99 instead of 100. An off-by-one in the renderer's width calculation.

### Fixable Failure #4 & #5: vLLM Integration Tests

**Files:** `tests/integration/test_vllm_real.py`, `tests/integration/helpers.py`

**Error:**
```
AttributeError: type object 'ConstraintPipeline' has no attribute 'no_constraints'
```

**Root Cause:** The `structured_agents` library removed the `ConstraintPipeline.no_constraints()` class method. Production code in `kernel_factory.py:65` already passes `constraint_pipeline=None` when no grammar config is needed. The test helpers still use the old API.

**Fix:** In `tests/integration/helpers.py`, replace `constraint_pipeline=ConstraintPipeline.no_constraints()` with `constraint_pipeline=None`. Remove the unused `ConstraintPipeline` import if no other references remain.

### Fixable Failure #6: Hypothesis Flaky Deadline

**File:** `tests/test_tool_script_fuzzing.py`

**Error:**
```
hypothesis.errors.FlakyFailure: Hypothesis test_tool_script_handles_malformed_json produces
unreliable results: ... DeadlineExceeded: Test took 286.39ms, which exceeds the deadline of 200ms
```

**Root Cause:** The test spawns a subprocess for each Hypothesis example. Subprocess creation is inherently slow and variable (150-300ms+), making the default 200ms deadline unreliable.

**Fix:** Add `deadline=None` to the `@settings(...)` decorator. Subprocess-based tests should not have tight timing deadlines — the 30s pytest timeout is sufficient protection against hangs.

### Fixable Failure #7: EventStore Assertion Path

**File:** `tests/unit/test_event_store.py`

**Error:**
```
KeyError: 'graph_id'
```
at `records[0]["payload"]["graph_id"]`

**Root Cause:** `EventStore._row_to_dict()` (line 483-497) separates meta keys (`graph_id`, `event_type`, `timestamp`, etc.) from payload keys. Meta keys appear at the top level of the returned dict, not nested inside `payload`. The test incorrectly looks for `graph_id` inside `payload`.

**Fix:** Change `records[0]["payload"]["graph_id"]` to `records[0]["graph_id"]`.

### Fixable Failure #8: Graph CLI Module Path

**File:** `tests/unit/test_graph_cli.py`

**Error:**
```
No module named remora_demo.graph (returncode=1)
```

**Root Cause:** The graph viewer module was moved from `remora_demo.graph` to `remora_demo.web.graph`. The test still references the old path.

**Fix:** Change `remora_demo.graph` to `remora_demo.web.graph` in the subprocess command.

### Fixable Failure #9: Service CLI Startup

**File:** `tests/integration/test_cli_real.py`

**Error:**
```
AssertionError: Service did not start: <urlopen error [Errno 111] Connection refused>
```

**Root Cause:** The test starts `remora serve` via subprocess and probes `http://localhost:<port>/` every second for 10 seconds. The service either takes longer to start, requires configuration, or doesn't serve a response on `/`.

**Investigation Needed:** Check what endpoint the service actually exposes, whether it needs environment variables or config to start, and whether the port binding takes longer than 10s.

---

## 3. Hypothesis Audit

### Current State

Hypothesis is used in **exactly 1 file**: `tests/test_tool_script_fuzzing.py`.

That single test (`test_tool_script_handles_malformed_json`) uses:
- `@given(st.text())` to generate random strings as malformed JSON input
- `@settings(max_examples=20)` to limit test count
- Subprocess execution per example (spawns `python -m remora.tools.script`)

### Issues

1. **Flaky deadline** — The default 200ms deadline is too tight for subprocess-based tests. Each subprocess creation takes 150-300ms+ depending on system load. This causes intermittent `DeadlineExceeded` failures.

2. **Single test** — Having only 1 Hypothesis test means we're barely using property-based testing. This is a missed opportunity for a system built around events, serialization, and state machines.

### Recommendations for Expansion

High-value areas where Hypothesis would add significant confidence:

| Area | Strategy | Priority |
|------|----------|----------|
| **Event serialization** | Roundtrip: generate events → serialize → deserialize → assert equal | High |
| **EventStore append/replay** | Generate event sequences → append → replay → verify ordering and content | High |
| **Subscription filtering** | Generate events + filter predicates → verify subscriptions fire correctly | High |
| **AgentNode construction** | Generate valid/invalid node data → verify validation works correctly | Medium |
| **Discovery operations** | Generate file paths + code structures → verify discovery produces valid nodes | Medium |
| **Tool script argument handling** | Fuzz various argument shapes → verify graceful handling | Medium |

---

## 4. Code Coverage Gap Analysis

### Modules Under 50% Coverage

| Module | Coverage | Statements | Missed | Notes |
|--------|----------|------------|--------|-------|
| `adapters/starlette.py` | 15% | ~100 | ~85 | Web adapter — requires HTTP request mocking |
| `core/workspace.py` | 23% | ~80 | ~62 | Cairn workspace integration (skip — cairn under dev) |
| `lsp/__init__.py` | 28% | ~50 | ~36 | LSP server initialization |
| `lsp/handlers/hover.py` | 28% | ~40 | ~29 | LSP hover handler |
| `lsp/notifications.py` | 30% | ~60 | ~42 | LSP notification dispatch |
| `lsp/__main__.py` | 33% | ~30 | ~20 | LSP entry point |
| `core/cairn_bridge.py` | 39% | ~80 | ~49 | Cairn bridge (skip — cairn under dev) |
| `service/chat_service.py` | 40% | ~100 | ~60 | Chat service — vLLM interaction |
| `core/manifest.py` | 44% | ~90 | ~50 | Manifest loading/validation |
| `lsp/handlers/lens.py` | 48% | ~50 | ~26 | Code lens handler |
| `lsp/handlers/commands.py` | 17% | ~100 | ~83 | LSP command execution — very low |

### Analysis

**Skip (external dependencies under active dev):**
- `core/workspace.py` and `core/cairn_bridge.py` — cairn integration, skip per project rules

**Hard to test (infrastructure):**
- `adapters/starlette.py` — requires ASGI test client setup with full middleware stack
- `lsp/__init__.py`, `lsp/__main__.py` — server lifecycle, requires LSP protocol mocking

**Good candidates for coverage improvement:**
- `lsp/handlers/commands.py` (17%) — most logic is dispatch, can be unit tested with mocked server
- `lsp/handlers/hover.py` (28%) — hover data formatting, testable with fixture data
- `lsp/notifications.py` (30%) — notification dispatch, testable with mock transport
- `core/manifest.py` (44%) — manifest parsing, very testable with fixture files
- `service/chat_service.py` (40%) — integration test territory, partially covered by vLLM tests
- `lsp/handlers/lens.py` (48%) — code lens generation, testable with fixture data

---

## 5. Recommendations

### Immediate (This Project)

1. **Fix all 6 non-companion failures** — straightforward fixes, all root-caused above
2. **Fix Hypothesis flakiness** — add `deadline=None` to subprocess test
3. **Add 3-5 new Hypothesis tests** in high-value areas (events, subscriptions, event store)

### Short-Term (Next Sprint)

4. **Improve `lsp/handlers/commands.py` coverage** (17% → 60%+) — largest gap in testable code
5. **Add manifest parsing tests** to improve `core/manifest.py` (44% → 70%+)
6. **Add LSP notification tests** to improve `lsp/notifications.py` (30% → 60%+)

### Medium-Term

7. **Set up ASGI test client** for `adapters/starlette.py` coverage
8. **Add LSP protocol mocking** infrastructure for comprehensive handler testing
9. **Establish coverage gates** — e.g., no new module below 50% coverage

### Not Recommended

- Do NOT pursue cairn-related coverage (`workspace.py`, `cairn_bridge.py`) until cairn stabilizes
- Do NOT chase 100% on LSP entry points (`__init__.py`, `__main__.py`) — low ROI
