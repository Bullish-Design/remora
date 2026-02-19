# Node State Hub Implementation Plan (v2)

**Goal**: Build a background "Smart Cache" that indexes code metadata and feeds it into the Agent's Short Track Memory.

**Core Philosophy**:
1.  **Detective, not Creative**: The Hub finds facts ("This function has 3 args"). It doesn't write poetry.
2.  **Pull, don't Push**: The Agent pulls context when it needs it.
3.  **Start Simple**: No LLMs in the Hub loop for V1.

---

## High-Level Architecture

1.  **`HubDaemon`**: The background process.
2.  **`FileWatcher`**: Detects file changes.
3.  **`RulesEngine`**: Decides which tools to run (e.g., "File changed? Run `extract_signature`").
4.  **`GrailTools`**: The actual workers (Python scripts).
5.  **`NodeStateStore`**: The database (KV Store).
6.  **`ContextMiddleware`**: The bridge that connects the Hub to the Agent.

---

## Phase 1: The Core (Watcher & Store)

**Goal**: Can we detect a change and save a "dirty" flag?

### 1. Define `NodeState` Schema
**File**: `remora/hub/schema.py`
```python
class NodeState(BaseModel):
    node_id: str
    file_path: str
    content_hash: str
    
    # Metadata (populated by tools)
    signature: str | None = None
    related_tests: list[str] = Field(default_factory=list)
    complexity_score: int | None = None
    
    last_updated: float
```

### 2. Implement `NodeStateStore`
**File**: `remora/hub/store.py`
-   Use `fsdantic` or simple JSON/SQLite.
-   Methods: `get(node_id)`, `save(state)`.

### 3. Implement `HubDaemon` & `FileWatcher`
**File**: `remora/hub/daemon.py`
-   Use `watchdog` to listen for file events.
-   On event:
    1.  Compute `new_hash`.
    2.  If `new_hash != stored_hash`, mark node as **dirty**.
    3.  Queue for processing.

---

## Phase 2: The Workers (Deterministic Tools)

**Goal**: Can we extract facts from a file without an LLM?

### 4. Port Existing Grail Scripts
Move/Create these scripts in `remora/hub/tools/`:
-   `extract_signature.pym`: Uses `tree-sitter` to get `def foo(a,b): ...`.
-   `find_tests.pym`: Scans `tests/` for imports/usage of the node.
-   `compute_complexity.pym`: Calculates cyclomatic complexity.

### 5. Implement `RulesEngine`
**File**: `remora/hub/rules.py`
-   **Hardcoded Logic**:
    ```python
    def decide_updates(node, event_type):
        updates = ["extract_signature"]  # Always do this
        if event_type == "new_function":
            updates.append("find_tests")
        return updates
    ```

### 6. Connect Daemon to Tools
-   When `Daemon` processes a dirty node:
    1.  Call `RulesEngine` -> Get list of tools.
    2.  Run `GrailExecutor` for each tool.
    3.  Update `NodeState` with results.
    4.  Save to `NodeStateStore`.

---

## Phase 3: The Bridge (Integration with Memory V2)

**Goal**: The Agent "sees" the Hub data.

### 7. Implement `HubClient`
**File**: `remora/hub/client.py`
-   `get_context(node_ids)`: Retrieves `NodeState` for the requested nodes.
-   Filters out stale data (if we want strictly fresh data).
-   Returns a simplified string/dict for the LLM.

### 8. Implement `HubMiddleware`
**File**: `remora/memory/middleware/hub.py`
-   Hooks into `ContextManager` (from Memory V2).
-   **Logic**:
    ```python
    def hub_middleware(packet):
        # 1. Identify "Active Nodes" from packet.recent_history
        nodes = extract_node_ids(packet.recent_history)
        
        # 2. Query Hub
        context = hub_client.get_context(nodes)
        
        # 3. Inject
        packet.knowledge.update(context)
        packet.hub_context_freshness.update(...)
    ```

---

## Phase 4: CLI & Operations

**Goal**: We can run it.

### 9. CLI Command
**File**: `remora/cli.py`
-   `remora hub start`: Starts the daemon.
-   `remora hub scan`: Runs a one-off full scan of the repo.
-   `remora hub status`: Shows queue size and basic stats.

---

## Checklist for Junior Devs

### Step-by-Step Implementation

- [ ] **Step 1**: Create `remora/hub/schema.py` with `NodeState`.
- [ ] **Step 2**: Create `remora/hub/store.py` (KV Store).
- [ ] **Step 3**: Create `remora/hub/daemon.py` with a basic `watchdog` loop to print file changes.
- [ ] **Step 4**: Implement `extract_signature.pym` using `tree-sitter`.
- [ ] **Step 5**: Wire up Daemon to run `extract_signature.pym` on change.
- [ ] **Step 6**: Verify `NodeState` is updated with signatures in the KV store.
- [ ] **Step 7**: Implement `HubClient` to read from the KV store.
- [ ] **Step 8**: Add `HubMiddleware` to `remora/runner.py` (connecting to Memory V2).
- [ ] **Step 9**: Verify that `DecisionPacket` contains the signature when the Agent runs.

## Key Changes from V1
-   **No "Triage Agent"**: We strictly use code rules in Phase 2.
-   **Explicit Middleware**: We formally hook into the Memory V2 "Pull" phase.
-   **Simplicity**: We focus on just "Signatures" and "Tests" first. Complexity metrics can come later.
