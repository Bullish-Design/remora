# Cairn Integration Report

## Executive Summary

This report analyzes the integration between Remora and Cairn, examining how Cairn wraps Turso's fsdantic (AgentFS) library to provide concurrent copy-on-write filesystem databases for agent execution. The analysis covers the Cairn architecture, Remora's integration patterns, integration tests, and demos.

**Key Finding**: The integration architecture is sound, but there are potential issues with how the integration tests verify Cairn functionality. The tests primarily check that `fsdantic` can be imported and that basic workspace operations work, but they don't fully exercise the copy-on-write isolation semantics that Cairn is designed to provide.

---

## Part 1: Cairn Architecture

### 1.1 What is Cairn?

Cairn is a workspace-aware orchestration runtime for sandboxed code execution with copy-on-write isolation. Key features:

- **Safe execution of untrusted code** in sandboxed environments
- **Isolated workspace management** with copy-on-write overlays
- **Human-controlled integration** via explicit accept/reject gates
- **Pluggable code providers** for sourcing code from various sources

### 1.2 Core Metaphor

From `docs/CONCEPT.md`:

> A cairn is a pile of stones where each traveler adds to a shared structure.
>
> - Stable workspace remains the source of truth
> - Code executes in isolated overlays with copy-on-write semantics
> - Changes are previewed before integration
> - Humans accept (merge into stable) or reject (discard)

### 1.3 How Cairn Wraps fsdantic (AgentFS)

Cairn uses `fsdantic` as its storage layer. The key components:

**fsdantic imports in Cairn:**
```python
# From cairn/runtime/workspace_manager.py
from fsdantic import Fsdantic, Workspace

# From cairn/orchestrator/orchestrator.py
from fsdantic import Fsdantic, MergeStrategy, Workspace

# From cairn/orchestrator/lifecycle.py
from fsdantic import VersionedKVRecord, Workspace
```

**Workspace Opening Pattern:**
```python
# cairn/runtime/workspace_manager.py:23-31
async def _open_workspace(path: Path | str, *, readonly: bool) -> Workspace:
    try:
        signature = inspect.signature(Fsdantic.open)
    except (TypeError, ValueError):
        signature = None

    if signature and "readonly" in signature.parameters:
        return await Fsdantic.open(path=str(path), readonly=readonly)
    return await Fsdantic.open(path=str(path))
```

### 1.4 Data Layout

Cairn stores data in a `.agentfs/` directory:

```
$PROJECT_ROOT/.agentfs/
├── stable.db        # Source of truth workspace
├── agent-{id}.db    # Per-agent overlay databases
└── bin.db           # Lifecycle metadata storage
```

### 1.5 Copy-on-Write Implementation

The copy-on-write semantics are implemented in `cairn/runtime/external_functions.py`:

```python
# Read: Try agent overlay first, fall through to stable
async def read_file(self, path: str) -> str:
    request = ReadFileRequest(path=path)
    try:
        content = await self.agent_fs.files.read(request.path)
    except FileNotFoundError:
        content = await self.stable_fs.files.read(request.path)
    return ReadFileResponse(content=content).content

# Write: Only to agent overlay
async def write_file(self, path: str, content: str) -> bool:
    request = WriteFileRequest(path=path, content=content)
    await self.agent_fs.files.write(request.path, request.content)
    return True

# Exists: Check both
async def file_exists(self, path: str) -> bool:
    request = FileExistsRequest(path=path)
    if await self.agent_fs.files.exists(request.path):
        return True
    return await self.stable_fs.files.exists(request.path)
```

### 1.6 Merging Agent Changes

When changes are accepted:

```python
# cairn/orchestrator/orchestrator.py:383
merge_result = await self.stable.overlay.merge(agent_fs, strategy=MergeStrategy.OVERWRITE)
```

---

## Part 2: Remora's Integration with Cairn

### 2.1 Key Integration Files

| File | Purpose |
|------|---------|
| `src/remora/cairn_bridge.py` | Main integration layer - CairnWorkspaceService |
| `src/remora/cairn_externals.py` | Wraps Cairn's external functions with path normalization |
| `src/remora/workspace.py` | AgentWorkspace, WorkspaceManager, CairnDataProvider |

### 2.2 CairnWorkspaceService

This is the primary integration point (`src/remora/cairn_bridge.py:39-169`):

```python
class CairnWorkspaceService:
    """Manage stable and agent workspaces via Cairn."""

    def __init__(
        self,
        config: WorkspaceConfig,
        graph_id: str,
        project_root: Path | str | None = None,
    ) -> None:
        self._config = config
        self._graph_id = graph_id
        self._project_root = Path(project_root or Path.cwd()).resolve()
        self._resolver = PathResolver(self._project_root)
        self._base_path = Path(config.base_path) / graph_id
        self._manager = cairn_workspace_manager.WorkspaceManager()
        self._stable_workspace: Any | None = None
        self._agent_workspaces: dict[str, AgentWorkspace] = {}
```

**Key Methods:**

1. `initialize()` - Opens stable workspace and syncs project files
2. `get_agent_workspace(agent_id)` - Creates/retrieves agent overlay
3. `get_externals(agent_id, workspace)` - Builds Cairn external functions for Grail
4. `close()` - Cleans up all workspaces

### 2.3 CairnExternals

Wraps Cairn's external functions with path normalization (`src/remora/cairn_externals.py`):

```python
@dataclass(slots=True)
class CairnExternals:
    """Namespace for Cairn-backed Grail externals with path normalization."""

    agent_id: str
    agent_fs: Any
    stable_fs: Any
    resolver: PathResolver
    _delegate: CairnExternalFunctions = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._delegate = CairnExternalFunctions(
            agent_id=self.agent_id,
            agent_fs=self.agent_fs,
            stable_fs=self.stable_fs,
        )

    def _normalize(self, path: str) -> str:
        return self.resolver.to_workspace_path(path)

    async def read_file(self, path: str) -> str:
        return await self._delegate.read_file(self._normalize(path))
```

### 2.4 Integration in GraphExecutor

The `GraphExecutor` (`src/remora/executor.py`) uses Cairn throughout execution:

```python
# Initialize workspace service
workspace_service = CairnWorkspaceService(
    self.config.workspace,
    graph_id,
    project_root=self._path_resolver.project_root,
)
await workspace_service.initialize(sync=True)

# Per-agent execution
workspace = await workspace_service.get_agent_workspace(node.id)
externals = workspace_service.get_externals(node.id, workspace)

# Load files via CairnDataProvider
data_provider = CairnDataProvider(workspace, self._path_resolver)
files = await data_provider.load_files(node.target)

# Discover and run Grail tools with externals
tools = discover_grail_tools(
    manifest.agents_dir,
    externals=externals,
    files_provider=files_provider,
)
```

---

## Part 3: Integration Tests Analysis

### 3.1 AgentFS Availability Check

Tests check if fsdantic is available (`tests/integration/helpers.py:58-84`):

```python
async def agentfs_available(timeout: float = 3.0) -> bool:
    global _AGENTFS_AVAILABLE
    if _AGENTFS_AVAILABLE is not None:
        return _AGENTFS_AVAILABLE
    try:
        from fsdantic import Fsdantic
    except Exception:
        _AGENTFS_AVAILABLE = False
        return _AGENTFS_AVAILABLE

    temp_dir = Path(tempfile.mkdtemp(prefix="remora-agentfs-"))
    db_path = temp_dir / "agentfs.db"

    try:
        workspace = await asyncio.wait_for(Fsdantic.open(path=str(db_path)), timeout=timeout)
    except Exception:
        _AGENTFS_AVAILABLE = False
        return _AGENTFS_AVAILABLE
    # ...
```

**Issue**: This only checks that `Fsdantic.open()` works, not the full copy-on-write semantics.

### 3.2 Smoke Test (`test_smoke_real.py`)

Two tests:

1. **`test_vllm_graph_executor_smoke`** - Runs a minimal graph execution
2. **`test_grail_tool_cairn_write_smoke`** - Tests writing via Grail tool

The second test verifies workspace writing:

```python
async def test_grail_tool_cairn_write_smoke(tmp_path: Path) -> None:
    # ... setup ...

    # Execute tool that writes to workspace
    result = await tool.execute({"path": str(target_path), "content": "hello"}, None)

    # Verify content was written to workspace
    resolver = PathResolver(project_root)
    workspace_path = resolver.to_workspace_path(target_path)
    content = await workspace.read(workspace_path)
    assert content == "hello"
```

**Good**: Tests that writes go to workspace.
**Missing**: Doesn't verify isolation (that stable is unchanged).

### 3.3 Executor Test (`test_executor_real.py`)

**`test_vllm_tool_call_writes_and_submits`** - Tests full workflow:

```python
# Execute graph
results = await executor.run(graph, "tool-call")

# Verify submission output
assert result.output == summary

# Re-open workspace and verify content
workspace_service = CairnWorkspaceService(config.workspace, "tool-call", project_root=project_root)
await workspace_service.initialize(sync=False)
workspace = await workspace_service.get_agent_workspace(agent_id)
stored = await workspace.read(workspace_path)
assert stored == content
```

**Good**: Verifies end-to-end workflow including submission.
**Missing**: Doesn't verify that:
1. Changes are isolated to agent workspace
2. Stable workspace is unchanged
3. Multiple agents don't interfere

### 3.4 Workflow Test (`test_agent_workflow_real.py`)

Most comprehensive test - runs 20 concurrent trials:

```python
@pytest.mark.asyncio
async def test_vllm_agent_workflow_concurrent(tmp_path: Path) -> None:
    # Run 20 trials with 8 concurrent
    runs = max(1, DEFAULT_RUNS)  # 20
    concurrency = max(1, DEFAULT_CONCURRENCY)  # 8
    min_success = max(0.0, min(1.0, DEFAULT_MIN_SUCCESS))  # 0.8
```

Validates:
- Tool calls are made
- Tool results are received
- Submission summaries match
- Workspace content matches expected

**Good**: Tests concurrent execution.
**Missing**: Doesn't verify agent isolation from each other.

---

## Part 4: Demo Analysis

### 4.1 Simple Demo (`demo/run_agent.py`)

Uses structured-agents directly, not the full Remora/Cairn stack. Creates simple file workspaces, not AgentFS.

### 4.2 One Stop Shop Demo (`demo/one_stop_shop/`)

This demo properly exercises Cairn:

```python
# From run_demo.py
workspace_service = CairnWorkspaceService(
    config.workspace, graph_id, project_root=PROJECT_ROOT
)
await workspace_service.initialize(sync=True)

# Inspect workspace
workspace = await service.get_agent_workspace(agent_id)
workspace_path = service.resolver.to_workspace_path(target_path)
contents = await workspace.read(workspace_path)
```

**Documentation** (`demo/one_stop_shop/README.md`):

> Remora uses Cairn to create a stable workspace plus per-agent workspaces:
>
> - `demo/one_stop_shop/workspaces/one-stop-shop/stable.db`
> - `demo/one_stop_shop/workspaces/one-stop-shop/<agent-id>.db`

---

## Part 5: Identified Issues

### 5.1 Copy-on-Write Isolation Not Fully Tested

**Problem**: No test verifies that writes to agent workspace don't affect stable workspace.

**Recommended Test**:
```python
async def test_cow_isolation(tmp_path: Path):
    service = CairnWorkspaceService(config, "test", project_root=tmp_path)
    await service.initialize(sync=True)

    # Write to agent workspace
    workspace = await service.get_agent_workspace("agent-1")
    await workspace.write("test.txt", "agent content")

    # Verify stable is unchanged
    stable_content = await service._stable_workspace.files.read("test.txt")
    # Should raise FileNotFoundError or return original content
```

### 5.2 Multi-Agent Isolation Not Tested

**Problem**: No test verifies that agent-1's writes don't appear in agent-2's reads.

**Recommended Test**:
```python
async def test_agent_isolation(tmp_path: Path):
    service = CairnWorkspaceService(config, "test", project_root=tmp_path)
    await service.initialize(sync=True)

    ws1 = await service.get_agent_workspace("agent-1")
    ws2 = await service.get_agent_workspace("agent-2")

    await ws1.write("test.txt", "agent-1 content")

    # agent-2 should NOT see agent-1's write
    exists = await ws2.exists("test.txt")
    assert not exists  # or raises FileNotFoundError
```

### 5.3 Accept/Reject Not Implemented in Remora

The `AgentWorkspace` class has placeholder methods:

```python
# src/remora/workspace.py:64-70
async def accept(self) -> None:
    """Accept all changes in this workspace."""
    raise WorkspaceError("Accept/reject is not supported by the Cairn workspace API")

async def reject(self) -> None:
    """Reject all changes and reset to base state."""
    raise WorkspaceError("Accept/reject is not supported by the Cairn workspace API")
```

**Issue**: Remora doesn't expose Cairn's accept/reject/merge functionality. This means changes written to agent workspaces are not being merged back to stable.

### 5.4 Stable Workspace Sync During Tests

The tests use `sync=True` or `sync=False`:

```python
# sync=True - syncs project files to stable
await workspace_service.initialize(sync=True)

# sync=False - skips sync (used when re-opening)
await workspace_service.initialize(sync=False)
```

**Observation**: When `sync=True`, the stable workspace is populated from the project root. This is correct behavior, but tests should verify this happened.

### 5.5 Path Resolution Complexity

Remora uses `PathResolver` to normalize paths:

```python
# CairnExternals._normalize()
def _normalize(self, path: str) -> str:
    return self.resolver.to_workspace_path(path)
```

**Potential Issue**: If path normalization is inconsistent, files might be written to different paths than expected.

---

## Part 6: Recommendations

### 6.1 Add Isolation Tests

Create tests that verify:
1. Agent writes don't affect stable
2. Agent writes don't affect other agents
3. Read fall-through from agent to stable works correctly

### 6.2 Implement Accept/Reject in Remora

Wire up the merge functionality:

```python
async def accept(self) -> None:
    """Merge agent changes into stable."""
    if self._stable_workspace is None:
        raise WorkspaceError("No stable workspace")
    await self._stable_workspace.overlay.merge(
        self._workspace,
        strategy=MergeStrategy.OVERWRITE
    )
```

### 6.3 Add Workspace State Assertions

After each test, verify workspace state:

```python
# Verify stable workspace state
stable_files = await list_workspace_files(service._stable_workspace)
assert "expected_file.txt" not in stable_files  # or in, depending on test

# Verify agent workspace state
agent_files = await list_workspace_files(workspace.cairn)
assert "written_file.txt" in agent_files
```

### 6.4 Test Concurrent Agent Isolation

The existing concurrent test verifies success rate but should also verify isolation:

```python
# After concurrent execution
for agent_id in agent_ids:
    ws = await service.get_agent_workspace(agent_id)
    # Verify this agent's files exist
    assert await ws.exists(f"output-{agent_id}.txt")
    # Verify other agents' files don't exist
    for other_id in agent_ids:
        if other_id != agent_id:
            other_file = f"output-{other_id}.txt"
            # Should not exist in this agent's workspace
```

---

## Part 7: Summary

### What's Working

1. **Cairn correctly wraps fsdantic** - The workspace abstraction is properly implemented
2. **Copy-on-write semantics are implemented** - Read fall-through and write isolation are coded correctly in `CairnExternalFunctions`
3. **Remora integrates with Cairn** - `CairnWorkspaceService` and `CairnExternals` properly bridge the two libraries
4. **Integration tests pass** - The tests that exist verify basic functionality works
5. **Demos show correct usage** - The one_stop_shop demo properly exercises the integration

### What's Missing

1. **No isolation verification** - Tests don't verify copy-on-write isolation
2. **Accept/reject not exposed** - Remora can't merge agent changes to stable
3. **No multi-agent isolation tests** - Can't verify agents don't interfere
4. **Limited error path testing** - Happy path works, edge cases untested

### Confidence Level

**Medium-High**: The integration architecture is sound and follows the intended design patterns. The primary concern is that the tests verify functionality (tool calls work, files are written) but not the isolation guarantees that make Cairn valuable. Adding isolation tests would increase confidence significantly.

---

## Appendix: File Reference

### Cairn Files

| File | Purpose |
|------|---------|
| `.context/cairn/src/cairn/runtime/workspace_manager.py` | Workspace lifecycle management |
| `.context/cairn/src/cairn/orchestrator/orchestrator.py` | Main orchestrator with agent lifecycle |
| `.context/cairn/src/cairn/runtime/external_functions.py` | Copy-on-write external functions |
| `.context/cairn/src/cairn/orchestrator/lifecycle.py` | Agent lifecycle persistence |
| `.context/cairn/src/cairn/runtime/workspace_cache.py` | LRU cache for workspaces |

### Remora Files

| File | Purpose |
|------|---------|
| `src/remora/cairn_bridge.py` | CairnWorkspaceService - main integration |
| `src/remora/cairn_externals.py` | Path-normalized Cairn externals |
| `src/remora/workspace.py` | AgentWorkspace, CairnDataProvider |
| `src/remora/executor.py` | GraphExecutor using Cairn workspaces |
| `src/remora/tools/grail.py` | Grail tool execution with externals |

### Test Files

| File | Purpose |
|------|---------|
| `tests/integration/helpers.py` | agentfs_available(), test helpers |
| `tests/integration/test_smoke_real.py` | Basic smoke tests |
| `tests/integration/test_executor_real.py` | Executor tests with tools |
| `tests/integration/test_agent_workflow_real.py` | Concurrent workflow tests |
