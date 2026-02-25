# NEW_NODE_CONCEPT.md

## Overview

This document describes the concept for enabling users to start a new graph/node in the Remora system **without** requiring them to manually enter a Graph ID. The goal is to provide a seamless "one-click" experience where the system generates the appropriate identifier automatically.

## Current State

### Architecture

```
┌─────────────────┐    proxy     ┌─────────────────┐
│  Frontend       │ ──────────▶ │  Hub            │
│  (Stario)       │ ◀───────── │  (Starlette)    │
│  Port 8001      │   SSE      │  Port 8000      │
└─────────────────┘            └─────────────────┘
```

- **Frontend**: Stario app on port 8001 - serves SPA, proxies requests to hub
- **Hub**: Starlette + datastar-py on port 8000 - runs agents, publishes SSE events

### Current Flow (Requires Graph ID)

1. User opens browser to `http://localhost:8001`
2. User fills in the "Launch Graph" form with a **required** Graph ID
3. User clicks "Start Graph"
4. Frontend sends POST to `/graph/execute` with `graph_id` in payload
5. Frontend proxies to hub at `http://localhost:8000/graph/execute`
6. Hub creates workspace and executes the graph
7. Hub returns response with `graph_id`, agent count, workspace info
8. Frontend subscribes to SSE for real-time updates

### Current Hub Implementation

From `.context/remora/src/remora/hub/server.py:107-133`:

```python
async def execute_graph(self, request: Request) -> JSONResponse:
    """Execute an agent graph - starts agents in the graph."""
    signals = await read_signals(request) or {}
    graph_id = signals.get("graph_id", "")

    if not graph_id:
        return JSONResponse({"error": "graph_id required"}, status_code=400)

    workspace = await self._workspace_manager.create(graph_id)
    graph = self._build_agent_graph(graph_id, workspace, signals)
    # ... execution continues

    return JSONResponse({
        "status": "started",
        "graph_id": graph_id,
        "agents": len(graph.agents()),
        "workspace": workspace.id,
    })
```

**Problem**: The hub currently requires `graph_id` to be provided. If omitted, it returns a 400 error.

## Desired State

### New Flow (Auto-generate Graph ID)

1. User opens browser to `http://localhost:8001`
2. User optionally fills in Bundle, Target, or uses "Browse" to select a file
3. User clicks "Start Graph" **without entering a Graph ID**
4. Frontend sends POST to `/graph/execute` **without** `graph_id` (or with empty string)
5. Hub generates a unique graph ID (e.g., using UUID or timestamp-based)
6. Hub creates workspace with the generated ID
7. Hub returns response including the **generated graph_id**
8. Frontend displays/confirms the new graph was started (shows the generated ID)
9. SSE updates continue as normal

### Benefits

1. **Simpler UX**: Users don't need to think of a unique ID
2. **Faster workflow**: One less field to fill out
3. **Reduced errors**: No chance of ID collisions or naming conflicts
4. **Better demo experience**: New users can just click and see results

## Implementation Plan

### Part 1: Hub Modifications (Remora Developer)

Modify `.context/remora/src/remora/hub/server.py`:

1. **Update `execute_graph` method** to generate `graph_id` if not provided:
   ```python
   async def execute_graph(self, request: Request) -> JSONResponse:
       signals = await read_signals(request) or {}
       graph_id = signals.get("graph_id", "")

       # NEW: Auto-generate graph_id if not provided
       if not graph_id:
           import uuid
           graph_id = f"graph-{uuid.uuid4().hex[:8]}"
           
       # ... rest of the method remains the same
   ```

2. **Alternative: Add separate endpoint** for "new graph" (more RESTful):
   ```python
   # Option A: POST to /graph/new - creates a new graph with auto-generated ID
   # Option B: POST to /graph/execute - with optional graph_id (current approach)
   ```

3. **Return the generated ID** in the response (already does this, just needs to return the generated one)

### Part 2: Frontend Modifications (remora-demo Developer)

Modify `src/remora_demo/frontend/views.py`:

1. **Remove the validation check** that blocks when Graph ID is empty:
   ```javascript
   // BEFORE (requires graph_id):
   const graphId = $graphLauncher?.graphId?.trim();
   if (!graphId) {
       alert('Graph ID is required to launch a graph.');
       return;
   }
   
   // AFTER (optional graph_id):
   // Just use the value if provided, otherwise let hub generate one
   ```

2. **Update the payload** to only include `graph_id` if it has a value:
   ```javascript
   const payload = {};
   const graphId = $graphLauncher?.graphId?.trim();
   if (graphId) {
       payload.graph_id = graphId;
   }
   // ... add other optional fields
   payload.bundle = $graphLauncher?.bundle?.trim() || 'default';
   // ...
   @post('/graph/execute', payload);
   ```

3. **Display the generated ID** after successful launch (optional enhancement):
   - Read the response from the POST
   - Show the generated `graph_id` to the user so they know what their graph is called

### Part 3: Frontend Proxy Modifications

Modify `src/remora_demo/frontend/main.py`:

1. **Update `execute_graph` handler** to not require `graph_id` in payload:
   ```python
   async def execute_graph(c: Context, w: Writer) -> None:
       signals = await c.signals(ExecuteSignals)
       
       payload = {}
       # Only include graph_id if it's provided and non-empty
       if signals.graph_id:
           payload["graph_id"] = signals.graph_id
       if signals.bundle:
           payload["bundle"] = signals.bundle
       if signals.target:
           payload["target"] = signals.target
       if signals.target_path:
           payload["target_path"] = signals.target_path

       # ... proxy to hub
   ```

## Expected API Contract

### Request (Optional graph_id)

```json
{
  "bundle": "default",
  "target": "Analyze this code",
  "target_path": "/path/to/file.py"
}
```

OR with graph_id provided:

```json
{
  "graph_id": "my-custom-graph",
  "bundle": "default",
  "target": "Analyze this code"
}
```

### Response

```json
{
  "status": "started",
  "graph_id": "graph-a1b2c3d4",
  "agents": 1,
  "workspace": "workspace-123"
}
```

Note: The response always includes the `graph_id` - either the one provided by the user or the one auto-generated by the hub.

## Testing Plan

1. **Test with empty payload**: `curl -X POST http://localhost:8000/graph/execute -H "Content-Type: application/json" -d '{}'`
   - Should return 200 with auto-generated `graph_id`

2. **Test with custom ID**: `curl -X POST http://localhost:8000/graph/execute -H "Content-Type: application/json" -d '{"graph_id": "my-graph"}'`
   - Should return 200 with provided `graph_id`

3. **Frontend integration**: 
   - Open http://localhost:8001
   - Leave Graph ID empty
   - Click "Start Graph"
   - Should start a new graph and display the generated ID

## Future Enhancements

1. **Naming scheme customization**: Allow users to specify a prefix for auto-generated IDs (e.g., "demo-" → "demo-a1b2c3d4")

2. **Graph templates**: Pre-configured graph configurations that can be launched without any input

3. **Recent graphs**: Store and display recently launched graphs so users can reference them

4. **Graph management UI**: A dedicated page to manage (view, stop, restart) launched graphs

## Questions for Remora Developer

1. Is there a preferred ID generation scheme (UUID, timestamp-based, sequential)?
2. Should there be a separate `/graph/new` endpoint, or modify `/graph/execute`?
3. Is there a maximum number of concurrent graphs allowed?
4. Should the hub validate the provided graph_id format?
5. Is there any security concern with allowing auto-generated IDs?

---

**Status**: Awaiting implementation by Remora developer
**Priority**: High - enables simpler user Onboarding
**Dependencies**: Hub changes required before frontend changes are fully functional
