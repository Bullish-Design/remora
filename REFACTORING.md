# Remora Refactoring Guide

**Date:** 2026-02-18
**Repository:** `Bullish-Design/remora`
**Scope:** Authoritative master reference — consolidates `CODE_REVIEW.md`,
`VLLM_REFACTOR.md`, `ERROR_ANALYSIS.md`, `GRAIL_SCRIPT_REFACTOR.md`,
`GRAIL_RUNTIME_TESTING_REFACTOR.md`, and `REMORA_GRAIL_PYDANTREE_INTEGRATION.md`
into a single prioritised, actionable plan.

---

## Table of Contents

1. [Current State](#1-current-state)
2. [Phase A — Code-Level Bug Fixes (Immediate)](#2-phase-a--code-level-bug-fixes-immediate)
3. [Phase B — Code-Level Improvements (Short Term)](#3-phase-b--code-level-improvements-short-term)
4. [Phase C — Grail Script Compliance](#4-phase-c--grail-script-compliance)
5. [Phase D — Test Architecture Migration](#5-phase-d--test-architecture-migration)
6. [Phase E — Architectural Rewrite (Cairn + Grail + Pydantree)](#6-phase-e--architectural-rewrite-cairn--grail--pydantree)
7. [Work Already Done](#7-work-already-done)
8. [Outstanding Issues Summary Table](#8-outstanding-issues-summary-table)

---

## 1. Current State

Remora is a `v0.1.0` async orchestration layer that drives multi-turn
`FunctionGemma` agents over Python codebases. The core abstractions — subagent
YAML definitions, the `FunctionGemmaRunner` loop, Pydantic result models, and
the event stream — are well-structured.

**Completed work (already merged):**

- vLLM native tool-calling API (`tools=`, `tool_choice=`, `message.tool_calls`).
- `_build_system_prompt` no longer injects tool JSON into the system message.
- Tool results use `role="tool"` with `tool_call_id` instead of `role="user"`.
- Multi-tool responses are fully accumulated before re-calling the model.
- `max_tokens`, `temperature`, and `tool_choice` are configurable via
  `RunnerConfig`.
- `_tool_choice_for_turn` forces `submit_result` on the last allowed turn.

**Remaining work is divided into five phases** (A through E), ordered by
urgency and dependency.

---

## 2. Phase A — Code-Level Bug Fixes (Immediate)

These are correctness bugs that affect production runs today.

### A1 · `AGENT_003` reused for two distinct failure modes

**File:** `remora/runner.py`
**Severity: Medium**

Both "model produced no tool call" and "turn limit exceeded" raise `AGENT_003`.
These are meaningfully different — one is a model misbehaviour, the other is a
resource budget exhaustion — and consumers need to distinguish them.

**Fix:** Add a new error code `AGENT_004` for turn-limit exhaustion.

```python
# remora/errors.py
AGENT_003 = "AGENT_003"   # Model produced no tool call when one was required
AGENT_004 = "AGENT_004"   # Turn limit exceeded before submit_result was called
```

```python
# remora/runner.py — _handle_no_tool_calls
raise AgentError(..., error_code=AGENT_003,
                 message="Model stopped without calling submit_result")

# remora/runner.py — run() turn-limit branch
raise AgentError(..., error_code=AGENT_004,
                 message=f"Turn limit {self.definition.max_turns} exceeded")
```

### A2 · `_build_submit_result` can raise uncaught `ValidationError`

**File:** `remora/runner.py:_build_submit_result`
**Severity: High**

`AgentResult.status` is `Literal["success", "failed", "skipped"]`. If the model
returns an unexpected string for `status` (e.g., `"added"`, `"done"`), Pydantic
raises a `ValidationError` that is not caught inside `_build_submit_result`.
The error propagates as an unstructured exception; the orchestrator catches it
as a generic string, losing the structured `AgentError` context.

**Fix:**

```python
def _build_submit_result(self, arguments: Any) -> AgentResult:
    ...
    status_raw = filtered.get("status", "success")
    if status_raw not in {"success", "failed", "skipped"}:
        status_raw = "success"    # model used a non-standard value; treat as success
    result_data = {
        "status": status_raw,
        ...
    }
    try:
        return AgentResult.model_validate(result_data)
    except ValidationError as exc:
        raise AgentError(
            node_id=self.node.node_id,
            operation=self.definition.name,
            phase="merge",
            error_code=AGENT_003,
            message=f"submit_result payload failed validation: {exc}",
        ) from exc
```

### A3 · Orchestrator loses `AgentError` phase and error_code on re-emit

**File:** `remora/orchestrator.py:run_with_limit`
**Severity: Medium**

When `run_with_limit` catches an exception from `runner.run()` it emits a
generic `phase="run"` event, discarding the structured `AgentError.phase` and
`AgentError.error_code`:

```python
# current (wrong)
self._event_emitter.emit({
    "event": "agent_error",
    "phase": "run",          # always "run", even if the AgentError said "loop"
    "error": str(exc),       # loses error_code entirely
})
```

**Fix:** Read fields from the exception when it is an `AgentError`:

```python
from remora.runner import AgentError

phase = exc.phase if isinstance(exc, AgentError) else "run"
error_code = exc.error_code if isinstance(exc, AgentError) else None
payload: dict[str, Any] = {
    "event": "agent_error",
    "agent_id": runner.workspace_id,
    "node_id": node.node_id,
    "operation": operation,
    "phase": phase,
    "error": str(exc),
}
if error_code is not None:
    payload["error_code"] = error_code
self._event_emitter.emit(payload)
```

---

## 3. Phase B — Code-Level Improvements (Short Term)

These do not break existing runs but reduce performance, observability, and
maintainability.

### B1 · `tools_by_name` property recomputed on every access

**File:** `remora/subagent.py:SubagentDefinition`
**Severity: Medium**

`tools_by_name` builds a fresh dict on every property access. It is called once
per tool call in `_dispatch_tool`, meaning a 20-turn agent with 5 tools per
turn calls it 100 times unnecessarily.

**Fix:**

```python
from functools import cached_property

class SubagentDefinition(BaseModel):
    ...
    @cached_property
    def tools_by_name(self) -> dict[str, ToolDefinition]:
        return {tool.name: tool for tool in self.tools}
```

Note: `cached_property` on a Pydantic v2 model requires `model_config =
ConfigDict(arbitrary_types_allowed=True)` — check compatibility. An alternative
is to compute this in a `model_post_init` and store it in a `PrivateAttr`.

### B2 · Duplicate tool names silently overwritten

**File:** `remora/subagent.py:load_subagent_definition`
**Severity: Medium**

If a YAML subagent accidentally defines two tools with the same name, only the
last is reachable via `tools_by_name`. There is no validation or warning.

**Fix:** Add a duplicate-name check alongside the existing `_validate_submit_result`:

```python
def _validate_tool_names(definition: SubagentDefinition, path: Path) -> None:
    seen: set[str] = set()
    for tool in definition.tools:
        if tool.name in seen:
            raise SubagentError(
                AGENT_001,
                f"Duplicate tool name '{tool.name}' in subagent definition: {path}",
            )
        seen.add(tool.name)
```

### B3 · Jinja2 template syntax not validated at load time

**File:** `remora/subagent.py:InitialContext.render`
**Severity: Medium**

An invalid `node_context` template raises `jinja2.TemplateSyntaxError` at
render time (during `runner.__post_init__`), not at load time. This makes
errors hard to attribute.

**Fix:** Validate syntax in `load_subagent_definition`:

```python
import jinja2

def _validate_jinja2_template(definition: SubagentDefinition, path: Path) -> None:
    env = jinja2.Environment()
    try:
        env.parse(definition.initial_context.node_context)
    except jinja2.TemplateSyntaxError as exc:
        raise SubagentError(
            AGENT_001,
            f"Invalid Jinja2 template in node_context of {path}: {exc}",
        ) from exc
```

### B4 · `watch_task` and event emitter opened/closed per `process_node` call

**File:** `remora/orchestrator.py:Coordinator`
**Severity: Medium**

The event stream is created in `Coordinator.__init__` but `watch_task` is
created inside `process_node`, causing a new task (and potential file handle)
per node in a batch run.

**Fix:** Move the watch task into `Coordinator.__init__` and introduce an
explicit `close()` / async context manager:

```python
class Coordinator:
    def __init__(self, ...) -> None:
        ...
        self._watch_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "Coordinator":
        if isinstance(self._event_emitter, EventStreamController):
            self._watch_task = asyncio.create_task(self._event_emitter.watch())
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watch_task
        self._event_emitter.close()

    async def process_node(self, node: CSTNode, operations: list[str]) -> NodeResult:
        # no watch_task management here
        ...
```

### B5 · `return_exceptions=True` dead code in `asyncio.gather`

**File:** `remora/orchestrator.py`
**Severity: Low**

`run_with_limit` never raises — it always returns `(operation, result_or_exc)`.
The `isinstance(item, BaseException)` branch can never be reached.

**Fix:** Either remove `return_exceptions=True` and the dead branch, or add a
comment explaining why it is defensive:

```python
raw = await asyncio.gather(
    *[run_with_limit(op, runner) for op, runner in runners.items()],
    # return_exceptions=False: run_with_limit never raises
)
```

### B6 · `socket.getaddrinfo` blocks synchronously during config load

**File:** `remora/config.py:_warn_unreachable_server`
**Severity: Medium**

On a slow or absent DNS resolver this call can hang for 5–10 seconds on the
main thread.

**Fix:** Run the DNS check in a thread with a 1-second timeout, or gate it
behind a config flag:

```python
import concurrent.futures

def _warn_unreachable_server(server: ServerConfig) -> None:
    parsed = urlparse(server.base_url)
    hostname = parsed.hostname
    if hostname is None:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(socket.getaddrinfo, hostname, None)
        try:
            future.result(timeout=1.0)
        except (socket.gaierror, concurrent.futures.TimeoutError):
            warnings.warn(
                f"Remora server may be unreachable: {server.base_url}",
                stacklevel=2,
            )
```

### B7 · `JsonlEventEmitter.emit` mutates the caller's dict

**File:** `remora/events.py:JsonlEventEmitter.emit`
**Severity: Low**

`payload.setdefault("ts", ...)` adds a key to the dict passed in by the caller.
If the caller reuses that dict object it will carry a stale timestamp.

**Fix:** Write to a shallow copy:

```python
def emit(self, payload: dict[str, Any]) -> None:
    if not self.enabled:
        return
    out = {**payload}                             # shallow copy
    out.setdefault("ts", _iso_timestamp())
    ...
```

### B8 · `AgentResult.details` is untyped

**File:** `remora/results.py`
**Severity: Low**

```python
# before
details: dict = Field(default_factory=dict)

# after
details: dict[str, Any] = Field(default_factory=dict)
```

### B9 · Error codes `CONFIG_001` and `CONFIG_002` are missing

**File:** `remora/errors.py`

The module begins at `CONFIG_003`. Either define `CONFIG_001` / `CONFIG_002` for
previously deleted or planned cases, or renumber sequentially from `CONFIG_001`
and update all callers.

### B10 · `OperationConfig` `extra="allow"` is undocumented

**File:** `remora/config.py`

Add an inline comment:

```python
class OperationConfig(BaseModel):
    # extra="allow" is intentional: operation-specific keys (e.g. style="google")
    # are passed through to the subagent and are not validated by Remora.
    model_config = ConfigDict(extra="allow")
```

### B11 · `CSTNode` name is misleading — uses `ast`, not a CST library

**File:** `remora/discovery.py`

The module docstring says "CST node discovery" but the implementation uses
Python's `ast` module (an AST). Rename `CSTNode` → `ASTNode` for clarity, or
add a prominent comment that `CSTNode` is a forward-compatible name reserved for
the Pydantree migration in Phase E.

Query `.scm` files are loaded and syntax-checked but never used for actual
querying — the real discovery is done via `ast.walk()`. This dead infrastructure
should be documented as a placeholder for the Pydantree migration.

### B12 · CLI exit code 3 is non-standard; `--version` is missing

**File:** `remora/cli.py`

- Change `typer.Exit(code=3)` to `typer.Exit(code=1)` for config errors (Unix
  convention).
- Add a `--version` flag:

```python
import importlib.metadata

def version_callback(value: bool) -> None:
    if value:
        typer.echo(importlib.metadata.version("remora"))
        raise typer.Exit()

@app.callback()
def main(
    version: bool = typer.Option(None, "--version", callback=version_callback,
                                  is_eager=True),
) -> None:
    ...
```

---

## 4. Phase C — Grail Script Compliance

All `.pym` agent scripts must pass `grail check --strict` and be structurally
valid Monty before any Grail-runtime tests or the Phase E architecture
migration can proceed.

### C1 · Inventory all `.pym` files

```bash
rg --files -g "*.pym"
```

Create a tracking table (see end of this section).

### C2 · Baseline validation

```bash
grail check --strict
```

Capture all errors per file before making any edits.

### C3 · Per-file refactor checklist

Apply in this order for every `.pym` file:

| Step | Rule | Common Fix |
|------|------|------------|
| Imports | Only `from grail import external, Input` and `from typing import Any` | Remove stdlib imports; replace functionality with `@external` |
| Inputs | Every `Input()` has a type annotation on the LHS | Add missing annotations |
| Externals | Every `@external` has full parameter + return annotations and body `...` | Replace `pass` with `...`; add annotations |
| Unsupported syntax | No `class`, `yield`, `with`, `match`, `lambda` | Rewrite to use dicts, explicit lists, externals |
| Executable section | All work at top level, not inside `main()` | Lift code to module scope |
| `submit_result` | Must be declared with `@external` and called before the final return | Add declaration + call |
| Final return | Last expression is a meaningful `dict` | Replace bare values |

### C4 · Validate per file after editing

```bash
grail check --strict agents/<file>.pym
```

Check generated artifacts under `.grail/<script_name>/`:
- `check.json` — `"valid": true`
- `monty_code.py` — executable code without declarations
- `inputs.json` — declared inputs
- `externals.json` — declared externals

### C5 · Escalation criteria

Escalate a script if:
- A new `@external` function is needed that does not exist in the Cairn
  workspace yet.
- The script exceeds ~200 lines and requires redesign.
- Complex stdlib behaviour (regex, JSON, filesystem walking) cannot be mapped
  cleanly to an external.

### C6 · Progress tracking template

```
| File                                    | Status | Notes                      |
|-----------------------------------------|--------|----------------------------|
| agents/docstring/*.pym                  | 🔲     |                            |
| agents/lint/*.pym                       | 🔲     |                            |
| agents/test/*.pym                       | 🔲     |                            |
| agents/sample_data/*.pym                | 🔲     |                            |
```

---

## 5. Phase D — Test Architecture Migration

Tests currently import `.pym` files via `SourceFileLoader`, which bypasses Grail
entirely and makes top-level `await` fail. All tool tests must migrate to the
Grail runtime harness.

### D1 · Create `tests/utils/grail_runtime.py`

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

### D2 · Add `tests/test_pym_validation.py`

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

### D3 · Migrate tool test files

Replace `SourceFileLoader` with `run_script` from the harness in:

- `tests/test_lint_tools.py`
- `tests/test_docstring_tools.py`
- `tests/test_test_tools.py`
- `tests/test_sample_data_tools.py`

Pattern for each migrated test:

```python
# before
import importlib
loader = importlib.machinery.SourceFileLoader("tool", str(path))
module = loader.load_module()

# after
from tests.utils.grail_runtime import run_script

result = run_script(
    path=path,
    inputs={"node_text": "...", "workspace_id": "test-ws"},
    externals={"read_file": lambda path: "...", ...},
)
assert result["status"] == "ok"
```

### D4 · Add artifact assertions to every runtime test

```python
def test_lint_tool_returns_issues(tmp_path: Path) -> None:
    grail_dir = tmp_path / ".grail"
    result = run_script(path, inputs={...}, externals={...}, grail_dir=grail_dir)
    assert_artifacts(grail_dir, "lint_tool")
    assert "issues" in result
```

### D5 · Update pytest markers

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "integration: requires live Cairn/vLLM server",
    "grail_runtime: exercises Grail runtime execution",
]
```

CI requirements:
- `pytest -m "not integration"` must include Grail runtime tests.
- `pytest -m grail_runtime` is a required CI step.

### D6 · Add CLI tests for the `config` command

`cli.py` has no test coverage despite `config` being fully implemented.

```python
# tests/test_cli.py
from typer.testing import CliRunner
from remora.cli import app

def test_config_command_outputs_yaml(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["config", "--format", "yaml"])
    assert result.exit_code == 0
    assert "agents_dir" in result.output
```

---

## 6. Phase E — Architectural Rewrite (Cairn + Grail + Pydantree)

This phase replaces all current runtime paths with canonical integrations.
Phases A–D are prerequisites. Do not begin Phase E until all `.pym` scripts
pass `grail check --strict` and all tests use the Grail runtime harness.

### E0 · Delete parallel runtimes

- Remove AST-based `NodeDiscoverer` and `_iter_python_files`.
- Remove any in-process `.pym` execution from `FunctionGemmaRunner` and
  `CairnClient`.
- Remove manual tool parameter schemas from YAML subagent definitions (schemas
  become Grail-first).

### E1 · Grail Tool Registry

Build a catalog builder that runs `grail check --strict` and reads artifacts:

```
.grail/agents/{agent_id}/
  check.json        ← validation status + warnings
  inputs.json       ← parameter schema (source of truth)
  externals.json    ← external function signatures
  stubs.pyi
  monty_code.py
```

**Schema assembly rules:**

1. Start with `inputs.json` from Grail.
2. Apply YAML overrides (`tool_name`, `tool_description`, `inputs_override`).
3. Emit warnings if overrides change `type`, `required`, or `default` relative
   to Grail.
4. Final schema is what is surfaced to the model via `tools=`.

This eliminates schema drift between what YAML declares and what the `.pym`
file actually accepts.

### E2 · Cairn Execution Bridge (CLI-first)

Replace the in-process `CairnClient.run_pym` with a subprocess bridge:

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

Updated config:

```python
class CairnConfig(BaseModel):
    command: str = "cairn"
    home: Path | None = None
    max_concurrent_agents: int = 16
    timeout: int = 300
```

### E3 · Pydantree Discovery

Replace `NodeDiscoverer` with a `PydantreeDiscoverer`:

```python
class PydantreeDiscoverer:
    def __init__(self, root_dirs: list[Path], query_pack: str) -> None:
        self.root_dirs = root_dirs
        self.query_pack = query_pack   # e.g. "python/remora_core"

    def discover(self) -> list[CSTNode]:
        ...   # invoke Pydantree CLI; parse typed captures; return CSTNode list
```

The `CSTNode` type does not change externally — only its source changes from
`ast` to Pydantree captures. Rename the internal implementation class to
`ASTNode` in the interim (Phase B11) and reuse `CSTNode` as the stable public
type throughout the migration.

Ship a Pydantree query pack at `queries/python/remora_core/` and version it
with manifest hashes validated in CI.

### E4 · Unified Event + Result Model

All stages — discovery, Grail validation, Cairn execution, and
`submit_result` — emit JSONL events with consistent fields:

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

### E5 · Updated config surface

```python
class RemoraConfig(BaseModel):
    discovery: DiscoveryConfig        # language, query_pack
    cairn: CairnConfig                # command, home, max_concurrent_agents, timeout
    runner: RunnerConfig              # max_turns, max_tokens, temperature, tool_choice
    event_stream: EventStreamConfig   # enabled, output, control_file
    agents_dir: Path
    operations: dict[str, OperationConfig]
```

Remove:
- AST-specific `queries` list (replaced by `discovery.query_pack`).
- Ad-hoc runtime toggles not aligned with Cairn/Grail/Pydantree contracts.

---

## 7. Work Already Done

The following items from earlier analysis documents are **already resolved**
in the current codebase. They are listed here for completeness and to avoid
duplicate effort.

| Item | Resolved In | Description |
|------|-------------|-------------|
| Manual tool injection into system prompt | `runner.py` | `_build_system_prompt` returns only `system_prompt`; no tool JSON injected |
| Wrong tool calling API (`role="user"` tool results) | `runner.py` | Tool results use `role="tool"` with `tool_call_id` |
| `_parse_tool_calls` regex parser | `runner.py` | Deleted; replaced by `message.tool_calls` from vLLM |
| `_coerce_tool_calls` | `runner.py` | Deleted |
| Multi-tool-response inner-loop re-call bug | `runner.py` | All tool results accumulated before model re-call |
| `max_tokens` / `temperature` hardcoded | `runner.py` / `config.py` | Moved to `RunnerConfig` |
| `tool_choice` not configurable | `config.py` | `RunnerConfig.tool_choice` added |
| Last-turn forced `submit_result` | `runner.py` | `_tool_choice_for_turn` forces `submit_result` on turn `max_turns - 1` |
| vLLM server flags undocumented | `docs/SERVER_SETUP.md` | `--enable-auto-tool-choice --tool-call-parser functiongemma --chat-template` documented |
| Test fakes not supporting `tool_calls` | `tests/test_runner.py` | `FakeToolCall` / `FakeCompletionResponse` updated |

---

## 8. Outstanding Issues Summary Table

| Priority | Phase | Issue | File | Severity |
|----------|-------|-------|------|----------|
| 1 | A | `_build_submit_result` raises uncaught `ValidationError` | `runner.py` | High |
| 2 | A | `AGENT_003` reused for two distinct failure modes | `runner.py`, `errors.py` | Medium |
| 3 | A | Orchestrator overwrites `AgentError.phase`/`error_code` on re-emit | `orchestrator.py` | Medium |
| 4 | B | `watch_task` and emitter opened/closed per `process_node` call | `orchestrator.py` | Medium |
| 5 | B | `tools_by_name` recomputed on every hot-path access | `subagent.py` | Medium |
| 6 | B | Duplicate tool names silently overwritten | `subagent.py` | Medium |
| 7 | B | Jinja2 template syntax not validated at load time | `subagent.py` | Medium |
| 8 | B | `socket.getaddrinfo` blocks main thread during config load | `config.py` | Medium |
| 9 | B | `return_exceptions=True` dead code in `asyncio.gather` | `orchestrator.py` | Low |
| 10 | B | `JsonlEventEmitter.emit` mutates caller's dict | `events.py` | Low |
| 11 | B | `AgentResult.details` untyped (`dict` vs `dict[str, Any]`) | `results.py` | Low |
| 12 | B | Error codes skip `CONFIG_001`, `CONFIG_002` | `errors.py` | Low |
| 13 | B | `OperationConfig` `extra="allow"` undocumented | `config.py` | Low |
| 14 | B | `CSTNode` name misleading — uses `ast`, not CST | `discovery.py` | Low |
| 15 | B | CLI exit code 3 non-standard; `--version` missing | `cli.py` | Low |
| 16 | C | `.pym` scripts not validated with `grail check --strict` | `agents/**` | High |
| 17 | D | Tests import `.pym` via `SourceFileLoader`, bypassing Grail | `tests/` | High |
| 18 | D | No `tests/test_pym_validation.py` | `tests/` | Medium |
| 19 | D | `cli.py` has no test coverage | `tests/` | Low |
| 20 | E | Discovery uses `ast`; Pydantree not integrated | `discovery.py` | Architectural |
| 21 | E | Cairn client calls in-process; no CLI bridge | `runner.py` | Architectural |
| 22 | E | Tool schemas declared in YAML, not generated from `inputs.json` | `subagent.py` | Architectural |
| 23 | E | Event model has no `phase` for discovery / grail_check stages | `events.py` | Architectural |
