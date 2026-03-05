# CONTEXT — vLLM Message Delivery Failure

Created: 2026-03-05

## Why This Project Exists
User reports that chat messages are still not reaching vLLM, despite major fixes in scan/startup paths.

## Current Known State
- Background scan is now completing with unchanged-file skips.
- Panel/read operations are responsive in latest logs.
- Agent execution is still unstable around workspace initialization in some runs.
- This project isolates and verifies the model-delivery path specifically.

## Immediate Next Action
Run targeted log analysis and code-path inspection from `on_input_submitted` through the LLM client call boundary, then reproduce with fresh timestamps.

## 2026-03-05 Findings + Fixes Applied

### Root Cause
Latest failing run (`server-2026-03-05_171713.log`) showed chat submit reached runner trigger, but execution stalled before model dispatch:
- `execute_agent_turn: initializing workspace service`
- then timeout / workspace-open failures:
  - `execute_agent_turn timed out after 30.0s`
  - `Failed to create stable workspace: [WORKSPACE_OPEN_FAILED] ... stable.db`

This meant messages never reached the vLLM boundary in those failing turns.

### Contributing Factors
- Per-turn workspace initialization was expensive and brittle in this environment.
- LSP runner created a fresh workspace service each turn and did not reuse one.
- Stable workspace files had grown very large (`stable.db` + `stable.db-wal` multiple GB), amplifying init cost/risk.
- Some file paths are `file:///...` URIs; path normalization needed to preserve valid filesystem paths in workspace/disk loaders.

### Code Changes
1) `execute_agent_turn` workspace init now uses lightweight mode when it has to create its own service:
- `CairnWorkspaceService.initialize(sync_mode=SyncMode.NONE)`
- Added detailed timing logs for workspace init, workspace acquisition, and model dispatch.
- Added explicit model-boundary diagnostics (`base_url`, `model`, `kernel.run` start/end/failure).
- Added cleanup for internally-created workspace service.

2) LSP runner now reuses a long-lived workspace service:
- Added `AgentRunner._get_workspace_service(...)` with `SyncMode.NONE`.
- `execute_turn()` now passes shared `workspace_service` into `execute_agent_turn(...)`.
- Added `AgentRunner.close()` and wired shutdown close in `lsp/__main__.py`.

3) Path normalization improvement:
- `normalize_path()` now maps `file://` URIs to real filesystem paths.

### Validation Performed
- `ruff check` on changed files: pass.
- Unit tests:
  - `tests/unit/test_execution.py`
  - `tests/unit/test_runner_loop.py`
  - `tests/unit/test_lsp_runner.py`
  all pass.
- Connectivity probe from Remora env:
  - `GET http://remora-server:8000/v1/models` returned HTTP 200.
- Direct execution probe:
  - `execute_agent_turn(...)` against an existing node returned non-empty model response text.

### Remaining Validation
- Need manual Neovim chat run with fresh logs to confirm UI path now consistently reaches vLLM after these changes.
