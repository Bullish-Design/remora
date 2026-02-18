# Remora Runtime Integration Plan (Cairn + Grail + Pydantree)

## Objective

Unify Remora’s runtime across Cairn, Grail, and Pydantree so that:

- `.pym` tooling runs through Grail consistently in all execution paths.
- Cairn orchestration invokes Grail validation and artifacts as first‑class outputs.
- AST/CST discovery is upgraded to a true concrete syntax pipeline via Pydantree.

## Current State

- Remora runtime does **not** invoke Grail directly; it only consumes `.pym` files through Cairn’s client execution model.
- `.pym` tools are treated as Python files in tests, which bypasses Grail.
- Discovery uses a Python `ast` walker, not a concrete syntax tree.

## Integration Principles

1. **Grail is the source of truth for `.pym` parsing + validation.**
2. **Cairn runs scripts but must surface Grail check artifacts and errors.**
3. **Pydantree provides the CST layer to enrich node text, span, and edits.**

## Phase 1: Grail‑First `.pym` Validation

### Goals

- Every `.pym` file passes `grail check --strict`.
- Grail artifacts (`stubs.pyi`, `monty_code.py`, `check.json`) generated for all tools.

### Exact Steps

1. Add a Grail validation step in Remora’s CLI run path:
   - `remora/runner.py`: validate `.pym` using `grail.load(...).check()` before execution.
   - If `check.valid` is false, abort with `AGENT_001` and surface Grail error list.
2. Store Grail artifacts alongside existing `.remora/` artifacts per workspace.
3. Expose artifacts in event stream payloads (for UI + logs).

### Required Tests

- Unit test: `grail.load(...).check()` invoked in runner.
- Integration test: bad `.pym` yields structured error with Grail messages.

## Phase 2: Cairn Execution Consistency

### Goals

- Cairn uses Grail artifacts for execution parity in all environments.
- Remora never executes `.pym` without Grail validation.

### Exact Steps

1. In `remora/runner.py`, persist Grail artifacts to workspace `.grail/<script>`.
2. If Cairn executes a `.pym`, verify Grail artifacts exist before execution.
3. Update event stream to include Grail check summary and artifact paths.

### Required Tests

- Verify artifacts are created during a normal runner execution.
- Ensure missing artifacts surface a clear actionable error.

## Phase 3: Pydantree CST Integration

### Goals

- Replace `ast`-based discovery with Pydantree CST for stable node IDs and accurate spans.
- Node text and edits become whitespace‑preserving and round‑trip safe.

### Exact Steps

1. Introduce a CST discovery adapter:
   - New module: `remora/pydantree_discovery.py`.
   - Interface returns `CSTNode` with concrete ranges + exact source text.
2. Add feature flag in config:
   - `discovery.engine = "pydantree" | "ast"`.
3. Update `remora/discovery.py` to route by config flag.
4. Add mapping logic from Pydantree nodes to Remora `CSTNode` shape.

### Required Tests

- Golden tests for node IDs + spans under Pydantree.
- Regression tests to ensure AST and Pydantree output parity for key cases.

## Phase 4: Cohesive Runtime Pipeline

### Goals

- Unified error model across Grail, Cairn, and Pydantree.
- Clear user‑facing diagnostics for syntax, validation, and runtime failures.

### Exact Steps

1. Normalize error types:
   - Map Grail errors to Remora’s `AgentError` codes.
   - Map Pydantree parse errors to `DISC_002` (or introduce a new error code).
2. Standardize event payloads:
   - `error_phase`: `discovery | grail_check | execution | submission`.
3. Update CLI to report errors with structured summaries + remediation hints.

## Validation Checklist

- All `.pym` files validated via Grail before any execution.
- All `.pym` tools run through Grail in tests and CI.
- Cairn orchestration emits Grail artifacts and uses them in runtime context.
- Pydantree discovery is a supported, tested code path.

## Risks & Mitigations

- **Risk**: Grail example files imply top‑level `await` but parser rejects it.
  - **Mitigation**: Update `.pym` files to avoid top‑level `await` or add a Grail‑compliant wrapper.
- **Risk**: Pydantree node mapping diverges from current AST node IDs.
  - **Mitigation**: Introduce compatibility mode and validate outputs side‑by‑side.

## Success Criteria

- Grail validation runs for 100% of tool scripts.
- Cairn runtime persists Grail artifacts per agent execution.
- Pydantree provides concrete syntax nodes for all discovery operations.
- Tests cover Grail + Cairn + Pydantree execution paths end‑to‑end.
