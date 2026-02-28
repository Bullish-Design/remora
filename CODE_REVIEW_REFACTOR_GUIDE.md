# Remora Code Refactoring Guide

This guide provides step-by-step instructions for implementing the changes identified in the code review. Changes are organized by priority and grouped to minimize risk of breaking functionality.

---

## Phase 1: Remove Legacy/Dead Code

**Goal**: Clean up code that no longer serves a purpose in the reactive swarm architecture.

### Step 1.1: Remove Legacy Graph Events

**File**: `src/remora/core/events.py`

**Changes**:
1. Remove `GraphStartEvent` dataclass (lines 34-41)
2. Remove `GraphCompleteEvent` dataclass (lines 43-50)
3. Remove `GraphErrorEvent` dataclass (lines 52-60)
4. Remove `AgentSkippedEvent` dataclass (lines 98-105)
5. Remove these from `RemoraEvent` union type (lines 181-190)
6. Remove these from `__all__` list (lines 212-216)

**After**:
```python
# events.py - Only keep reactive swarm events
RemoraEvent = (
    # Agent events
    AgentStartEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    |
    # Human-in-the-loop events
    HumanInputRequestEvent
    | HumanInputResponseEvent
    |
    # Reactive swarm events
    AgentMessageEvent
    | FileSavedEvent
    | ContentChangedEvent
    | ManualTriggerEvent
    |
    # Re-exported structured-agents events
    ...
)
```

**Test**: Run `pytest tests/unit/test_event_bus.py tests/unit/test_subscriptions.py` to verify no breakage.

---

### Step 1.2: Remove EventBridge Dead Code

**File**: `src/remora/core/event_bus.py`

**Changes**:
1. Remove `EventBridge` class (lines 127-161)
2. Remove from `__all__` list

**After**:
```python
__all__ = [
    "EventBus",
    "EventHandler",
]
```

**Test**: Run `pytest tests/unit/test_event_bus.py`

---

### Step 1.3: Remove Unused Helper Function

**File**: `src/remora/nvim/server.py`

**Changes**:
1. Remove `_asdict_nested` function (lines 263-267) - it's defined but never called

---

### Step 1.4: Fix Duplicate API Export

**File**: `src/remora/__init__.py`

**Changes**:
1. Remove duplicate `"CairnExternals"` from `__all__` (line 101)

---

## Phase 2: Configuration Simplification

**Goal**: Consolidate all configuration into a single flat `Config` dataclass.

### Step 2.1: Remove Redundant Config Classes

**File**: `src/remora/core/config.py`

**Changes**:
1. Remove `WorkspaceConfig` class (lines 69-76)
2. Remove `BundleConfig` class (lines 78-84)
3. Remove `ModelConfig` class (lines 86-93)
4. Remove `ExecutionConfig` class (lines 95-101)
5. Remove `RemoraConfig` class (lines 103-110)
6. Remove these from `__all__`

**After**: Only `Config`, `load_config`, `serialize_config`, `ConfigError` remain.

```python
__all__ = [
    "Config",
    "ConfigError",
    "load_config",
    "serialize_config",
]
```

---

### Step 2.2: Update CairnWorkspaceService

**File**: `src/remora/core/cairn_bridge.py`

**Changes**:
1. Remove `WorkspaceConfig` import (line 18)
2. Update `__init__` to only accept `Config`:

```python
def __init__(
    self,
    config: Config,
    *,
    graph_id: str | None = None,
    swarm_root: PathLike | None = None,
    project_root: PathLike | None = None,
) -> None:
    self._config = config

    base_path = normalize_path(swarm_root or config.swarm_root)
    # ... rest unchanged, but remove WorkspaceConfig handling
```

---

## Phase 3: API Consistency

**Goal**: Make all database-backed components use async API consistently.

### Step 3.1: Make SwarmState Async

**File**: `src/remora/core/swarm_state.py`

**Changes**:
1. Change `initialize()` to `async def initialize()`:

```python
async def initialize(self) -> None:
    """Initialize the database and create tables."""
    if self._conn is not None:
        return

    self._conn = await asyncio.to_thread(
        sqlite3.connect, str(self._db_path), check_same_thread=False
    )
    self._conn.row_factory = sqlite3.Row

    await asyncio.to_thread(self._conn.execute, """
        CREATE TABLE IF NOT EXISTS agents (...)
    """)
    await asyncio.to_thread(self._conn.commit)
```

2. Update all methods (`upsert`, `mark_orphaned`, `list_agents`, `get_agent`, `close`) to be async

3. Return `AgentMetadata` instead of dict from `list_agents` and `get_agent`:

```python
async def list_agents(self, status: str | None = None) -> list[AgentMetadata]:
    """List all agents, optionally filtered by status."""
    # ... query logic ...
    return [
        AgentMetadata(
            agent_id=row["agent_id"],
            node_type=row["node_type"],
            # ... etc
        )
        for row in rows
    ]
```

---

### Step 3.2: Update Callers of SwarmState

**Files to update**:
- `src/remora/cli/main.py`: Add `await` to `swarm_state.initialize()` calls
- `src/remora/core/agent_runner.py`: If it calls swarm_state methods

---

### Step 3.3: Fix Async Close in AgentRunner

**File**: `src/remora/core/agent_runner.py`

**Change** (line 269):
```python
# Before:
self._subscriptions.close()

# After:
await self._subscriptions.close()
```

---

## Phase 4: Fix Event Types

**Goal**: Make event types consistent with subscription pattern matching.

### Step 4.1: Fix ManualTriggerEvent

**File**: `src/remora/core/events.py`

**Change** `ManualTriggerEvent`:
```python
@dataclass(frozen=True, slots=True)
class ManualTriggerEvent:
    """Manual trigger to start an agent."""

    to_agent: str  # Changed from agent_id to match subscription patterns
    reason: str
    timestamp: float = field(default_factory=time.time)
```

---

### Step 4.2: Update ManualTriggerEvent Usages

**Files to update**:
- `src/remora/cli/main.py`: Change `agent_id=` to `to_agent=`
- `tests/integration/test_agent_runner.py`: Change `agent_id=` to `to_agent=`

---

## Phase 5: Add Missing Components

**Goal**: Add error types and tools specified in concept docs.

### Step 5.1: Add SwarmError

**File**: `src/remora/core/errors.py`

**Add**:
```python
class SwarmError(RemoraError):
    """Error in swarm operations."""

    pass
```

**Update** `__all__`:
```python
__all__ = [
    "RemoraError",
    "ConfigError",
    "DiscoveryError",
    "GraphError",  # Keep for backwards compat, consider deprecating
    "ExecutionError",
    "WorkspaceError",
    "SwarmError",
]
```

---

### Step 5.2: Complete Swarm Tools

**File**: `src/remora/core/tools/swarm.py`

**Add** `unsubscribe` tool:
```python
async def unsubscribe(subscription_id: int) -> str:
    """Remove a subscription by ID."""
    # Implementation depends on how subscriptions stores IDs
    return f"Subscription {subscription_id} removed."
```

**Add** `broadcast` tool:
```python
async def broadcast(to_pattern: str, content: str) -> str:
    """Broadcast message to multiple agents matching pattern.

    Patterns:
    - "children" - All child agents
    - "siblings" - All sibling agents
    - "file:path" - All agents in file
    """
    # Implementation
    return f"Broadcast sent to {to_pattern}."
```

**Add** `query_agents` tool:
```python
async def query_agents(filter_type: str | None = None) -> list[dict]:
    """Query available agents in the swarm.

    Args:
        filter_type: Optional node type filter (function, class, file)

    Returns:
        List of agent metadata
    """
    # Implementation using swarm_state
    return []
```

---

### Step 5.3: Export New Error Type

**File**: `src/remora/__init__.py`

**Add** to imports and `__all__`:
```python
from remora.core.errors import (
    ...
    SwarmError,
)

__all__ = [
    ...
    "SwarmError",
]
```

---

## Phase 6: Code Quality Improvements

### Step 6.1: Simplify CLI Swarm ID Extraction

**File**: `src/remora/cli/main.py`

**Change** (line 70):
```python
# Before:
swarm_id = getattr(config, "swarm_id", "swarm") if hasattr(config, "__dataclass_fields__") else "swarm"

# After:
swarm_id = config.swarm_id
```

---

### Step 6.2: Add Missing Type Annotations

**File**: `src/remora/core/agent_runner.py`

**Add** return type to `_run_agent`:
```python
async def _run_agent(self, context: ExecutionContext) -> str | None:
    """Run the actual agent logic using SwarmExecutor."""
```

---

## Phase 7: Optional Simplifications

These changes are more invasive but improve the architecture.

### Step 7.1: Remove Human Input Events (Optional)

If HITL is not being used in the reactive model, consider removing:
- `HumanInputRequestEvent`
- `HumanInputResponseEvent`

### Step 7.2: Simplify Workspace Layering (Optional)

Consider removing the stable workspace layer if not needed:

**File**: `src/remora/core/workspace.py`

Remove the `stable_workspace` parameter and fallback logic from `AgentWorkspace`.

---

## Verification Checklist

After completing all changes, verify:

- [ ] `pytest tests/unit/` passes
- [ ] `pytest tests/integration/` passes (where applicable)
- [ ] `mypy src/remora/` has no new errors
- [ ] `ruff check src/remora/` passes
- [ ] CLI commands work: `remora swarm start`, `remora swarm list`

---

## File Change Summary

| File | Action | Est. LOC Change |
|------|--------|-----------------|
| `core/events.py` | Remove legacy events | -70 |
| `core/event_bus.py` | Remove EventBridge | -35 |
| `core/config.py` | Remove extra classes | -45 |
| `core/errors.py` | Add SwarmError | +5 |
| `core/swarm_state.py` | Make async | +20 |
| `core/tools/swarm.py` | Add new tools | +60 |
| `nvim/server.py` | Remove unused function | -5 |
| `cli/main.py` | Simplify, fix async | +5 |
| `__init__.py` | Fix exports | ±0 |
| **Total** | | ~-65 LOC |

---

## Order of Implementation

Recommended order to minimize risk:

1. **Phase 1**: Remove dead code (lowest risk)
2. **Phase 4**: Fix event types (isolated change)
3. **Phase 5**: Add missing components (additive)
4. **Phase 2**: Simplify config (check for usages)
5. **Phase 3**: API consistency (requires caller updates)
6. **Phase 6**: Code quality (polish)
7. **Phase 7**: Optional (major changes)

---

## Notes

- All changes are backwards-incompatible as per project guidelines
- Test after each phase before proceeding
- Consider adding deprecation warnings if gradual migration needed
- Update documentation after changes are complete
