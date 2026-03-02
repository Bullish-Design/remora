# Zoom-to-Cursor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a toggleable "Follow Cursor" mode to the web graph view that smoothly zooms/pans to keep the focused node and its connected neighborhood centered in the viewport.

**Architecture:** Server computes a focus bounding box (focused node + edge-connected neighbors) during layout and emits it as data attributes on `#graph-content`. Client JS reads these after each SSE patch and, when follow mode is active, smoothly CSS-transitions the viewport transform to center/fit that box. A toggle button in the header switches between manual overview and follow mode.

**Tech Stack:** Python (layout.py, render.py), vanilla JS (CSS transforms), Datastar SSE patching.

---

### Task 1: Compute focus bounding box in layout.py

**Files:**
- Modify: `remora_demo/web/layout.py` (add `FocusBBox` dataclass, add `focus_bbox` to `LayoutResult`, compute it in `compute_layout`)

**Step 1: Write the failing test**

Create `tests/unit/test_web_layout.py`:

```python
"""Tests for the web graph layout focus bounding box."""
from remora_demo.web.layout import compute_layout, LayoutResult


def _make_node(nid, node_type, file_path, parent_id=None, start_line=1, end_line=10):
    return {
        "remora_id": nid,
        "node_type": node_type,
        "file_path": file_path,
        "name": nid,
        "parent_id": parent_id,
        "start_line": start_line,
        "end_line": end_line,
    }


def _make_edge(from_id, to_id, edge_type="calls"):
    return {"from_id": from_id, "to_id": to_id, "edge_type": edge_type}


class TestFocusBBox:
    def test_no_focus_returns_none(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        result = compute_layout(nodes, [], None)
        assert result.focus_bbox is None

    def test_focus_includes_focused_node(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        focus = {"file_path": "/a/b.py", "agent_id": "fn1"}
        result = compute_layout(nodes, [], focus)
        assert result.focus_bbox is not None
        # The focused node must be inside the bbox
        pos = result.positions["fn1"]
        assert result.focus_bbox.x <= pos.x
        assert result.focus_bbox.y <= pos.y
        assert result.focus_bbox.x + result.focus_bbox.w >= pos.x + pos.w
        assert result.focus_bbox.y + result.focus_bbox.h >= pos.y + pos.h

    def test_focus_includes_edge_neighbors(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
            _make_node("f2", "file", "/a/c.py"),
            _make_node("fn2", "function", "/a/c.py", parent_id="f2"),
        ]
        edges = [_make_edge("fn1", "fn2", "calls")]
        focus = {"file_path": "/a/b.py", "agent_id": "fn1"}
        result = compute_layout(nodes, edges, focus)
        bbox = result.focus_bbox
        assert bbox is not None
        # fn2 is a neighbor via edge, must be in bbox
        pos2 = result.positions.get("fn2")
        if pos2:  # fn2 may be visible as file-only, not positioned individually
            assert bbox.x <= pos2.x
            assert bbox.y <= pos2.y

    def test_focus_with_no_matching_node_returns_none(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        focus = {"file_path": "/a/b.py", "agent_id": "nonexistent"}
        result = compute_layout(nodes, [], focus)
        # agent_id not found, falls back to file_path focus
        # focus_bbox should still exist since we have a focused file
        assert result.focus_bbox is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_web_layout.py -v`
Expected: FAIL with `AttributeError: 'LayoutResult' has no attribute 'focus_bbox'`

**Step 3: Write minimal implementation**

In `remora_demo/web/layout.py`:

1. Add `FocusBBox` dataclass after `CollapsedDir`:

```python
@dataclass
class FocusBBox:
    """Bounding box around the focused node and its edge-connected neighbors."""
    x: float
    y: float
    w: float
    h: float
```

2. Add `focus_bbox: FocusBBox | None = None` field to `LayoutResult`.

3. At the end of `compute_layout()`, after computing layout but before return, compute the bounding box:

```python
    # Compute focus bounding box (focused node + edge-connected neighbors)
    if focused_file and result.positions:
        focus_node_ids: set[str] = set()
        # Add the focused agent if positioned
        if cursor_focus:
            agent_id = cursor_focus.get("agent_id")
            if agent_id and agent_id in result.positions:
                focus_node_ids.add(agent_id)
        # Add all positioned nodes in the focused file
        for n in nodes:
            nid = n.get("remora_id") or n.get("id", "")
            fp = _normalize_path(n.get("file_path", ""))
            if fp == focused_file and nid in result.positions:
                focus_node_ids.add(nid)
        # Add edge-connected neighbors (1 hop)
        for edge in edges:
            fid = edge.get("from_id", "")
            tid = edge.get("to_id", "")
            if fid in focus_node_ids and tid in result.positions:
                focus_node_ids.add(tid)
            if tid in focus_node_ids and fid in result.positions:
                focus_node_ids.add(fid)
        # Compute bounding box
        if focus_node_ids:
            min_x = min_y = float("inf")
            max_x = max_y = float("-inf")
            for nid in focus_node_ids:
                pos = result.positions[nid]
                min_x = min(min_x, pos.x)
                min_y = min(min_y, pos.y)
                max_x = max(max_x, pos.x + pos.w)
                max_y = max(max_y, pos.y + pos.h)
            pad = 40.0  # breathing room around the neighborhood
            result.focus_bbox = FocusBBox(
                x=min_x - pad,
                y=min_y - pad,
                w=(max_x - min_x) + pad * 2,
                h=(max_y - min_y) + pad * 2,
            )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_web_layout.py -v`
Expected: all 4 tests PASS

**Step 5: Commit**

```bash
git add remora_demo/web/layout.py tests/unit/test_web_layout.py
git commit -m "feat(web): compute focus bounding box for zoom-to-cursor"
```

---

### Task 2: Emit focus bbox as data attributes in render.py

**Files:**
- Modify: `remora_demo/web/render.py` (add data attributes to `#graph-content` div)

**Step 1: Write the failing test**

Add to `tests/unit/test_web_layout.py`:

```python
from remora_demo.web.render import render_graph
from remora_demo.web.state import GraphSnapshot


class TestRenderFocusBBox:
    def test_render_includes_focus_data_attrs(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        snapshot = GraphSnapshot(
            nodes=nodes,
            edges=[],
            cursor_focus={"file_path": "/a/b.py", "agent_id": "fn1"},
        )
        html = render_graph(snapshot)
        assert 'data-focus-x="' in html
        assert 'data-focus-y="' in html
        assert 'data-focus-w="' in html
        assert 'data-focus-h="' in html

    def test_render_no_focus_no_data_attrs(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        snapshot = GraphSnapshot(nodes=nodes, edges=[], cursor_focus=None)
        html = render_graph(snapshot)
        assert 'data-focus-x' not in html
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_web_layout.py::TestRenderFocusBBox -v`
Expected: FAIL (no `data-focus-x` in the rendered HTML)

**Step 3: Write minimal implementation**

In `remora_demo/web/render.py`, in `render_graph()`, modify the opening `#graph-content` div to include focus bbox data attributes when available:

```python
    # Build data attributes for focus bbox (used by client zoom-to-cursor)
    focus_attrs = ""
    if layout.focus_bbox:
        fb = layout.focus_bbox
        focus_attrs = (
            f' data-focus-x="{fb.x:.1f}"'
            f' data-focus-y="{fb.y:.1f}"'
            f' data-focus-w="{fb.w:.1f}"'
            f' data-focus-h="{fb.h:.1f}"'
        )

    parts = [
        f'<div id="graph-content" style="position:relative;'
        f'width:{layout.total_width + 100}px;height:{layout.total_height + 100}px;"{focus_attrs}>'
    ]
```

Also add `FocusBBox` to the imports from layout.

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_web_layout.py -v`
Expected: all tests PASS

**Step 5: Commit**

```bash
git add remora_demo/web/render.py tests/unit/test_web_layout.py
git commit -m "feat(web): emit focus bbox as data attributes for client zoom"
```

---

### Task 3: Add Follow Cursor toggle button in render.py

**Files:**
- Modify: `remora_demo/web/render.py` (add button to header in `render_shell()`, add CSS)

**Step 1: Add toggle button to header**

In `render_shell()`, add a "Follow Cursor" toggle button next to the existing "Fit All" button:

```html
<button class="follow-btn" id="follow-btn" title="Toggle follow cursor mode">Follow Cursor</button>
```

**Step 2: Add CSS for the toggle button**

In `_css()`, add after `.fit-btn:hover`:

```css
.follow-btn {
    font-family: inherit;
    font-size: 11px;
    padding: 3px 10px;
    border: 1px solid var(--surface2);
    border-radius: 4px;
    background: var(--surface2);
    color: var(--text);
    cursor: pointer;
    letter-spacing: 0.3px;
    transition: background 0.15s, border-color 0.15s;
}

.follow-btn:hover {
    background: var(--overlay);
}

.follow-btn.active {
    background: var(--blue);
    color: var(--bg);
    border-color: var(--blue);
}
```

**Step 3: Verify syntax**

Run: `python -c "import ast; ast.parse(open('remora_demo/web/render.py').read()); print('OK')"`

**Step 4: Commit**

```bash
git add remora_demo/web/render.py
git commit -m "feat(web): add Follow Cursor toggle button to header"
```

---

### Task 4: Client-side follow-cursor zoom logic in _js()

**Files:**
- Modify: `remora_demo/web/render.py` (rewrite `_js()` to add follow mode)

**Step 1: Implement follow mode in JS**

Replace/extend `_js()` in `render.py`. The key additions:

1. A `followMode` boolean, toggled by clicking `#follow-btn`.
2. A `MutationObserver` that watches `#graph-content` for attribute changes (`data-focus-*`).
3. When `followMode` is true and focus data attributes exist, compute the transform to center/fit the focus bbox in the viewport, then apply with CSS transition.
4. Manual pan/zoom still works but does NOT disable follow mode (next SSE patch re-centers).
5. Add `transition: transform 0.3s ease` to `graph-container` when following.

```javascript
(function() {
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let followMode = false;
    const viewport = document.getElementById('graph-viewport');
    const container = document.getElementById('graph-container');
    const followBtn = document.getElementById('follow-btn');

    if (!viewport || !container) return;

    function applyTransform(animate) {
        if (animate) {
            container.style.transition = 'transform 0.3s ease';
        } else {
            container.style.transition = 'none';
        }
        container.style.transform =
            'translate(' + translateX + 'px, ' + translateY + 'px) scale(' + scale + ')';
    }

    function fitAll() {
        const content = document.getElementById('graph-content');
        if (!content) return;
        const vw = viewport.clientWidth;
        const vh = viewport.clientHeight;
        const cw = content.scrollWidth || 800;
        const ch = content.scrollHeight || 600;
        if (cw === 0 || ch === 0) return;
        const pad = 40;
        const sx = (vw - pad * 2) / cw;
        const sy = (vh - pad * 2) / ch;
        scale = Math.min(sx, sy, 1.5);
        scale = Math.max(scale, 0.1);
        translateX = (vw - cw * scale) / 2;
        translateY = (vh - ch * scale) / 2;
        applyTransform(true);
    }

    function zoomToFocus() {
        if (!followMode) return;
        const content = document.getElementById('graph-content');
        if (!content) return;
        const fx = parseFloat(content.dataset.focusX);
        const fy = parseFloat(content.dataset.focusY);
        const fw = parseFloat(content.dataset.focusW);
        const fh = parseFloat(content.dataset.focusH);
        if (isNaN(fx) || isNaN(fy) || isNaN(fw) || isNaN(fh)) return;
        if (fw <= 0 || fh <= 0) return;

        const vw = viewport.clientWidth;
        const vh = viewport.clientHeight;
        const pad = 60;

        const sx = (vw - pad * 2) / fw;
        const sy = (vh - pad * 2) / fh;
        scale = Math.min(sx, sy, 2.0);
        scale = Math.max(scale, 0.2);

        // Center the focus bbox in the viewport
        const centerX = fx + fw / 2;
        const centerY = fy + fh / 2;
        translateX = vw / 2 - centerX * scale;
        translateY = vh / 2 - centerY * scale;

        applyTransform(true);
    }

    // Toggle follow mode
    if (followBtn) {
        followBtn.addEventListener('click', function() {
            followMode = !followMode;
            followBtn.classList.toggle('active', followMode);
            if (followMode) {
                zoomToFocus();
            }
        });
    }

    // Observe graph-content for SSE patches (content replacement or attr changes)
    let fitted = false;
    const observer = new MutationObserver(function() {
        if (followMode) {
            zoomToFocus();
        } else if (!fitted) {
            fitted = true;
            setTimeout(fitAll, 50);
        }
    });
    observer.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-focus-x', 'data-focus-y', 'data-focus-w', 'data-focus-h'] });

    // Fit All button
    const fitBtn = document.getElementById('fit-all-btn');
    if (fitBtn) fitBtn.addEventListener('click', function() {
        followMode = false;
        if (followBtn) followBtn.classList.remove('active');
        fitAll();
    });

    // Zoom via scroll wheel
    viewport.addEventListener('wheel', function(e) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.05, Math.min(4, scale * delta));
        const rect = viewport.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        translateX = mx - (mx - translateX) * (newScale / scale);
        translateY = my - (my - translateY) * (newScale / scale);
        scale = newScale;
        applyTransform(false);
    }, { passive: false });

    // Pan via left-click drag on background
    let isPanning = false;
    let startX, startY;

    viewport.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        if (e.target.closest('.graph-node')) return;
        isPanning = true;
        startX = e.clientX - translateX;
        startY = e.clientY - translateY;
        e.preventDefault();
    });

    window.addEventListener('mousemove', function(e) {
        if (!isPanning) return;
        translateX = e.clientX - startX;
        translateY = e.clientY - startY;
        applyTransform(false);
    });

    window.addEventListener('mouseup', function() {
        isPanning = false;
    });
})();
```

**Step 2: Verify syntax and imports**

Run: `python -c "from remora_demo.web import create_app; app = create_app(); print('OK')"`

**Step 3: Commit**

```bash
git add remora_demo/web/render.py
git commit -m "feat(web): client-side follow cursor zoom with smooth transitions"
```

---

### Task 5: End-to-end manual verification

**Step 1: Start the web server**

```bash
python -m remora_demo.web --port 8420 --db .remora/indexer.db
```

**Step 2: Open browser at http://localhost:8420**

Verify:
- Graph renders with "Fit All" and "Follow Cursor" buttons in header
- Click "Follow Cursor" — button highlights blue
- Move cursor in neovim — graph smoothly pans/zooms to show focused node + neighbors
- Click "Fit All" — disables follow mode, zooms to fit all nodes
- Manual scroll-wheel zoom and drag-pan work in both modes
- In follow mode, next cursor move re-centers even after manual pan

**Step 3: Run all tests**

```bash
pytest tests/unit/test_web_layout.py -v
```

**Step 4: Final commit if any fixups needed**
