# Semantic Node Identity — Full Implementation Plan

## Goal

Replace positional hash-based node identity with deterministic semantic identity everywhere. Remove source mutation, old_nodes parameter, and random ID generation. Unify source hash. Result: a single, clean identity model across the entire codebase.

## Design Decision

**All node IDs everywhere become `sha256(file_path:node_type:full_name)[:16]`.**

No random `rm_*` IDs. No positional `sha256(path:name:start:end)`. One deterministic function, used by core discovery, LSP watcher, reconciler, and spawn_child. Same inputs always produce the same ID. Identity survives restarts, line shifts, and non-semantic edits.

---

## Proposed Changes

### Component 1: Core Identity

#### [MODIFY] [discovery.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py)

**Change [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) signature and implementation (line 77-80):**

```diff
-def compute_node_id(file_path: str, name: str, start_line: int, end_line: int) -> str:
-    """Compute deterministic node ID using SHA256."""
-    content = f"{file_path}:{name}:{start_line}:{end_line}"
-    return hashlib.sha256(content.encode()).hexdigest()[:16]
+def compute_node_id(file_path: str, node_type: str, full_name: str) -> str:
+    """Compute deterministic node ID from semantic key.
+
+    Identity is based on (file_path, node_type, full_name) — not position.
+    Same inputs always produce the same ID across restarts and line shifts.
+    """
+    content = f"{file_path}:{node_type}:{full_name}"
+    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

**Add a unified [compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) function (new, near line 80):**

```python
def compute_source_hash(text: str) -> str:
    """Compute SHA256-based hash of source text. Single source of truth."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]
```

This replaces:
- MD5 in `watcher.py:68` (`hashlib.md5(cst.text.encode("utf-8")).hexdigest()`)
- SHA256 in `reconciler.py:40` (`hashlib.sha256(text.encode()).hexdigest()[:16]`)
- SHA256 in `spawn_child.py:31` (`hashlib.sha256(source.encode()).hexdigest()[:16]`)

**Update all call sites in [_parse_file](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#136-200) and [parse_content](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#421-499):**

The challenge: [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81) now needs [full_name](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py#73-95), but [full_name](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py#73-95) depends on parent relationships (computed by [_assign_parents](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#100-141) in the LSP path, or just `f"{stem}.{name}"` in core). Currently, [_parse_file](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#136-200) sets [full_name](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py#73-95) to a basic qualified path. Need to confirm these call sites already compute [full_name](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py#73-95) before calling [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81).

- Line 178: [_parse_file](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#136-200) — currently passes [(str(file_path), name, start_point+1, end_point+1)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398). Change to [(str(file_path), node_type, full_name)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398). The [full_name](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py#73-95) is already computed at line ~174 as the capture-based name. For non-method nodes this is just the name; for methods inside classes it's the dot-separated path.
- Line 242: [_postprocess_markdown](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#202-256) — passes [(str(file_path), name, 1, line_count)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398). Change to [(str(file_path), "note", full_name)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398).
- Line 316: [_create_file_node](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#304-327) — passes [(str(file_path), file_path.name, 1, line_count)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398). Change to [(str(file_path), "file", file_path.name)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398).
- Line 477: [parse_content](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#421-499) — same pattern as line 178.
- Line 507: [_create_file_node_from_content](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#501-518) — passes [(file_path, path_obj.name, 1, line_count)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398). Change to [(file_path, "file", path_obj.name)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398).

**Export [compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33)** via `__all__`.

---

### Component 2: LSP Watcher — Simplify to Pure Conversion

#### [MODIFY] [watcher.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py)

This file changes dramatically. The watcher becomes a stateless converter from CSTNode → dict. No ID assignment, no old_nodes lookup, no source mutation.

**Remove imports (line 10-17):**
```diff
-import hashlib
-import re
-from remora.lsp.models import generate_id
+from remora.core.discovery import compute_source_hash
```

**Rename and simplify [parse_and_inject_ids](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#26-34) → [parse](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#410-419) (lines 26-33):**
```diff
-def parse_and_inject_ids(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[dict]:
-    """Parse text and return list of node dicts for the LSP path.
-
-    Delegates to ``core.discovery.parse_content()`` for tree-sitter parsing,
-    then converts CSTNode objects to dicts and assigns stable IDs.
-    """
-    cst_nodes = parse_content(uri, text)
-    return self._convert_nodes(uri, text, cst_nodes, old_nodes)
+def parse(self, uri: str, text: str) -> list[dict]:
+    """Parse text and return list of node dicts for the LSP path.
+
+    Delegates to ``core.discovery.parse_content()`` for tree-sitter parsing,
+    then converts CSTNode objects to dicts. Node IDs are deterministic
+    from the parse output — no state or prior nodes needed.
+    """
+    cst_nodes = parse_content(uri, text)
+    return self._convert_nodes(uri, text, cst_nodes)
```

**Simplify [_convert_nodes](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#35-99) (lines 35-98):**

Remove `old_nodes` parameter. Remove `old_by_key` dict. Remove [generate_id()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/models.py#25-28) call. Node IDs come directly from `cst.node_id` (which [parse_content](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#421-499) already computes via the new deterministic [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81)). Replace MD5 source hash with [compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33).

```diff
 def _convert_nodes(
     self,
     uri: str,
     text: str,
     cst_nodes: list[CSTNode],
-    old_nodes: list[dict] | None = None,
 ) -> list[dict]:
     """Convert CSTNode list to LSP-path dicts with parent_id and stable IDs."""
-    old_by_key = {(n["name"], n["node_type"]): n for n in (old_nodes or [])}
     stem = Path(uri).stem
     # ... (dedup logic stays) ...
     for cst in filtered:
         # ...
-        source_hash = hashlib.md5(cst.text.encode("utf-8")).hexdigest()
+        source_hash = compute_source_hash(cst.text)
-        key = (name, node_type)
-        if key in old_by_key:
-            node_id = old_by_key[key]["node_id"]
-            del old_by_key[key]
-        else:
-            node_id = generate_id()
+        node_id = cst.node_id  # deterministic from parse_content
```

**Delete [inject_ids](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) function entirely (lines 143-160).** 18 lines removed.

---

### Component 3: LSP Document Handlers

#### [MODIFY] [documents.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py)

**Remove import (line 10):**
```diff
-from remora.lsp.watcher import inject_ids
```

**Simplify [did_open](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#13-89) (lines 13-88):**

Remove `old_agents` → `old_dicts` construction. Call `server.watcher.parse(uri, text)` instead of [parse_and_inject_ids(uri, text, old_dicts)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#26-34).

```diff
-old_agents = await server.event_store.list_nodes(file_path=uri) if server.event_store else []
-old_dicts = [{"name": a.name, "node_type": a.node_type, "node_id": a.node_id} for a in old_agents]
-new_dicts = server.watcher.parse_and_inject_ids(uri, text, old_dicts)
+new_dicts = server.watcher.parse(uri, text)
```

Orphan detection stays in the handler (the caller), which is where it belongs:

```python
if server.event_store:
    old_agents = await server.event_store.list_nodes(file_path=uri)
    old_ids = {a.node_id for a in old_agents}
    new_ids = {nd["node_id"] for nd in new_dicts}
    for orphan_id in old_ids - new_ids:
        await server.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))
```

**Extract shared `_emit_node_events` helper** to deduplicate the identical NodeDiscoveredEvent construction blocks in [did_open](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#13-89) and [did_save](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#110-181) (~25 LOC each → one ~15 LOC function):

```python
async def _emit_node_events(uri: str, new_dicts: list[dict]) -> None:
    """Emit NodeDiscovered/NodeRemoved events for a file's parse results."""
    if not server.event_store:
        return
    old_agents = await server.event_store.list_nodes(file_path=uri)
    old_ids = {a.node_id for a in old_agents}
    new_ids = {nd["node_id"] for nd in new_dicts}
    for orphan_id in old_ids - new_ids:
        await server.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))
    for nd in new_dicts:
        event = NodeDiscoveredEvent(
            node_id=nd["node_id"], node_type=nd["node_type"],
            name=nd["name"], full_name=nd["full_name"],
            file_path=nd["file_path"], start_line=nd["start_line"],
            end_line=nd["end_line"], source_code=nd["source_code"],
            source_hash=nd["source_hash"], parent_id=nd["parent_id"],
            start_byte=nd.get("start_byte", 0), end_byte=nd.get("end_byte", 0),
        )
        await server.event_store.append("nodes", event)
```

**Simplify [did_save](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/handlers/documents.py#110-181) (lines 110-180):**

- Remove `_injecting` early-return guard (lines 116-118)
- Remove `old_dicts` construction
- Call `server.watcher.parse(uri, text)` 
- Call shared `_emit_node_events(uri, new_dicts)`
- Remove [inject_ids](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) call block (lines 170-173)
- Remove `server._injecting.add(uri)` line

---

### Component 4: LSP Server

#### [MODIFY] [server.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py)

**Remove `_injecting` from [__init__](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#25-45) (line 39):**
```diff
-self._injecting: set[str] = set()
```

**Simplify [_do_reparse](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#78-118) (lines 78-117):**

Remove `old_dicts` construction and `old_nodes` parameter from watcher call:

```diff
-old_agents = await self.event_store.list_nodes(file_path=uri) if self.event_store else []
-old_dicts = [{"name": a.name, "node_type": a.node_type, "node_id": a.node_id} for a in old_agents]
-new_dicts = self.watcher.parse_and_inject_ids(uri, text, old_dicts)
+new_dicts = self.watcher.parse(uri, text)
```

Orphan detection and event emission stays in [_do_reparse](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/server.py#78-118) as before, but is cleaner (the `old_agents` query is only needed for diffing, not for ID assignment):

```python
if self.event_store:
    old_agents = await self.event_store.list_nodes(file_path=uri)
    old_ids = {a.node_id for a in old_agents}
    new_ids = {nd["node_id"] for nd in new_dicts}
    for orphan_id in old_ids - new_ids:
        await self.event_store.append("nodes", NodeRemovedEvent(node_id=orphan_id))
    # ... emit NodeDiscoveredEvent for each nd ...
```

---

### Component 5: Background Scanner

#### [MODIFY] [__main__.py](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py)

**Simplify [_background_scan](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#121-372) (lines 247-266):**

Remove `old_nodes` construction. Call `server.watcher.parse(uri, text)`. Move orphan detection to after parse (diff old_ids from EventStore vs new_ids from parse).

```diff
-old_nodes = []
-if server.event_store:
-    existing = await server.event_store.list_nodes(file_path=uri)
-    old_nodes = [
-        {
-            "node_id": n.node_id, "name": n.name, "node_type": n.node_type,
-            "start_line": n.start_line, "end_line": n.end_line,
-            "source_hash": n.source_hash,
-        }
-        for n in existing
-    ]
-nodes = await asyncio.to_thread(server.watcher.parse_and_inject_ids, uri, text, old_nodes)
+nodes = await asyncio.to_thread(server.watcher.parse, uri, text)
```

For orphan detection (line 271):
```diff
-old_ids = {n["node_id"] for n in old_nodes}
+old_agents = await server.event_store.list_nodes(file_path=uri) if server.event_store else []
+old_ids = {a.node_id for a in old_agents}
```

---

### Component 6: Reconciler & Spawn Child

#### [MODIFY] [reconciler.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/reconciler.py)

**Replace local [_compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) (line 40) with import from discovery:**
```diff
+from remora.core.discovery import compute_source_hash
-def _compute_source_hash(text: str) -> str:
-    """Compute a hash of the source code text."""
-    return hashlib.sha256(text.encode()).hexdigest()[:16]
```

Update all 3 call sites (lines 94, 134, 150) from [_compute_source_hash(...)](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) → [compute_source_hash(...)](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33).

No other changes needed — the reconciler already diffs by [node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81), and those IDs are now deterministic from the semantic key. Same file parsed twice = same IDs = no churn. This is the "free" fix for restart reconciliation described in the recommendation.

#### [MODIFY] [spawn_child.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py)

**Replace both local functions with imports (lines 31-37):**
```diff
+from remora.core.discovery import compute_node_id, compute_source_hash
-def _compute_source_hash(source: str) -> str:
-    return hashlib.sha256(source.encode()).hexdigest()[:16]
-
-def _compute_node_id(file_path: str, name: str, start_line: int, end_line: int) -> str:
-    content = f"{file_path}:{name}:{start_line}:{end_line}"
-    return hashlib.sha256(content.encode()).hexdigest()[:16]
```

Update call site (line 112) to use new signature: [compute_node_id(file_path, node_type, full_name)](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81).

---

### Component 7: Exports

#### [MODIFY] [core/__init__.py](file:///home/andrew/Documents/Projects/remora/src/remora/core/__init__.py)

Add [compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) to exports alongside [compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#77-81).

#### [MODIFY] [__init__.py](file:///home/andrew/Documents/Projects/remora/src/remora/__init__.py)

Add [compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) to top-level exports.

---

### Component 8: Tests

#### [MODIFY] [test_discovery.py](file:///home/andrew/Documents/Projects/remora/tests/test_discovery.py)

Update [TestComputeNodeId](file:///home/andrew/Documents/Projects/remora/tests/test_discovery.py#17-31) (lines 17-30) to use new [(file_path, node_type, full_name)](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/__main__.py#61-398) signature:

```diff
-id1 = compute_node_id("test.py", "hello", 1, 2)
-id2 = compute_node_id("test.py", "hello", 1, 2)
+id1 = compute_node_id("test.py", "function", "test.hello")
+id2 = compute_node_id("test.py", "function", "test.hello")
```

#### [MODIFY] [test_lsp_watcher.py](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py)

- Change all `watcher.parse_and_inject_ids(...)` calls to `watcher.parse(...)` (drop `old_nodes` arg).
- Update [test_parse_preserves_ids](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_watcher.py#32-40) — since IDs are now deterministic from parse, re-parsing the same content produces the same IDs without needing `old_nodes`:

```diff
-nodes1 = watcher.parse_and_inject_ids("file:///t.py", text)
-old_nodes = [{"name": n["name"], "node_type": n["node_type"], "node_id": n["node_id"]} for n in nodes1]
-nodes2 = watcher.parse_and_inject_ids("file:///t.py", text, old_nodes)
+nodes1 = watcher.parse("file:///t.py", text)
+nodes2 = watcher.parse("file:///t.py", text)
 assert nodes1[0]["node_id"] == nodes2[0]["node_id"]
```

#### [MODIFY] [test_scaffold_watcher.py](file:///home/andrew/Documents/Projects/remora/tests/unit/test_scaffold_watcher.py)

- Change all `watcher.parse_and_inject_ids(...)` calls to `watcher.parse(...)`.

#### [MODIFY] [test_lsp_background_scan_manifest.py](file:///home/andrew/Documents/Projects/remora/tests/unit/test_lsp_background_scan_manifest.py)

- Update mock [parse_and_inject_ids](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#26-34) stubs to match new [parse](file:///home/andrew/Documents/Projects/remora/src/remora/core/discovery.py#410-419) signature (remove `_old_nodes` param).

---

## Summary of Deletions

| What | Where | LOC |
|---|---|---:|
| [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) function | `watcher.py:143-160` | 18 |
| `_injecting` set init | `server.py:39` | 1 |
| `_injecting` guard block | `documents.py:116-118` | 3 |
| `_injecting.add()` + [inject_ids()](file:///home/andrew/Documents/Projects/remora/src/remora/lsp/watcher.py#143-161) call | `documents.py:170-173` | 4 |
| `old_by_key` logic | `watcher.py:43,70-76` | 7 |
| `old_dicts` construction | `documents.py:22,127`; `server.py:85` | 6 |
| `old_nodes` construction | `__main__.py:252-265` | 14 |
| [_compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) (local) | `reconciler.py:40-42` | 3 |
| [_compute_source_hash](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#31-33) (local) | `spawn_child.py:31-32` | 2 |
| [_compute_node_id](file:///home/andrew/Documents/Projects/remora/src/remora/core/tools/spawn_child.py#35-38) (local) | `spawn_child.py:35-37` | 3 |
| `import re` | `watcher.py:11` | 1 |
| `import generate_id` | `watcher.py:17` | 1 |
| **Total** | | **~63** |

---

## Verification Plan

### Automated Tests

```bash
# Full suite (excluding known failures)
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# Targeted
devenv shell -- python -m pytest tests/test_discovery.py -v
devenv shell -- python -m pytest tests/unit/test_lsp_watcher.py -v
devenv shell -- python -m pytest tests/unit/test_scaffold_watcher.py -v
devenv shell -- python -m pytest tests/unit/test_lsp_background_scan_manifest.py -v
```

### Key Behaviors to Verify

1. **Determinism** — Parse same file twice → identical IDs
2. **Line-shift stability** — Add blank lines above a function → same ID
3. **No source mutation** — Save [.py](file:///home/andrew/Documents/Projects/remora/src/remora/__main__.py) file → no `# rm_` comments written
4. **Orphan detection** — Remove a function → [NodeRemovedEvent](file:///home/andrew/Documents/Projects/remora/src/remora/core/events.py#197-202) for that function
5. **Source hash consistency** — All paths use `sha256[:16]`
6. **Rename detection** — Rename function → new ID (expected — we don't track renames in v1; body-hash fallback is a future enhancement)
