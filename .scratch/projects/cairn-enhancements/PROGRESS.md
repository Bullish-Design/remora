# Cairn Enhancements — Progress Tracker

## Phase 0: Cairn API Additions — DONE
- [x] `open_workspace()` public function in `src/cairn/runtime/workspace_manager.py`
- [x] `WorkspaceInspector`, `WorkspaceStats` in `src/cairn/runtime/inspection.py`
- [x] `AgentStateManager` in `src/cairn/runtime/state.py`
- [x] Updated `src/cairn/runtime/__init__.py` exports
- [x] Updated `src/cairn/__init__.py` top-level exports
- [x] 20 tests in `tests/cairn/test_workspace_api.py` — all passing
- [x] Fixed Grail compatibility in `src/cairn/orchestrator/orchestrator.py`
- [x] Fixed `tests/cairn/test_orchestrator.py` to use `GrailExecutionError`

## Phase 1: CLI Wrappers — DONE
- [x] `src/remora/workspace/__init__.py` — exports `RemoraWorkspaceInspector`
- [x] `src/remora/workspace/inspector.py` — `RemoraWorkspaceInspector` wrapper
- [x] `src/remora/cli/workspace.py` — 7 subcommands: stats, tree, ls, cat, find, kv-list, kv-get
- [x] `src/remora/cli/main.py` — wired workspace command group
- [x] `tests/unit/test_workspace_cli.py` — 13/13 tests passing
- [x] Fixed `__aexit__` AsyncMock returning truthy value that suppressed exceptions

## Phase 2: WorkspaceProtocol — DONE
- [x] `src/remora/core/protocols.py` — `WorkspaceProtocol`, `KVStoreProtocol`
- [x] `src/remora/testing/__init__.py` — exports MockWorkspace, MockKVStore
- [x] `src/remora/testing/mock_workspace.py` — in-memory implementations
- [x] `src/remora/core/workspace.py` — added `delete()`, `mkdir()` methods
- [x] `tests/unit/test_protocols.py` — 30/30 tests passing

## Phase 3: KV Store Integration — DONE
- [x] `src/remora/core/agent_state.py` — `AgentTurnState`, `AgentMemory`, `AgentExecutionMetrics`
- [x] `src/remora/core/state_manager.py` — `RemoraStateManager`
- [x] `src/remora/core/agent_context.py` — added `state_manager` field
- [x] `src/remora/core/__init__.py` — updated exports
- [x] `tests/unit/test_state_manager.py` — 35/35 tests passing

## Phase 4: Private API Fix — DONE
- [x] `src/remora/core/cairn_bridge.py` — uses public `cairn_open_workspace`

## Phase 4.5: Turso Concurrency Layer — DONE

### fsdantic v0.3.1 (tagged & pushed)
- [x] `src/fsdantic/client.py` — `Fsdantic.open()` accepts `enable_wal` and `enable_mvcc`
- [x] `src/fsdantic/workspace.py` — `connection` property
- [x] `tests/test_concurrency.py` — 9 new tests passing
- [x] Version bump to 0.3.1, tagged, pushed to origin/main

### Cairn v0.2.1 (tagged & pushed)
- [x] `src/cairn/runtime/workspace_manager.py` — rewritten to delegate WAL/MVCC to fsdantic
- [x] `src/cairn/runtime/workspace_manager.py` — added `create_workspace()` non-context-manager variant
- [x] `open_workspace()` and `WorkspaceManager` accept `enable_wal`/`enable_mvcc` kwargs
- [x] Module-level concurrency docstring added
- [x] `tests/cairn/test_workspace_manager.py` — fixed monkeypatch signatures for new kwargs
- [x] `tests/cairn/test_concurrency.py` — 11 new tests (WAL, MVCC, create_workspace, manager)
- [x] `pyproject.toml` — version 0.2.1, fsdantic pinned to v0.3.1 tag
- [x] `src/cairn/__init__.py` — version 0.2.1
- [x] Committed, tagged v0.2.1, pushed to origin/main

### Remora lock removal — DONE
- [x] `src/remora/core/workspace.py` — removed `asyncio.Lock` from `AgentWorkspace`
- [x] `src/remora/core/cairn_bridge.py` — removed locks from `CairnWorkspaceService`
- [x] Added concurrency note docstrings

### Remora dependency updates — DONE
- [x] `pyproject.toml` — cairn pinned to v0.2.1 tag, fsdantic pinned to v0.3.1 tag
- [x] `pyproject.toml` — minimum versions updated (cairn>=0.2.1, fsdantic>=0.3.1)

### Cairn venv restoration — DONE
- [x] Restored local fsdantic and cairn editables after accidental remora cross-install
- [x] Removed remora from cairn's venv

## Phase 5: Bidirectional Sync — DONE
- [x] `src/remora/workspace/sync.py` — `WorkspaceSync`, `SyncChange`, `SyncResult`
- [x] `tests/unit/test_workspace_sync.py` — 24/24 tests passing
- [x] `src/remora/cli/workspace.py` — `sync` CLI command
- [x] `src/remora/workspace/__init__.py` — exports updated

## Phase 6: Container Sandbox — DONE
- [x] `src/remora/workspace/sandbox.py` — clean design: `WorkspaceSandbox`, `SandboxConfig`, `ExecutionResult`, `ContainerRuntime`, `DockerRuntime`
- [x] No cairn dependency in sandbox module — materialization is caller's responsibility
- [x] `tests/unit/test_sandbox.py` — 33/33 tests passing (rewritten for clean design, no `patch()` of cairn internals)
- [x] `src/remora/cli/workspace.py` — `sandbox` CLI command (handles cairn materialize → sandbox exec → optional sync-back)
- [x] `src/remora/workspace/__init__.py` — sandbox exports added

## Phase 7: Validation Harness — DONE
- [x] `src/remora/workspace/validation.py` — `WorkspaceValidator`, `ValidationCheck`, `ValidationResult`
- [x] Clean design: takes `WorkspaceSandbox` instance, no cairn dependency
- [x] `from_work_dir()` factory method for convenience
- [x] 4 built-in checks: syntax, types, tests, lint
- [x] `tests/unit/test_validation.py` — 21/21 tests passing (uses `MockRuntime`, no patching)
- [x] `src/remora/cli/workspace.py` — `validate` CLI command (handles cairn materialize → sandbox → validator)
- [x] `src/remora/workspace/__init__.py` — validation exports added

---

## Phase 8: Sandbox Container Image — DONE
- [x] `sandbox/Dockerfile` — lightweight `python:3.13-slim` based image with pytest, mypy, ruff pre-installed
- [x] `sandbox/entrypoint.sh` — simple entrypoint that runs commands in /workspace
- [x] `sandbox/build.sh` — docker build wrapper script
- [x] Image builds in ~50 seconds (replaced slow Nix-based approach)
- [x] Works air-gapped (`--network none`), read-only filesystem (`--read-only`), and with workspace volume mounts
- [x] Fixed `DockerRuntime` — changed `--no-new-privileges` to `--security-opt no-new-privileges` (compatible with Docker versions that don't support the shorthand)
- [x] Added `read_only` parameter to `ContainerRuntime.run()` and `DockerRuntime.run()`
- [x] Default image changed from `python:3.12-slim` to `remora-sandbox:latest`
- [x] `tests/unit/test_sandbox.py` — 33/33 unit tests passing
- [x] `tests/integration/test_sandbox_container.py` — 17/17 integration tests passing (real Docker, skipped if image not built)

---

**Test Summary:**
- fsdantic: 320/321 passing (1 pre-existing version assertion test)
- Cairn: 48/49 passing (1 pre-existing grail.GrailExecutionError test)
  - workspace API: 20/20
  - orchestrator: 12/13 (1 pre-existing)
  - workspace manager: 5/5
  - concurrency: 11/11
- Remora unit tests: 156 passing across cairn-enhancement test files:
  - sandbox: 33/33
  - validation: 21/21
  - workspace sync: 24/24
  - workspace CLI: 13/13
  - protocols: 30/30
  - state manager: 35/35
- Remora integration tests: 17 passing (sandbox container)
  - DockerRuntime integration: 7/7
  - WorkspaceSandbox integration: 10/10
