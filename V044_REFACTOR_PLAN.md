# Remora V0.4.4 Refactor Plan

Date: 2026-02-26
Author: Codex

## Goals
- Make Grail tools perform real writes via Cairn externals (no "write-by-output" ambiguity).
- Add a workspace-aware `PathResolver` so absolute/relative paths behave consistently.
- Fix remaining runtime issues from V043 review (graph ordering, indexer node types, dashboard progress, context subscription duplication, bundle overrides, etc.).

## Approach Options (with Examples, Pros/Cons, Recommendation)

### A) Tool Writes + Cairn Integration

#### Approach A1: Result handler writes based on tool output
- **Example**: Tool returns `{ "written_file": "src/foo.py", "content": "..." }` and Remora writes it.
- **Pros**: Minimal tool changes; easy to keep existing scripts.
- **Cons**: Indirect, error-prone contract; tools can "succeed" without writing; mixed output formats (`written_file` vs `modified_file`) lead to silent failures.
- **Implications**: Requires strict output schema enforcement; still harder to reason about side effects.

#### Approach A2: Tools call Cairn externals as standalone functions
- **Example**: `await write_file("src/foo.py", content)` using `@external` stubs.
- **Pros**: Direct writes; simpler runtime contract; tools explicitly perform side effects.
- **Cons**: Flat namespace; hard to extend without adding many globals; no grouping/organization.
- **Implications**: Still clean, but grows messy as external surface area expands.

#### Approach A3: Built-in Cairn external class (recommended)
- **Example**: Tools call `await write_file("src/foo.py", content)` / `await submit_result(...)`, and Remora supplies those externals via a built-in `CairnExternals` class.
- **Pros**: Clean internal design; centralized path normalization; direct writes; easy to stub in tests.
- **Cons**: Tools still call function-style externals (Monty does not allow class definitions in `.pym` scripts).
- **Implications**: Most elegant long-term contract given Monty constraints; keeps tool scripts compatible while consolidating logic in Remora.

**Recommendation**: A3. Implement a `CairnExternals` class in Remora that normalizes paths and exposes external function implementations. Tools call externals directly; the class stays internal.

### B) Path Normalization + Workspace Access

#### Approach B1: Normalize paths at discovery time
- **Example**: Convert all `CSTNode.file_path` values to project-relative strings inside `discover()`.
- **Pros**: Single source of truth; downstream code stays simple.
- **Cons**: Discovery loses original absolute paths; ambiguous if discovery happens on multiple roots.
- **Implications**: Requires careful handling in multi-root scenarios.

#### Approach B2: Add a `PathResolver` used by workspace + executor (recommended)
- **Example**: `resolver.to_workspace_path("/abs/repo/src/foo.py") -> "src/foo.py"`.
- **Pros**: Keeps original paths while ensuring workspace correctness; localized change; supports multiple roots if needed later.
- **Cons**: Slightly more plumbing; must be used consistently.
- **Implications**: Best balance of correctness and flexibility.

#### Approach B3: Store both absolute and relative paths in workspace
- **Example**: Write files into Cairn under both `/abs/...` and `src/...` keys.
- **Pros**: Maximum compatibility.
- **Cons**: Duplicate storage; more confusing; easy to drift.
- **Implications**: High maintenance cost and unclear semantics.

**Recommendation**: B2. Introduce `PathResolver` and enforce its use in workspace reads/writes and prompt building.

## Work Plan (Implementation Order)
1) Add `PathResolver` and integrate it into `CairnWorkspaceService`, `CairnDataProvider`, and `GraphExecutor`.
2) Introduce `CairnExternals` class that wraps Cairn's external functions with path normalization and provides the external function implementations.
3) Update Grail tools to call `write_file`/`submit_result` externals directly for side effects.
4) Update `GraphExecutor` prompt building to use workspace-loaded content, and honor bundle-level overrides (`max_turns`, `requires_context`).
5) Fix graph dependency ordering logic to be input-order independent.
6) Fix indexer node type mismatch (map method/file nodes to supported types or filter).
7) Fix dashboard progress to count failures and de-duplicate EventBus subscriptions.
8) Align `CairnResultHandler` with current tool output keys as a fallback.
9) Minor cleanups: switch to `get_running_loop()` in `EventBus.wait_for`.

## Notes
- Per user request, tool-schema expansion for complex parameter types is intentionally skipped.
- Backwards compatibility will be maintained for legacy tools during the migration to `cairn` externals.
