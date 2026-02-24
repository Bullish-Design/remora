# Remora Demo Integration Review

## Executive Summary

This report analyzes the alignment between the remora library and the remora-demo frontend implementation. The review identifies **critical architectural mismatches** that prevent the demo from properly interacting with remora's workspace/backend functionality.

---

## 1. Architecture Overview

### 1.1 Remora Library (`src/remora/`)

| Component | File | Purpose |
|-----------|------|---------|
| Event System | `event_bus.py` | Unified EventBus for all components |
| Frontend Module | `frontend/` | Provides views, state, registry, routes |
| Workspace | `workspace.py` | GraphWorkspace for agent graph execution |
| Interactive | `interactive/coordinator.py` | WorkspaceInboxCoordinator for user responses |

### 1.2 Remora-Demo (`src/remora_demo/`)

The demo has **two separate dashboard implementations**:

1. **Stario-based** (`src/remora_demo/main.py`): Uses remora.frontend
2. **FastAPI-based** (`dashboard/app.py`): Standalone implementation

---

## 2. Critical Issues Found

### Issue 1: GraphWorkspace Lacks KV Store

**Location**: `src/remora/workspace.py`

The `GraphWorkspace` class provides only file-based storage:
- `agent_space(agent_id)` - returns a `Path`
- `shared_space()` - returns a `Path`
- `original_source()` - returns a `Path`

**However**, the `WorkspaceInboxCoordinator` in `interactive/coordinator.py:92-114` expects:
```python
entries = await workspace.kv.list(prefix="outbox:question:")
data = await workspace.kv.get(key)
await workspace.kv.set(inbox_key, {...})
```

**Impact**: The coordinator cannot work with `GraphWorkspace` because there's no `kv` attribute. The demo cannot receive user responses to blocked agents.

---

### Issue 2: Two Incompatible Dashboard Implementations

The remora-demo contains **two separate dashboards** that don't share code:

| Aspect | Stario Version | FastAPI Version |
|--------|---------------|-----------------|
| Entry | `src/remora_demo/main.py` | `dashboard/app.py` |
| Framework | Stario | FastAPI |
| State | `remora.frontend.state.DashboardState` | Local `DashboardState` |
| Events | SSE via EventBus | WebSocket + SSE |
| Responses | POST `/agent/{agent_id}/respond` | Same endpoint |
| Frontend | Datastar (stario.html) | Vanilla JS |

The FastAPI version (`dashboard/app.py:32-49`) has its own state management:
```python
class DashboardState:
    def __init__(self):
        self.event_bus: EventBus = get_event_bus()
        self._responses: dict[str, AgentResponse] = {}
        self._websockets: set[WebSocket] = set()
```

This duplicates `remora.frontend.state.DashboardState` which has different logic.

---

### Issue 3: Frontend Views Not Integrated with Workspaces

**Location**: `src/remora/frontend/views.py`

The dashboard view (`dashboard_view`) at line 225 expects signals from `DashboardState`:
- `events` - event stream
- `blocked` - agents waiting for input
- `agentStates` - agent status
- `results` - completed agent results
- `progress` - execution progress

**However**, there's no integration with actual workspace creation/management. The routes at `frontend/routes.py:30-86` register endpoints but:
1. Don't create workspaces
2. Don't wire agents to workspaces
3. Don't start the coordinator watchers

---

### Issue 4: Routes Missing Workspace Registration

**Location**: `src/remora/frontend/routes.py`

The `register_routes` function at line 30:
```python
def register_routes(app: Stario, event_bus: EventBus | None = None) -> WorkspaceInboxCoordinator:
    # Sets up routes but never:
    # - Creates workspaces
    # - Registers agents to workspaces
    # - Starts the coordinator's watchers
```

There's no mechanism to:
1. Start an agent graph execution
2. Associate agents with workspaces
3. Feed events to the coordinator

---

### Issue 5: Stale Dashboard Static Files

**Location**: `dashboard/static/` (FastAPI version)

The static files (`dashboard.js`, `index.html`) are designed for the FastAPI backend and use:
- WebSocket connection (`dashboard.js:252`)
- Different event handling logic than the Stario version
- Manual DOM manipulation instead of Datastar

These files are separate from the Stario frontend views.

---

## 3. Functional Alignment Matrix

| Feature | Remora Library | Demo Implementation | Status |
|---------|---------------|---------------------|--------|
| Event Streaming | `EventBus.stream()` | SSE/WebSocket | **Partial** |
| Agent State Tracking | `DashboardState.record()` | Custom implementation | **Mismatch** |
| Blocked Agent Handling | `WorkspaceInboxCoordinator` | Doesn't use coordinator | **Missing** |
| Workspace KV IPC | Expected by coordinator | Not implemented | **Missing** |
| Graph Execution | `agent_graph.py` | Not exposed | **Missing** |
| Route Registration | `register_routes()` | Uses it but incomplete | **Partial** |

---

## 4. Specific Code Issues

### 4.1 Workspace KV Interface Mismatch

```python
# frontend/routes.py:63-77
workspace = workspace_registry.get_workspace(signals.agent_id)
if not workspace:
    writer.json({"error": "No workspace found for agent..."})
    return

await coordinator.respond(
    agent_id=signals.agent_id,
    msg_id=msg_id,
    answer=signals.answer,
    workspace=workspace,  # This will fail - GraphWorkspace has no .kv
)
```

### 4.2 Coordinator Expects KV Methods

```python
# interactive/coordinator.py:92-114
async def _list_pending_questions(self, workspace: Any) -> list[QuestionPayload]:
    try:
        entries = await workspace.kv.list(prefix="outbox:question:")  # FAILS
    except Exception:
        return []
```

### 4.3 Event Payload Field Mismatch

The frontend views expect specific payload fields:

| Field | Used In | Expected From |
|-------|---------|---------------|
| `question` | `views.py:89` | Event payload |
| `options` | `views.py:92` | Event payload |
| `msg_id` | `views.py:93` | Event payload |
| `name` | `state.py:29` | Event payload |
| `workspace_id` | `state.py:30,41` | Event payload |
| `result` | `state.py:62` | Event payload |

Events must be published with these exact payload keys.

---

## 5. Recommendations

### 5.1 Add KV Store to GraphWorkspace

The `GraphWorkspace` class needs a KV store interface:

```python
@dataclass
class GraphWorkspace:
    # ... existing fields ...
    _kv: KVStore | None = None
    
    def kv(self) -> KVStore:
        if self._kv is None:
            self._kv = WorkspaceKVStore(self.root / "kv")
        return self._kv
```

### 5.2 Consolidate Dashboard Implementations

Choose one approach:
- **Option A**: Use Stario + remora.frontend (recommended for consistency)
- **Option B**: Keep FastAPI but integrate remora.frontend components

### 5.3 Add Workspace Lifecycle Management

The frontend needs to:
1. Create workspaces for graph execution
2. Register agents to workspaces via `workspace_registry.register()`
3. Start coordinator watchers via `coordinator.watch_workspace()`

### 5.4 Expose Agent Graph Execution

Add routes to:
1. Start a new graph execution (`POST /graph/execute`)
2. Get execution status (`GET /graph/{graph_id}/status`)
3. Stream graph events (`GET /graph/{graph_id}/events`)

---

## 6. Conclusion

The remora-demo and remora library have significant architectural misalignment:

1. **GraphWorkspace doesn't support KV** - required by WorkspaceInboxCoordinator
2. **Two separate dashboards** - code duplication, inconsistent behavior
3. **No workspace lifecycle** - agents aren't associated with workspaces
4. **Missing graph execution API** - no way to start/run agent graphs

**Priority Fixes**:
1. Add KV store to GraphWorkspace (critical for user interaction)
2. Integrate coordinator with workspace registry
3. Add graph execution endpoints
4. Consolidate dashboard implementations

The demo cannot meaningfully interact with remora's backend until these issues are resolved.
