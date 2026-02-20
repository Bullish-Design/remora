# Remora Hub Integration Guide

> **Version**: 1.0
> **Status**: Reference Documentation
> **Audience**: Remora Users & Library Developers

This guide explains how Remora and its Node State Hub work together, from two perspectives:
- **Part 1**: For users who want to leverage Hub context in their agents
- **Part 2**: For developers who need to understand the internal architecture

---

# Part 1: User Guide

## 1.1 Introduction

### What is the Hub?

The **Node State Hub** is a background daemon that maintains a live index of your codebase's metadata. It watches your Python files and pre-computes information that Remora agents can use instantly, without expensive AST parsing at runtime.

### Why Use the Hub?

| Without Hub | With Hub |
|-------------|----------|
| Agent parses file on each run | Metadata pre-computed, instant access |
| No cross-file knowledge | Knows callers, callees, related tests |
| Context limited to current file | Rich context from entire codebase |
| Cold start on every run | Warm cache, continuous updates |

### What the Hub Provides

When your agent runs, it can access:

- **Signatures**: `def process_data(items: list[Item]) -> Summary`
- **Docstrings**: First line of documentation
- **Decorators**: `@staticmethod`, `@cached_property`, etc.
- **Callers**: Which functions call this one
- **Callees**: Which functions this one calls
- **Related Tests**: Test functions that exercise this code
- **Complexity**: Cyclomatic complexity score
- **Type Hint Coverage**: Whether the function has type annotations

---

## 1.2 Quick Start

### Starting the Hub Daemon

```bash
# Start the Hub daemon for your project
$ remora-hub start --project-root /path/to/your/project

# Or from within your project directory
$ cd /path/to/your/project
$ remora-hub start
```

The daemon will:
1. Create `.remora/hub.db` in your project
2. Index all Python files (cold start)
3. Watch for file changes continuously

### Checking Status

```bash
$ remora-hub status

Hub: running
  Database: /path/to/project/.remora/hub.db
  Files indexed: 142
  Nodes indexed: 1,247
  Last update: 2026-02-19T10:30:45Z
```

### Running Remora with Hub Context

Once the Hub is running, Remora agents automatically receive Hub context:

```bash
# Run Remora - Hub context is injected automatically
$ remora analyze --operation lint src/
```

Your agents will see `hub_context` populated in their DecisionPacket.

### Stopping the Hub

```bash
$ remora-hub stop
```

---

## 1.3 What the Hub Provides to Your Agents

### In Your Agent's Context

When your agent runs, the `DecisionPacket` includes:

```python
{
    "hub_context": {
        "signature": "def process_items(data: list[dict]) -> Result",
        "docstring": "Process a batch of items and return aggregated result.",
        "decorators": ["@transaction", "@retry(max_attempts=3)"],
        "callers": ["main.py:run_pipeline", "cli.py:handle_command"],
        "callees": ["db.py:fetch_items", "utils.py:validate"],
        "related_tests": ["test_processing.py:test_process_items"],
        "complexity": 12,
        "has_type_hints": true
    }
}
```

### Using Hub Context in Decisions

Your agent's system prompt can reference this context:

```yaml
# In your subagent.yaml
initial_context:
  system_prompt: |
    You are analyzing the function: {{ node.name }}

    {% if hub_context %}
    Current signature: {{ hub_context.signature }}
    Called by: {{ hub_context.callers | join(', ') }}
    Calls: {{ hub_context.callees | join(', ') }}
    Related tests: {{ hub_context.related_tests | join(', ') }}
    {% endif %}

    Make sure any changes maintain compatibility with callers.
```

---

## 1.4 Integrating with Custom .pym Scripts

### Accessing Hub Context in Tools

Your `.pym` tool scripts can receive Hub context as an input:

```python
# agents/my_operation/tools/analyze_function.pym
"""Analyze a function using Hub context."""

from grail import Input, external

# Hub context is passed automatically when available
hub_context: dict = Input("hub_context", default={})
target_node: str = Input("target_node")

@external
async def read_file(path: str) -> str:
    ...

async def main() -> dict:
    # Use Hub context if available
    signature = hub_context.get("signature", "unknown")
    callers = hub_context.get("callers", [])

    # Make decisions based on Hub knowledge
    if len(callers) > 5:
        impact = "high"  # Many callers = high impact change
    else:
        impact = "low"

    return {
        "result": {
            "signature": signature,
            "caller_count": len(callers),
            "impact": impact,
        },
        "summary": f"Function has {len(callers)} callers ({impact} impact)",
        "outcome": "success",
    }
```

### Example: Using Caller Information

```python
# agents/refactor/tools/check_callers.pym
"""Check if it's safe to change a function's signature."""

from grail import Input, external

hub_context: dict = Input("hub_context", default={})
proposed_change: str = Input("proposed_change")

async def main() -> dict:
    callers = hub_context.get("callers", [])

    if not callers:
        return {
            "result": {"safe": True, "callers": []},
            "summary": "No known callers - safe to modify",
            "outcome": "success",
        }

    return {
        "result": {
            "safe": False,
            "callers": callers,
            "warning": f"Found {len(callers)} callers that may need updates"
        },
        "summary": f"Warning: {len(callers)} callers may be affected",
        "outcome": "partial",
        "knowledge_delta": {
            "affected_callers": callers,
        }
    }
```

### Example: Checking Related Tests

```python
# agents/test/tools/find_related_tests.pym
"""Find tests related to the current function."""

from grail import Input, external

hub_context: dict = Input("hub_context", default={})
node_id: str = Input("node_id")

@external
async def run_tests(test_files: list[str]) -> dict:
    ...

async def main() -> dict:
    related_tests = hub_context.get("related_tests", [])

    if not related_tests:
        return {
            "result": {"has_tests": False},
            "summary": "No related tests found - consider adding coverage",
            "outcome": "partial",
        }

    # Run related tests
    results = await run_tests(related_tests)

    return {
        "result": {
            "has_tests": True,
            "test_count": len(related_tests),
            "test_results": results,
        },
        "summary": f"Ran {len(related_tests)} related tests",
        "outcome": "success" if results.get("passed") else "error",
    }
```

---

## 1.5 TreeSitter Node Integration

### How Hub Indexes TreeSitter-Discovered Nodes

Remora uses TreeSitter to discover code nodes (functions, classes, methods). The Hub maintains the same node identification:

```
TreeSitter Discovery              Hub Index
       ↓                              ↓
   CSTNode                       NodeState
   - node_id (SHA256)     ←→     - key (node:{path}:{name})
   - file_path                   - file_path
   - node_type                   - node_type
   - name                        - node_name
   - text                        - source_hash
```

### Node ID Stability

Both systems use stable identifiers:

```python
# TreeSitter discovery creates stable node_id
node_id = sha256(f"{file_path}:{node_type}:{name}")[:16]

# Hub uses the same key format
hub_key = f"node:{file_path}:{name}"
```

This means:
- Renaming a function creates a new node (old one deleted, new one created)
- Moving a function to a new file creates a new node
- Editing function body updates the existing node (same key, new source_hash)

### Mapping Between Systems

When your agent runs:

```python
# The orchestrator discovers nodes via TreeSitter
nodes = discoverer.discover(root_path)

for node in nodes:
    # Each node has a stable node_id
    print(node.node_id)  # e.g., "a1b2c3d4e5f6g7h8"

    # The Hub stores state keyed by this format
    hub_key = f"node:{node.file_path}:{node.name}"

    # Context manager fetches from Hub
    hub_context = await hub_client.get_context([hub_key])
```

### Custom Node Types

If you add custom TreeSitter queries (in `src/remora/queries/`), the Hub will index those nodes too:

```scheme
; src/remora/queries/python/my_custom/decorators.scm
; Capture decorated functions
(decorated_definition
  (decorator) @decorator.name
  definition: (function_definition
    name: (identifier) @function.name)) @decorated.def
```

The Hub's `extract_signatures.pym` script uses Python's `ast` module by default, but you can extend it to handle custom node types.

---

## 1.6 Configuration

### Hub Database Location

Default: `{project_root}/.remora/hub.db`

Override:
```bash
$ remora-hub start --db-path /custom/path/hub.db
```

### Ignore Patterns

The Hub ignores these directories by default:
- `.git`, `.jj`
- `__pycache__`
- `node_modules`
- `.venv`, `venv`, `.tox`
- `build`, `dist`, `.eggs`
- `.remora` (its own database)

### Freshness Thresholds

The Hub client considers data "stale" if the source file was modified after the last index. Default threshold: **5 seconds**.

### Lazy Daemon Fallback

If the Hub daemon isn't running, the `HubClient` performs **ad-hoc indexing**:

1. Checks if `hub.db` exists
2. Checks if files are stale (mtime > last_scanned)
3. If stale and daemon not running, indexes up to 5 critical files
4. Proceeds with available data

This ensures agents always get some context, even without the daemon.

---

## 1.7 Troubleshooting

### Hub Not Running

**Symptom**: `hub_context` is empty in your agent

**Check**:
```bash
$ remora-hub status
Hub: not initialized
```

**Fix**:
```bash
$ remora-hub start
```

### Stale Data Warnings

**Symptom**: Log message "Hub has stale data, daemon running - proceeding"

**Cause**: Files changed faster than daemon could index

**Fix**: This is normal during rapid editing. The daemon will catch up.

### Ad-Hoc Indexing

**Symptom**: Log message "Hub daemon not running - performing ad-hoc index"

**Cause**: Daemon not running but `hub.db` exists

**Impact**:
- Slight delay (50-200ms per file)
- Only critical files indexed (max 5)
- Partial context may be available

**Fix**: Start the daemon for best performance:
```bash
$ remora-hub start --background
```

### Corrupted Database

**Symptom**: Errors reading from `hub.db`

**Fix**:
```bash
$ rm .remora/hub.db
$ remora-hub start  # Will rebuild from scratch
```

---

# Part 2: Developer Guide

## 2.1 Architecture Overview

### Design Principles

1. **Daemon + Shared Workspace**: Background process indexes, clients read directly
2. **No IPC**: Clients read from FSdantic workspace (Turso handles concurrency)
3. **Lazy Fallback**: Works without daemon via ad-hoc indexing
4. **Type Safety**: Pydantic models everywhere, FSdantic repositories

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Hub Daemon                                │
│                    (remora-hub process)                          │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │  HubWatcher  │───►│ RulesEngine  │───►│  NodeStateStore   │  │
│  │ (watchfiles) │    │ (no LLM)     │    │ (TypedKVRepository)│  │
│  └──────────────┘    └──────────────┘    └─────────┬─────────┘  │
│                                                     │            │
│                                              Fsdantic.open()     │
│                                               (read-write)       │
└─────────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
                                    ┌─────────────────────────────┐
                                    │         hub.db              │
                                    │     (AgentFS/Turso)         │
                                    │                             │
                                    │  • Excellent concurrency    │
                                    │  • WAL handled natively     │
                                    │  • No locking concerns      │
                                    └─────────────────────────────┘
                                                     │
                                              Fsdantic.open()
                                               (read-only)
                                                     │
                                                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Remora Agent                                │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌───────────────────┐  │
│  │   Runner     │───►│ContextManager│───►│    HubClient      │  │
│  │              │    │ (Pull Hook)  │    │ (Lazy Daemon)     │  │
│  └──────────────┘    └──────────────┘    └───────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Why Shared Workspace (Not IPC)?

The original design proposed Unix socket IPC. We chose shared workspace because:

| IPC (Rejected) | Shared Workspace (Chosen) |
|----------------|---------------------------|
| ~1-5ms latency | <0.1ms latency |
| JSON serialization overhead | Native Pydantic objects |
| Complex failure modes | Simple: file exists or not |
| Daemon required for reads | Reads work without daemon |

AgentFS is built on **Turso** (embedded libSQL), which handles concurrent readers + single writer natively.

---

## 2.2 Core Components

### NodeState Model

```python
# src/remora/hub/models.py

class NodeState(VersionedKVRecord):
    """State for a single code node.

    Inherits from fsdantic.VersionedKVRecord:
    - created_at: float (Unix timestamp)
    - updated_at: float (Unix timestamp)
    - version: int (auto-incremented on save)
    """

    # Identity
    key: str                    # "node:{file_path}:{node_name}"
    file_path: str              # Absolute path
    node_name: str              # Function/class name
    node_type: Literal["function", "class", "module"]

    # Content hashes
    source_hash: str            # SHA256 of node source
    file_hash: str              # SHA256 of entire file

    # Static analysis
    signature: str | None       # "def foo(x: int) -> str"
    docstring: str | None       # First line of docstring
    imports: list[str]          # Used imports
    decorators: list[str]       # "@staticmethod", etc.

    # Cross-file analysis (lazy)
    callers: list[str] | None
    callees: list[str] | None
    related_tests: list[str] | None

    # Metrics
    line_count: int | None
    complexity: int | None
    has_type_hints: bool

    # Metadata
    update_source: Literal["file_change", "cold_start", "manual", "adhoc"]
```

### NodeStateStore

```python
# src/remora/hub/store.py

class NodeStateStore:
    """FSdantic-backed storage for Hub data."""

    def __init__(self, workspace: Workspace):
        # Type-safe repositories via FSdantic
        self.node_repo = workspace.kv.repository(
            prefix="node:",
            model_type=NodeState
        )
        self.file_repo = workspace.kv.repository(
            prefix="file:",
            model_type=FileIndex
        )

    # CRUD operations delegate to TypedKVRepository
    async def get(self, key: str) -> NodeState | None
    async def get_many(self, keys: list[str]) -> dict[str, NodeState]
    async def set(self, state: NodeState) -> None
    async def delete(self, key: str) -> None

    # Hub-specific operations
    async def get_by_file(self, file_path: str) -> list[NodeState]
    async def invalidate_file(self, file_path: str) -> list[str]
    async def gc_stale_nodes(self, max_age_seconds: float) -> int
```

### HubDaemon

```python
# src/remora/hub/daemon.py

class HubDaemon:
    """Background daemon that watches and indexes."""

    async def run(self) -> None:
        # 1. Open workspace
        self.workspace = await Fsdantic.open(path=str(self.db_path))
        self.store = NodeStateStore(self.workspace)

        # 2. Write PID file
        self._write_pid_file()

        # 3. Cold start index
        await self._cold_start_index()

        # 4. Watch for changes
        self.watcher = HubWatcher(self.project_root, self._handle_change)
        await self.watcher.start()

    async def _handle_change(self, change_type: str, path: Path) -> None:
        # Get actions from rules engine
        actions = self.rules.get_actions(change_type, path)

        # Execute each action
        for action in actions:
            result = await action.execute(context)

            # Store extracted nodes
            if "nodes" in result:
                await self._process_extraction_result(path, result)
```

### HubClient (Lazy Daemon Pattern)

```python
# src/remora/context/hub_client.py

class HubClient:
    """Client with graceful degradation."""

    async def get_context(self, node_ids: list[str]) -> dict[str, NodeState]:
        # 1. Check if Hub available
        if not await self._is_available():
            return {}

        # 2. Open workspace (cached)
        await self._ensure_workspace()

        # 3. Check freshness
        stale_files = await self._check_freshness(node_ids)

        # 4. Handle stale data
        if stale_files:
            if await self._daemon_running():
                logger.debug("Stale but daemon running")
            else:
                # Ad-hoc indexing fallback
                await self._adhoc_index(stale_files)

        # 5. Return context
        return await self._store.get_many(node_ids)
```

### RulesEngine

```python
# src/remora/hub/rules.py

class RulesEngine:
    """Deterministic update rules (no LLM)."""

    def get_actions(
        self,
        change_type: str,  # "added", "modified", "deleted"
        file_path: Path,
    ) -> list[UpdateAction]:

        if change_type == "deleted":
            return [DeleteFileNodes(file_path)]

        # For added/modified: extract signatures
        return [ExtractSignatures(file_path)]
```

---

## 2.3 Data Flow

### Write Path (Daemon → Storage)

```
1. watchfiles detects change
       ↓
2. HubWatcher._handle_change(change_type, path)
       ↓
3. RulesEngine.get_actions(change_type, path)
       ↓
4. ExtractSignatures.execute(context)
       ↓
5. Grail script: extract_signatures.pym
       ↓
6. NodeStateStore.set(node_state)
       ↓
7. TypedKVRepository.save(key, record)
       ↓
8. AgentFS.kv.set(qualified_key, data)
       ↓
9. Turso SQLite write
```

### Read Path (Agent → Context)

```
1. FunctionGemmaRunner.run() starts
       ↓
2. await context_manager.pull_hub_context()
       ↓
3. HubClient.get_context([node_id])
       ↓
4. NodeStateStore.get_many(keys)
       ↓
5. TypedKVRepository.load_many(keys)
       ↓
6. AgentFS.kv.get(qualified_key)
       ↓
7. Turso SQLite read (concurrent with writes)
       ↓
8. DecisionPacket.hub_context = {...}
       ↓
9. context_manager.get_prompt_context()
       ↓
10. Injected into system prompt
```

---

## 2.4 Integration Points

### Pull Hook (`ContextManager.pull_hub_context`)

**Location**: `src/remora/context/manager.py:88-103`

```python
async def pull_hub_context(self) -> None:
    """Called at start of each turn."""

    if self._hub_client is None:
        from remora.context.hub_client import get_hub_client
        self._hub_client = get_hub_client()

    try:
        context = await self._hub_client.get_context([self.packet.node_id])

        if context:
            node_state = context.get(self.packet.node_id)
            if node_state:
                self.packet.hub_context = {
                    "signature": node_state.signature,
                    "docstring": node_state.docstring,
                    # ... more fields
                }
    except Exception:
        pass  # Graceful degradation
```

### Where Pull Hook is Called (`runner.py`)

**Location**: `src/remora/runner.py` in `FunctionGemmaRunner.run()`

```python
async def run(self) -> AgentResult:
    while self.turn_count < self.max_turns:
        # Pull fresh Hub context before each turn
        await self.context_manager.pull_hub_context()

        # Build prompt with context
        prompt_context = self.context_manager.get_prompt_context()
        system_prompt = self._build_system_prompt(prompt_context)

        # Call model
        response = await self._call_model(system_prompt)
        # ...
```

### DecisionPacket Hub Fields

**Location**: `src/remora/context/models.py`

```python
class DecisionPacket(BaseModel):
    # ... other fields ...

    # Hub Context (Injected via Pull Hook)
    hub_context: dict[str, Any] | None = None
    """External context from Node State Hub."""

    hub_freshness: datetime | None = None
    """When hub_context was last updated."""
```

### Future: Push Hook

Not yet implemented, but the integration point would be:

```python
# In runner.py after tool execution
async def _handle_tool_result(self, tool_name: str, result: dict) -> None:
    # Apply to context manager
    self.context_manager.apply_event({
        "type": "tool_result",
        "tool_name": tool_name,
        "data": result,
    })

    # Future: Push to Hub
    # await self.context_manager.push_hub_context(tool_name, result)
```

---

## 2.5 FSdantic Usage

### TypedKVRepository Pattern

```python
from fsdantic import Fsdantic, TypedKVRepository, VersionedKVRecord

# Open workspace
workspace = await Fsdantic.open(path="hub.db")

# Create typed repository
repo: TypedKVRepository[NodeState] = workspace.kv.repository(
    prefix="node:",
    model_type=NodeState
)

# CRUD operations - fully typed
await repo.save("key", node_state)      # Auto-increments version
state = await repo.load("key")          # Returns NodeState | None
await repo.delete("key")
all_states = await repo.list_all()      # Returns list[NodeState]

# Batch operations
result = await repo.load_many(["k1", "k2", "k3"])
for item in result.items:
    if item.ok:
        print(item.value)  # NodeState
```

### VersionedKVRecord Semantics

```python
# First save: version = 1
state = NodeState(key="...", ...)
await repo.save("key", state)
assert state.version == 1

# Second save: version auto-incremented
state.signature = "updated"
await repo.save("key", state)
assert state.version == 2

# Concurrent modification detection
# If someone else saved between our read and write,
# FSdantic raises KVConflictError
```

### Workspace Lifecycle

```python
# Open
workspace = await Fsdantic.open(path="hub.db")

# Use
store = NodeStateStore(workspace)
await store.set(node_state)

# Close (important!)
await workspace.close()

# Or use context manager
async with await Fsdantic.open(path="hub.db") as workspace:
    store = NodeStateStore(workspace)
    await store.set(node_state)
# Automatically closed
```

---

## 2.6 Grail Script Execution

### Extract Signatures Script Anatomy

**Location**: `.grail/hub/extract_signatures.pym`

```python
"""Extract function/class signatures from a Python file."""

from grail import Input, external
import ast
import hashlib

# === Inputs ===
file_path: str = Input("file_path")

# === External Functions ===
@external
async def read_file(path: str) -> str:
    """Provided by host."""
    ...

# === Main ===
async def main() -> dict:
    # Read file
    content = await read_file(file_path)
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    # Parse AST
    tree = ast.parse(content)

    # Extract nodes
    nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            nodes.append(_extract_function(node, content))

    return {
        "file_path": file_path,
        "file_hash": file_hash,
        "nodes": nodes,
        "error": None,
    }
```

### External Functions

The daemon provides implementations for external functions:

```python
# In daemon.py
context = ActionContext(
    store=self.store,
    grail_executor=self.grail_executor,
    project_root=self.project_root,
)

# External implementation
async def read_file(path: str) -> str:
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = self.project_root / file_path
    return file_path.read_text(encoding="utf-8")
```

### Result Format

Scripts return structured results:

```python
{
    "file_path": "/path/to/file.py",
    "file_hash": "abc123...",
    "nodes": [
        {
            "name": "process_data",
            "type": "function",
            "signature": "def process_data(items: list) -> dict",
            "docstring": "Process data items.",
            "decorators": ["@staticmethod"],
            "source_hash": "def456...",
            "line_count": 15,
            "has_type_hints": True,
        }
    ],
    "error": None,  # Or error message string
}
```

---

## 2.7 Extending the Hub

### Adding New Analysis Scripts

1. Create a new `.pym` script in `.grail/hub/`:

```python
# .grail/hub/analyze_complexity.pym
"""Compute cyclomatic complexity."""

from grail import Input, external

file_path: str = Input("file_path")

@external
async def read_file(path: str) -> str:
    ...

async def main() -> dict:
    content = await read_file(file_path)
    # Use radon or custom logic
    complexity = compute_complexity(content)
    return {"complexity": complexity}
```

2. Add action in `rules.py`:

```python
@dataclass
class ComputeComplexity(UpdateAction):
    file_path: Path

    async def execute(self, context: ActionContext) -> dict:
        return await context.run_grail_script(
            "hub/analyze_complexity.pym",
            {"file_path": str(self.file_path)}
        )
```

3. Update `RulesEngine` to include the action:

```python
def get_actions(self, change_type: str, file_path: Path) -> list:
    actions = [ExtractSignatures(file_path)]
    actions.append(ComputeComplexity(file_path))
    return actions
```

### Adding Cross-File Analysis

Cross-file analysis (callers, callees) requires more complex logic:

```python
# In daemon.py
async def _compute_callers(self, node_key: str) -> list[str]:
    """Find all nodes that call this one."""
    all_nodes = await self.store.list_all_nodes()

    callers = []
    for node in all_nodes:
        if node.callees and node_key in node.callees:
            callers.append(f"{node.file_path}:{node.node_name}")

    return callers
```

### Custom Node Types

To index custom constructs (e.g., decorated factories):

1. Extend `extract_signatures.pym` to recognize them
2. Add a new `node_type` value
3. Update `NodeState` model if needed

---

## 2.8 API Reference

### HubClient

```python
class HubClient:
    def __init__(
        self,
        hub_db_path: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        """Initialize client.

        Args:
            hub_db_path: Path to hub.db (auto-discovered if None)
            project_root: Project root for ad-hoc indexing
        """

    async def get_context(
        self,
        node_ids: list[str]
    ) -> dict[str, NodeState]:
        """Get context for nodes.

        Args:
            node_ids: List of node keys (e.g., "node:/path:name")

        Returns:
            Dict mapping node IDs to NodeState objects.
            Missing nodes are omitted.
        """

    async def health_check(self) -> dict[str, Any]:
        """Check Hub health.

        Returns:
            {
                "available": bool,
                "daemon_running": bool,
                "indexed_files": int,
                "indexed_nodes": int,
                "last_update": str | None,
            }
        """

    async def close(self) -> None:
        """Close workspace connection."""

# Module-level singleton
def get_hub_client() -> HubClient:
    """Get or create HubClient singleton."""

async def close_hub_client() -> None:
    """Close singleton client."""
```

### NodeStateStore

```python
class NodeStateStore:
    def __init__(self, workspace: Workspace) -> None:
        """Initialize with open workspace."""

    # Node operations
    async def get(self, key: str) -> NodeState | None
    async def get_many(self, keys: list[str]) -> dict[str, NodeState]
    async def set(self, state: NodeState) -> None
    async def set_many(self, states: list[NodeState]) -> None
    async def delete(self, key: str) -> None
    async def list_all_nodes(self) -> list[NodeState]
    async def get_by_file(self, file_path: str) -> list[NodeState]
    async def invalidate_file(self, file_path: str) -> list[str]

    # File index operations
    async def get_file_index(self, file_path: str) -> FileIndex | None
    async def set_file_index(self, index: FileIndex) -> None
    async def delete_file_index(self, file_path: str) -> None
    async def list_all_files(self) -> list[FileIndex]

    # Status
    async def get_status(self) -> HubStatus | None
    async def set_status(self, status: HubStatus) -> None
    async def stats(self) -> dict[str, int]

    # Maintenance
    async def gc_stale_nodes(self, max_age_seconds: float = 86400) -> int
```

### HubDaemon

```python
class HubDaemon:
    def __init__(
        self,
        project_root: Path,
        db_path: Path | None = None,
        grail_executor: Any = None,
    ) -> None:
        """Initialize daemon.

        Args:
            project_root: Directory to watch
            db_path: Path to hub.db (default: {root}/.remora/hub.db)
            grail_executor: Grail script runner
        """

    async def run(self) -> None:
        """Main daemon loop. Blocks until shutdown."""

    # Internal methods
    async def _cold_start_index(self) -> None
    async def _handle_file_change(self, change_type: str, path: Path) -> None
    async def _index_file(self, path: Path, update_source: str) -> None
    async def _shutdown(self) -> None
```

---

## Appendix: File Locations

| Component | Path |
|-----------|------|
| Hub models | `src/remora/hub/models.py` |
| Hub store | `src/remora/hub/store.py` |
| Hub daemon | `src/remora/hub/daemon.py` |
| Hub watcher | `src/remora/hub/watcher.py` |
| Hub rules | `src/remora/hub/rules.py` |
| Hub indexer | `src/remora/hub/indexer.py` |
| Hub CLI | `src/remora/hub/cli.py` |
| HubClient | `src/remora/context/hub_client.py` |
| ContextManager | `src/remora/context/manager.py` |
| DecisionPacket | `src/remora/context/models.py` |
| Extract script | `.grail/hub/extract_signatures.pym` |
| FSdantic lib | `.context/fsdantic/` |
| Grail lib | `.context/grail/` |
