# Task Concept V2: The Task Forest

## Executive Summary

This document describes a flexible, context-aware task management system for Remora. It replaces the complex DAG approach with a robust **Task Forest** model and leverages **Cairn KV** for persistence.

It outlines two implementation paths to handle the "Hub Context" dependency:
- **Path A (Future):** Deep integration with the Node State Hub.
- **Path B (Immediate):** Lightweight local provenance when the Hub is not yet available.

## 1. Core Philosophy

1.  **Context is King:** A task is not just text; it is anchored to a specific location in the code (file + span).
2.  **Flat by Default, Hierarchical on Demand:** We treat tasks as a flat list for quick scanning, but allow `parent_id` linking to form a "Forest" of task trees for complex features.
3.  **Agent-Executable:** Tasks are readable and writable by Remora agents, bridging the gap between "planning" and "doing".
4.  **Cairn Native:** We use the existing `fsdantic` KV store, avoiding new database dependencies.

## 2. Data Model

The core unit is the `Task` record.

```python
class TaskState(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"

class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str | None = None
    status: TaskState = TaskState.OPEN
    
    # Hierarchy (The "Forest")
    parent_id: str | None = None
    
    # The "Where" (Implementation depends on Path A vs B)
    provenance: TaskProvenance 
    
    created_at: float
    updated_at: float
```

## 3. Implementation Paths

### Path A: Hub Context Available (Future)

In this path, we assume the **Node State Hub** (v2) is running. The Hub is the source of truth for code context.

**Provenance Model:**
```python
class TaskProvenance(BaseModel):
    # We reference the stable ID managed by the Hub
    hub_node_id: str  # e.g., "node:src/login.py:LoginClass.authenticate"
```

**Workflow:**
1.  **Creation:** When a user creates a task on `login.py`, we query the Hub for the `hub_node_id` of the current function and store it.
2.  **Context Retrieval:**
    -   Agent asks: "What is the context for Task-123?"
    -   System: Queries Hub for `NodeState` of `hub_node_id`.
    -   Result: Returns fresh signature, complexity metrics, and related tests.
3.  **Stale Detection:** The Hub automatically flags if the `NodeState` has drifted (e.g., function deleted).

**Pros:**
-   Context is always fresh (auto-updated by Hub watchers).
-   Rich metadata (test coverage, complexity) available gratis.

### Path B: Hub Unavailable (Immediate)

In this path, the Task System manages its own lightweight context. This allows us to ship Tasks *before* the Hub is fully implemented.

**Provenance Model:**
```python
class TaskProvenance(BaseModel):
    file_path: str
    span: tuple[int, int]  # (start_byte, end_byte)
    
    # Snapshot for stale detection
    content_hash: str     # sha256 of the span at creation time
    symbol_name: str | None # e.g. "authenticate" (captured via simplistic parsing)
```

**Workflow:**
1.  **Creation:** We record the file, byte range, and a hash of the content. Code is sourced via standard `read_file`.
2.  **Context Retrieval:**
    -   Agent asks: "What is the context for Task-123?"
    -   System: Reads `file_path`. Extracts current text at `span`.
    -   Result: Returns the raw code.
3.  **Stale Detection:**
    -   We re-hash the current text at `span`.
    -   If `current_hash != content_hash`, we flag the task as "Potentially Stale" or "Drifted".
    -   *Self-Healing:* Re-run a tree-sitter query to find `symbol_name` in `file_path` to find the new span (basic anchor tracking).

**Pros:**
-   Self-contained; no external daemon required.
-   Can be implemented immediately using existing Remora/Cairn primitives.

## 4. Storage Architecture (Cairn KV)

We leverage `fsdantic` and its `TypedKVRepository` pattern.

**Location:** `$PROJECT_ROOT/.agentfs/tasks.db`
This segregates task data from agent execution state (`bin.db`) and user code (`stable.db`).

**Schema Access:**
```python
from fsdantic.kv import KVManager

# Initialize manager backed by tasks.db
kv = KVManager(agent_fs=tasks_fs)

# Create typed repository
task_repo = kv.repository(prefix="task:", model_type=Task)
```

**Indices (Manual management via KV keys):**
-   `idx:file:{file_path} -> list[task_id]`
-   `idx:status:{status} -> list[task_id]`

## 5. Agent Integration

Remora Agents (`FunctionGemma`) need to interact with the Task Forest.

### Injected Context
The `TaskSystem` will inject a summary of active tasks into the `RemoraAgentContext`.

**Prompt Addition:**
```text
ACTIVE TASKS (Current File):
- [ ] Refactor error handling (ID: t-882)
- [ ] Add type hints to `process_request` (ID: t-991)
```

### New Tools
We register these tools in `remora/tool_registry.py`:

1.  `add_task(custom_title: str, description: str, parent_id: str | None)`
    -   Creates a task anchored to the agent's current node.
2.  `list_tasks(file_path: str | None, status: str | None)`
    -   Lists tasks (defaulting to current file).
3.  `complete_task(task_id: str, resolution: str)`
    -   Marks as completed and logs the resolution.

## 6. Migration Strategy (B -> A)

When the Hub (Path A) is ready, we can migrate Path B tasks:
1.  Iterate all tasks.
2.  Use `file_path` + `symbol_name` (from Path B) to query the Hub.
3.  If Hub finds a match, update `provenance` to the new `HubNodeID`.
4.  Delete legacy Path B fields.
