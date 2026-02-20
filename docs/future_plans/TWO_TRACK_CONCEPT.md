# Concept Review: Two-Track Memory & Node State Hub

## Executive Summary

After studying both concept documents and the current Remora codebase, this review provides a detailed analysis of how these concepts align with the existing architecture and what gaps need to be addressed.

**Key Finding**: The Two-Track Memory concept is well-aligned with Remora's current architecture - the "Long Track" essentially already exists via `JsonlEventEmitter`. The critical missing piece is the **Short Track (Decision Packet)** and the projection logic that distills events into clean, structured context for FunctionGemma.

The Hub concept is architecturally sound but represents a larger lift - it requires a new daemon process, file watching, persistent storage, and integration hooks.

---

## Part 1: Two-Track Memory Concept Review

### 1.1 What Exists Today

| Component | Current State | Location |
|-----------|--------------|----------|
| **Event Emission** | Complete | `remora/events.py` - `EventEmitter` protocol, `JsonlEventEmitter` |
| **Event Types** | Comprehensive | `EventName` enum: MODEL_REQUEST, MODEL_RESPONSE, TOOL_CALL, TOOL_RESULT, SUBMIT_RESULT, AGENT_ERROR |
| **Event Logging** | Active | Writes to `~/.cache/remora/events.jsonl` |
| **Conversation Logging** | Active | `LlmConversationLogger` creates human-readable transcripts |
| **Message History** | In-memory list | `FunctionGemmaRunner.messages` - full conversation sent to model |

### 1.2 Gap Analysis

| Two-Track Component | Current State | Gap |
|---------------------|--------------|-----|
| **Long Track (Event Stream)** | **EXISTS** | Already implemented via `JsonlEventEmitter`. Events are immutable, timestamped, and contain full payloads. |
| **Short Track (Decision Packet)** | **MISSING** | No `DecisionPacket` class exists. The model receives raw message history, not a distilled projection. |
| **Summary Delta** | **MISSING** | Tools return raw results. No mechanism to generate `summary_delta` alongside `raw_output`. |
| **Context Manager** | **MISSING** | No component that projects events → Decision Packet. The `LlmConversationLogger` does event → text, but not event → structured JSON. |
| **Hub Pull Hook** | **MISSING** | No integration point for external context injection. |

### 1.3 Critical Observations

**FunctionGemma's Needs**: The model requires **clean context**, not compressed context. This means:
- Tool results must be distilled to structured summaries
- The Decision Packet should be a well-defined JSON schema, not free-form text
- Raw outputs (full file contents, stack traces) stay in Long Track only

**Architecture Alignment**: The event sourcing pattern in the concept aligns well with Remora's existing `emit()` pattern. The change is:
- **Before**: Event → Log (fire and forget)
- **After**: Event → Log + Apply to DecisionPacket

### 1.4 Decision Packet Deep Dive

#### 1.4.1 Full Schema Design

```python
from pydantic import BaseModel, Field
from typing import Any, Literal
from datetime import datetime

class RecentAction(BaseModel):
    """A single action in the rolling history."""
    turn: int                          # Which turn this happened
    tool: str                          # Tool name
    summary: str                       # Distilled summary
    outcome: Literal["success", "error", "partial"]

class KnowledgeEntry(BaseModel):
    """A piece of working knowledge."""
    key: str                           # e.g., "lint_errors", "test_results"
    value: Any                         # Structured data
    source_turn: int                   # When this was learned
    supersedes: str | None = None      # Key this replaces (for updates)

class DecisionPacket(BaseModel):
    """The Short Track - what the model sees."""

    # === Identity ===
    agent_id: str
    turn: int                          # Current turn number

    # === Goal Context ===
    goal: str                          # "Fix lint errors in foo.py"
    operation: str                     # "lint", "test", "docstring"
    node_id: str                       # Current target
    node_summary: str                  # Brief description of the code

    # === Recent Actions (Rolling Window) ===
    recent_actions: list[RecentAction] = Field(default_factory=list, max_length=10)

    # === Working Knowledge (Structured) ===
    knowledge: dict[str, KnowledgeEntry] = Field(default_factory=dict)

    # === Error State ===
    last_error: str | None = None      # Most recent error summary
    error_count: int = 0               # Total errors this session

    # === Hub Context (Injected) ===
    hub_context: dict[str, Any] | None = None
    hub_freshness: datetime | None = None

    # === Metadata ===
    packet_version: str = "1.0"
```

#### 1.4.2 Projection Logic

The `ContextManager` applies events to maintain the Decision Packet. Here's the projection logic:

```python
class ContextManager:
    """Projects events onto the Decision Packet."""

    def __init__(self, initial_context: dict[str, Any]):
        self.packet = DecisionPacket(
            agent_id=initial_context["agent_id"],
            turn=0,
            goal=initial_context["goal"],
            operation=initial_context["operation"],
            node_id=initial_context["node_id"],
            node_summary=initial_context.get("node_summary", ""),
        )
        self._summarizers: dict[str, Summarizer] = {}

    def apply_event(self, event: dict[str, Any]) -> None:
        """Apply an event to update the Decision Packet."""
        event_type = event["type"]

        if event_type == "tool_result":
            self._apply_tool_result(event)
        elif event_type == "model_response":
            self._apply_model_response(event)
        elif event_type == "turn_start":
            self.packet.turn = event["turn"]
        elif event_type == "hub_update":
            self._apply_hub_context(event)

    def _apply_tool_result(self, event: dict[str, Any]) -> None:
        """Handle TOOL_RESULT events."""
        tool_name = event["tool"]
        raw_result = event["data"]["raw_output"]

        # 1. Get summary (tool-provided or generated)
        if "summary" in event["data"]:
            summary = event["data"]["summary"]
        else:
            summary = self._generate_summary(tool_name, raw_result)

        # 2. Add to recent actions (with rolling window)
        action = RecentAction(
            turn=self.packet.turn,
            tool=tool_name,
            summary=summary,
            outcome=self._infer_outcome(raw_result),
        )
        self.packet.recent_actions.append(action)
        if len(self.packet.recent_actions) > 10:
            self.packet.recent_actions.pop(0)

        # 3. Update knowledge (tool-specific logic)
        knowledge_delta = event["data"].get("knowledge_delta", {})
        for key, value in knowledge_delta.items():
            self.packet.knowledge[key] = KnowledgeEntry(
                key=key,
                value=value,
                source_turn=self.packet.turn,
            )

        # 4. Update error state
        if "error" in event["data"]:
            self.packet.last_error = event["data"]["error"]
            self.packet.error_count += 1
        else:
            self.packet.last_error = None

    def _generate_summary(self, tool_name: str, raw_result: Any) -> str:
        """Generate summary using pluggable summarizer."""
        if tool_name in self._summarizers:
            return self._summarizers[tool_name].summarize(raw_result)
        return f"Executed {tool_name}"  # Fallback

    def register_summarizer(self, tool_name: str, summarizer: "Summarizer") -> None:
        """Register a custom summarizer for a specific tool."""
        self._summarizers[tool_name] = summarizer
```

#### 1.4.3 Pluggable Summarizer Architecture

Since you want tool-side summaries as primary with fallback capability:

```python
from abc import ABC, abstractmethod

class Summarizer(ABC):
    """Base class for tool result summarizers."""

    @abstractmethod
    def summarize(self, raw_result: Any) -> str:
        """Generate a summary from raw tool output."""
        ...

    @abstractmethod
    def extract_knowledge(self, raw_result: Any) -> dict[str, Any]:
        """Extract knowledge entries from raw output."""
        ...


class LinterSummarizer(Summarizer):
    """Summarizer for linter tool results."""

    def summarize(self, raw_result: dict[str, Any]) -> str:
        errors = raw_result.get("errors", [])
        fixed = raw_result.get("fixed", 0)
        if fixed > 0:
            return f"Fixed {fixed} lint errors, {len(errors)} remaining"
        return f"Found {len(errors)} lint errors"

    def extract_knowledge(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "lint_errors_remaining": len(raw_result.get("errors", [])),
            "lint_errors_fixed": raw_result.get("fixed", 0),
        }


class ToolSidePassthrough(Summarizer):
    """Passes through tool-provided summaries (primary path)."""

    def summarize(self, raw_result: dict[str, Any]) -> str:
        return raw_result.get("summary", f"Tool completed")

    def extract_knowledge(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        return raw_result.get("knowledge_delta", {})
```

#### 1.4.4 Tool Return Contract

Tools should return this structure:

```python
# Tool return format
{
    "result": { ... },              # Full raw output (Long Track)
    "summary": "Fixed 3 errors",    # Short description (Short Track)
    "knowledge_delta": {            # Updates to working knowledge
        "errors_remaining": 2,
        "files_modified": ["foo.py"]
    },
    "outcome": "success"            # success | error | partial
}
```

If a tool doesn't provide `summary`, the registered `Summarizer` generates one.

#### 1.4.5 Prompt Injection

The Decision Packet is injected into the system prompt:

```python
def build_system_prompt(packet: DecisionPacket) -> str:
    """Build the system prompt with Decision Packet."""
    return f"""You are a code maintenance agent.

## Current State
- Goal: {packet.goal}
- Target: {packet.node_id}
- Turn: {packet.turn}

## Recent Actions
{format_recent_actions(packet.recent_actions)}

## Working Knowledge
{format_knowledge(packet.knowledge)}

{format_error_state(packet.last_error) if packet.last_error else ""}

## Available Tools
...
"""
```

### 1.5 Tool Result Distillation Strategy

The key challenge is: **how do tools produce both raw output and summary?**

**Option A: Tool-side summaries** (Recommended)
- Each `.pym` script returns `{"result": ..., "summary": "..."}`
- Pros: Tool authors control summary quality
- Cons: Requires updating all existing tools

**Option B: Runner-side extraction**
- Runner applies heuristics to extract summaries from results
- Pros: No tool changes
- Cons: Fragile, tool-specific logic in runner

**Option C: Hybrid**
- Tools return structured results with known fields
- A `Summarizer` component extracts summaries based on result schema
- Pros: Separation of concerns
- Cons: Additional abstraction layer

### 1.6 Integration Points

```
                    ┌─────────────────────────────────────┐
                    │         FunctionGemmaRunner         │
                    │                                     │
                    │  messages[] ──────► KEEP (debug)    │
                    │                                     │
                    │  ┌─────────────────────────────┐   │
                    │  │    ContextManager (NEW)     │   │
                    │  │                             │   │
                    │  │  DecisionPacket ◄── Event   │   │
                    │  │        │                    │   │
                    │  │        └─► Prompt Builder   │   │
                    │  └─────────────────────────────┘   │
                    └─────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
            JsonlEventEmitter               Hub Pull Hook
            (Long Track - exists)           (Future)
```

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
┌─────────────────────────────────────────────────────────────────┐
│                        Hub Daemon                               │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐ │
│  │   Watcher    │───►│ Rules Engine │───►│  Update Workers  │ │
│  │  (watchfiles)│    │ (if/then)    │    │  (.pym scripts)  │ │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘ │
│                                                    │           │
│                                           ┌───────▼────────┐  │
│                                           │  Node State KV │  │
│                                           │   (SQLite)     │  │
│                                           └───────┬────────┘  │
│                                                   │           │
│  ┌────────────────────────────────────────────────▼────────┐  │
│  │                    IPC Server                           │  │
│  │              (Unix Socket / HTTP)                       │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
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

1. **Summary Granularity**: How detailed should tool summaries be?
   - Proposal: 1-2 sentences max, focus on outcome not process
   - Example: "Fixed 3 lint errors" not "Ran ruff with --fix flag on lines 12, 45, 67..."

2. **Incremental Adoption**: Can we ship Two-Track incrementally?
   - Proposal: Yes, start with `submit_result` tool, then expand
   - Tools without summaries use fallback summarizer

3. **Hub as Optional**: Should Remora work without Hub?
   - Proposal: Yes, Pull Hook returns empty dict if Hub not running
   - Zero impact on core functionality

4. **Testing Strategy**: How do we test projection logic?
   - Proposal: Snapshot tests with known event sequences
   - Golden files: `events.jsonl` → expected `DecisionPacket`

---

## Part 5: Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Tool summary quality varies | High | Medium | Define clear summary guidelines, review during PR |
| DecisionPacket schema churn | Medium | High | Start minimal, add fields incrementally |
| Hub adds operational complexity | High | Medium | Make Hub optional, Remora should work without it |
| Performance regression | Low | High | Benchmark before/after, ensure O(1) event application |
| FunctionGemma confusion with new format | Medium | High | A/B test prompt formats, validate with real tasks |

---

## Summary

### Concept Viability Assessment

| Concept | Viability | Effort | Value |
|---------|-----------|--------|-------|
| **Two-Track Memory** | High | Medium | High |
| **Node State Hub** | High | High | Medium-High |

### Two-Track Memory

**Ready for implementation.** Addresses the core need: **clean, distilled context for FunctionGemma while preserving full context for debugging**.

Key components to build:
1. `DecisionPacket` model with `RecentAction` and `KnowledgeEntry`
2. `ContextManager` with event projection logic
3. `Summarizer` protocol with tool-specific implementations
4. Tool return contract (`result`, `summary`, `knowledge_delta`)
5. Updated `FunctionGemmaRunner` to use both tracks

Existing infrastructure to leverage:
- `JsonlEventEmitter` (Long Track exists)
- Event types already comprehensive
- Message history preserved for debugging

### Node State Hub

**Well-designed, higher lift.** Requires:
1. Daemon architecture with lifecycle management
2. File watching via `watchfiles`
3. SQLite storage with concurrent access handling
4. Unix socket IPC (HTTP fallback)
5. Rules engine for deterministic updates
6. Grail scripts for static analysis

Dependencies already in place:
- `fsdantic` for SQLite
- Grail execution infrastructure
- Process isolation patterns

### Recommended Sequence

1. **Phase 1**: Two-Track Memory (enables cleaner model context)
2. **Phase 2**: Node State Hub (provides proactive context)

Two-Track can ship independently and immediately improve FunctionGemma's effectiveness. The Hub builds on Two-Track's Pull Hook interface.

### Critical Path

```
DecisionPacket Model
        │
        ▼
ContextManager + Projection Logic
        │
        ▼
Tool Return Contract (summary + knowledge_delta)
        │
        ▼
Update Existing Tools (lint, test, docstring)
        │
        ▼
Runner Integration (dual-track)
        │
        ▼
Pull Hook Stub (no-op, ready for Hub)
        │
        ▼
[Future] Hub Daemon + HubClient
```
