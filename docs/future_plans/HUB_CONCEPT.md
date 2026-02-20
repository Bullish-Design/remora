# Concept Review: Node State Hub

## Executive Summary

After studying the concept document and the current Remora codebase, this review provides a detailed analysis of how the hub concept aligns with the existing architecture and what gaps need to be addressed.

**Key Finding**: 
The Hub concept is architecturally sound but represents a larger lift - it requires a new daemon process, file watching, persistent storage, and integration hooks.

---

## Part 2: Node State Hub Concept Review

### 2.1 Current State

Remora has **no background daemon** or persistent state cache. Each analyzer run:
1. Discovers nodes via AST parsing
2. Runs agents against nodes
3. Produces results
4. Terminates

There is no:
- File watching
- Persistent KV store
- Pre-computed metadata cache
- Background workers

### 2.2 Hub Architecture Deep Dive

#### 2.2.1 Component Overview

```
┌───────────────────────────────────────────────────────────────┐
│                        Hub Daemon                             │
│                                                               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Watcher    │───►│ Rules Engine │───►│  Update Workers  │ │
│  │  (watchfiles)│    │ (if/then)    │    │  (.pym scripts)  │ │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘ │
│                                                   │           │
│                                           ┌───────▼────────┐  │
│                                           │  Node State KV │  │
│                                           │   (SQLite)     │  │
│                                           └───────┬────────┘  │
│                                                   │           │
│  ┌────────────────────────────────────────────────▼────────┐  │
│  │                    IPC Server                           │  │
│  │              (Unix Socket / HTTP)                       │  │
│  └─────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
                              │
                              │ HubClient.get_context()
                              ▼
                    ┌─────────────────────┐
                    │   Remora Analyzer   │
                    │   (ContextManager)  │
                    └─────────────────────┘
```

#### 2.2.2 IPC Options Analysis

| Option | Latency | Portability | Complexity | Concurrent Access |
|--------|---------|-------------|------------|-------------------|
| **Unix Socket** | ~0.1ms | Linux/macOS only | Low | Good (built-in) |
| **HTTP REST** | ~1-5ms | Cross-platform | Medium | Excellent |
| **Shared SQLite** | ~1ms | Cross-platform | Low | Poor (locking) |
| **Memory-mapped file** | ~0.01ms | Platform-specific | High | Complex |

**Recommendation**: **Unix Socket** as primary, with HTTP fallback for Windows.

```python
# Hub Server
class HubServer:
    def __init__(self, socket_path: Path = Path("/tmp/remora-hub.sock")):
        self.socket_path = socket_path
        self.kv = NodeStateKV()

    async def handle_request(self, request: bytes) -> bytes:
        msg = json.loads(request)
        if msg["type"] == "get_context":
            nodes = msg["nodes"]
            result = {n: self.kv.get(n) for n in nodes}
            return json.dumps(result).encode()
        elif msg["type"] == "health":
            return b'{"status": "ok"}'

# Hub Client (used by Remora)
class HubClient:
    def __init__(self, socket_path: Path = Path("/tmp/remora-hub.sock")):
        self.socket_path = socket_path
        self._connected = False

    async def get_context(self, nodes: list[str]) -> dict[str, NodeState]:
        if not self._connected:
            return {}  # Graceful degradation if Hub not running
        # ... socket communication ...
```

#### 2.2.3 Storage Architecture

**SQLite Schema** (via fsdantic):

```sql
-- Core node state table
CREATE TABLE node_state (
    key TEXT PRIMARY KEY,           -- "node:{file_path}:{node_name}"
    file_path TEXT NOT NULL,
    node_name TEXT NOT NULL,
    node_type TEXT NOT NULL,        -- "function", "class", "module"
    source_hash TEXT NOT NULL,
    state_json TEXT NOT NULL,       -- Full NodeState as JSON
    last_updated REAL NOT NULL,     -- Unix timestamp
    INDEX idx_file_path (file_path),
    INDEX idx_last_updated (last_updated)
);

-- File-level tracking for quick invalidation
CREATE TABLE file_index (
    file_path TEXT PRIMARY KEY,
    file_hash TEXT NOT NULL,
    node_count INTEGER NOT NULL,
    last_scanned REAL NOT NULL
);

-- Dependency graph for cascade updates
CREATE TABLE dependencies (
    source_key TEXT NOT NULL,       -- Node that imports
    target_key TEXT NOT NULL,       -- Node being imported
    dependency_type TEXT NOT NULL,  -- "import", "call", "inherit"
    PRIMARY KEY (source_key, target_key)
);
```

**Why SQLite?**
- Already have fsdantic as a dependency
- Single-file database, easy to locate/backup
- Good read performance for this use case
- WAL mode handles concurrent reads well

**Concurrent Access Strategy**:
- Hub daemon owns write access
- Remora (HubClient) has read-only access
- Use WAL mode for non-blocking reads
- If Hub is not running, Remora continues without context

#### 2.2.4 Daemon Lifecycle

```python
# CLI entry point
@click.command()
@click.option("--root", type=Path, help="Project root to watch")
@click.option("--socket", type=Path, default="/tmp/remora-hub.sock")
@click.option("--db", type=Path, default="~/.cache/remora/hub.db")
def hub_daemon(root: Path, socket: Path, db: Path):
    """Start the Remora Hub daemon."""
    hub = HubDaemon(root=root, socket_path=socket, db_path=db)
    asyncio.run(hub.run())

class HubDaemon:
    async def run(self):
        # 1. Cold start: index existing files
        await self._cold_start_index()

        # 2. Start IPC server
        server_task = asyncio.create_task(self._run_server())

        # 3. Start file watcher
        watcher_task = asyncio.create_task(self._run_watcher())

        # 4. Run until shutdown
        await asyncio.gather(server_task, watcher_task)

    async def _cold_start_index(self):
        """Index all Python files on startup."""
        for py_file in self.root.rglob("*.py"):
            file_hash = hash_file(py_file)
            if self._file_changed(py_file, file_hash):
                await self._index_file(py_file)

    async def _run_watcher(self):
        """Watch for file changes and trigger updates."""
        async for changes in watchfiles.awatch(self.root):
            for change_type, path in changes:
                if path.endswith(".py"):
                    await self._handle_file_change(change_type, Path(path))
```

#### 2.2.5 Rules Engine

Deterministic, no LLM involved:

```python
class RulesEngine:
    """Decides what to recompute when a file changes."""

    def get_update_actions(
        self,
        change_type: str,
        file_path: Path,
        old_state: dict[str, NodeState] | None
    ) -> list[UpdateAction]:
        actions = []

        if change_type == "deleted":
            # Remove all nodes from this file
            actions.append(DeleteFileNodes(file_path))
            return actions

        # Always: extract new state
        actions.append(ExtractSignatures(file_path))
        actions.append(ScanImports(file_path))

        if old_state:
            # Diff-based updates
            for node_key, old_node in old_state.items():
                if self._signature_changed(node_key, old_node):
                    actions.append(FindCallers(node_key))
                if self._is_new_function(node_key, old_state):
                    actions.append(FindTests(node_key))

        return actions

class UpdateAction(ABC):
    """Base class for update actions."""
    @abstractmethod
    async def execute(self, executor: GrailExecutor) -> dict[str, Any]:
        ...

class ExtractSignatures(UpdateAction):
    def __init__(self, file_path: Path):
        self.file_path = file_path

    async def execute(self, executor: GrailExecutor) -> dict[str, Any]:
        return await executor.run_script(
            "hub/extract_signatures.pym",
            inputs={"file_path": str(self.file_path)}
        )
```

#### 2.2.6 State Invalidation & Cleanup

```python
class NodeStateKV:
    def invalidate_file(self, file_path: str) -> list[str]:
        """Remove all nodes for a file, return deleted keys."""
        deleted = []
        with self.conn:
            cursor = self.conn.execute(
                "SELECT key FROM node_state WHERE file_path = ?",
                (file_path,)
            )
            deleted = [row[0] for row in cursor.fetchall()]

            self.conn.execute(
                "DELETE FROM node_state WHERE file_path = ?",
                (file_path,)
            )
            self.conn.execute(
                "DELETE FROM dependencies WHERE source_key LIKE ?",
                (f"node:{file_path}:%",)
            )
        return deleted

    def gc_orphans(self, max_age_hours: int = 24) -> int:
        """Remove stale entries that haven't been updated."""
        cutoff = time.time() - (max_age_hours * 3600)
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM node_state WHERE last_updated < ?",
                (cutoff,)
            )
            return cursor.rowcount
```

### 2.3 Key Design Questions (Answered)

**Q1: What is a "Node"?**
- Functions, classes, and modules
- Key format: `node:{file_path}:{node_name}` or `node:{file_path}:__module__`
- Granularity is per-callable for precision

**Q2: How does the Hub communicate with Remora?**
- Unix socket (primary) for low latency
- HTTP REST (fallback) for portability
- Graceful degradation if Hub not running

**Q3: What happens on Hub startup?**
- Cold start indexes all Python files
- Parallelized across available cores
- Expected: ~1-5 seconds for small projects, ~30-60 seconds for large ones
- Indexes are persisted, so restarts are fast after first run

**Q4: Hub state invalidation**
- File deletion removes all nodes from that file
- Rename detection via content hash (same hash = rename, not delete+create)
- GC process removes orphaned entries older than 24h

### 2.4 NodeState Schema (Finalized)

```python
class NodeState(BaseModel):
    """State for a single code node."""

    # Identity
    key: str                           # "node:{file_path}:{node_name}"
    file_path: str
    node_name: str
    node_type: Literal["function", "class", "module"]

    # Content hash (for change detection)
    source_hash: str                   # SHA256 of node source
    file_hash: str                     # SHA256 of entire file

    # Static analysis results
    signature: str | None              # "def foo(x: int) -> str"
    docstring: str | None              # First line of docstring
    imports: list[str]                 # ["os", "typing.Optional"]
    decorators: list[str]              # ["@staticmethod", "@cached"]

    # Cross-file analysis (expensive, computed lazily)
    callers: list[str] | None = None   # ["bar.py:process"]
    callees: list[str] | None = None   # ["os.path.join"]

    # Test discovery
    related_tests: list[str] | None = None

    # Quality metrics
    line_count: int | None = None
    complexity: int | None = None      # Cyclomatic complexity

    # Flags
    docstring_outdated: bool = False
    has_type_hints: bool = True

    # Freshness
    last_updated: datetime
    update_source: Literal["file_change", "dependency_change", "manual"]
```

### 2.5 Grail Tool Candidates

The concept mentions these scripts. Assessment of what exists vs. needs building:

| Script | Exists? | Notes |
|--------|---------|-------|
| `extract_signature.pym` | Partial | Can use Python's `ast` module or `inspect` |
| `scan_imports.pym` | No | AST-based import extraction |
| `find_callers.pym` | No | Requires cross-file analysis (harder) |
| `find_tests.pym` | Partial | Pattern matching + pytest collection |
| `compute_complexity.pym` | No | Can wrap `radon` or implement |

### 2.6 Dependency on Two-Track

The Hub feeds into Two-Track via the "Pull Hook":

```
Hub ──── Pull Hook ────► ContextManager ──► DecisionPacket.hub_context
```

This means **Two-Track should be implemented first**, establishing:
- The `DecisionPacket` structure
- The `ContextManager` component
- The Pull Hook interface

Then the Hub can be developed to fulfill that interface.

---

## Part 3: Implementation Recommendations

### 3.1 Recommended Order

1. **Two-Track Memory (Phase 1)**: High value, lower complexity
   - Builds on existing event infrastructure
   - Immediately improves FunctionGemma's context quality
   - Can be done without Hub

2. **Node State Hub (Phase 2)**: Higher complexity, depends on Phase 1
   - Requires new daemon architecture
   - Provides context for Pull Hook after it exists

### 3.2 Two-Track Implementation Steps

1. **Define DecisionPacket model** (`remora/context.py`)
2. **Create ContextManager** that:
   - Initializes DecisionPacket from initial context
   - Exposes `apply_event(event)` method
   - Provides `get_prompt_context()` for runner
3. **Modify tools to return summaries** (tool-side or hybrid approach)
4. **Update FunctionGemmaRunner** to:
   - Use ContextManager instead of raw messages list
   - Inject DecisionPacket into prompt
5. **Add Pull Hook stub** (initially no-op, ready for Hub)

### 3.3 Hub Implementation Steps (Future)

1. **Define NodeState model** and KV interface
2. **Implement Watcher** (file system monitoring)
3. **Build Rules Engine** (deterministic update logic)
4. **Create Update Scripts** (`.pym` for analysis)
5. **Implement Hub daemon** (CLI entry point, IPC)
6. **Implement HubClient** (for Remora integration)
7. **Wire Pull Hook** in ContextManager

---

## Part 4: Design Decisions (Confirmed)

Based on our discussion, the following decisions are locked in:

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Message History** | Keep both `messages[]` and `DecisionPacket` | Safer transition; messages for debugging, DecisionPacket for model |
| **Summary Strategy** | Tool-side primary, pluggable summarizer fallback | Tools control quality, but architecture allows overrides |
| **Hub Lifecycle** | Separate daemon process | Independent operation, survives Remora restarts |
| **Hub Storage** | SQLite via fsdantic | Already a dependency, good for this use case |
| **Hub IPC** | Unix socket primary, HTTP fallback | Low latency where available, portable fallback |

### 4.1 Dual-Track Architecture (messages[] + DecisionPacket)

Since we're keeping both, here's how they coexist:

```python
class FunctionGemmaRunner:
    def __init__(self, ...):
        # Long Track (for debugging, existing behavior)
        self.messages: list[ChatCompletionMessageParam] = []

        # Short Track (for model, new)
        self.context_manager = ContextManager(initial_context)

    async def run(self) -> AgentResult:
        while self.turn_count < self.max_turns:
            # Build prompt from DecisionPacket (not messages)
            prompt_context = self.context_manager.get_prompt_context()
            system_prompt = self._build_system_prompt(prompt_context)

            # Call model with clean context
            response = await self._call_model(system_prompt)

            # Update BOTH tracks
            self.messages.append(...)  # Long Track (full message)
            self.context_manager.apply_event(event)  # Short Track (distilled)

            # Emit to event stream (for JSONL logging)
            self._emit_event(event)
```

**Key insight**: The model sees `DecisionPacket`, but developers can inspect `messages[]` during debugging without reconstructing from the event stream.

### 4.2 Remaining Open Questions

1. **Hub as Optional**: Should Remora work without Hub?
   - Answer: Yes, Pull Hook returns empty dict if Hub not running
   - Zero impact on core functionality

