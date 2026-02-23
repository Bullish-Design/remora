# Recursive Decomposition Task Manager Concept

> **Status**: Concept / Prototype
> **Related**: RECURSIVE_ENVIRONMENT_MODELS.md, LINKED_EMBEDDINGS_SWARM_CONCEPT.md

## 1. Overview

The **Recursive Decomposition Task Manager** brings the theory of Recursive Environment Models (REM) into code. It completely abandons linear task execution in favor of **Extreme Recursion**. The manager starts by treating the user's prompt *itself* as a problem to be decomposed, spawning exploratory environments to gather context, define "done", and build the actual execution tree.

Every node in this tree corresponds to a completely isolated **Cairn Workspace Sandbox**. The state, intent, and architectural constraints of these sandboxes are synchronized through Remora's central **Hub Daemon** using versioned object models (FSdantic), acting as the "Memory Bus" for the swarm.

## 2. Core Components

To achieve "The Remora Way", the system uses strictly typed Pydantic models persisted via the Hub:

### `TaskEnvironment`
Defines the spatial and temporal boundaries for a task.
*   **`workspace_id`**: Links to a Cairn Workspace `workspace.db`. Every environment is isolated.
*   **`parent_workspace_id`**: For temporal or spatial recursion, a sub-task can overlay or inherit context from its parent.
*   **`context_keys`**: List of keys in the Hub DB that this environment is allowed to read.

### `TaskNode`
The orchestrating model for a unit of work.
*   **`task_id`**: Unique identifier (UUID).
*   **`parent_task_id`**: The UUID of the task forming the decomposition tree.
*   **`task_type`**: Enum defining the node's purpose (`DECOMPOSITION`, `RESEARCH`, `EXECUTION`, `VERIFICATION`).
*   **`intent`**: Natural language description of what *must* be done inside this node's environment.
*   **`environment`**: The encapsulated `TaskEnvironment` definition.
*   **`agent_bundle`**: The specific LoRA/Grail `.pym` configuration needed.
*   **`status`**: State machine (`PENDING`, `EXECUTING`, `BLOCKED`, `COMPLETED`, `FAILED`).
*   **`sub_tasks`**: A list of `task_id`s representing children spawned recursively by the agent.

### `TaskResult`
The output of a `TaskNode` execution.
*   **`changed_files`**: List of files mutated in the sandbox (for Execution nodes).
*   **`emitted_artifacts`**: Key-value pairs written back to the Hub (e.g., `"definition_of_done"`, `"golden_examples"`).
*   **`success_boolean`**: Result of verification tasks running in the sandbox.

## 3. The Extreme Recursive Cycle mapped to Remora

1.  **Ingestion:** User requests: *"Update all configuration to a Pydantic Settings baseclass."*
2.  **Root Decomposition:** The `TaskManager` creates a `DECOMPOSITION` Root `TaskNode`. It provisions `Workspace A` and assigns the `"architect"` bundle.
3.  **Iterative Breakdown (Inside Workspace A):** The Architect analyzes the prompt and realizes it lacks context. It spawns three parallel `RESEARCH` sub-tasks using `spawn_sub_task.pym`:
    *   **Research Task 1:** "Find current config usage in library." (Spawns an agent that uses Tree-sitter tools to map config imports).
    *   **Research Task 2:** "Research pydantic-settings." (Spawns an agent that searches `COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE.md` or external docs for best practices).
    *   **Research Task 3:** "Determine validation targets." (Spawns an agent that analyzes `tests/` to see how config is currently tested).
4.  **Context Aggregation:** As the Research tasks complete, they write their findings back to the Hub (e.g., `KV.set("golden_example", "...")`). The Architect in `Workspace A` observes these Hub events.
5.  **Execution Tree Generation:** Armed with context and a clear "Definition of Done" (e.g., "pytest suite passes"), the Architect spawns the actual `EXECUTION` sub-tasks (e.g., "Refactor `config.py`", "Update `cli.py` to use new config").
6.  **Verification Recursion:** Once an `EXECUTION` task finishes, the Architect spawns a `VERIFICATION` sub-task. If verification fails (pytest errors), the Verification node spawns a `DEBUG` node (Temporal Recursion) with the stack trace, which may then spawn further `EXECUTION` nodes to fix the issue.
7.  **Upward Resolution:** Once the Verification node confirms the "Definition of Done" is met, the Root `TaskNode` resolves. The `WorkspaceBridge` recursively merges the execution sandboxes back to the trunk.

## 4. Implementation Details

To achieve this architecture, we will build explicit, strictly typed Pydantic models and a stateful orchestration layer.

### 4.1. Core Orchestration Models (`src/remora/hub/tasks.py`)

We create a suite of models that inherit from `fsdantic.VersionedKVRecord` to enable safe, version-controlled storage in `remora.hub.db`.

```python
from enum import Enum
from pydantic import BaseModel, Field
from fsdantic import VersionedKVRecord

class TaskStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    BLOCKED = "BLOCKED"      # Waiting on sub-tasks (e.g., RESEARCH or VERIFICATION)
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class TaskType(str, Enum):
    DECOMPOSITION = "DECOMPOSITION" # Breaks down a problem
    RESEARCH = "RESEARCH"           # Read-only exploration
    EXECUTION = "EXECUTION"         # Code mutation
    VERIFICATION = "VERIFICATION"   # Test running & assertion

class TaskEnvironment(BaseModel):
    workspace_id: str
    parent_workspace_id: str | None = None
    context_keys: list[str] = Field(default_factory=list)

class TaskResult(BaseModel):
    changed_files: list[str] = Field(default_factory=list)
    emitted_artifacts: dict[str, str] = Field(default_factory=dict)
    verification_passed: bool | None = None

class TaskNode(VersionedKVRecord):
    task_id: str
    parent_task_id: str | None = None
    task_type: TaskType
    intent: str
    environment: TaskEnvironment | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: TaskResult | None = None
    agent_bundle: str
    sub_tasks: list[str] = Field(default_factory=list) # IDs of child nodes
```

### 4.2. Task Manager Layer (`src/remora/task_manager.py`)

The OOP entry point for managing the lifecycle of these tree-based tasks, leveraging the `HubClient` and `CairnWorkspaceBridge`.

```python
from pydantic import BaseModel
# imports omitted for brevity

class TaskManager(BaseModel):
    hub_client: "HubClient"
    workspace_bridge: "CairnWorkspaceBridge"

    def create_root_task(self, intent: str, agent_bundle: str = "architect") -> TaskNode:
        """Entrypoint for a new user request."""
        # 1. Create DECOMPOSITION task node
        # 2. Assign root workspace
        # 3. Write to Hub
        pass

    def spawn_sub_task(self, parent_id: str, intent: str, task_type: TaskType, agent_bundle: str) -> TaskNode:
        """The core recursive loop enabler."""
        # 1. Fetch parent node
        # 2. Create sub-task node. Link parent_id.
        # 3. Create sandboxed workspace. Link parent_workspace_id if needed.
        # 4. Append sub-task to parent.sub_tasks.
        # 5. Set parent.status = BLOCKED (if waiting for results).
        # 6. Save both to Hub.
        pass

    async def handle_task_completion(self, task_id: str, result: TaskResult):
        """Called via event stream when an agent finishes."""
        # 1. Fetch completed task
        # 2. Process based on type:
        #    - RESEARCH: Store emitted context to Hub. Discard workspace.
        #    - EXECUTION: Keep workspace ready for VERIFICATION.
        #    - VERIFICATION: If passed, unblock parent. If failed, spawn DEBUG task automatically.
        # 3. If parent was BLOCKED and ALL sub_tasks are completed/successful, set parent to EXECUTING (wakes it up).
        pass

    async def resolve_task_tree(self, root_task_id: str):
        """Post-Verification cleanup."""
        # Depth-first walk of the execution tree, invoking workspace_bridge.merge()
        # on all successful EXECUTION workspaces to push to project root.
        pass
```
