# Frontend Refactor Guide: File Picker Implementation

This guide walks through implementing a file picker for the remora-demo frontend using proper Stario and Datastar patterns.

## Architecture

```
Browser ──▶ GET /api/files?path=──▶ Frontend ──▶ Hub ──▶ Filesystem
   │                                   │
   │◀── w.patch() + w.sync() ◀────────┘
   │
   └── Selects file, path sent on graph execution
```

**The Stario/Datastar way:**
- Single GET endpoint fetches from hub, renders HTML, patches DOM, syncs state
- Server does the rendering (not client-side JS)
- Use `w.patch()` for HTML fragments, `w.sync()` for reactive state

---

## Step 1: Add the Proxy Endpoint (main.py)

```python
import logging
import aiohttp
from stario import Context, Writer

HUB_URL = "http://localhost:8000"
logger = logging.getLogger(__name__)


async def list_files(c: Context, w: Writer) -> None:
    """
    Fetch file list from hub and render the file picker UI.
    
    Query params:
    - path: relative path from workspace base (default: "")
    
    This is the core pattern: proxy to hub, render HTML, patch DOM.
    """
    path = c.req.query.get("path", "")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{HUB_URL}/api/files",
                params={"path": path} if path else {}
            ) as resp:
                result = await resp.json()
                
                if resp.status >= 400:
                    error = result.get("error", "Unknown error")
                    w.patch(Div({"id": "file-picker-list"}, 
                        f"Error: {error}"))
                    w.sync({"filePickerError": error})
                    return
                
                entries = result.get("entries", [])
                current_path = result.get("path", path)
                
                # Render file list items (server-side rendering)
                items_html = "".join(
                    _render_file_item(e["name"], e["type"] == "directory", e.get("size"))
                    for e in sorted(entries, key=lambda e: (e["type"] != "directory", e["name"]))
                )
                
                if not items_html:
                    items_html = '<div class="empty-state">No files</div>'
                
                # Patch the list into DOM AND sync navigation state
                w.patch(Div({"id": "file-picker-list"}, items_html))
                w.sync({"filePickerPath": current_path, "filePickerError": ""})
                
    except aiohttp.ClientError as e:
        logger.error(f"Failed to list files: {e}")
        w.patch(Div({"id": "file-picker-list"}, f"Error: {e}"))


def _render_file_item(name: str, is_dir: bool, size: int | None = None) -> str:
    """Render a single file/directory entry. Called from list_files."""
    import html
    icon = "📁" if is_dir else "📄"
    size_str = f" ({size})" if size and not is_dir else ""
    safe_name = html.escape(name)
    
    if is_dir:
        return f'''<div class="file-item directory">
            <button type="button" class="file-item-btn" 
                data-on-click="$graphLauncher.filePickerPath = $graphLauncher.filePickerPath 
                    ? $graphLauncher.filePickerPath + '/{safe_name}' 
                    : '{safe_name}';
                @get('/api/files?path=' + $graphLauncher.filePickerPath);">
                {icon} {safe_name}/
            </button>
        </div>'''
    else:
        return f'''<div class="file-item file">
            <button type="button" class="file-item-btn"
                data-on-click="$graphLauncher.targetPath = $graphLauncher.filePickerPath 
                    ? $graphLauncher.filePickerPath + '/{safe_name}' 
                    : '{safe_name}';
                $graphLauncher.filePickerOpen = false;">
                {icon} {safe_name}{size_str}
            </button>
        </div>'''


# Register route in run_app():
async def run_app() -> None:
    with RichTracer() as tracer:
        app = Stario(tracer, compression=CompressionConfig())
        app.assets("/static", "src/remora_demo/static")
        
        app.get("/", home)
        app.get("/subscribe", subscribe)
        app.get("/api/files", list_files)  # NEW
        app.post("/graph/execute", execute_graph)
        app.post("/agent/*", respond)
        
        await app.serve(host="0.0.0.0", port=8001)
```

---

## Step 2: Update views.py Signals

Add file picker state to the signals:

```python
from stario import at, data

def home_view() -> Html:
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1.0"}),
            Title("Remora Dashboard"),
            Link({"rel": "stylesheet", "href": "/static/css/style.css"}),
            Script({
                "type": "module",
                "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
            }),
        ),
        Body(
            data.signals(
                {
                    "selectedAgent": None,
                    "events": [],
                    "blocked": [],
                    "agentStates": {},
                    "progress": {"total": 0, "completed": 0},
                    "results": [],
                    "responseDraft": {},
                    "graphLauncher": {
                        "graphId": "",
                        "bundle": "default",
                        "target": "",
                        "targetPath": "",
                        # File picker state
                        "filePickerOpen": False,
                        "filePickerPath": "",
                        "filePickerError": "",
                    },
                },
                ifmissing=True,
            ),
            data.init(at.get("/subscribe")),
            # ... rest of view
        ),
    )
```

---

## Step 3: Add File Picker UI (views.py)

Add the modal to the main panel:

```python
def file_picker_modal() -> str:
    """File picker modal - only visible when filePickerOpen is true."""
    return f'''
    <div id="file-picker" class="modal-overlay" data-show="$graphLauncher.filePickerOpen">
        <div class="modal-content card">
            <div class="modal-header">Select File</div>
            <div class="error-message" data-text="$graphLauncher.filePickerError"></div>
            <div class="path-display">
                Path: <span data-text="$graphLauncher.filePickerPath || '/'"></span>
            </div>
            <div class="nav-buttons">
                <button type="button" class="btn btn-small"
                    data-show="$graphLauncher.filePickerPath !== ''"
                    data-on-click="const parts = $graphLauncher.filePickerPath.split('/'); parts.pop(); @get('/api/files?path=' + parts.join('/'));">
                    ⬆ Up
                </button>
            </div>
            <div id="file-picker-list" class="file-list"></div>
            <div class="modal-footer">
                <button type="button" class="btn"
                    data-on-click="$graphLauncher.filePickerOpen = false">
                    Cancel
                </button>
            </div>
        </div>
    </div>'''
```

---

## Step 4: Update Graph Launcher Form (views.py)

Add the Browse button:

```python
# In the graph launcher form, replace targetPath input with:
f'''
<div class="form-group input-with-button">
    <input type="text" placeholder="Target file path (optional)" data-bind="graphLauncher.targetPath">
    <button type="button" class="btn" 
        data-on-click="$graphLauncher.filePickerOpen = true; $graphLauncher.filePickerPath = ''; @get('/api/files');">
        Browse
    </button>
</div>'''
```

---

## Step 5: Add CSS (style.css)

```css
.modal-overlay {
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}
.modal-content {
    background: white;
    border-radius: 8px;
    padding: 1.5rem;
    max-width: 500px;
    width: 90%;
    max-height: 80vh;
    overflow-y: auto;
}
.modal-header { font-size: 1.25rem; font-weight: bold; margin-bottom: 1rem; }
.modal-footer { margin-top: 1rem; display: flex; justify-content: flex-end; gap: 0.5rem; }
.path-display { font-family: monospace; padding: 0.5rem; background: #f5f5f5; border-radius: 4px; margin-bottom: 0.5rem; }
.nav-buttons { margin-bottom: 0.5rem; }
.file-list { max-height: 300px; overflow-y: auto; border: 1px solid #e0e0e0; border-radius: 4px; }
.file-item { padding: 0.25rem 0.5rem; border-bottom: 1px solid #f0f0f0; }
.file-item:last-child { border-bottom: none; }
.file-item-btn { background: none; border: none; text-align: left; width: 100%; padding: 0.5rem; cursor: pointer; font-size: 0.9rem; }
.file-item-btn:hover { background: #f5f5f5; }
.file-item.directory .file-item-btn { font-weight: 500; }
.error-message { color: #dc3545; padding: 0.5rem; background: #ffe6e6; border-radius: 4px; margin-bottom: 0.5rem; }
.empty-state { padding: 2rem; text-align: center; color: #666; }
.input-with-button { display: flex; gap: 0.5rem; }
.input-with-button input { flex: 1; }
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `main.py` | Add `list_files` handler with `app.get("/api/files", list_files)` |
| `views.py` | Add file picker signals, modal HTML, Browse button |
| `style.css` | Add modal styles |

---

## Testing Checklist

- [ ] Hub starts with WORKSPACE_BASE environment variable
- [ ] `/api/files` returns directory listing
- [ ] `/api/files?path=subdir` navigates into subdirectories
- [ ] Directory traversal attacks blocked (`../`)
- [ ] Browse button opens file picker
- [ ] Clicking directory navigates into it
- [ ] Up button navigates to parent
- [ ] Clicking file sets targetPath and closes picker
- [ ] Selected path sent to hub on graph execution

---

## Key Stario/Datastar Patterns Used

| Pattern | Used For |
|---------|----------|
| `app.get()` | Fetching data (not POST) |
| `c.req.query.get()` | Reading query params |
| `w.patch(Div(...))` | Replacing HTML fragment in DOM |
| `w.sync({...})` | Updating reactive signals |
| `data.show()` | Conditional visibility |
| `data-on-click` | Event handlers |
| `at.get()` | Server requests from client |
