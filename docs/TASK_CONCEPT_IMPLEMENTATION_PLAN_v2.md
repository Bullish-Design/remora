# Task System Implementation Plan (V2)

This plan details how to implement the **Task Forest** system in Remora. We are following **Path B (Immediate)**, which means the Task System will manage its own provenance until the Node State Hub is ready.

## 🎯 Goal
Enable Remora agents to **create, list, and complete tasks** that are anchored to specific code locations. Code context (source code) will be retrieved directly from files.

## 🛠️ Phase 1: Core Infrastructure

### Step 1.1: Define Data Models
**File:** `remora/tasks/models.py` (New File)

Create Pydantic models to represent tasks and their provenance.

-   **`TaskState` (Enum):** `OPEN`, `IN_PROGRESS`, `COMPLETED`, `BLOCKED`.
-   **`TaskProvenance` (Model):**
    -   `file_path: str` (Absolute or relative to project root)
    -   `span: tuple[int, int]` (Start/End byte offsets)
    -   `content_hash: str` (SHA256 of the span content for stale detection)
    -   `symbol_name: str | None` (Optional: function/class name for recovery)
-   **`Task` (Model):**
    -   `id: str` (UUID)
    -   `title: str`
    -   `description: str | None`
    -   `status: TaskState`
    -   `parent_id: str | None`
    -   `provenance: TaskProvenance`
    -   `created_at: float`
    -   `updated_at: float`

### Step 1.2: Implement Storage
**File:** `remora/tasks/storage.py` (New File)

Use `fsdantic` to manage the lifecycle of tasks in a generic KV store.

-   **Helper:** `get_tasks_fs() -> AgentFS`: Opens/creates `$PROJECT_ROOT/.agentfs/tasks.db`.
-   **Class:** `TaskStore`:
    -   `__init__(self, fs: AgentFS)`
    -   `add_task(self, task: Task) -> None`
    -   `get_task(self, task_id: str) -> Task | None`
    -   `update_task(self, task: Task) -> None`
    -   `list_tasks(self, file_path: str | None = None, status: TaskState | None = None) -> list[Task]`
        -   *Note on Indexing:* For v1, just iterate all tasks. If performance drops (N > 1000), add a secondary index key `idx:file:{path}`.

### Step 1.3: Orchestrator Integration
**File:** `remora/orchestrator.py`

We need to inject open tasks into the agent's prompt so it knows what to do.

-   **Modify `Coordinator`:** Initialize `TaskStore` on startup.
-   **Modify `process_node`:**
    1.  Call `task_store.list_tasks(file_path=node.file_path, status=TaskState.OPEN)`.
    2.  Pass this list to `RemoraAgentContext`.
-   **Modify `RemoraAgentContext`:** Add `active_tasks: list[Task]`.

**File:** `remora/runner.py`

-   **Modify `_build_system_prompt`:**
    -   Check `self.ctx.active_tasks`.
    -   If present, append a section:
        ```text
        ## Active Tasks for this file
        - [ ] Refactor error handling (ID: t-882)
        ```

## 🛠️ Phase 2: Agent Tools

Create `.pym` tools that the agent can call.

### Step 2.1: `add_task` Tool
**File:** `agents/common/tools/tasks/add.pym`

-   **Inputs:** `title`, `description`, `parent_id` (optional).
-   **Logic:**
    1.  Get current node info (via `get_node_metadata` external).
    2.  Compute `content_hash` of the current node text.
    3.  Construct `Task` object.
    4.  Call internal `_save_task` (you might need to expose a `save_task_external` or implementation in Python and expose it).
    -   *Alternative:* Since `.pym` runs in isolation, creating a `TaskStore` directly might be hard if it locks the DB.
    -   *Better approach:* Expose `manage_tasks` as an **External Function** in `remora/externals.py`.

### Step 2.2: Refined Externals Strategy
**File:** `remora/externals.py`

Instead of raw DB access in `.pym`, expose safe C++ style externals:

-   `create_task(title: str, description: str, ...) -> str` (returns ID)
-   `update_task_status(task_id: str, status: str) -> bool`
-   `list_tasks_external(file_path: str) -> list[dict]`

### Step 2.3: Tool Definitions
**File:** `remora/tool_registry.py` -> `_default_operations` (indirectly) or specific agent YAMLs.

-   Update `agents/lint/lint_subagent.yaml` (and others) to include:
    -   `add_task`
    -   `complete_task`
    -   `list_tasks`

## 🛠️ Phase 3: Testing & Verification

### Step 3.1: Unit Tests
**File:** `tests/tasks/test_storage.py`
-   Test creating, retrieving, and updating tasks.
-   Test filtering by file path.

### Step 3.2: Integration Test
**File:** `tests/integration/test_task_flow.py`
-   Mock the LLM.
-   Run an agent that calls `add_task`.
-   Verify the task exists in `.agentfs/tasks.db`.

## 🔮 Appendix: Migration to Path A (The Future)

Once the **Node State Hub** is ready, we upgrade.

### 1. Data Migration
Write a script `scripts/migrate_tasks_v2.py`:
1.  Iterate all tasks in `tasks.db`.
2.  For each task:
    -   Read `provenance.file_path`.
    -   Query Hub: `hub.resolve_node(file_path, span)`.
    -   Get `hub_node_id`.
    -   Update task: `provenance = HubProvenance(hub_node_id=...)`.

### 2. Code Updates
-   **Update Models:** Switch `TaskProvenance` to use `hub_node_id`.
-   **Update Context Injection:**
    -   Instead of `task_store.list_tasks(file_path)`, call `hub.get_context(node_id)`.
    -   The Hub returns tasks linked to that node ID.
