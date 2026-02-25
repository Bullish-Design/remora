# Workspace Base Hub Refactor Guide

## Executive Summary

This document describes the changes needed to enable file picking from the Remora frontend UI. Currently, users must manually type server-side file paths to launch agent graphs. We need to add a file browser that lets users select files from a configured workspace base directory.

## Problem Statement

### Current Flow (Annoying)
1. User must know the exact server-side file path
2. User types path into text field (error-prone)
3. No validation that path exists
4. Poor UX

### Desired Flow
1. User clicks "Browse" button in frontend
2. Modal/dropdown shows directory tree from configured workspace base
3. User selects a file
4. Path is auto-filled in the form

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Browser            │     │  Frontend           │     │  Hub                │
│  (Laptop)          │     │  (Stario)           │     │  (Starlette)       │
│                     │     │                     │     │                     │
│  File Picker UI    │────▶│  /api/files/*       │────▶│  lists files        │
│  (React-like)      │◀────│  proxies to hub     │◀────│  under BASE_PATH   │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

## Implementation Plan

### Phase 1: Hub Changes (Backend)

#### 1.1 Add WorkspaceBase Configuration

Add to hub configuration (environment variable or config file):

```python
# Option A: Environment variable
WORKSPACE_BASE=/home/user/remora-workspaces

# Option B: Config file (remora.toml)
# [hub]
# workspace_base = "/home/user/remora-workspaces"
```

#### 1.2 Add File Listing Endpoint

Add a new endpoint to the hub server:

```python
# In remora/hub/server.py

from pathlib import Path
import os

class HubServer:
    def __init__(self, ...):
        # ... existing code ...
        self.workspace_base = Path(os.environ.get(
            "WORKSPACE_BASE", 
            "/tmp/remora/workspaces"  # default
        ))
        # Ensure base directory exists
        self.workspace_base.mkdir(parents=True, exist_ok=True)

    async def list_workspace_files(self, request: Request) -> JSONResponse:
        """
        List files under workspace_base.
        
        Query params:
        - path: relative path from workspace_base (default: "")
        
        Returns:
        {
            "path": "subdir",
            "entries": [
                {"name": "file.py", "type": "file", "size": 1234},
                {"name": "subdir", "type": "directory"},
            ]
        }
        """
        # Get relative path from query params
        query = request.query_params.get("path", "")
        
        # Security: prevent directory traversal
        resolved = (self.workspace_base / query).resolve()
        if not str(resolved).startswith(str(self.workspace_base.resolve())):
            return JSONResponse({"error": "Invalid path"}, status_code=400)
        
        if not resolved.exists():
            return JSONResponse({"error": "Path not found"}, status_code=404)
        
        entries = []
        for item in sorted(resolved.iterdir()):
            entries.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        
        return JSONResponse({
            "path": query,
            "entries": entries,
            "base": str(self.workspace_base),
        })
```

#### 1.3 Register the Route

```python
# In HubServer.__init__ or route setup
routes = [
    Route("/", self.home),
    Route("/subscribe", self.subscribe),
    Route("/graph/execute", self.execute_graph, methods=["POST"]),
    Route("/api/files", self.list_workspace_files),  # NEW
    Route("/agent/{agent_id}/respond", self.respond, methods=["POST"]),
    Mount("/static", StaticFiles(...)),
]
```

### Phase 2: Frontend Changes

#### 2.1 Add File Picker UI Component

The frontend needs to query `/api/files` and display a file browser. Add a new component in `views.py`:

```python
# In remora_demo/frontend/views.py

# Add signal for file picker state
"graphLauncher": {
    "graphId": "",
    "bundle": "default",
    "target": "",
    "targetPath": "",
    "filePickerOpen": False,      # NEW: modal state
    "filePickerPath": "",         # NEW: current browsing path
    "filePickerFiles": [],        # NEW: current directory contents
},
```

#### 2.2 Add File Browser Modal/Card

Add a file browser section in the UI (inside main-panel or as a modal):

```python
# File browser card - shown when filePickerOpen is true
Div(
    {"class": "card file-browser-card", "id": "file-browser"},
    Div({}, "Select File"),
    Div(
        {"data-show": "$graphLauncher.filePickerOpen"},
        # Current path breadcrumb
        Div(
            {"class": "file-browser-path"},
            "Path: ", 
            Span({"data-text": "$graphLauncher.filePickerPath"}),
        ),
        # Back button (if not at root)
        Button(
            {
                "data-show": "$graphLauncher.filePickerPath !== ''",
                "data-on-click": """
                    const parts = $graphLauncher.filePickerPath.split('/');
                    parts.pop();
                    $graphLauncher.filePickerPath = parts.join('/');
                    @get('/api/files?path=' + $graphLauncher.filePickerPath);
                """,
            },
            "⬆ Up",
        ),
        # File list
        Div(
            {"id": "file-list"},
            # Render entries from $graphLauncher.filePickerFiles
        ),
        # Cancel/Select buttons
        Button(
            {"data-on-click": "$graphLauncher.filePickerOpen = false"},
            "Cancel",
        ),
    ),
),
```

#### 2.3 Wire "Browse" Button

Replace the text input for targetPath with a button:

```python
# Instead of just an input, add a browse button
Div(
    {"class": "input-with-button"},
    Input(
        {
            "type": "text",
            "placeholder": "Target file path (optional)",
            "data-bind": "graphLauncher.targetPath",
        }
    ),
    Button(
        {
            "type": "button",
            "data-on-click": """
                $graphLauncher.filePickerOpen = true;
                $graphLauncher.filePickerPath = '';
                @get('/api/files');
            """,
        },
        "Browse",
    ),
),
```

#### 2.4 Handle File Click

When user clicks a directory, navigate into it. When clicking a file, select it:

```python
# For each entry in file list:
Button(
    {
        "data-on-click": f"""
            const entry = $graphLauncher.filePickerFiles.find(e => e.name === '{name}');
            if (entry.type === 'directory') {{
                $graphLauncher.filePickerPath = $graphLauncher.filePickerPath 
                    ? $graphLauncher.filePickerPath + '/' + '{name}'
                    : '{name}';
                @get('/api/files?path=' + $graphLauncher.filePickerPath);
            }} else {{
                // File selected
                $graphLauncher.targetPath = $graphLauncher.filePickerPath 
                    ? $graphLauncher.filePickerPath + '/' + '{name}'
                    : '{name}';
                $graphLauncher.filePickerOpen = false;
            }}
        """,
    },
    f"{'📁' if is_dir else '📄'} {name}",
)
```

### Phase 3: Frontend Proxy

#### 3.1 Proxy File API to Hub

In `frontend/main.py`, add a handler to proxy file requests:

```python
async def list_files(c: Context, w: Writer) -> None:
    """Proxy file listing to hub."""
    path = c.req.query.get("path", "")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HUB_URL}/api/files?path={path}") as resp:
                result = await resp.json()
                w.json(result)
    except aiohttp.ClientError as e:
        logger.error(f"Failed to list files: {e}")
        w.json({"error": str(e)})

# In run_app():
app.get("/api/files", list_files)
```

## Security Considerations

### Directory Traversal Prevention
The hub MUST validate that requested paths don't escape the workspace base:

```python
# CRITICAL: Validate path
resolved = (self.workspace_base / query).resolve()
if not str(resolved).startswith(str(self.workspace_base.resolve())):
    return JSONResponse({"error": "Invalid path"}, status_code=400)
```

### Future Enhancements (Out of Scope)
- File content preview
- Multi-file selection
- File search/filter
- Upload new files

## Testing Checklist

- [ ] Hub starts with WORKSPACE_BASE environment variable
- [ ] `/api/files` returns directory listing
- [ ] `/api/files?path=subdir` navigates into subdirectories
- [ ] Directory traversal attacks are blocked
- [ ] Frontend "Browse" button opens file picker
- [ ] Clicking directory navigates into it
- [ ] Clicking file sets targetPath and closes picker
- [ ] Selected path is sent to hub on graph execution
- [ ] Non-existent paths return 404

## File Changes Summary

### Hub (`remora` library)
| File | Change |
|------|--------|
| `remora/hub/server.py` | Add `workspace_base`, `list_workspace_files` method, register route |
| `remora/hub/__init__.py` | Export new config/classes if needed |

### Frontend (`remora-demo`)
| File | Change |
|------|--------|
| `src/remora_demo/frontend/views.py` | Add file picker UI, signals, modal/card |
| `src/remora_demo/frontend/main.py` | Add `/api/files` proxy handler |

## Example Usage

1. Set environment on hub server:
   ```bash
   export WORKSPACE_BASE=/home/user/projects
   remora-hub serve
   ```

2. Open frontend at http://localhost:8001

3. Click "Browse" button next to target file path

4. Navigate directory tree, select a file

5. Click "Start Graph" - the file path is sent to hub

## Questions for Developer

1. Should `WORKSPACE_BASE` be a required config or optional with a default?
2. Should we cache directory listings? (performance for large dirs)
3. Should we support file glob patterns for filtering?
4. Should we integrate with existing workspace management or create separate concept?
