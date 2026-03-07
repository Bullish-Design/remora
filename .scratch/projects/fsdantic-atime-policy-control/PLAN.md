# Plan

## Goal
Expose a Remora-usable switch to disable `atime` writes on file reads, implemented primarily in FSdantic (without changing AgentFS).

## Scope
- FSdantic: add read-atime policy and no-atime read path.
- Cairn: plumb the policy into `Fsdantic.open(...)`.
- Remora: expose config and pass it to Cairn workspace opens.
- Tests/docs across all touched codebases.

## Exact Change List

### 1) FSdantic (primary ownership)

1. Update [client.py](/home/andrew/Documents/Projects/remora/.context/fsdantic/src/fsdantic/client.py)
- Add new `open()` kwarg:
  - `read_atime_policy: Literal["strict", "noatime"] = "strict"`
- Propagate this into `Workspace(...)` construction.

2. Update [workspace.py](/home/andrew/Documents/Projects/remora/.context/fsdantic/src/fsdantic/workspace.py)
- Add `read_atime_policy` field on `Workspace`.
- Pass policy into `FileManager` constructor.

3. Update [files.py](/home/andrew/Documents/Projects/remora/.context/fsdantic/src/fsdantic/files.py)
- Extend `FileManager.__init__` with `read_atime_policy`.
- In `FileManager.read(...)`:
  - if policy is `strict` -> current path (`agent_fs.fs.read_file(...)`).
  - if policy is `noatime` -> use new internal helper that reads bytes without performing the `UPDATE fs_inode SET atime ...` write.
- Add internal helper (example name: `_read_without_atime(...)`) that:
  - resolves inode using existing AgentFS FS internals,
  - validates readable inode (same validation semantics),
  - reads chunks from `fs_data` ordered by `chunk_index`,
  - decodes bytes when text mode is requested,
  - does **not** update `fs_inode.atime`.
- Add guard/fallback behavior:
  - if required AgentFS internals are unavailable, raise clear `FsdanticError` with guidance (or log+fallback to strict mode, choose one and document it).

4. Update docs
- [README.md](/home/andrew/Documents/Projects/remora/.context/fsdantic/README.md): add API option and behavior notes.
- [SPEC.md](/home/andrew/Documents/Projects/remora/.context/fsdantic/SPEC.md): define strict vs noatime semantics.

5. FSdantic tests (new or existing test module)
- Add tests for:
  - strict mode still updates atime (behavior parity).
  - noatime mode does not change atime on reads.
  - noatime mode improves concurrent read/write success for single workspace connection.

### 2) Cairn (pass-through plumbing)

1. Update [workspace_manager.py](/home/andrew/Documents/Projects/remora/.context/cairn/src/cairn/runtime/workspace_manager.py)
- Add parameter to `_open_workspace(...)`, `open_workspace(...)`, and `WorkspaceManager.create_workspace/open_workspace(...)`:
  - `read_atime_policy: Literal["strict", "noatime"] = "strict"`
- Pass through to `Fsdantic.open(...)`.
- Include policy in workspace-open error context payload.

2. Cairn docs/tests
- Document new workspace open option in relevant docs.
- Add/adjust tests for option passthrough.

### 3) Remora (consumer control)

1. Update [config.py](/home/andrew/Documents/Projects/remora/src/remora/core/config.py)
- Add config field:
  - `workspace_read_atime_policy: Literal["strict", "noatime"] = "noatime"`
- Keep explicit default in Remora as `noatime` to prioritize concurrency/stability.

2. Update [cairn_bridge.py](/home/andrew/Documents/Projects/remora/src/remora/core/agents/cairn_bridge.py)
- Pass `read_atime_policy=self._config.workspace_read_atime_policy` on both stable and agent workspace opens.

3. Optional CLI plumbing
- Add `--workspace-read-atime-policy` where relevant in workspace CLI commands.

4. Remora tests
- Integration test: concurrent read/write and concurrent write tests pass under default config.
- Unit test: service passes config value through to Cairn open call.

## Acceptance Criteria
- Remora can disable read-driven atime writes via config.
- Existing behavior remains available with `strict` mode.
- Concurrency tests that currently fail due to DB locks pass with `noatime` mode.
- No AgentFS source changes required.

## Non-Goals
- Implementing full `relatime`/`lazytime` variants in first pass.
- Changing AgentFS upstream code.
