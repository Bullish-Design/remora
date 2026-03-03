# Cairn Gap Analysis

Analysis of what Cairn provides vs what we need for workspace enhancements.

---

## Current Cairn Public API

### From `cairn/__init__.py`

```python
__all__ = [
    "AgentContext",
    "AgentState", 
    "CairnExternalFunctions",
    "CairnOrchestrator",
    "CodeProvider",
    "FileCodeProvider",
    "InlineCodeProvider",
    "resolve_code_provider",
    "ExecutorSettings",
    "OrchestratorSettings", 
    "PathsSettings",
    "QueuedTask",
    "RetryStrategy",
    "with_retry",
    "SignalHandler",
    "TaskPriority",
    "TaskQueue",
    "create_external_functions",
    "FileWatcher",
]
```

### From `cairn.runtime`

| Class/Function | Purpose | fsdantic Dependency |
|----------------|---------|---------------------|
| `WorkspaceManager` | Lifecycle management, open/close | Uses `fsdantic.Workspace` |
| `CairnExternalFunctions` | File I/O for Grail tools | Uses `fsdantic.Workspace.files` |
| `create_external_functions()` | Factory for externals dict | Uses above |

### From `cairn.orchestrator`

| Class | Purpose | fsdantic Dependency |
|-------|---------|---------------------|
| `LifecycleStore` | Agent state persistence | Uses `fsdantic.Workspace.kv.repository()` |
| `LifecycleRecord` | Agent metadata model | Uses `fsdantic.VersionedKVRecord` |

---

## What Remora Currently Uses from Cairn

| Usage Location | Cairn Import | What It Does |
|----------------|--------------|--------------|
| `cairn_bridge.py` | `workspace_manager._open_workspace()` | Open workspace (PRIVATE!) |
| `cairn_bridge.py` | `WorkspaceManager()` | Track/close workspaces |
| `cairn_externals.py` | `CairnExternalFunctions` | File I/O for Grail |

---

## What's MISSING from Cairn's Public API

### 1. **Workspace Opening (P0)**

**Problem:** Cairn only exposes `WorkspaceManager.open_workspace()` as an async context manager, not a standalone open function.

**Current workaround:** Remora uses private `_open_workspace()`.

**What Cairn should add:**
```python
# In cairn.runtime.workspace_manager
async def open_workspace(path: Path | str, *, readonly: bool = False) -> Workspace:
    """Open a workspace without context manager."""
    return await _open_workspace(path, readonly=readonly)
```

### 2. **Workspace Inspection Utilities**

**Problem:** Cairn doesn't expose any inspection/debugging tools.

**What Cairn should add:**
```python
# New module: cairn/runtime/inspection.py

class WorkspaceInspector:
    """Read-only workspace inspection utilities."""
    
    def __init__(self, workspace: Workspace): ...
    
    async def tree(self, path: str = "/", max_depth: int | None = None) -> dict: ...
    async def stats(self) -> WorkspaceStats: ...
    async def diff(self, base: Workspace) -> list[FileChange]: ...
```

### 3. **Materialization Wrapper**

**Problem:** Materialization exists in fsdantic but Cairn doesn't expose it.

**What Cairn should add:**
```python
# In cairn/runtime/__init__.py or new module

async def materialize_workspace(
    workspace: Workspace,
    target_path: Path,
    base: Workspace | None = None,
) -> MaterializationResult:
    """Extract workspace contents to disk."""
    return await workspace.materialize.to_disk(target_path, base_fs=base)
```

### 4. **Agent State Manager**

**Problem:** Cairn has `LifecycleStore` for orchestrator state, but no general-purpose agent state API.

**What Cairn should add:**
```python
# New module: cairn/runtime/state.py

class AgentStateManager:
    """Manage agent state in workspace KV store."""
    
    def __init__(self, workspace: Workspace, agent_id: str): ...
    
    async def get(self, key: str, default: Any = None) -> Any: ...
    async def set(self, key: str, value: Any) -> None: ...
    async def increment_turn(self) -> int: ...
```

### 5. **Bidirectional Sync**

**Problem:** Neither Cairn nor fsdantic has disk → workspace sync.

**What should be added (location TBD):**
```python
class WorkspaceSync:
    """Sync changes between disk and workspace."""
    
    async def scan_disk_changes(self, disk_dir: Path) -> list[SyncChange]: ...
    async def sync_from_disk(self, disk_dir: Path) -> SyncResult: ...
```

**Question:** Should this go in fsdantic (lower-level) or Cairn (higher-level)?

---

## Recommendation: What to Add to Cairn

### Tier 1: Essential (Block our implementation)

| Addition | Location | Effort |
|----------|----------|--------|
| Public `open_workspace()` function | `runtime/workspace_manager.py` | 1h |
| Re-export in `__init__.py` | `__init__.py` | 0.5h |

### Tier 2: Convenient (Avoid fsdantic imports in Remora)

| Addition | Location | Effort |
|----------|----------|--------|
| `WorkspaceInspector` class | `runtime/inspection.py` | 4h |
| `materialize_workspace()` wrapper | `runtime/materialization.py` | 2h |
| `AgentStateManager` class | `runtime/state.py` | 3h |

### Tier 3: New Functionality

| Addition | Location | Effort |
|----------|----------|--------|
| `WorkspaceSync` class | `runtime/sync.py` | 6h |
| CLI commands (`cairn workspace tree`, etc.) | `cli/workspace.py` | 4h |

---

## Decision Point

**Option A: Add to Cairn first, then implement in Remora**
- Pros: Clean architecture, single import path
- Cons: Requires Cairn PR, delays Remora work

**Option B: Implement in Remora now, migrate to Cairn later**
- Pros: Faster for Remora
- Cons: Tech debt, dual maintenance

**Option C: Minimal Cairn additions (Tier 1 only), rest in Remora**
- Pros: Balance of speed and cleanliness
- Cons: Some fsdantic imports remain in Remora

---

## Proposed Path Forward

1. **Add to Cairn (Tier 1):**
   - Public `open_workspace()` function
   - Export `Workspace` type from Cairn

2. **Add to Cairn (Tier 2):**
   - `AgentStateManager` (since state persistence is core to agent execution)
   - `WorkspaceInspector` (useful for debugging Cairn itself)

3. **Keep in Remora:**
   - CLI commands (Remora-specific UX)
   - Container sandbox (Remora execution concern)
   - Validation harness (Remora quality gate)

4. **Keep in fsdantic:**
   - `WorkspaceSync` (low-level filesystem operation)
   - Materialization (already exists there)

---

## Summary Table

| Feature | Where It Should Live | Current State |
|---------|---------------------|---------------|
| Open workspace | **Cairn** | Private API only |
| Workspace type | **Cairn** (re-export) | fsdantic only |
| File I/O | **Cairn** | ✅ CairnExternalFunctions |
| KV operations | **Cairn** | Partial (LifecycleStore) |
| Agent state | **Cairn** | ❌ Missing |
| Inspection | **Cairn** | ❌ Missing |
| Materialization | fsdantic | ✅ Exists |
| Bidirectional sync | fsdantic | ❌ Missing |
| CLI commands | Remora | ❌ Missing |
| Container sandbox | Remora | ❌ Missing |
| Validation | Remora | ❌ Missing |
