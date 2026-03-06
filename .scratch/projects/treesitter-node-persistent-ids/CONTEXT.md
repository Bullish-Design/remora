# Context

## Current State
The runtime implementation described in
`.scratch/projects/treesitter-node-persistent-ids/implementation_plan.md`
is complete in `src/remora` and integrated through LSP + reconciliation paths.

## What Was Implemented
- Core identity now uses semantic IDs via
  `compute_node_id(file_path, node_type, full_name)` in
  `src/remora/core/discovery.py`.
- Source hashing is unified with `compute_source_hash(text)` in discovery and
  reused by watcher/reconciler/spawn_child.
- `ASTWatcher` now exposes `parse(uri, text)` only; old-node reuse + random ID
  generation + `inject_ids()` source mutation were removed.
- LSP document handlers/server/background scan now perform parse + orphan diff
  without watcher state or mutation guards.
- Reconciler now updates nodes when either source hash changes or metadata
  changes (line/byte/name/full_name/path), preserving semantic identity while
  keeping position metadata fresh.
- Spawn child now uses shared identity/hash primitives and emits semantic
  `full_name`.
- Exports were updated in `remora.core` and top-level `remora`.
- Tests were updated for new watcher API and semantic identity behavior.

## Validation
- Passed:
  - `tests/test_discovery.py`
  - `tests/unit/test_lsp_watcher.py`
  - `tests/unit/test_scaffold_watcher.py`
  - `tests/unit/test_lsp_background_scan_manifest.py`
  - `tests/integration/test_lsp_integration.py`
  - `tests/integration/test_reconcile_real.py`
  - `tests/unit/test_spawn_child.py`
  - `tests/unit/test_identity_unification.py`
- Attempted broad run:
  - `tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn`
  - This still fails during collection on pre-existing missing modules under
    `remora_demo.graph` / `remora_demo.web`, unrelated to this implementation.

## Next Logical Steps
1. Optional cleanup: address unrelated `remora_demo.*` import gaps so the broader
   non-ignored test run can collect fully.
