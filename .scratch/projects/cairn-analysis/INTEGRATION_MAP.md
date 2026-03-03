# Cairn Integration Map

Overview of all Cairn touchpoints in Remora.

---

## Architecture Diagram

```
+------------------+     +------------------+     +------------------+
|   RemoraService  |     |  SwarmExecutor   |     |   ChatSession    |
|     (api.py)     |     | (swarm_executor) |     |    (chat.py)     |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         |                        |                        |
         v                        v                        v
+--------+------------------------+------------------------+---------+
|                      CairnWorkspaceService                         |
|                       (cairn_bridge.py)                            |
|                                                                    |
|  +----------------+    +-------------------+    +----------------+ |
|  | stable_workspace|    | agent_workspaces  |    | WorkspaceManager| |
|  | (project files)|    | (per-agent CoW)   |    | (lifecycle)    | |
|  +----------------+    +-------------------+    +----------------+ |
+--------------------------------------------------------------------+
         |                        |                        |
         v                        v                        v
+--------+------------------------+------------------------+---------+
|                         Cairn Runtime                              |
|                   workspace_manager module                         |
|                                                                    |
|  +---------------------+    +----------------------------+         |
|  | _open_workspace()   |    | CairnExternalFunctions     |         |
|  | WorkspaceManager    |    | (read_file, write_file...) |         |
|  +---------------------+    +----------------------------+         |
+--------------------------------------------------------------------+
```

---

## File Dependency Graph

```
chat_service.py -----> cairn (import check only)
        |
        v
    chat.py ----------> CairnWorkspaceService
        |                       |
        v                       v
  AgentWorkspace <-------- cairn_bridge.py -------> workspace_manager
        |                       |
        v                       v
  CairnDataProvider       CairnExternals ---------> CairnExternalFunctions
        |                       |
        v                       v
    workspace.py          cairn_externals.py


api.py ---------> CairnWorkspaceService
   |                     |
   v                     v
handlers.py         ServiceDeps (workspace_service field)
   |
   v
swarm_executor.py --+
   |                |
   +--> CairnWorkspaceService
   +--> CairnDataProvider
   +--> AgentContext (cairn_externals)
```

---

## Import Chains

### Chain 1: Service API
```
api.py
  -> cairn_bridge.CairnWorkspaceService
    -> cairn.runtime.workspace_manager
    -> cairn_externals.CairnExternals
      -> cairn.runtime.external_functions.CairnExternalFunctions
```

### Chain 2: Swarm Executor
```
swarm_executor.py
  -> cairn_bridge.CairnWorkspaceService
  -> workspace.CairnDataProvider
    -> cairn.runtime.workspace_manager (workspace.files API)
```

### Chain 3: Chat Session
```
chat.py
  -> cairn_bridge.CairnWorkspaceService
  -> workspace.AgentWorkspace
    -> cairn.runtime.workspace_manager (workspace.files API)
```

---

## Data Flow

### 1. Workspace Initialization

```
RemoraService.create_default()
    |
    v
CairnWorkspaceService.__init__()
    |
    +-- Creates WorkspaceManager
    +-- Sets up path resolver
    |
    v
CairnWorkspaceService.initialize()
    |
    +-- Opens stable.db workspace
    +-- Tracks with manager
    +-- Syncs project files (mtime-based)
```

### 2. Agent Execution

```
SwarmExecutor.run_agent(node)
    |
    v
CairnWorkspaceService.get_agent_workspace(agent_id)
    |
    +-- Opens agents/{id}/workspace.db
    +-- Creates AgentWorkspace wrapper
    +-- Returns cached or new workspace
    |
    v
CairnWorkspaceService.get_externals(agent_id, workspace)
    |
    +-- Creates CairnExternals
    +-- Returns as_externals() dict
    |
    v
AgentContext(cairn_externals=externals)
    |
    v
Grail tools receive externals via context
```

### 3. File Operations

```
Grail tool calls read_file("src/foo.py")
    |
    v
CairnExternals.read_file(path)
    |
    +-- Normalizes path via resolver
    |
    v
CairnExternalFunctions.read_file(normalized_path)
    |
    +-- Reads from agent workspace
    +-- Falls back to stable workspace
    |
    v
Returns file content to tool
```

---

## Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| `CairnWorkspaceService` | Workspace lifecycle, sync, externals factory |
| `CairnExternals` | Path normalization wrapper for Grail |
| `AgentWorkspace` | Single agent's workspace with fallback reads |
| `CairnDataProvider` | Load files for Grail virtual FS |
| `AgentContext` | Typed context container with `cairn_externals` |
| `ServiceDeps` | Dependency injection container |

---

## Cairn APIs Used

| API | Location | Purpose |
|-----|----------|---------|
| `workspace_manager.WorkspaceManager()` | cairn_bridge:52 | Lifecycle management |
| `workspace_manager._open_workspace()` | cairn_bridge:78,101 | Create/open workspace |
| `manager.track_workspace()` | cairn_bridge:82,105 | Register for cleanup |
| `manager.close_all()` | cairn_bridge:135 | Cleanup all workspaces |
| `workspace.files.write()` | cairn_bridge:169,191 | Write to workspace |
| `workspace.files.read()` | workspace:60,66,74 | Read from workspace |
| `workspace.files.exists()` | workspace:87,92 | Check file existence |
| `workspace.files.list_dir()` | workspace:98,102 | List directory |
| `CairnExternalFunctions` | cairn_externals:22 | Grail external functions |

---

## Test Coverage

### Integration Tests

| Test File | Coverage |
|-----------|----------|
| `test_lifecycle.py` | Workspace open/close |
| `test_error_recovery.py` | Error handling |
| `test_concurrent_safety.py` | Concurrent access |
| `test_merge_operations.py` | Merge semantics |
| `test_path_resolution.py` | Path normalization |
| `test_workspace_isolation.py` | CoW isolation |
| `test_kv_operations.py` | KV store usage |
| `test_write_semantics.py` | Write operations |
| `test_agent_isolation.py` | Per-agent isolation |
| `test_read_semantics.py` | Read operations |

### Unit Tests

| Test File | Coverage |
|-----------|----------|
| `test_agent_context.py` | `cairn_externals` field |
| `test_batch8_fixes.py` | CairnWorkspaceService patches |

---

## Public vs Private APIs

| Type | APIs | Risk |
|------|------|------|
| Public | `CairnExternalFunctions`, `WorkspaceManager` | Low |
| Private | `_open_workspace` | Medium - may change |

---

## Entry Points Summary

| Entry Point | Cairn Usage |
|-------------|-------------|
| `RemoraService.create_default()` | Creates CairnWorkspaceService |
| `SwarmExecutor.run_agent()` | Uses workspace for agent |
| `ChatSession.create()` | Creates workspace for chat |
| `chat_service.startup()` | Checks Cairn availability |
