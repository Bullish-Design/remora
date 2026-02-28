# Phase 1 - Clean Up

## Goal
Strip dead code and flatten configuration so the reactive swarm work can be added on a clean base. This phase should not introduce new behavior; it should only remove unused pieces and simplify config loading.

## Guiding principles (from the simplification guide)
- Keep the unified, reactive mental model in mind. Do not add new polling paths.
- Preserve the core primitives that we will extend: `EventStore`, `EventBus`, `Discovery`, `Workspace`.
- Avoid reintroducing features that are explicitly removed (indexer, checkpointing, streaming sync).

## Definition of done
- Dead modules are removed or no longer referenced.
- Configuration is a single flat dataclass with YAML loading.
- Tests updated to match removals; build still imports cleanly.

## Step-by-step implementation

### 1) Inventory all removal targets and references
Implementation:
- Use ripgrep to list references before deleting anything.
  - `rg -n "indexer" src tests`
  - `rg -n "container" src tests`
  - `rg -n "checkpoint" src tests`
  - `rg -n "streaming_sync" src tests`
  - `rg -n "WorkspaceManager|EventBridge|snapshot" src tests`
- Create a short checklist of the files and call sites you will update.
- Identify any imports re-exported from `src/remora/core/__init__.py`.

Testing:
- None yet (discovery-only). Confirm you have a complete list by checking `rg` output for each term.

### 2) Remove the indexer package
Implementation:
- Delete the entire `src/remora/indexer/` directory.
- Remove any CLI or service entry points that call the indexer daemon.
  - Start with `src/remora/cli/main.py` and `src/remora/service/handlers.py`.
- Remove any indexer-related exports from `src/remora/__init__.py` and `src/remora/core/__init__.py`.
- Remove or rewrite tests that are purely about the indexer:
  - `tests/integration/test_indexer_daemon_real.py`
  - `tests/unit` tests that directly import indexer modules.
- If tests are still needed later, add a TODO note in the test file before deleting it (or move it into a temporary archive folder if the repo uses one).

Testing:
- Run `rg -n "indexer" src tests` again and ensure there are no runtime imports left.
- Run a quick import check: `python -c "import remora"`.

### 3) Remove container module
Implementation:
- Delete `src/remora/core/container.py`.
- Remove any imports of `container` from `src/remora/core/__init__.py` and call sites.
- If the container defined shared setup helpers, move any still-needed logic into a more concrete place (likely `src/remora/core/context.py` or `src/remora/core/executor.py`).

Testing:
- Run `rg -n "container" src tests` to confirm no references remain.
- Run `python -m pytest tests/test_main.py` to ensure CLI imports do not fail.

### 4) Remove checkpoint module
Implementation:
- Delete `src/remora/core/checkpoint.py`.
- Remove checkpoint-related events from `src/remora/core/events.py` if they are unused after removal (CheckpointSavedEvent, CheckpointRestoredEvent).
- Remove any tests specifically for checkpointing:
  - `tests/integration/test_checkpoint_roundtrip.py`
  - `tests/integration/test_checkpoint_resume_real.py`
- Update documentation that mentions checkpointing (README or docs) to remove references.

Testing:
- Run `rg -n "Checkpoint" src tests` to confirm no lingering imports.
- Run `python -m pytest tests/unit/test_event_store.py` to make sure event serialization still passes if events were pruned.

### 5) Remove streaming sync module
Implementation:
- Delete `src/remora/core/streaming_sync.py`.
- Remove any references from UI or service layers.
- Remove `tests/unit/test_streaming_sync.py` and any integration tests that rely on it.

Testing:
- Run `rg -n "streaming_sync" src tests` to verify removal.
- Run `python -m pytest tests/unit/test_ui_projector.py` to ensure UI paths do not import it.

### 6) Remove dead code stubs (WorkspaceManager, EventBridge, snapshot stubs)
Implementation:
- Use `rg -n "WorkspaceManager|EventBridge|snapshot" src` to find stubs.
- If the class is unused, delete the class and any file containing only that stub.
- If the file contains other still-used code, remove only the unused class and fix imports.
- Update any tests that were asserting on stub behavior (delete or adjust).

Testing:
- Run `rg -n "WorkspaceManager|EventBridge|snapshot" src tests` to verify no references.
- Run `python -m pytest tests/test_context_manager.py` if it depends on any of those modules.

### 7) Flatten configuration into a single `Config` dataclass
Implementation:
- Replace `RemoraConfig` and nested dataclasses in `src/remora/core/config.py` with a single flat `Config` class as defined in Part 7 of the simplification guide.
- Keep only the fields required by the simplified architecture (project, execution, model, swarm, reactive, nvim).
- Update the YAML loader to `Config.from_yaml(path)` to match the guide. Remove the environment override logic unless it is still explicitly needed (if kept, apply it to the flat config fields).
- Update any references to `RemoraConfig` in the codebase:
  - Use `rg -n "RemoraConfig|DiscoveryConfig|ExecutionConfig|WorkspaceConfig|ModelConfig" src tests`.
  - Convert `config.discovery.paths` style accessors to flat fields (e.g., `config.project_path`, `config.languages`).
- Update `remora.yaml` and `remora.yaml.example` to match the flat schema.

Testing:
- Run `python -m pytest tests/test_config.py` and update assertions for the new field names.
- Run `python -m pytest tests/test_main.py` to confirm CLI config loading works.

### 8) Clean exports and docs
Implementation:
- Update `src/remora/core/__init__.py` and `src/remora/__init__.py` to export only the simplified modules.
- Remove references to deleted modules in `README.md`, `HOW_TO_USE_REMORA.md`, and any docs under `docs/`.
- Ensure the docs mention the reactive swarm direction (EventStore + SubscriptionRegistry) rather than polling.

Testing:
- Run `python -c "import remora; import remora.core"` to verify imports.
- Spot-check docs for no stale references (use `rg -n "indexer|checkpoint|streaming_sync" README.md docs`).

### 9) Sanity test sweep
Implementation:
- Execute a minimal test set that represents the remaining core pieces: config, discovery, event store, event bus.

Testing:
- `python -m pytest tests/test_config.py tests/test_discovery.py tests/unit/test_event_store.py tests/unit/test_event_bus.py`

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/test_config.py::test_flat_config_from_yaml` (new) - verifies `Config.from_yaml` reads flat keys and ignores nested sections.
- `tests/test_config.py::test_flat_config_defaults` (update) - asserts default values match the simplified config fields.
- `tests/test_main.py::test_main_invokes_cli` (update if CLI entry points move).
- `tests/test_exports.py::test_core_exports_clean` (new) - ensures removed modules are not exported.

Smoke tests to add/update:
- `tests/integration/test_smoke_real.py::test_vllm_graph_executor_smoke` (update) - ensure the smoke path still runs after config flattening.
- `tests/test_boot_smoke.py::test_import_and_config_loads` (new) - lightweight import + config load with no external dependencies.

Example tests to add:
- `tests/test_config.py::test_config_ignores_unknown_fields` (new) - confirm unknown YAML keys are ignored.
- `tests/test_exports.py::test_removed_modules_not_importable` (new) - verify deleted modules raise ImportError.

## Notes
- Do not add new behavior in this phase. If you need to preserve logic for later phases, move it into TODO notes rather than leaving dead stubs.
- Keep removals small and incremental to avoid large merge conflicts.
