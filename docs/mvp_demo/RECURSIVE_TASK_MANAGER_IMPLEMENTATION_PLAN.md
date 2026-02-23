# Recursive Task Manager Implementation Plan

> **Status**: Implementation Plan / Technical Review
> **Author**: Claude Opus 4.5
> **Date**: 2026-02-22
> **Related**: RECURSIVE_TASK_MANAGER_CONCEPT.md, RECURSIVE_ENVIRONMENT_MODELS.md

---

## 1. Executive Summary

This document provides a detailed implementation plan for the **Recursive Decomposition Task Manager** as specified in `RECURSIVE_TASK_MANAGER_CONCEPT.md`. The plan maps the concept's models and workflows to Remora's existing infrastructure, identifies gaps, and provides concrete implementation steps.

**Assessment**: The concept is architecturally sound and aligns well with Remora's existing patterns. Approximately **60% of required infrastructure already exists**. The remaining 40% consists of:
- Task tree orchestration layer
- Sub-task spawning tools
- Hub-based task state persistence
- Verification/debugging loop automation

**Recommended Use**: Personal productivity tool and internal dogfooding, not initial MVP demo (too abstract for visual impact).

---

## 2. Concept Review & Validation

### 2.1 Core Models Assessment

| Model | Concept Design | Existing Infrastructure | Gap Assessment |
|-------|---------------|------------------------|----------------|
| **TaskEnvironment** | workspace_id, parent_workspace_id, context_keys | `CairnConfig` + `WorkspaceCache` | **Small gap**: Add parent linking |
| **TaskNode** | task_id, parent_task_id, task_type, intent, status, sub_tasks | No direct equivalent | **New model needed** |
| **TaskResult** | changed_files, emitted_artifacts, verification_passed | `AgentResult` | **Extend existing** |

### 2.2 Architectural Alignment

**Strengths of the Concept:**

1. **FSdantic Integration**: Using `VersionedKVRecord` for task persistence is correct. The Hub's KV store is designed for exactly this.

2. **Workspace Isolation**: Each `TaskEnvironment` mapping to a Cairn workspace leverages existing isolation guarantees.

3. **Event-Driven Coordination**: The `handle_task_completion` async handler fits naturally with `RemoraEventBridge`.

4. **Agent Bundle Flexibility**: Different `task_type` values (DECOMPOSITION, RESEARCH, EXECUTION, VERIFICATION) can map to different bundles.

**Areas Requiring Refinement:**

1. **Blocking vs Async**: The concept implies blocking `spawn_sub_task` behavior. For performance, sub-tasks should spawn asynchronously with completion events.

2. **Hub Dependency**: The concept requires the Hub daemon to be fully operational. Currently, Hub is at 60% implementation.

3. **Merge Semantics**: The `resolve_task_tree` workspace merging needs careful conflict resolution, especially for RESEARCH tasks that may touch the same files.

---

## 3. Implementation Mapping to Existing Components

### 3.1 TaskEnvironment → Cairn Integration

**Existing Component**: `src/remora/workspace.py` (WorkspaceCache, WorkspaceState)

**Current Capabilities:**
- Workspace creation via `cairn.Workspace()`
- File isolation and resource limits
- Accept/reject/retry state machine
- Workspace pooling for performance

**Required Extensions:**

```python
# Extend WorkspaceState or create new TaskEnvironmentState
class TaskEnvironmentState(BaseModel):
    workspace_id: str
    parent_workspace_id: str | None = None
    parent_task_id: str | None = None
    context_keys: list[str] = Field(default_factory=list)

    # Bridge to existing workspace
    workspace: cairn.Workspace | None = None
```

**Implementation Steps:**
1. Add `parent_workspace_id` field to workspace metadata
2. Create workspace bridge that can mount parent workspace as read-only overlay
3. Add context key filtering to limit what Hub keys the agent can access

### 3.2 TaskNode → New Model + Hub Persistence

**New Component**: `src/remora/hub/tasks.py`

The TaskNode model from the concept is well-designed. Implementation should:

```python
# src/remora/hub/tasks.py
from enum import Enum
from pydantic import BaseModel, Field
from fsdantic import VersionedKVRecord
from datetime import datetime
import uuid

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class TaskType(str, Enum):
    DECOMPOSITION = "DECOMPOSITION"
    RESEARCH = "RESEARCH"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"
    DEBUG = "DEBUG"  # Added for temporal recursion

class TaskEnvironment(BaseModel):
    """Defines the spatial and temporal boundaries for a task."""
    workspace_id: str
    parent_workspace_id: str | None = None
    context_keys: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class TaskResult(BaseModel):
    """The output of a TaskNode execution."""
    changed_files: list[str] = Field(default_factory=list)
    emitted_artifacts: dict[str, str] = Field(default_factory=dict)
    verification_passed: bool | None = None
    error_message: str | None = None
    execution_time_seconds: float | None = None

class TaskNode(VersionedKVRecord):
    """The orchestrating model for a unit of work."""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_task_id: str | None = None
    task_type: TaskType
    intent: str
    environment: TaskEnvironment | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: TaskResult | None = None
    agent_bundle: str
    sub_tasks: list[str] = Field(default_factory=list)

    # Metadata for observability
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def hub_key(self) -> str:
        """FSdantic key for Hub persistence."""
        return f"task:{self.task_id}"
```

### 3.3 TaskManager → Orchestration Layer

**New Component**: `src/remora/task_manager.py`

This is the core new functionality. It sits above the existing `Coordinator` and manages the task tree.

```python
# src/remora/task_manager.py
from pydantic import BaseModel
from typing import TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from remora.hub.client import HubClient
    from remora.workspace import WorkspaceBridge

class TaskManager(BaseModel):
    """Manages the lifecycle of recursive task trees."""

    hub_client: "HubClient"
    workspace_bridge: "WorkspaceBridge"

    # Active task tracking
    _active_tasks: dict[str, TaskNode] = {}
    _completion_events: dict[str, asyncio.Event] = {}

    model_config = {"arbitrary_types_allowed": True}

    async def create_root_task(
        self,
        intent: str,
        agent_bundle: str = "architect"
    ) -> TaskNode:
        """Entry point for a new user request."""
        # 1. Create DECOMPOSITION task node
        task = TaskNode(
            task_type=TaskType.DECOMPOSITION,
            intent=intent,
            agent_bundle=agent_bundle,
        )

        # 2. Create root workspace
        workspace_id = await self.workspace_bridge.create_workspace(
            parent_id=None,
            context_keys=["*"],  # Root has full access
        )
        task.environment = TaskEnvironment(workspace_id=workspace_id)

        # 3. Persist to Hub
        await self.hub_client.set(task.hub_key, task.model_dump())

        # 4. Track locally
        self._active_tasks[task.task_id] = task
        self._completion_events[task.task_id] = asyncio.Event()

        return task

    async def spawn_sub_task(
        self,
        parent_id: str,
        intent: str,
        task_type: TaskType,
        agent_bundle: str,
        context_keys: list[str] | None = None,
    ) -> TaskNode:
        """The core recursive loop enabler."""
        parent = self._active_tasks.get(parent_id)
        if not parent:
            parent = await self._load_task(parent_id)

        # 1. Create sub-task node
        sub_task = TaskNode(
            parent_task_id=parent_id,
            task_type=task_type,
            intent=intent,
            agent_bundle=agent_bundle,
        )

        # 2. Create sandboxed workspace with parent overlay
        workspace_id = await self.workspace_bridge.create_workspace(
            parent_id=parent.environment.workspace_id if parent.environment else None,
            context_keys=context_keys or [],
        )
        sub_task.environment = TaskEnvironment(
            workspace_id=workspace_id,
            parent_workspace_id=parent.environment.workspace_id if parent.environment else None,
            context_keys=context_keys or [],
        )

        # 3. Update parent
        parent.sub_tasks.append(sub_task.task_id)
        parent.status = TaskStatus.BLOCKED

        # 4. Persist both
        await asyncio.gather(
            self.hub_client.set(sub_task.hub_key, sub_task.model_dump()),
            self.hub_client.set(parent.hub_key, parent.model_dump()),
        )

        # 5. Track
        self._active_tasks[sub_task.task_id] = sub_task
        self._completion_events[sub_task.task_id] = asyncio.Event()

        return sub_task

    async def handle_task_completion(
        self,
        task_id: str,
        result: TaskResult
    ) -> None:
        """Called via event stream when an agent finishes."""
        task = self._active_tasks.get(task_id)
        if not task:
            task = await self._load_task(task_id)

        task.result = result
        task.status = TaskStatus.COMPLETED if result.verification_passed != False else TaskStatus.FAILED
        task.completed_at = datetime.utcnow()

        # Process based on type
        if task.task_type == TaskType.RESEARCH:
            # Store emitted artifacts to Hub, discard workspace
            for key, value in result.emitted_artifacts.items():
                await self.hub_client.set(f"artifact:{task_id}:{key}", value)
            await self.workspace_bridge.discard(task.environment.workspace_id)

        elif task.task_type == TaskType.VERIFICATION:
            if result.verification_passed:
                # Unblock parent
                await self._check_parent_unblock(task.parent_task_id)
            else:
                # Spawn DEBUG task automatically (Temporal Recursion)
                await self.spawn_sub_task(
                    parent_id=task.parent_task_id,
                    intent=f"Debug verification failure: {result.error_message}",
                    task_type=TaskType.DEBUG,
                    agent_bundle="debugger",
                    context_keys=[f"artifact:{task_id}:*"],
                )

        # Persist and signal
        await self.hub_client.set(task.hub_key, task.model_dump())
        self._completion_events[task_id].set()

    async def _check_parent_unblock(self, parent_id: str | None) -> None:
        """Check if all sub-tasks complete and unblock parent."""
        if not parent_id:
            return

        parent = await self._load_task(parent_id)
        sub_tasks = [await self._load_task(tid) for tid in parent.sub_tasks]

        all_complete = all(t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) for t in sub_tasks)
        if all_complete and parent.status == TaskStatus.BLOCKED:
            parent.status = TaskStatus.EXECUTING
            await self.hub_client.set(parent.hub_key, parent.model_dump())

    async def resolve_task_tree(self, root_task_id: str) -> None:
        """Post-verification cleanup: merge workspaces depth-first."""
        root = await self._load_task(root_task_id)
        await self._merge_recursive(root)

    async def _merge_recursive(self, task: TaskNode) -> None:
        """Depth-first workspace merge."""
        # First, merge all children
        for sub_task_id in task.sub_tasks:
            sub_task = await self._load_task(sub_task_id)
            await self._merge_recursive(sub_task)

        # Then merge this task's workspace if EXECUTION type succeeded
        if task.task_type == TaskType.EXECUTION and task.result and task.result.verification_passed:
            await self.workspace_bridge.merge(
                source_workspace_id=task.environment.workspace_id,
                target_workspace_id=task.environment.parent_workspace_id,
            )

    async def _load_task(self, task_id: str) -> TaskNode:
        """Load task from Hub."""
        data = await self.hub_client.get(f"task:{task_id}")
        return TaskNode.model_validate(data)
```

### 3.4 Grail Tools for Agent-Driven Recursion

The agents themselves need tools to spawn sub-tasks. These are `.pym` scripts in the agent bundles.

**New Tools Directory**: `agents/architect/tools/`

```python
# agents/architect/tools/spawn_sub_task.pym
"""Spawn a sub-task for recursive decomposition."""
from grail import Input, Output
from remora.task_manager import TaskManager, TaskType

intent: str = Input("The intent/goal for the sub-task")
task_type: str = Input("Type: RESEARCH, EXECUTION, or VERIFICATION")
agent_bundle: str = Input("The agent bundle to use")
context_keys: list[str] = Input("Hub keys this sub-task can access", default=[])

# Access task manager from Grail context
task_manager: TaskManager = ctx.get("task_manager")
parent_task_id: str = ctx.get("current_task_id")

# Spawn the sub-task
sub_task = await task_manager.spawn_sub_task(
    parent_id=parent_task_id,
    intent=intent,
    task_type=TaskType[task_type.upper()],
    agent_bundle=agent_bundle,
    context_keys=context_keys,
)

Output({
    "sub_task_id": sub_task.task_id,
    "workspace_id": sub_task.environment.workspace_id,
    "status": "PENDING",
})
```

```python
# agents/architect/tools/hub_write.pym
"""Write a key-value pair to the Hub memory bus."""
from grail import Input, Output

key: str = Input("The key to write")
value: str = Input("The value to store")

hub_client = ctx.get("hub_client")
task_id = ctx.get("current_task_id")

# Namespace the key under the current task
namespaced_key = f"task_context:{task_id}:{key}"
await hub_client.set(namespaced_key, value)

Output({"key": namespaced_key, "success": True})
```

```python
# agents/architect/tools/hub_read.pym
"""Read a key from the Hub memory bus."""
from grail import Input, Output

key: str = Input("The key to read")

hub_client = ctx.get("hub_client")
task_id = ctx.get("current_task_id")
task = await hub_client.get(f"task:{task_id}")

# Check if key is in allowed context_keys
allowed_keys = task.get("environment", {}).get("context_keys", [])
if "*" not in allowed_keys and not any(key.startswith(k.rstrip("*")) for k in allowed_keys):
    Output({"error": f"Key '{key}' not in allowed context_keys", "value": None})
else:
    value = await hub_client.get(key)
    Output({"key": key, "value": value})
```

---

## 4. Implementation Phases

### Phase 1: Foundation Models (1 week)

**Deliverables:**
- [ ] `TaskNode`, `TaskEnvironment`, `TaskResult` models in `src/remora/hub/tasks.py`
- [ ] FSdantic integration for Hub persistence
- [ ] Unit tests for model serialization/deserialization

**Key Files:**
```
src/remora/hub/tasks.py          # New
tests/unit/hub/test_tasks.py     # New
```

### Phase 2: Workspace Bridge Extension (1 week)

**Deliverables:**
- [ ] Parent workspace overlay support in Cairn
- [ ] Workspace metadata tracking (parent_id, context_keys)
- [ ] Merge semantics for depth-first resolution

**Key Files:**
```
src/remora/workspace.py          # Extend
tests/unit/test_workspace.py     # Extend
```

### Phase 3: TaskManager Core (2 weeks)

**Deliverables:**
- [ ] `TaskManager` class with all methods from concept
- [ ] Event stream integration for completion handling
- [ ] Async sub-task spawning with event coordination

**Key Files:**
```
src/remora/task_manager.py       # New
tests/integration/test_task_manager.py  # New
```

### Phase 4: Grail Tools (1 week)

**Deliverables:**
- [ ] `spawn_sub_task.pym` tool
- [ ] `hub_write.pym` and `hub_read.pym` tools
- [ ] Context injection for `task_manager` and `hub_client`

**Key Files:**
```
agents/architect/tools/spawn_sub_task.pym  # New
agents/architect/tools/hub_write.pym       # New
agents/architect/tools/hub_read.pym        # New
```

### Phase 5: Architect Bundle (1 week)

**Deliverables:**
- [ ] Architect agent bundle with decomposition system prompt
- [ ] Few-shot examples for task decomposition
- [ ] Integration with existing operations (lint, test, docstring) as sub-tasks

**Key Files:**
```
agents/architect/bundle.yaml     # New
agents/architect/context/        # New
```

### Phase 6: CLI Integration (1 week)

**Deliverables:**
- [ ] `remora task <prompt>` command for recursive execution
- [ ] Task tree visualization in CLI
- [ ] Task status monitoring

**Key Files:**
```
src/remora/cli.py                # Extend
```

---

## 5. Integration with Existing Infrastructure

### 5.1 Coordinator Bridge

The existing `Coordinator` handles agent execution. The `TaskManager` should delegate to it:

```python
# In task_manager.py
async def _execute_task(self, task: TaskNode) -> None:
    """Bridge to existing Coordinator for agent execution."""
    from remora.orchestrator import Coordinator

    coordinator = Coordinator(
        config=self._config,
        workspace_cache=self.workspace_bridge.cache,
    )

    # Inject task context into the agent
    task.status = TaskStatus.EXECUTING
    task.started_at = datetime.utcnow()
    await self.hub_client.set(task.hub_key, task.model_dump())

    # Run the agent
    result = await coordinator.run_single_agent(
        bundle_name=task.agent_bundle,
        intent=task.intent,
        workspace_id=task.environment.workspace_id,
        context={
            "task_manager": self,
            "hub_client": self.hub_client,
            "current_task_id": task.task_id,
        },
    )

    # Convert to TaskResult
    task_result = TaskResult(
        changed_files=result.changed_files,
        verification_passed=result.success,
        error_message=result.error if not result.success else None,
    )

    await self.handle_task_completion(task.task_id, task_result)
```

### 5.2 Event Stream Integration

Subscribe to completion events and route to `handle_task_completion`:

```python
# In event_bridge.py extension
class TaskManagerEventHandler:
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager

    async def handle_event(self, event: dict) -> None:
        if event.get("event") == "agent_complete":
            task_id = event.get("context", {}).get("task_id")
            if task_id:
                result = TaskResult(
                    changed_files=event.get("changed_files", []),
                    verification_passed=event.get("success", False),
                )
                await self.task_manager.handle_task_completion(task_id, result)
```

### 5.3 Hub Daemon Dependency

The TaskManager requires an operational Hub daemon for:
- Task state persistence
- Context key storage (artifacts, golden examples)
- Cross-task communication

**Current Hub Status**: 60% implemented

**Required Before TaskManager:**
1. Complete `HubDaemon.start()` implementation
2. Implement `HubClient.watch()` for event subscription
3. Add FSdantic record versioning for conflict detection

---

## 6. Testing Strategy

### 6.1 Unit Tests

```python
# tests/unit/hub/test_tasks.py
def test_task_node_serialization():
    task = TaskNode(
        task_type=TaskType.DECOMPOSITION,
        intent="Refactor auth module",
        agent_bundle="architect",
    )
    data = task.model_dump()
    restored = TaskNode.model_validate(data)
    assert restored.task_id == task.task_id
    assert restored.status == TaskStatus.PENDING

def test_task_hub_key():
    task = TaskNode(task_type=TaskType.RESEARCH, intent="Find config", agent_bundle="researcher")
    assert task.hub_key == f"task:{task.task_id}"
```

### 6.2 Integration Tests

```python
# tests/integration/test_task_manager.py
@pytest.mark.asyncio
async def test_create_root_task(task_manager, mock_hub):
    task = await task_manager.create_root_task(
        intent="Add rate limiting",
        agent_bundle="architect",
    )
    assert task.task_id in task_manager._active_tasks
    assert task.status == TaskStatus.PENDING
    assert task.environment is not None

@pytest.mark.asyncio
async def test_spawn_sub_task(task_manager, mock_hub):
    root = await task_manager.create_root_task("Test", "architect")
    sub = await task_manager.spawn_sub_task(
        parent_id=root.task_id,
        intent="Research existing tests",
        task_type=TaskType.RESEARCH,
        agent_bundle="researcher",
    )
    assert sub.parent_task_id == root.task_id
    assert root.task_id in sub.environment.parent_workspace_id

    # Parent should be BLOCKED
    updated_root = await task_manager._load_task(root.task_id)
    assert updated_root.status == TaskStatus.BLOCKED
```

### 6.3 Acceptance Tests

```python
# tests/acceptance/test_recursive_task_flow.py
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_full_recursive_decomposition(
    task_manager,
    mock_vllm_server,
):
    """Test complete flow: decompose → research → execute → verify."""
    root = await task_manager.create_root_task(
        intent="Add caching to get_users endpoint",
        agent_bundle="architect",
    )

    # Simulate architect spawning sub-tasks
    research = await task_manager.spawn_sub_task(
        parent_id=root.task_id,
        intent="Find existing caching patterns",
        task_type=TaskType.RESEARCH,
        agent_bundle="researcher",
    )

    # Simulate research completion
    await task_manager.handle_task_completion(
        research.task_id,
        TaskResult(
            emitted_artifacts={"caching_pattern": "Redis with 5min TTL"},
            verification_passed=True,
        ),
    )

    # Check artifact was stored
    artifact = await task_manager.hub_client.get(
        f"artifact:{research.task_id}:caching_pattern"
    )
    assert artifact == "Redis with 5min TTL"
```

---

## 7. Risk Assessment & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Hub daemon instability | Medium | High | Fallback to in-process Hub mode |
| Infinite recursion | Low | Critical | Add max_depth limit (default 5) |
| Workspace merge conflicts | Medium | Medium | Conflict detection + manual resolution flag |
| Sub-task timeout | Medium | Medium | Per-task timeout with FAILED status |
| Agent misuse of spawn_sub_task | High | Medium | Rate limit sub-task creation, few-shot examples |

---

## 8. Future Extensions

### 8.1 Visual Task Tree (Post-MVP)

A TUI dashboard showing the task tree in real-time:

```
 DECOMPOSITION: Add rate limiting [BLOCKED]
 ├── RESEARCH: Find existing patterns [COMPLETED]
 ├── RESEARCH: Check test coverage [EXECUTING]
 ├── EXECUTION: Modify routes.py [PENDING]
 │   └── VERIFICATION: Run pytest [PENDING]
 └── EXECUTION: Update middleware [PENDING]
```

### 8.2 Task Resumption (Post-MVP)

Save task tree state and resume after restart:

```bash
# Start a task
remora task "Refactor auth" --persist

# Later, resume
remora task --resume task_abc123
```

### 8.3 Multi-User Task Coordination (Post-MVP)

Allow multiple Remora instances to coordinate on the same task tree via Hub synchronization.

---

## 9. Conclusion

The Recursive Task Manager concept is well-designed and maps cleanly onto Remora's existing architecture. The implementation requires:

1. **New code**: ~1,500 lines (models, task manager, tools)
2. **Extended code**: ~300 lines (workspace, coordinator, CLI)
3. **Dependencies**: Complete Hub daemon implementation

**Total estimated effort**: 6-8 weeks for full implementation

**Recommendation**: Begin with Phase 1 (Foundation Models) as it has no dependencies and provides immediate value for task tracking. Defer full recursive execution to post-MVP when Hub daemon is complete.

---

*End of Implementation Plan*
