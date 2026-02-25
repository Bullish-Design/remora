# NEW_NODE_UI_PLAN.md

## Overview

This document outlines the changes required to enable:
1. **Auto-generating graph IDs** when users don't provide one
2. **Creating graphs from files/directories** by providing a target path instead of a pre-existing graph ID
3. **Pre-populating the frontend** with existing workspace graphs so users can resume prior work

## Architecture

```
┌─────────────────┐    proxy     ┌─────────────────┐
│  Frontend       │ ──────────▶ │  Hub            │
│  (Stario)       │ ◀───────── │  (Starlette)    │
│  Port 8001      │   SSE      │  Port 8000      │
└─────────────────┘            └─────────────────┘
```

## Changes Required

### Part 1: Hub Server Changes (`src/remora/hub/server.py`)

#### 1.1 Allow Optional Graph ID (Auto-Generate)

**Why**: The frontend wants users to launch graphs without manually entering an ID. The hub currently returns 400 if `graph_id` is missing.

**Current code** (`server.py:155-161`):
```python
async def execute_graph(self, request: Request) -> JSONResponse:
    signals = await read_signals(request) or {}
    graph_id = signals.get("graph_id", "")

    if not graph_id:
        return JSONResponse({"error": "graph_id required"}, status_code=400)
```

**Implementation**:
1. Remove the 400 check that requires `graph_id`
2. Auto-generate a unique ID using UUID if not provided:
   ```python
   import uuid
   
   if not graph_id:
       graph_id = f"graph-{uuid.uuid4().hex[:8]}"
   ```

**Result**: The response always includes the generated or provided `graph_id`, enabling the frontend to display it to users.

---

#### 1.2 Support File/Directory Target Paths

**Why**: Users should be able to select a file or directory (via file picker) to create a new graph. The code already supports `target_path` in `_build_agent_graph`.

**Current behavior**:
- `target_path` is optional; if provided, it's passed to the agent
- Workspaces are created but not pre-populated with the source file

**Implementation**:
1. Ensure `target_path` from signals is passed through correctly (already done at line 195-206)
2. The workspace's `snapshot_original` method already handles copying files/directories (see `workspace.py:181-197`)
3. Call `workspace.snapshot_original(Path(target_path))` when `target_path` is provided:
   ```python
   workspace = await self._workspace_manager.create(graph_id)
   
   # NEW: Snapshot the target if provided
   target_path = signals.get("target_path")
   if target_path:
       await workspace.snapshot_original(Path(target_path))
   ```

---

#### 1.3 Add Endpoint to List Existing Workspaces

**Why**: The frontend needs to show users their existing graphs so they can "pick back up" on prior work.

**Implementation**: Add a new route in `server.py`:

```python
Route("/graph/list", self.list_graphs, methods=["GET"]),
```

Handler:
```python
async def list_graphs(self, request: Request) -> JSONResponse:
    """
    List all existing workspaces (root nodes of each graph).
    
    Returns:
    {
        "graphs": [
            {
                "graph_id": "graph-abc123",
                "bundle": "default",
                "target_path": "/path/to/file.py",
                "target": "Analyze this code",
                "created_at": "2024-01-15T10:30:00Z",
                "status": "running|completed|stopped"
            }
        ]
    }
    """
    workspaces = self._workspace_manager.list_all()
    
    graphs = []
    for ws in workspaces:
        # Read metadata from workspace if available
        graph_info = {
            "graph_id": ws.id,
            "target_path": str(ws._original_source) if ws._original_source else None,
        }
        graphs.append(graph_info)
    
    return JSONResponse({"graphs": graphs})
```

**Note**: This requires updating `WorkspaceManager` to list workspaces from disk (not just in-memory). See Section 2.1.

---

### Part 2: Workspace Manager Changes (`src/remora/workspace.py`)

#### 2.1 List Workspaces from Disk

**Why**: Currently `WorkspaceManager.list()` only returns workspaces created in the current process. We need to discover all workspaces on startup.

**Current code** (`workspace.py:306-308`):
```python
def list(self) -> list[GraphWorkspace]:
    """List all workspaces."""
    return list(self._workspaces.values())
```

**Implementation**: Add a method to scan the base directory:

```python
def list_all(self) -> list[GraphWorkspace]:
    """List all workspaces (including persisted ones on disk)."""
    # First return in-memory workspaces
    all_workspaces = list(self._workspaces.values())
    
    # Then scan disk for any we don't have in memory
    if self._base_dir.exists():
        for item in self._base_dir.iterdir():
            if item.is_dir():
                ws_id = item.name
                # Skip if already loaded
                if ws_id not in self._workspaces:
                    # Load workspace metadata without full init
                    ws = GraphWorkspace(id=ws_id, root=item)
                    all_workspaces.append(ws)
    
    return all_workspaces
```

---

#### 2.2 Add Workspace Metadata Storage

**Why**: To display useful info about each graph (target path, bundle, status), we need to persist metadata when creating a workspace.

**Implementation**: Add a `metadata.json` file in each workspace:

```python
@dataclass
class GraphMetadata:
    graph_id: str
    bundle: str = "default"
    target: str = ""
    target_path: str = ""
    created_at: str = ""
    status: str = "running"

async def save_metadata(self, metadata: GraphMetadata) -> None:
    """Save graph metadata to workspace."""
    metadata_path = self.root / "metadata.json"
    import json
    metadata_path.write_text(json.dumps(asdict(metadata)))

async def load_metadata(self) -> GraphMetadata | None:
    """Load graph metadata from workspace."""
    metadata_path = self.root / "metadata.json"
    if not metadata_path.exists():
        return None
    import json
    return GraphMetadata(**json.loads(metadata_path.read_text()))
```

Update `execute_graph` in server.py to save metadata:
```python
workspace = await self._workspace_manager.create(graph_id)

# Save metadata
metadata = GraphMetadata(
    graph_id=graph_id,
    bundle=signals.get("bundle", "default"),
    target=signals.get("target", ""),
    target_path=signals.get("target_path", ""),
    created_at=datetime.now().isoformat(),
    status="running"
)
await workspace.save_metadata(metadata)
```

---

### Part 3: Frontend Changes (Stario App)

#### 3.1 Update Graph Launcher Form

**Why**: Remove the requirement for Graph ID; make bundle, target, and target_path optional.

**File**: `.context/remora-demo/src/remora_demo/frontend/views.py`

**Current code** (lines 84-139):
```python
Input(
    {
        "type": "text",
        "placeholder": "Graph ID (required)",
        "data-bind": "graphLauncher.graphId",
    }
),
# ... other inputs ...
Button(
    {
        "type": "button",
        "data-on": "click",
        "data-on-click": """
        const graphId = $graphLauncher?.graphId?.trim();
        if (!graphId) {
            alert('Graph ID is required to launch a graph.');
            return;
        }
        // ... rest of handler
        """,
    },
    "Start Graph",
),
```

**Implementation**:
1. Change placeholder to "(auto-generated if empty)"
2. Update the click handler to:
   - Only include `graph_id` in payload if user provided one
   - Include `target_path` from file picker
   - Show the generated ID after successful launch

```python
Input(
    {
        "type": "text",
        "placeholder": "Graph ID (optional, auto-generated)",
        "data-bind": "graphLauncher.graphId",
    }
),
# Add file input for target_path
Input(
    {
        "type": "file",
        # For directory: "webkitdirectory" attribute
        "data-bind": "graphLauncher.targetPath",
    }
),
Button(
    {
        "type": "button",
        "data-on": "click",
        "data-on-click": """
        const payload = {};
        const graphId = $graphLauncher?.graphId?.trim();
        if (graphId) {
            payload.graph_id = graphId;
        }
        payload.bundle = $graphLauncher?.bundle?.trim() || 'default';
        
        const targetValue = $graphLauncher?.target?.trim();
        if (targetValue) {
            payload.target = targetValue;
        }
        
        const targetPathValue = $graphLauncher?.targetPath?.trim();
        if (targetPathValue) {
            payload.target_path = targetPathValue;
        }
        
        @post('/graph/execute', payload);
        $graphLauncher.graphId = '';
        $graphLauncher.target = '';
        $graphLauncher.targetPath = '';
        """,
    },
    "Start Graph",
),
```

---

#### 3.2 Add Existing Graphs List

**Why**: Show users their prior graphs so they can resume work.

**Implementation**: Add a new card to the view:

```python
Div(
    {"class": "card"},
    Div({}, "Existing Graphs"),
    Div({"id": "existing-graphs"}, "Loading..."),
),
```

Add a handler to fetch the list on load:

```python
# In the view's data.signals:
data.init(at.get("/graph/list")),

# Or fetch on page load:
data.on("load", at.get("/graph/list")),
```

Update the click handler for each existing graph to re-launch it:
```python
# In the card rendering for each graph:
Button(
    {
        "data-on": "click",
        "data-on-click": f"""
            @post('/graph/execute', {{graph_id: '{graph_id}'}});
        """,
    },
    "Resume",
)
```

---

#### 3.3 Update Frontend Proxy

**File**: `.context/remora-demo/src/remora_demo/frontend/main.py`

**Changes needed**:
1. Add route for `/graph/list`:
   ```python
   app.get("/graph/list", list_graphs)
   ```

2. Add handler:
   ```python
   async def list_graphs(c: Context, w: Writer) -> None:
       try:
           async with aiohttp.ClientSession() as session:
               async with session.get(f"{HUB_URL}/graph/list") as resp:
                   result = await resp.json()
                   w.json(result)
       except aiohttp.ClientError as e:
           logger.error(f"Failed to list graphs: {e}")
           w.json({"graphs": []})
   ```

3. Update `execute_graph` to not always send `graph_id`:
   ```python
   async def execute_graph(c: Context, w: Writer) -> None:
       signals = await c.signals(ExecuteSignals)
       
       payload = {}
       if signals.graph_id:
           payload["graph_id"] = signals.graph_id
       if signals.bundle:
           payload["bundle"] = signals.bundle
       # ... include other optional fields
       
       # Always include bundle at minimum
       payload.setdefault("bundle", "default")
       
       try:
           async with aiohttp.ClientSession() as session:
               async with session.post(f"{HUB_URL}/graph/execute", json=payload) as resp:
                   result = await resp.json()
                   w.json(result)
       except aiohttp.ClientError as e:
           logger.error(f"Failed to execute graph: {e}")
           w.json({"error": str(e)})
   ```

---

## Implementation Order

1. **Hub Server** (`src/remora/hub/server.py`)
   - [ ] Remove graph_id required check
   - [ ] Add auto-generation logic
   - [ ] Add snapshot_original call for target_path
   - [ ] Add `/graph/list` endpoint

2. **Workspace** (`src/remora/workspace.py`)
   - [ ] Add `list_all()` method
   - [ ] Add `GraphMetadata` dataclass
   - [ ] Add `save_metadata()` / `load_metadata()` methods

3. **Frontend Proxy** (`.context/remora-demo/src/remora_demo/frontend/main.py`)
   - [ ] Add `/graph/list` route and handler
   - [ ] Update `execute_graph` to send optional fields

4. **Frontend Views** (`.context/remora-demo/src/remora_demo/frontend/views.py`)
   - [ ] Update graph launcher form (remove required ID, add file input)
   - [ ] Update click handler to not require graph_id
   - [ ] Add existing graphs card

## API Contract Summary

### POST /graph/execute

**Request** (all fields optional except bundle):
```json
{
  "bundle": "default",
  "target": "Analyze this code",
  "target_path": "/path/to/file.py"
}
```

OR with graph_id:
```json
{
  "graph_id": "my-custom-graph",
  "bundle": "default"
}
```

**Response**:
```json
{
  "status": "started",
  "graph_id": "graph-a1b2c3d4",
  "agents": 1,
  "workspace": "workspace-123"
}
```

### GET /graph/list

**Response**:
```json
{
  "graphs": [
    {
      "graph_id": "graph-abc123",
      "bundle": "default",
      "target_path": "/path/to/file.py",
      "target": "Analyze this code",
      "created_at": "2024-01-15T10:30:00Z",
      "status": "running"
    }
  ]
}
```

## Testing

1. **Empty payload**: `curl -X POST http://localhost:8000/graph/execute -H "Content-Type: application/json" -d '{"bundle": "default"}'`
   - Should return 200 with auto-generated `graph_id`

2. **With target_path**: `curl -X POST http://localhost:8000/graph/execute -H "Content-Type: application/json" -d '{"bundle": "default", "target_path": "/tmp/test.py"}'`
   - Should create workspace and snapshot the file

3. **List graphs**: `curl http://localhost:8000/graph/list`
   - Should return all existing workspaces

4. **Frontend integration**:
   - Open http://localhost:8001
   - Leave Graph ID empty
   - Select a file or enter a target path
   - Click "Start Graph"
   - Should display the generated ID
