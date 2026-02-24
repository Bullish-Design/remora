# Remora-Demo Refactoring Guide

This guide outlines all changes needed to refactor the remora-demo library to properly integrate with the remora library's workspace/backend functionality.

## Overview

The remora-demo currently has two separate dashboard implementations:
1. **Stario version** (`src/remora_demo/main.py`) - Uses remora.frontend
2. **FastAPI version** (`dashboard/app.py`) - Standalone, duplicates functionality

The goal is to have a single, unified implementation that properly integrates with remora.

---

## Changes to Make

### Phase 1: Remove Duplicate Dashboard (Easy)

**File to delete:** `dashboard/app.py`  
**Files to delete:** `dashboard/static/dashboard.js`, `dashboard/static/index.html`, `dashboard/static/projector.html`, `dashboard/static/style.css`, `dashboard/mobile/remote.html`

**Action:** Remove the entire `dashboard/` directory. The Stario-based implementation at `src/remora_demo/main.py` will be the single dashboard.

### Phase 2: Update Main Entry Point (Easy)

**File:** `src/remora_demo/main.py`

Replace the entire file with:

```python
from pathlib import Path

import asyncio
import traceback
from remora.frontend import register_routes
from stario import RichTracer, Stario
from stario.http.writer import CompressionConfig

tracer = RichTracer()

with tracer:
    app = Stario(tracer, compression=CompressionConfig())

    app.assets("/static", Path(__file__).parent / "static")

    def error_handler(c, w, exc):
        w.text(f"Error: {exc}\n{traceback.format_exc()}", 500)

    app.on_error(Exception, error_handler)

    coordinator = register_routes(app)

    # TODO: Add your graph execution routes here
    # Example:
    # from remora import GraphWorkspace
    # from remora.frontend import register_agent_workspace
    #
    # @app.post("/graph/execute")
    # async def execute_graph(c, w):
    #     signals = await c.signals(ExecuteGraphSignals)
    #     workspace = await GraphWorkspace.create(signals.graph_id)
    #     # ... start graph execution with workspace ...
    #     # ... call register_agent_workspace(agent_id, workspace) for each agent ...


def main() -> None:
    import logging

    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(app.serve(host="0.0.0.0", port=8000))


if __name__ == "__main__":
    main()
```

### Phase 3: Update Static Files (Easy)

**File:** `src/remora_demo/static/js/datastar.js`

Ensure this file contains the Datastar JavaScript library. This is required for the reactive frontend.

**File:** `src/remora_demo/static/css/style.css`

This file should contain CSS for:
- Event stream panel
- Blocked agents cards
- Agent status list
- Results display
- Progress bar

### Phase 4: Wire Up Agent Execution (Medium)

When running an agent graph, you must:

1. **Create a workspace:**
```python
from remora import GraphWorkspace

workspace = await GraphWorkspace.create(graph_id)
```

2. **Register each agent with the workspace:**
```python
from remora.frontend import register_agent_workspace

# For each agent in your graph:
await register_agent_workspace(agent_id, workspace)
```

3. **Publish events when agents start/block/complete:**
```python
from remora.event_bus import Event, get_event_bus

event_bus = get_event_bus()

# When agent starts:
await event_bus.publish(Event.agent_started(
    agent_id=agent_id,
    name=agent_name,
    workspace_id=workspace.id
))

# When agent blocks:
await event_bus.publish(Event.agent_blocked(
    agent_id=agent_id,
    question="Your question here",
    options=["option1", "option2"],  # Optional
    msg_id=msg_id
))

# When agent completes:
await event_bus.publish(Event.agent_completed(
    agent_id=agent_id,
    result="Agent result here"
))
```

4. **Unregister when done:**
```python
from remora.frontend import unregister_agent

await unregister_agent(agent_id)
```

### Phase 5: Add Graph Execution Endpoint (Medium)

**File:** `src/remora_demo/main.py`

Add an endpoint to start graph execution:

```python
from dataclasses import dataclass

@dataclass
class ExecuteGraphSignals:
    graph_id: str = ""
    source_path: str = ""

@app.post("/graph/execute")
async def execute_graph(c, w, signals: ExecuteGraphSignals):
    from remora import GraphWorkspace
    from remora.frontend import register_agent_workspace
    
    if not signals.graph_id:
        w.json({"error": "graph_id required"}, status=400)
        return
    
    workspace = await GraphWorkspace.create(signals.graph_id)
    
    # Snapshot source if provided
    if signals.source_path:
        from pathlib import Path
        workspace.snapshot_original(Path(signals.source_path))
    
    # TODO: Replace with actual agent graph execution
    # This is where you'd run your agents with the workspace
    demo_agents = [
        {"id": "agent-1", "name": "Analyzer"},
        {"id": "agent-2", "name": "Writer"},
    ]
    
    for agent in demo_agents:
        await register_agent_workspace(agent["id"], workspace)
        event_bus = get_event_bus()
        await event_bus.publish(Event.agent_started(
            agent_id=agent["id"],
            name=agent["name"],
            workspace_id=workspace.id
        ))
    
    w.json({"status": "started", "graph_id": signals.graph_id, "agents": len(demo_agents)})
```

### Phase 6: Update Views (Optional)

The views at `src/remora_demo/views.py` re-export from `remora.frontend.views`. This is correct.

The state at `src/remora_demo/state.py` also re-exports from `remora.frontend.state`. This is correct.

---

## Complete File List

After refactoring, your project structure should be:

```
remora-demo/
├── pyproject.toml
├── README.md
├── src/
│   └── remora_demo/
│       ├── __init__.py
│       ├── main.py          # NEW: Unified entry point
│       ├── state.py         # Keep as re-export
│       ├── views.py         # Keep as re-export
│       ├── workspace_registry.py  # Keep as re-export
│       └── static/
│           ├── css/
│           │   └── style.css
│           └── js/
│               └── datastar.js
└── tests/
    └── __init__.py
```

**Delete these files:**
- `dashboard/` (entire directory)
- `dashboard/` (entire directory)

---

## Key Integration Points

| Remora Feature | Demo Usage |
|--------------|------------|
| `GraphWorkspace` | Create per graph execution |
| `GraphWorkspace.kv` | Store questions/responses |
| `register_agent_workspace()` | Wire agent to workspace |
| `unregister_agent()` | Cleanup when done |
| `Event.agent_started()` | Publish when agent starts |
| `Event.agent_blocked()` | Publish when waiting for input |
| `Event.agent_completed()` | Publish when done |
| `dashboard_view()` | Render the UI |
| `DashboardState` | Manages event state |

---

## Testing Your Integration

1. Start the demo server:
   ```bash
   python -m remora_demo.main
   ```

2. Open `http://localhost:8000` in browser

3. Use curl to start a demo graph:
   ```bash
   curl -X POST http://localhost:8000/graph/execute \
     -H "Content-Type: application/json" \
     -d '{"graph_id": "test-1"}'
   ```

4. Check the dashboard shows agents

5. Find a blocked agent and respond:
   ```bash
   curl -X POST "http://localhost:8000/agent/agent-1/respond" \
     -H "Content-Type: application/json" \
     -d '{"agent_id": "agent-1", "answer": "my answer", "msg_id": "msg-123"}'
   ```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| "No workspace found" | Call `register_agent_workspace()` before agent blocks |
| Events not showing | Ensure event bus is publishing events |
| KV errors | Check `workspace.kv` is accessible |
| Dashboard blank | Check Datastar JS is loaded |

---

## Next Steps

After basic integration, consider:
- Adding authentication
- Supporting actual agent graph execution
- Adding more dashboard views (logs, metrics)
- Mobile-responsive design
