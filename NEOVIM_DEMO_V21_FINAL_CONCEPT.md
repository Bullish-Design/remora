# Remora Neovim V2.1: The MVP Blueprint

A complete rewrite. No legacy baggage. This document specifies the minimum viable implementation that delivers 90% of the V2 vision.

---

## Core Principles

1. **Every AST node is a potential agent.** Functions, classes, methods, files—all first-class citizens.
2. **Agents write themselves.** Each node has `rewrite_self()`. File nodes write their contents. The daemon handles ID preservation.
3. **Copy-on-write semantics.** Name changes create new nodes. Old nodes become orphans. No migration complexity.
4. **Graph-enforced sanity.** Cycles are detected and blocked at the topology level, not the application level.

---

## 1. The ID System

### 1a. ID Format & Injection

Every parseable AST node gets an 8-character alphanumeric ID. The daemon injects it as a trailing comment on the definition line:

```python
class ConfigLoader:                                    # rm_a1b2c3d4
    def __init__(self, path: str):                     # rm_e5f6g7h8
        self.path = path

    async def load(self) -> dict:                      # rm_i9j0k1l2
        pass
```

**Rules:**
- Prefix: `rm_` (identifies Remora-managed IDs)
- Body: 8 chars, `[a-z0-9]`
- Position: End of line, preceded by minimum 4 spaces from code
- Files get a magic comment at line 1: `# remora-file: rm_xyz12345`

### 1b. ID Preservation Logic (Daemon Responsibility)

When the daemon parses a file after modification:

```
FOR each AST node in new_parse:
    old_node = find_by_name_and_type(node.name, node.type, same_file)
    IF old_node exists:
        preserve old_node.id → inject into new_parse
    ELSE:
        generate new random ID → inject into new_parse

FOR each old_node not matched:
    mark as ORPHANED in topology (do not delete)
```

**Name changes = new identity.** If you rename `load()` to `load_config()`, that's a new node. The old `load()` becomes orphaned. This is intentional: agents might still reference it, and we never lose history.

### 1c. File-Level Nodes

Files are nodes too. When a file agent calls `rewrite_self(new_content)`:

1. Daemon receives the new content
2. Parses it for AST nodes
3. Matches names to preserve IDs (as above)
4. Injects any missing IDs
5. Writes the final content to disk

The file agent doesn't need to know about child IDs—the daemon handles it transparently.

---

## 2. The Topology Graph

### 2a. Dual Storage: SQLite + Rustworkx

**SQLite** (durable, source of truth):
```sql
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,           -- rm_a1b2c3d4
    node_type TEXT NOT NULL,       -- function|class|method|file
    name TEXT NOT NULL,            -- "load_config"
    file_path TEXT NOT NULL,       -- relative to project root
    start_line INTEGER,
    end_line INTEGER,
    status TEXT DEFAULT 'active',  -- active|orphaned
    source_hash TEXT               -- SHA256 of node body (for change detection)
);

CREATE TABLE edges (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,       -- parent_of|calls|imports
    PRIMARY KEY (from_id, to_id, edge_type),
    FOREIGN KEY (from_id) REFERENCES nodes(id),
    FOREIGN KEY (to_id) REFERENCES nodes(id)
);

CREATE TABLE activation_chain (
    correlation_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    PRIMARY KEY (correlation_id, agent_id)
);
```

**Rustworkx** (in-memory, fast traversal):
- Lazily hydrated from SQLite on demand
- Used for: cycle detection, shortest path, neighborhood queries
- Invalidated on file save (daemon signals "topology dirty")

### 2b. Edge Types

| Edge Type | Meaning | Derived From |
|-----------|---------|--------------|
| `parent_of` | Containment (class → method, file → function) | AST structure |
| `calls` | Function A calls function B | Static analysis (tree-sitter queries) |
| `imports` | File A imports from file B | Import statements |

### 2c. Cycle Detection for Message Passing

Before an agent sends `message_node(target_id, request)`:

```python
async def can_message(self, from_id: str, to_id: str, correlation_id: str) -> bool:
    # 1. Check activation chain depth
    chain = await self.db.get_activation_chain(correlation_id)
    if len(chain) >= MAX_CHAIN_DEPTH:  # Default: 5
        return False

    # 2. Check if target is already in the activation chain
    if to_id in [entry.agent_id for entry in chain]:
        return False  # Would create cycle

    # 3. Check graph for structural cycles (optional paranoia)
    # Rustworkx: is there already a path from to_id back to from_id in activation edges?

    return True
```

**Correlation IDs** propagate through the entire causal chain. When Agent A triggers Agent B triggers Agent C, they all share the same correlation ID. This makes cycle detection trivial: if the target is already in your correlation chain, you can't message it.

---

## 3. The Agent Model

### 3a. Single Base Prompt: `ASTAgentNode`

Every agent sent to vLLM uses this exact structure:

```python
from pydantic import BaseModel, Field
from typing import Literal

class ASTAgentNode(BaseModel):
    """
    BASE SYSTEM PROMPT (sent to vLLM as system message):

    You are an autonomous AI agent embodying a Python {node_type}: `{name}`

    # Identity
    - Node ID: {remora_id}
    - Location: {file_path}:{start_line}-{end_line}
    - Parent: {parent_id or "None (top-level)"}

    # Your Source Code
    ```python
    {source_code}
    ```

    # Graph Context
    - Called by: {caller_ids}
    - You call: {callee_ids}

    # Custom Instructions
    {custom_system_prompt}

    # Available Data
    {mounted_workspaces}

    # Core Rules
    1. You may ONLY edit your own body using `rewrite_self()`.
    2. To request changes elsewhere, use `message_node(target_id, request)`.
    3. Your parent can edit you. You cannot edit your parent.
    4. All edits are proposals until the human approves.
    """

    # Identity
    remora_id: str
    node_type: Literal["function", "class", "method", "file"]
    name: str
    file_path: str
    start_line: int
    end_line: int
    source_code: str

    # Graph context
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # Extension injection points
    custom_system_prompt: str = ""
    mounted_workspaces: str = "None"

    # Base tools (always available)
    tools: list[str] = Field(default_factory=lambda: [
        "rewrite_self",
        "message_node",
        "ask_parent",
        "get_my_callers",
        "get_my_callees",
        "read_node",
        "propose_new_node",
    ])
```

### 3b. Extension Nodes (User-Defined Behaviors)

Users create `.py` files in `.remora/models/`:

```python
# .remora/models/config_agents.py
from remora import ExtensionNode, tool

class ConfigHandler(ExtensionNode):
    """Handles all Config* classes."""

    match_type = "class"
    match_pattern = "Config*"  # fnmatch syntax

    system_prompt = """
    You are a configuration specialist. You ensure all config classes:
    - Have sensible defaults
    - Validate their inputs
    - Document their fields
    """

    def get_workspaces(self) -> str:
        return "- .env.template (read-only)\n- config/*.toml (read-write)"

    @tool
    async def read_env(self, key: str) -> str:
        """Read an environment variable."""
        return os.environ.get(key, "")

    @tool
    async def validate_config_schema(self) -> dict:
        """Run JSON schema validation on this config class."""
        # Implementation here
        pass
```

**Discovery at startup:**
```python
for py_file in Path(".remora/models/").glob("*.py"):
    module = importlib.import_module(py_file)
    for cls in module.__dict__.values():
        if isinstance(cls, type) and issubclass(cls, ExtensionNode):
            registry.register(cls)
```

**Hydration at runtime:**
```python
def hydrate_agent(node_id: str) -> ASTAgentNode:
    metadata = db.get_node(node_id)
    base = ASTAgentNode(**metadata)

    # Find matching extension
    for ext_cls in registry.extensions:
        if ext_cls.matches(metadata.node_type, metadata.name):
            ext = ext_cls()
            base.custom_system_prompt = ext.system_prompt
            base.mounted_workspaces = ext.get_workspaces()
            base.tools.extend(ext.get_tools())
            break

    return base
```

---

## 4. Core Tools (The Grail)

Every agent has these tools via the base `ASTAgentNode`:

### 4a. `rewrite_self`

```python
@tool
async def rewrite_self(new_source: str) -> RewriteProposal:
    """
    Propose a rewrite of your own source code.

    The new source will be validated for syntax errors.
    If valid, a diff will be shown to the human for approval.

    Args:
        new_source: The complete new source code for this node.
                   Do NOT include the remora ID comment—it will be preserved.

    Returns:
        A proposal ID. The human will approve or reject with feedback.
    """
```

**Flow:**
1. Agent calls `rewrite_self("def load(self): ...")`
2. Daemon validates syntax (tree-sitter parse)
3. Daemon creates `RewriteProposal` event with diff
4. Neovim shows diff in sidepanel
5. Human clicks [Accept] or [Reject + Feedback]
6. If accepted: daemon writes to file, preserves ID
7. If rejected: feedback routed back to agent for retry

### 4b. `message_node`

```python
@tool
async def message_node(target_id: str, request: str) -> str:
    """
    Send a request to another agent in the swarm.

    Use this when you need another node to change itself,
    or when you need information that another node controls.

    Args:
        target_id: The remora ID of the target node (e.g., "rm_a1b2c3d4")
        request: What you're asking the other agent to do

    Returns:
        The target agent's response (may be async—you'll be notified)
    """
```

**Flow:**
1. Cycle check via `can_message()` (see 2c)
2. If blocked: return error "Would create cycle in activation chain"
3. If allowed: queue `AgentMessageEvent` with correlation_id
4. Target agent wakes, processes, responds
5. Response routed back to caller

### 4c. `ask_parent`

```python
@tool
async def ask_parent(request: str) -> str:
    """
    Escalate a request to your containing node.

    Use this when:
    - You need permissions you don't have
    - You need to coordinate with siblings
    - You're stuck and need guidance
    """
```

Syntactic sugar for `message_node(self.parent_id, request)`.

### 4d. `propose_new_node`

```python
@tool
async def propose_new_node(
    node_type: Literal["function", "method", "class"],
    name: str,
    source: str,
    insert_after: str | None = None  # Node ID to insert after, or None for end of parent
) -> RewriteProposal:
    """
    Propose creating a new sibling node.

    This will be inserted into your parent's body.
    The human must approve the insertion.
    """
```

**Flow:**
1. Agent proposes new function
2. Daemon computes insertion point
3. Creates a "ghost" proposal showing the new code in context
4. Human approves → daemon inserts and assigns fresh ID

### 4e. `read_node`

```python
@tool
async def read_node(target_id: str) -> str:
    """
    Read the current source code of another node.

    This is read-only. To request changes, use message_node().
    """
```

---

## 5. The Daemon Architecture

### 5a. Process Model

```
┌─────────────────────────────────────────────────────────────────┐
│                        REMORA DAEMON                             │
│                                                                  │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │   AST Watcher    │    │   Agent Runner   │                   │
│  │                  │    │                  │                   │
│  │  - inotify/fsevt │    │  - Event loop    │                   │
│  │  - Tree-sitter   │    │  - vLLM client   │                   │
│  │  - ID injection  │    │  - Tool dispatch │                   │
│  │  - SQLite writes │    │  - Rustworkx     │                   │
│  └────────┬─────────┘    └────────┬─────────┘                   │
│           │                       │                              │
│           └───────────┬───────────┘                              │
│                       │                                          │
│              ┌────────▼────────┐                                │
│              │   Event Store   │                                │
│              │    (SQLite)     │                                │
│              └────────┬────────┘                                │
│                       │                                          │
│              ┌────────▼────────┐                                │
│              │   HTTP/SSE API  │                                │
│              │   (FastAPI)     │                                │
│              └────────┬────────┘                                │
└───────────────────────┼──────────────────────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
     ┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐
     │ Neovim  │  │ Web UI    │  │  CLI    │
     │ Plugin  │  │ Dashboard │  │ remora  │
     └─────────┘  └───────────┘  └─────────┘
```

### 5b. AST Watcher

Runs continuously. On file change:

```python
async def on_file_changed(file_path: Path):
    # 1. Parse with tree-sitter
    tree = parser.parse(file_path.read_bytes())

    # 2. Extract nodes
    new_nodes = extract_nodes(tree, file_path)

    # 3. Load existing nodes for this file
    old_nodes = db.get_nodes_for_file(file_path)
    old_by_name = {(n.name, n.node_type): n for n in old_nodes}

    # 4. Match and preserve IDs
    for node in new_nodes:
        key = (node.name, node.node_type)
        if key in old_by_name:
            node.remora_id = old_by_name[key].remora_id
            del old_by_name[key]
        else:
            node.remora_id = generate_id()

    # 5. Mark unmatched old nodes as orphaned
    for orphan in old_by_name.values():
        db.set_status(orphan.remora_id, "orphaned")

    # 6. Update topology
    db.upsert_nodes(new_nodes)
    db.update_edges(new_nodes)  # Recompute calls/imports

    # 7. Re-inject IDs into file if needed
    if ids_changed(tree, new_nodes):
        inject_ids(file_path, new_nodes)

    # 8. Signal topology change
    event_store.emit(TopologyChangedEvent(file_path=file_path))
```

### 5c. Agent Runner

Event-driven execution:

```python
async def run_forever():
    async for trigger in event_store.get_triggers():
        agent_id = trigger.agent_id
        event = trigger.event
        correlation_id = trigger.correlation_id or generate_correlation_id()

        # Check activation chain
        chain = await db.get_activation_chain(correlation_id)
        if len(chain) >= MAX_DEPTH:
            await emit_error(agent_id, "Max activation depth exceeded")
            continue

        if agent_id in [e.agent_id for e in chain]:
            await emit_error(agent_id, "Cycle detected in activation chain")
            continue

        # Record this activation
        await db.add_to_chain(correlation_id, agent_id, depth=len(chain))

        # Hydrate and run
        agent = hydrate_agent(agent_id)
        try:
            result = await run_agent_turn(agent, event, correlation_id)
            await emit_complete(agent_id, result, correlation_id)
        except Exception as e:
            await emit_error(agent_id, str(e), correlation_id)
```

---

## 6. Neovim Integration

### 6a. Communication: HTTP + SSE

**Why not Unix sockets?** HTTP is simpler, debuggable (curl), and SSE provides real-time push without custom framing.

```lua
-- lua/remora/client.lua
local M = {}

M.base_url = "http://localhost:7777"

function M.request(method, path, body)
    -- Uses plenary.curl or vim.fn.system with curl
    return curl.request({
        method = method,
        url = M.base_url .. path,
        body = body and vim.json.encode(body),
        headers = { ["Content-Type"] = "application/json" }
    })
end

function M.subscribe_sse(path, on_event)
    -- Background job reading SSE stream
    vim.fn.jobstart({"curl", "-N", M.base_url .. path}, {
        on_stdout = function(_, data)
            for _, line in ipairs(data) do
                if line:match("^data: ") then
                    local json = line:sub(7)
                    on_event(vim.json.decode(json))
                end
            end
        end
    })
end

return M
```

### 6b. API Endpoints

```
GET  /nodes/{file_path}          → List nodes in file
GET  /node/{remora_id}           → Get node details + source
GET  /node/{remora_id}/events    → Recent events for node
POST /node/{remora_id}/chat      → Send message to agent
GET  /events/stream              → SSE stream of all events
GET  /events/stream/{remora_id}  → SSE stream for specific node
POST /proposal/{id}/approve      → Approve a rewrite proposal
POST /proposal/{id}/reject       → Reject with feedback
```

### 6c. Sidepanel (nui.nvim)

```
┌─────────────────────────────────────┐
│ rm_a1b2c3d4                         │
│ class ConfigLoader                  │
│ src/config.py:12-45                 │
├─────────────────────────────────────┤
│ Parent: rm_xyz (file)               │
│ Callers: rm_abc, rm_def             │
│ Callees: rm_ghi                     │
├─────────────────────────────────────┤
│ ● Active (last: 2m ago)             │
├─────────────────────────────────────┤
│ PENDING PROPOSAL                    │
│ ┌─────────────────────────────────┐ │
│ │ -    def load(self):            │ │
│ │ +    def load(self) -> dict:    │ │
│ │      ...                        │ │
│ └─────────────────────────────────┘ │
│ [Accept]  [Reject + Feedback]       │
├─────────────────────────────────────┤
│ EVENT LOG                           │
│ 14:23 ToolCall rewrite_self         │
│ 14:22 Message from rm_xyz           │
│ 14:20 AgentStart                    │
├─────────────────────────────────────┤
│ [c]hat  [r]efresh  [q]uit          │
└─────────────────────────────────────┘
```

### 6d. Diff Approval Flow

1. Agent calls `rewrite_self(new_code)`
2. Daemon emits `RewriteProposalEvent` via SSE
3. Neovim receives event, sidepanel shows diff
4. User presses `a` (accept) or `r` (reject)
5. If reject: input prompt for feedback
6. Request sent to `/proposal/{id}/approve` or `/proposal/{id}/reject`
7. If approved: daemon writes file, emits `RewriteAppliedEvent`
8. If rejected: daemon emits `RewriteRejectedEvent` → agent retries with feedback

### 6e. Cursor Tracking

```lua
vim.api.nvim_create_autocmd({"CursorMoved", "CursorMovedI"}, {
    callback = function()
        local node_id = get_node_at_cursor()  -- Parse buffer for rm_ comments
        if node_id ~= M.current_node then
            M.current_node = node_id
            M.sidepanel.update(node_id)
            M.subscribe_to_node(node_id)
        end
    end
})
```

---

## 7. Event System

### 7a. Event Types

```python
class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    timestamp: float = Field(default_factory=time.time)
    correlation_id: str | None = None

class AgentStartEvent(BaseEvent):
    agent_id: str
    trigger_event_id: str | None = None

class AgentCompleteEvent(BaseEvent):
    agent_id: str
    result: str

class AgentErrorEvent(BaseEvent):
    agent_id: str
    error: str

class AgentMessageEvent(BaseEvent):
    from_agent: str
    to_agent: str
    message: str

class RewriteProposalEvent(BaseEvent):
    agent_id: str
    proposal_id: str
    old_source: str
    new_source: str
    diff: str  # Unified diff format

class RewriteAppliedEvent(BaseEvent):
    agent_id: str
    proposal_id: str

class RewriteRejectedEvent(BaseEvent):
    agent_id: str
    proposal_id: str
    feedback: str

class TopologyChangedEvent(BaseEvent):
    file_path: str
    added_nodes: list[str]
    removed_nodes: list[str]
    orphaned_nodes: list[str]

class HumanChatEvent(BaseEvent):
    to_agent: str
    message: str
```

### 7b. Event Store

Append-only log in SQLite:

```sql
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    correlation_id TEXT,
    payload JSON NOT NULL
);

CREATE INDEX idx_events_correlation ON events(correlation_id);
CREATE INDEX idx_events_type ON events(event_type);
```

### 7c. Subscription Triggers

```sql
CREATE TABLE subscriptions (
    agent_id TEXT NOT NULL,
    event_pattern TEXT NOT NULL,  -- JSON: {"event_types": [...], "from_agents": [...]}
    PRIMARY KEY (agent_id, event_pattern)
);
```

When an event is stored:
```python
async def emit(event: BaseEvent):
    await db.insert_event(event)

    # Find matching subscriptions
    triggers = await db.match_subscriptions(event)
    for agent_id in triggers:
        await trigger_queue.put(Trigger(
            agent_id=agent_id,
            event=event,
            correlation_id=event.correlation_id
        ))
```

---

## 8. MVP Scope

### Phase 1: Core Loop (Week 1-2)
- [ ] SQLite schema for nodes, edges, events
- [ ] AST Watcher with tree-sitter (Python only)
- [ ] ID injection/preservation logic
- [ ] Basic daemon with FastAPI
- [ ] `rewrite_self` tool with file writing

### Phase 2: Agent Execution (Week 2-3)
- [ ] Agent hydration from DB
- [ ] vLLM integration for agent turns
- [ ] `message_node` with cycle detection
- [ ] Activation chain tracking
- [ ] Event-driven trigger loop

### Phase 3: Neovim UI (Week 3-4)
- [ ] HTTP client in Lua
- [ ] SSE subscription
- [ ] Sidepanel with nui.nvim
- [ ] Diff approval UI
- [ ] Cursor tracking

### Phase 4: Polish (Week 4+)
- [ ] Extension node discovery (`.remora/models/`)
- [ ] `propose_new_node` tool
- [ ] Multi-language support (JS, TS, Go)
- [ ] Web dashboard
- [ ] Ghost nodes for UI-driven creation

---

## 9. Key Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| ID format | `# rm_xxxxxxxx` at EOL | Simple, survives formatting, easy to parse |
| ID preservation | Match by (name, type) | Copy-on-write semantics, no migration needed |
| Storage | SQLite (durable) + Rustworkx (fast) | Best of both worlds |
| Communication | HTTP + SSE | Debuggable, standard, no custom protocols |
| Cycle prevention | Correlation ID chain tracking | Simple, O(1) lookup, no graph algorithms needed |
| Extension system | File-based discovery in `.remora/models/` | Zero config, Pythonic |
| Edit flow | All edits are proposals | Human stays in control |

---

## 10. Non-Goals (For MVP)

- **Multi-repo support**: Single project root only
- **Remote agents**: All execution is local
- **Persistent conversations**: Agents are stateless between turns (context from events)
- **Collaborative editing**: Single user only
- **Language server disguise**: Direct HTTP API, not LSP protocol (LSP wrapper can come later)

---

## Appendix A: Example Session

```
User opens src/config.py in Neovim
→ Daemon has already parsed file, assigned IDs
→ Sidepanel shows rm_a1b2c3d4 (class ConfigLoader)

User types in chat: "Add type hints to all methods"
→ HumanChatEvent emitted to rm_a1b2c3d4
→ Agent wakes, reads its source via context
→ Agent calls rewrite_self() with type hints added
→ RewriteProposalEvent shows diff in sidepanel

User clicks [Accept]
→ Daemon applies edit, preserves ID
→ RewriteAppliedEvent emitted
→ File updates in Neovim buffer (via autoread or explicit refresh)

Agent sees methods it calls don't have type hints
→ Agent calls message_node(rm_xyz, "Please add type hints")
→ Cycle check passes (rm_xyz not in chain)
→ rm_xyz wakes, proposes its own rewrite
→ User approves that too

Chain complete. All correlation_id entries cleaned up after 60s.
```

---

## Appendix B: File Structure

```
remora/
├── daemon/
│   ├── __main__.py          # Entry point
│   ├── watcher.py           # AST watcher + ID injection
│   ├── runner.py            # Agent execution loop
│   ├── db.py                # SQLite operations
│   ├── graph.py             # Rustworkx lazy hydration
│   └── api.py               # FastAPI + SSE endpoints
├── agent/
│   ├── base.py              # ASTAgentNode
│   ├── tools.py             # Core Grail tools
│   ├── hydration.py         # Extension discovery + injection
│   └── llm.py               # vLLM client
├── nvim/
│   └── lua/
│       └── remora/
│           ├── init.lua     # Plugin setup
│           ├── client.lua   # HTTP + SSE client
│           ├── panel.lua    # Sidepanel UI
│           ├── diff.lua     # Diff display
│           └── track.lua    # Cursor tracking
└── .remora/
    └── models/              # User extension nodes
        └── example.py
```
