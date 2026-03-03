# Cairn Usage Analysis

Detailed analysis of each Cairn integration point in Remora.

---

## 1. Core Integration Files

### 1.1 `cairn_bridge.py` (213 lines)

**Location:** `src/remora/core/cairn_bridge.py`

**Purpose:** Central service for managing stable and per-agent workspaces via Cairn runtime APIs.

**Cairn Imports:**
```python
from cairn.runtime import workspace_manager as cairn_workspace_manager
```

**Key Classes:**
- `SyncMode` - Enum for workspace sync levels (FULL, NONE)
- `CairnWorkspaceService` - Main integration facade

**CairnWorkspaceService Responsibilities:**

| Method | Description |
|--------|-------------|
| `__init__` | Creates `WorkspaceManager`, sets up paths |
| `initialize()` | Opens stable workspace, syncs project files |
| `get_agent_workspace()` | Creates/returns per-agent CoW workspace |
| `get_externals()` | Builds Grail external functions dict |
| `close()` | Closes all tracked workspaces |
| `_sync_project_to_workspace()` | Incremental mtime-based file sync |
| `ensure_file_synced()` | On-demand single-file sync |

**Cairn API Usage:**
```python
# Opening workspaces
cairn_workspace_manager._open_workspace(path, readonly=False)

# Tracking for cleanup
self._manager.track_workspace(workspace)

# Closing all
await self._manager.close_all()

# File operations on workspace
await workspace.files.write(path, payload, mode="binary")
```

**Integration Quality:**
- **Cohesion:** High - single responsibility (workspace management)
- **Abstraction:** Good - Cairn details hidden behind `CairnWorkspaceService`
- **Coupling:** Medium - depends on Cairn's `_open_workspace` (underscore = private API)

---

### 1.2 `cairn_externals.py` (71 lines)

**Location:** `src/remora/core/cairn_externals.py`

**Purpose:** Adapter wrapping `CairnExternalFunctions` with path normalization for Grail tools.

**Cairn Imports:**
```python
from cairn.runtime.external_functions import CairnExternalFunctions
```

**Key Classes:**
- `CairnExternals` - Dataclass wrapper with path normalization

**Wrapped Methods:**

| Method | Description |
|--------|-------------|
| `read_file(path)` | Read file with normalized path |
| `write_file(path, content)` | Write file with normalized path |
| `list_dir(path)` | List directory entries |
| `file_exists(path)` | Check file existence |
| `search_files(pattern)` | Glob search (no normalization) |
| `search_content(pattern, path)` | Content search with normalized path |
| `submit_result(summary, changed_files)` | Submit agent result |
| `log(message)` | Agent logging |

**Key Pattern:**
```python
def _normalize(self, path: str) -> str:
    return self.resolver.to_workspace_path(path)

async def read_file(self, path: str) -> str:
    return await self._delegate.read_file(self._normalize(path))
```

**Integration Quality:**
- **Cohesion:** High - single responsibility (path-normalized file ops)
- **Abstraction:** Excellent - clean wrapper with no leaked Cairn details
- **Coupling:** Low - thin adapter, easy to swap implementation

---

### 1.3 `workspace.py` (191 lines)

**Location:** `src/remora/core/workspace.py`

**Purpose:** Agent workspace wrapper and data provider for Grail virtual FS.

**Cairn Imports:**
```python
from cairn.runtime import workspace_manager as cairn_workspace_manager
```

**Key Classes:**

#### `AgentWorkspace`
Wraps a Cairn workspace with agent-specific methods and stable workspace fallback.

| Property/Method | Description |
|-----------------|-------------|
| `cairn` | Access underlying Cairn workspace |
| `read(path)` | Read with agent -> stable fallback |
| `write(path, content)` | Write to agent workspace (CoW) |
| `exists(path)` | Check agent then stable |
| `list_dir(path)` | Union of agent + stable entries |

**Fallback Pattern:**
```python
async def read(self, path: PathLike) -> str:
    try:
        # Try agent workspace first
        return await self._workspace.files.read(path_str, mode="text")
    except Exception as exc:
        if not _is_missing_file_error(exc):
            raise
    # Fall back to stable workspace
    return await self._stable_workspace.files.read(path_str, mode="text")
```

#### `CairnDataProvider`
Loads files for Grail's virtual filesystem from workspace.

| Method | Description |
|--------|-------------|
| `load_files(node, related)` | Load target + related files |
| `_load_from_disk(path)` | Fallback to direct disk read |

**Integration Quality:**
- **Cohesion:** High - workspace abstraction only
- **Abstraction:** Good - hides workspace API details
- **Coupling:** Medium - exposes `.cairn` property for direct access

---

### 1.4 `agent_context.py` (66 lines)

**Location:** `src/remora/core/agent_context.py`

**Purpose:** Typed execution context replacing untyped `externals: dict`.

**Cairn Imports:** None (uses output from `CairnExternals`)

**Key Class:**
- `AgentContext` - Pydantic model with typed fields

**Cairn-Related Fields:**
```python
# Cairn file-system externals for Grail runtime
cairn_externals: dict[str, Any] = Field(default_factory=dict)
```

**Integration Pattern:**
```python
def as_externals(self) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    # Cairn externals first (read_file, write_file, etc.)
    merged.update(self.cairn_externals)
    # Swarm keys overlay
    merged["agent_id"] = self.agent_id
    ...
    return merged
```

**Integration Quality:**
- **Cohesion:** High - typed context container
- **Abstraction:** Good - cairn_externals is opaque dict
- **Coupling:** Low - no direct Cairn dependency

---

## 2. Service Layer Integration

### 2.1 `swarm_executor.py` (433 lines)

**Location:** `src/remora/core/swarm_executor.py`

**Purpose:** Executes single agent turns in reactive swarm mode.

**Cairn Integration Points:**

1. **Workspace Service Creation (line 74-78):**
```python
self._workspace_service = CairnWorkspaceService(
    config=config,
    swarm_root=config.swarm_root,
    project_root=project_root,
)
```

2. **Workspace Initialization (line 109-113):**
```python
if not self._workspace_initialized:
    await self._workspace_service.initialize()
    self._workspace_initialized = True
```

3. **Agent Workspace Retrieval (line 116-117):**
```python
workspace = await self._workspace_service.get_agent_workspace(node.node_id)
cairn_externals = self._workspace_service.get_externals(node.node_id, workspace)
```

4. **Context Creation (line 182-191):**
```python
agent_context = AgentContext(
    agent_id=node.node_id,
    ...
    cairn_externals=cairn_externals,
)
```

5. **Data Provider (line 193):**
```python
data_provider = CairnDataProvider(workspace, self._path_resolver)
```

**Integration Quality:**
- **Cohesion:** Medium - swarm executor does many things
- **Abstraction:** Good - uses `CairnWorkspaceService` facade
- **Coupling:** Medium - directly orchestrates workspace lifecycle

---

### 2.2 `chat.py` (331 lines)

**Location:** `src/remora/core/chat.py`

**Purpose:** Simplified single-agent chat interface.

**Cairn Integration Points:**

1. **Workspace Service Creation (line 140-144):**
```python
self._workspace = CairnWorkspaceService(
    config=workspace_config,
    swarm_root=workspace_path / ".remora",
    project_root=workspace_path,
)
await self._workspace.initialize()
```

2. **Agent Workspace for Tools (line 147-148):**
```python
agent_workspace = await self._workspace.get_agent_workspace(self.session_id)
self._tools = build_chat_tools(agent_workspace, workspace_path)
```

3. **Tool Wrappers (line 287-298):**
```python
async def read_file(path: str) -> str:
    return await agent_workspace.read(path)

async def write_file(path: str, content: str) -> bool:
    await agent_workspace.write(path, content)
    return True
```

**Integration Quality:**
- **Cohesion:** High - chat session management
- **Abstraction:** Good - `AgentWorkspace` methods only
- **Coupling:** Low - uses high-level workspace API

---

### 2.3 `api.py` (197 lines)

**Location:** `src/remora/service/api.py`

**Purpose:** Framework-agnostic Remora service API.

**Cairn Integration Points:**

1. **Workspace Service Creation (line 64-68):**
```python
workspace_service = CairnWorkspaceService(
    config=resolved_config,
    swarm_root=swarm_root,
    project_root=resolved_root,
)
```

2. **Service Dependency Injection (line 76, 96, 107):**
```python
workspace_service=workspace_service
```

3. **Accessor (line 167-168):**
```python
def get_workspace_service(self) -> CairnWorkspaceService | None:
    return self._workspace_service
```

**Integration Quality:**
- **Cohesion:** High - service facade
- **Abstraction:** Good - passes through `CairnWorkspaceService`
- **Coupling:** Low - dependency injection pattern

---

### 2.4 `handlers.py` (145 lines)

**Location:** `src/remora/service/handlers.py`

**Purpose:** Framework-agnostic service handlers.

**Cairn Integration Points:**

1. **Type Import Only (line 21):**
```python
from remora.core.cairn_bridge import CairnWorkspaceService
```

2. **ServiceDeps Field (line 34):**
```python
workspace_service: "CairnWorkspaceService | None" = None
```

**Integration Quality:**
- **Cohesion:** High - handler functions
- **Abstraction:** Excellent - type annotation only
- **Coupling:** Very Low - no direct usage

---

### 2.5 `chat_service.py` (253 lines)

**Location:** `src/remora/service/chat_service.py`

**Purpose:** Standalone chat service demo.

**Cairn Integration Points:**

1. **Health Check Import (line 226-230):**
```python
from cairn import Cairn
logger.info("cairn: OK")
```

**Integration Quality:**
- **Cohesion:** N/A - just availability check
- **Abstraction:** N/A
- **Coupling:** Minimal - import-time check only

---

## 3. Integration Patterns Summary

### Pattern 1: Facade Pattern
`CairnWorkspaceService` acts as the single entry point for all workspace operations. Other code uses this facade rather than calling Cairn APIs directly.

### Pattern 2: Adapter Pattern
`CairnExternals` adapts `CairnExternalFunctions` with path normalization, providing a workspace-relative interface.

### Pattern 3: Fallback Chain
`AgentWorkspace.read()` implements agent -> stable -> disk fallback for file reads.

### Pattern 4: Dependency Injection
`ServiceDeps` and `RemoraService` pass workspace service through constructor, enabling testability.

### Pattern 5: Late Initialization
`CairnWorkspaceService.initialize()` is called separately from construction, allowing async setup.

---

## 4. Direct Cairn API Usage

| File | API Used |
|------|----------|
| `cairn_bridge.py` | `workspace_manager._open_workspace()`, `WorkspaceManager()`, `track_workspace()`, `close_all()`, `workspace.files.write()` |
| `cairn_externals.py` | `CairnExternalFunctions` (all methods) |
| `workspace.py` | `workspace.files.read()`, `workspace.files.write()`, `workspace.files.exists()`, `workspace.files.list_dir()` |
| `chat_service.py` | `Cairn` (import check only) |

---

## 5. Coupling Assessment

| Category | Files | Assessment |
|----------|-------|------------|
| Direct Cairn Import | 4 | Low - concentrated in core |
| Private API Usage | 1 | Risk - `_open_workspace` is underscore-prefixed |
| Type-Only Import | 1 | Excellent - loose coupling |
| No Cairn Import | 2 | Good - uses Remora abstractions |

**Overall Coupling Score: 7/10** (Good)

The integration is well-abstracted with most Cairn details hidden behind `CairnWorkspaceService` and `CairnExternals`. The main concern is using `_open_workspace` which appears to be a private API.
