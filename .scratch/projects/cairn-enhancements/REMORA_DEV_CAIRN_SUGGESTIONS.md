# Remora Developer Suggestions for Cairn Library

Saved from conversation — these are changes the remora dev would like to see in cairn,
based on friction points identified from studying both the cairn source and how remora consumes it.
We'll come back to these after updating fsdantic.

---

## 1. Export open_workspace as a top-level convenience function

**Problem:** Remora currently does `from cairn.runtime.workspace_manager import open_workspace`, but that's actually a context manager method on WorkspaceManager, not a standalone function. What remora really calls is `_open_workspace` (the private module-level helper). The naming mismatch caused confusion during the migration.

**Suggestion:** Add a top-level `cairn.open_workspace(path, *, readonly=False) -> Workspace` function (not a context manager, just returns the workspace). This is the most common operation any consumer needs. Currently the only way to open a workspace without a WorkspaceManager is to call the private `_open_workspace`.

```python
# cairn/__init__.py should export:
from cairn.runtime.workspace_manager import open_workspace  # the standalone async function
```

## 2. Add AgentStateManager or equivalent

**Problem:** Remora imports `from cairn import AgentStateManager` but this class does not exist in cairn's source. Remora's `RemoraStateManager` wraps it and expects methods like `get_typed()`, `set_typed()`, `increment_turn()`, `get_turn()`, `get()`, `set()`, `delete()`, `clear_all()`. This is all typed KV state scoped to an agent.

**Suggestion:** Either:
- (a) Add `AgentStateManager` to cairn that wraps `workspace.kv.namespace(agent_id)` with `get_typed`/`set_typed` convenience methods, OR
- (b) Add `get_typed(key, model_class)` and `set_typed(key, model_instance)` directly to `KVManager` in fsdantic, so remora can just use `workspace.kv.namespace(agent_id).get_typed(...)`. This is cleaner.

Option (b) makes more sense — the typed KV pattern is general-purpose, not agent-specific. The `TypedKVRepository` already does this via `.load()`/`.save()` but requires a fixed model type at construction time, which doesn't work when you want different models under different keys in the same namespace.

## 3. Add WorkspaceInspector / WorkspaceStats

**Problem:** Remora imports `from cairn import WorkspaceInspector, WorkspaceStats` but neither exists. Remora's `RemoraWorkspaceInspector` expects `WorkspaceInspector.from_path(path)` to return an object with `stats()`, `tree()`, `list_dir()`, `read()`, `exists()`, plus a `.workspace` attribute for KV access.

**Suggestion:** Add a read-only `WorkspaceInspector` class to cairn. It's a thin facade:
- `from_path(path) -> WorkspaceInspector` — opens workspace in readonly mode
- `stats() -> WorkspaceStats` — returns file_count, dir_count, total_bytes
- `tree(path, max_depth)` — delegates to `workspace.files.tree()`
- `list_dir(path)` — delegates to `workspace.files.list_dir()`
- `read(path)` — delegates to `workspace.files.read()`
- `exists(path)` — delegates to `workspace.files.exists()`
- `.workspace` — exposes the underlying workspace for KV access

This keeps the "inspection" concern in cairn where it belongs, rather than every consumer reimplementing it.

## 4. Make WorkspaceManager.open_workspace return a plain workspace (non-context-manager variant)

**Problem:** `WorkspaceManager.open_workspace()` is an `@asynccontextmanager`. That's great for ephemeral use, but remora opens workspaces that live for the entire session and manages their lifetime manually via `track_workspace()` + `close_all()`. This forces remora to call the private `_open_workspace` directly and then `track_workspace()` separately — a two-step dance that should be one call.

**Suggestion:** Add `WorkspaceManager.create_workspace(path, *, readonly=False) -> Workspace` that opens, tracks, and returns the workspace without context-manager semantics. The existing `open_workspace` context manager stays for short-lived use.

## 5. Re-export Workspace type from cairn

**Problem:** Remora imports `from cairn.runtime import workspace_manager` and uses `Any` for workspace type annotations because `Workspace` is only available from `fsdantic.Workspace`. The cairn library is supposed to be remora's interface to fsdantic — remora shouldn't need to know about fsdantic directly.

**Suggestion:** Re-export `Workspace` from cairn:
```python
from cairn import Workspace  # re-exported from fsdantic
```

## Summary of suggested changes (priority order)

| # | Change | Effort | Impact |
|---|--------|--------|--------|
| 1 | Top-level `cairn.open_workspace()` standalone function | Small | Eliminates private-API access |
| 2 | Re-export `Workspace` type from cairn | Trivial | Enables proper typing without fsdantic import |
| 3 | `WorkspaceManager.create_workspace()` (non-context-manager) | Small | Eliminates two-step open+track pattern |
| 4 | `WorkspaceInspector` + `WorkspaceStats` | Medium | Eliminates phantom imports, gives read-only inspection |
| 5 | `AgentStateManager` or typed KV convenience on `KVManager` | Medium | Eliminates phantom import, typed state pattern |

Items 1-3 are quick wins. Items 4-5 are the bigger asks but eliminate the "phantom import" problem where remora imports classes that don't actually exist in cairn yet.
