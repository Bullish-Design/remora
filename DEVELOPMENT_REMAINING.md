# Development Remaining: Remora MVP Completion

**Document Version:** 1.0  
**Last Updated:** 2026-02-18  
**Status:** Post-Refactoring Planning

## Executive Summary

This document outlines the remaining work to complete the Remora MVP after the architectural refactoring to tightly integrate **Cairn** (workspace execution), **Grail** (`.pym` validation/runtime), and **Pydantree** (CST discovery). 

### Background

Remora is a local code analysis and enhancement tool that uses fine-tuned FunctionGemma subagents (~288MB each, Q8 quantized) to analyze Python code entirely offline. The original dev guide progressed through **Step 13** (end-to-end runner integration tests) before the decision to refactor the architecture for tighter integration with the three foundational libraries.

### Refactoring Goals

The refactoring aims to:
1. **Use Cairn as the only execution runtime** — CLI-first, not in-process API
2. **Use Grail as the only `.pym` validator and executor** — Grail-first tool schemas
3. **Use Pydantree as the only discovery engine** — replacing AST-based discovery
4. **Unify the event stream** — single timeline across discovery, validation, execution, and submission

---

## What Was Completed (Steps 1-13)

The following work was completed before the refactoring:

| Step | Description | Status |
|------|-------------|--------|
| 0 | vLLM Server Setup | ✅ Complete |
| 1 | Project Skeleton + Dependencies | ✅ Complete |
| 2 | Configuration System | ✅ Complete |
| 3 | Query Files + Node Discovery (AST-based) | ⚠️ Legacy — being replaced |
| 4 | Subagent Definition Format | ✅ Complete |
| 5 | FunctionGemmaRunner — Model Loading + Context | ✅ Complete |
| 6 | FunctionGemmaRunner — Multi-Turn Loop | ✅ Complete |
| 7 | Coordinator — Runner Dispatch | ✅ Complete |
| 8 | Lint Subagent Tool Scripts | ✅ Files exist, need Grail compliance |
| 9 | Test Subagent Tool Scripts | ✅ Files exist, need Grail compliance |
| 10 | Docstring Subagent Tool Scripts | ✅ Files exist, need Grail compliance |
| 11 | Sample Data Subagent Tool Scripts | ✅ Files exist, need Grail compliance |
| 12 | Runner Adaptation for OpenAI HTTP Client | ✅ Complete |
| 13 | End-to-End Runner Integration Test | ✅ Complete (pre-refactor) |

---

## Remaining Work Overview

The remaining work is organized into **four tracks** that can proceed in parallel after an initial cleanup phase:

1. **Track A: Pre-Refactoring Cleanup** — Bug fixes and code improvements
2. **Track B: Grail Compliance** — All `.pym` files must pass `grail check --strict`
3. **Track C: Test Architecture Migration** — Tests must use Grail runtime harness
4. **Track D: Architectural Rewrite** — Core refactoring to integrate Cairn, Grail, and Pydantree

---

## Track A: Pre-Refactoring Cleanup

These issues from `REFACTORING.md` should be addressed before starting the architectural rewrite. They are correctness bugs or performance issues that affect the current codebase.

### A1. Bug Fixes (Priority: High)

| Issue | File | Description | Fix |
|-------|------|-------------|-----|
| AGENT_003 reused for two failure modes | `remora/runner.py` | Both "no tool call" and "turn limit exceeded" use same error code | Add `AGENT_004` for turn-limit exhaustion |
| `_build_submit_result` raises uncaught ValidationError | `remora/runner.py` | Model returning unexpected status string causes crash | Wrap in try/except, normalize status values |
| Orchestrator loses AgentError fields | `remora/orchestrator.py` | `phase` and `error_code` discarded on re-emit | Check exception type, preserve structured fields |

### A2. Performance & Code Quality (Priority: Medium)

| Issue | File | Description | Fix |
|-------|------|-------------|-----|
| `tools_by_name` recomputed on every access | `remora/subagent.py` | Called 100+ times per agent run | Use `@cached_property` or `model_post_init` |
| Duplicate tool names silently overwritten | `remora/subagent.py` | No validation for duplicate names | Add `_validate_tool_names()` check |
| Jinja2 template syntax not validated at load time | `remora/subagent.py` | Errors surface at render time, not load time | Validate templates in `load_subagent_definition()` |
| `watch_task` created per `process_node` call | `remora/orchestrator.py` | Causes resource leak in batch runs | Move to `__init__`, add async context manager |
| `socket.getaddrinfo` blocks main thread | `remora/config.py` | DNS lookup can hang for 5-10 seconds | Run in thread pool with 1-second timeout |

### A3. Low Priority Fixes

- **B9:** Missing error codes `CONFIG_001`, `CONFIG_002` — either define or renumber
- **B10:** Document `OperationConfig.extra="allow"` intention
- **B11:** `CSTNode` naming — add comment explaining AST vs CST
- **B12:** CLI exit code 3 is non-standard; add `--version` flag

---

## Track B: Grail Compliance (All `.pym` Files)

All 21 `.pym` files across the four subagents must pass `grail check --strict`. This is a **hard prerequisite** for the architectural rewrite (Track D).

### Current `.pym` Inventory

**Lint Subagent (4 tools + 1 context):**
- `agents/lint/tools/run_linter.pym`
- `agents/lint/tools/apply_fix.pym`
- `agents/lint/tools/read_file.pym`
- `agents/lint/tools/submit.pym`
- `agents/lint/context/ruff_config.pym`

**Test Subagent (5 tools + 1 context):**
- `agents/test/tools/analyze_signature.pym`
- `agents/test/tools/read_existing_tests.pym`
- `agents/test/tools/write_test_file.pym`
- `agents/test/tools/run_tests.pym`
- `agents/test/tools/submit.pym`
- `agents/test/context/pytest_config.pym`

**Docstring Subagent (4 tools + 1 context):**
- `agents/docstring/tools/read_current_docstring.pym`
- `agents/docstring/tools/read_type_hints.pym`
- `agents/docstring/tools/write_docstring.pym`
- `agents/docstring/tools/submit.pym`
- `agents/docstring/context/docstring_style.pym`

**Sample Data Subagent (3 tools + 1 context):**
- `agents/sample_data/tools/analyze_signature.pym`
- `agents/sample_data/tools/write_fixture_file.pym`
- `agents/sample_data/tools/submit.pym`
- `agents/sample_data/context/existing_fixtures.pym`

### Compliance Checklist per File

For each `.pym` file, verify:

- [ ] **Imports:** Only `from grail import external, Input` and `from typing import Any`
- [ ] **Inputs:** Every `Input()` has a type annotation on the LHS
- [ ] **Externals:** Every `@external` has full parameter + return annotations and body `...`
- [ ] **No unsupported syntax:** No `class`, `yield`, `with`, `match`, `lambda`
- [ ] **Executable section:** All work at module scope, not inside `main()`
- [ ] **submit_result:** Declared with `@external` and called before final return
- [ ] **Final return:** Last expression is a meaningful `dict`

### Validation Command

```bash
grail check --strict agents/<path>.pym
```

Check generated artifacts under `.grail/<script_name>/`:
- `check.json` — `"valid": true`
- `monty_code.py` — executable code without declarations
- `inputs.json` — declared inputs
- `externals.json` — declared externals

---

## Track C: Test Architecture Migration

Tests currently import `.pym` files via `SourceFileLoader`, bypassing Grail entirely. All tool tests must migrate to the Grail runtime harness.

### C1. Create Shared Test Harness

**File:** `tests/utils/grail_runtime.py`

```python
"""Shared Grail runtime test harness."""
from pathlib import Path
from typing import Any

def load_script(path: Path, grail_dir: Path | None = None):
    """Load a .pym script via grail.load()."""
    import grail
    return grail.load(path, grail_dir=grail_dir)

def run_script(
    path: Path,
    inputs: dict[str, Any],
    externals: dict[str, Any],
    files: dict[str, Any] | None = None,
    grail_dir: Path | None = None,
) -> dict[str, Any]:
    script = load_script(path, grail_dir=grail_dir)
    return script.run_sync(inputs=inputs, externals=externals, files=files or {})

def assert_artifacts(grail_dir: Path, script_name: str) -> None:
    base = grail_dir / script_name
    assert (base / "check.json").exists(), f"Missing check.json for {script_name}"
    assert (base / "monty_code.py").exists(), f"Missing monty_code.py for {script_name}"
    assert (base / "stubs.pyi").exists(), f"Missing stubs.pyi for {script_name}"
```

### C2. Add Grail Validation Test

**File:** `tests/test_pym_validation.py`

```python
"""Validate every .pym file with grail check --strict."""
import pytest
from pathlib import Path

PYM_FILES = list((Path(__file__).parent.parent / "agents").rglob("*.pym"))

@pytest.mark.parametrize("pym_path", PYM_FILES, ids=lambda p: p.stem)
def test_grail_check_strict(pym_path: Path) -> None:
    import grail
    script = grail.load(pym_path)
    result = script.check(strict=True)
    assert result.valid, f"{pym_path} failed grail check:\n" + "\n".join(result.diagnostics)
```

### C3. Migrate Tool Tests

Replace `SourceFileLoader` with `run_script` from the harness in:
- `tests/test_lint_tools.py`
- `tests/test_docstring_tools.py`
- `tests/test_test_tools.py`
- `tests/test_sample_data_tools.py`

### C4. Update pytest Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "integration: requires live Cairn/vLLM server",
    "grail_runtime: exercises Grail runtime execution",
]
```

CI requirements:
- `pytest -m "not integration"` must include Grail runtime tests
- `pytest -m grail_runtime` is a required CI step

---

## Track D: Architectural Rewrite (Cairn + Grail + Pydantree)

This is the core refactoring work. **Do not begin until Track B and Track C are complete.**

### Phase D0: Delete Parallel Runtimes

- [ ] Remove AST-based `NodeDiscoverer` and `_iter_python_files`
- [ ] Remove any in-process `.pym` execution from `FunctionGemmaRunner` and `CairnClient`
- [ ] Remove manual tool parameter schemas from YAML subagent definitions (schemas become Grail-first)

### Phase D1: Grail Tool Registry

Build a catalog builder that runs `grail check --strict` and reads artifacts:

**Target directory structure:**
```
.grail/agents/{agent_id}/
  check.json        ← validation status + warnings
  inputs.json       ← parameter schema (source of truth)
  externals.json    ← external function signatures
  stubs.pyi
  monty_code.py
```

**Schema assembly rules:**
1. Start with `inputs.json` from Grail
2. Apply YAML overrides (`tool_name`, `tool_description`, `inputs_override`)
3. Emit warnings if overrides change `type`, `required`, or `default` relative to Grail
4. Final schema is what is surfaced to the model via `tools=`

### Phase D2: Cairn Execution Bridge (CLI-first)

Replace in-process `CairnClient.run_pym` with a subprocess bridge:

```python
class CairnCLIClient:
    async def run_pym(self, path: Path, workspace_id: str,
                      inputs: dict[str, Any]) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            "cairn", "run", str(path),
            "--workspace", workspace_id,
            "--inputs", json.dumps(inputs),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        if proc.returncode != 0:
            raise CairnError(stderr.decode())
        return json.loads(stdout)
```

**Updated config:**
```python
class CairnConfig(BaseModel):
    command: str = "cairn"
    home: Path | None = None
    max_concurrent_agents: int = 16
    timeout: int = 300
```

### Phase D3: Pydantree Discovery

Replace `NodeDiscoverer` with `PydantreeDiscoverer`:

```python
class PydantreeDiscoverer:
    def __init__(self, root_dirs: list[Path], query_pack: str) -> None:
        self.root_dirs = root_dirs
        self.query_pack = query_pack   # e.g. "python/remora_core"

    def discover(self) -> list[CSTNode]:
        ...   # invoke Pydantree CLI; parse typed captures; return CSTNode list
```

**Requirements:**
- Ship a Pydantree query pack at `queries/python/remora_core/`
- Version it with manifest hashes validated in CI
- `CSTNode` type remains the stable public type

### Phase D4: Unified Event + Result Model

All stages emit JSONL events with consistent fields:

```json
{
  "ts":          "2026-02-18T12:00:00Z",
  "phase":       "discovery | grail_check | execution | submission",
  "agent_id":    "docstring-node-1",
  "node_id":     "abc123",
  "tool_name":   "run_linter",
  "status":      "ok | error",
  "duration_ms": 140
}
```

Add Grail validation summaries to `AgentResult.details`:
```python
class AgentResult(BaseModel):
    ...
    details: dict[str, Any] = Field(default_factory=dict)
    # details["grail_check"] = {"valid": True, "warnings": [...]}
```

### Phase D5: Updated Config Surface

```python
class RemoraConfig(BaseModel):
    discovery: DiscoveryConfig        # language, query_pack
    cairn: CairnConfig                # command, home, max_concurrent_agents, timeout
    runner: RunnerConfig              # max_turns, max_tokens, temperature, tool_choice
    event_stream: EventStreamConfig   # enabled, output, control_file
    agents_dir: Path
    operations: dict[str, OperationConfig]
```

**Remove:**
- AST-specific `queries` list (replaced by `discovery.query_pack`)
- Ad-hoc runtime toggles not aligned with Cairn/Grail/Pydantree contracts

---

## Original Dev Guide Steps 14-17 (Rewritten for New Architecture)

The original Steps 14-17 assumed the pre-refactor architecture. Below are the equivalent deliverables for the tightly integrated architecture:

### Step 14: Results Aggregation + Formatting

**Original Goal:** Build result models and output formatters

**New Deliverables:**
- [ ] `AnalysisResults` and `NodeResult` models unchanged
- [ ] `TableFormatter` — renders node × operation grid using Rich tables
- [ ] `JSONFormatter` — renders full `AnalysisResults` as indented JSON
- [ ] `InteractiveFormatter` — step-through prompts for accept/reject per operation
- [ ] `ResultPresenter` orchestrator that picks formatter based on `--format` flag
- [ ] Failure summaries with per-operation error details
- [ ] Grail validation status displayed in formatters

**Key Change:** Results now include Grail validation metadata from `details["grail_check"]`

### Step 15: Accept / Reject / Retry Workflow

**Original Goal:** Implement `accept`, `reject`, `retry` on `RemoraAnalyzer`

**New Deliverables:**
- [ ] `RemoraAnalyzer.accept(node_id, operation)` — calls Cairn CLI to merge workspace into stable
- [ ] `RemoraAnalyzer.reject(node_id, operation)` — calls Cairn CLI to discard workspace
- [ ] `RemoraAnalyzer.retry(node_id, operation, config_override)` — re-runs runner with overrides
- [ ] Workspace state tracking: PENDING → ACCEPTED | REJECTED | RETRYING
- [ ] `bulk_accept(operations=None)` and `bulk_reject(operations=None)` for batch operations

**Key Change:** All workspace operations go through Cairn CLI, not in-process API

### Step 16: CLI + Watch Mode

**Original Goal:** Deliver end-to-end CLI experience

**New Deliverables:**
- [ ] `remora analyze <paths>` — full pipeline with all configured operations
- [ ] `remora watch <paths>` — debounced re-analysis on file changes
- [ ] `remora list-agents` — lists available subagent definitions with Grail validation status
- [ ] `remora config -f yaml` — displays merged configuration
- [ ] Exit codes aligned with spec
- [ ] Debounced watch mode using `watchfiles`

**Key Change:** `list-agents` now shows Grail validation status for each `.pym` file

### Step 17: MVP Acceptance Tests

**Original Goal:** Validate MVP success criteria end-to-end

**New Deliverables:**
- [ ] Acceptance test suite covering all six scenarios
- [ ] Uses real FunctionGemma model via vLLM (not mocks)
- [ ] Tests skip gracefully when vLLM server not available
- [ ] All `.pym` files pass `grail check --strict` before test run
- [ ] Pydantree discovery validated on sample project

**Acceptance Scenarios (unchanged):**
1. Point at Python file → lint runner identifies and fixes style issues → accept → changes in stable workspace
2. Point at undocumented function → docstring runner injects docstring → accept → docstring in source
3. Point at function → test runner generates pytest file → accept → test file exists in stable workspace
4. Process file with 5+ functions → all run concurrently → results returned for all nodes
5. Deliberately break one runner (invalid model ID) → other runners complete successfully
6. Watch mode → save a Python file → re-analysis runs automatically for that file

**Additional Scenario:**
7. All `.pym` tools validate with Grail before execution; invalid tools are skipped with clear error

---

## Success Criteria

The MVP is complete when:

1. **All 21 `.pym` files pass `grail check --strict`**
2. **All tests use the Grail runtime harness** (no `SourceFileLoader`)
3. **Discovery uses Pydantree only** (no AST fallback)
4. **Execution uses Cairn CLI only** (no in-process `.pym` execution)
5. **Tool schemas are Grail-first** with explicit YAML overrides
6. **Single event stream** covers discovery → validation → execution → submission
7. **All six original acceptance scenarios pass**
8. **New Grail validation scenario passes**
9. **CLI commands work end-to-end:** `analyze`, `watch`, `config`, `list-agents`
10. **Accept/reject/retry workflow** functions via Cairn CLI integration

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| YAML overrides drift from Grail semantics | Emit warnings for type/required/default changes; audit override usage |
| Pydantree query pack drift | Lock query pack with manifest hashes; validate in CI |
| CLI execution limits visibility | Parse Cairn status outputs; emit intermediate events |
| Grail validation breaks existing `.pym` files | Fix files incrementally; maintain Grail compliance checklist |
| Test migration breaks existing coverage | Run old and new test harnesses in parallel during transition |

---

## Recommended Implementation Order

### Week 1-2: Track A (Cleanup)
- Fix A1-A3 bugs
- Address B1-B8 performance/code quality issues

### Week 3-4: Track B (Grail Compliance)
- Baseline all 21 `.pym` files with `grail check --strict`
- Fix compliance issues per file
- Validate all files pass

### Week 5-6: Track C (Test Migration)
- Create `tests/utils/grail_runtime.py` harness
- Add `tests/test_pym_validation.py`
- Migrate tool test files one by one

### Week 7-10: Track D (Architectural Rewrite)
- Phase D0: Delete parallel runtimes
- Phase D1: Grail Tool Registry
- Phase D2: Cairn Execution Bridge
- Phase D3: Pydantree Discovery
- Phase D4: Unified Event Model
- Phase D5: Updated Config Surface

### Week 11-12: Integration & Acceptance
- Wire Steps 14-16 (Results, Workflow, CLI)
- Run all six acceptance scenarios
- Fix integration issues
- Performance testing and optimization

---

## Appendix: File Inventory

### Core Remora Modules
```
remora/
├── __init__.py
├── __main__.py
├── cli.py
├── config.py
├── discovery.py          # Being replaced by Pydantree
├── orchestrator.py
├── runner.py
├── results.py
├── errors.py
├── events.py
├── cairn.py              # Being replaced by CLI bridge
├── subagent.py
├── tool_registry.py      # Being replaced by Grail registry
└── client.py
```

### Agent Definitions (4 subagents, 16 tools, 4 contexts)
```
agents/
├── lint/
│   ├── lint_subagent.yaml
│   ├── tools/
│   │   ├── run_linter.pym
│   │   ├── apply_fix.pym
│   │   ├── read_file.pym
│   │   └── submit.pym
│   └── context/
│       └── ruff_config.pym
├── test/
│   ├── test_subagent.yaml
│   ├── tools/
│   │   ├── analyze_signature.pym
│   │   ├── read_existing_tests.pym
│   │   ├── write_test_file.pym
│   │   ├── run_tests.pym
│   │   └── submit.pym
│   └── context/
│       └── pytest_config.pym
├── docstring/
│   ├── docstring_subagent.yaml
│   ├── tools/
│   │   ├── read_current_docstring.pym
│   │   ├── read_type_hints.pym
│   │   ├── write_docstring.pym
│   │   └── submit.pym
│   └── context/
│       └── docstring_style.pym
└── sample_data/
    ├── sample_data_subagent.yaml
    ├── tools/
    │   ├── analyze_signature.pym
    │   ├── write_fixture_file.pym
    │   └── submit.pym
    └── context/
        └── existing_fixtures.pym
```

### Tests
```
tests/
├── conftest.py
├── test_pym_validation.py        # NEW: Grail validation for all .pym
├── test_lint_tools.py            # MIGRATE: Use grail_runtime harness
├── test_docstring_tools.py       # MIGRATE: Use grail_runtime harness
├── test_test_tools.py            # MIGRATE: Use grail_runtime harness
├── test_sample_data_tools.py     # MIGRATE: Use grail_runtime harness
├── test_runner.py
├── test_orchestrator.py
├── test_discovery.py             # UPDATE: Pydantree-based
├── integration/                  # Integration tests (vLLM required)
│   ├── test_runner_lint.py
│   ├── test_runner_docstring.py
│   └── test_runner_test.py
├── acceptance/                   # Acceptance tests (vLLM required)
│   ├── conftest.py
│   └── sample_project/
└── utils/
    └── grail_runtime.py          # NEW: Shared test harness
```
