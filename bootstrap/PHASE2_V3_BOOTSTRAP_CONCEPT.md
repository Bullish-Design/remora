# Phase 2 Bootstrap v3: Grail-First Semantic Swarm

> Refines v2 by grounding all agent interaction in the actual Grail/.pym/Cairn
> system, clarifying the workspace as the sole interface boundary, specifying
> graph substrate options (anchored on Rustworkx), and integrating the
> Primitives design as the canonical turn execution model.

---

## Table of Contents

1. [Core Premise](#1-core-premise)
   What v3 adds to v2's self-evolving swarm goal.

2. [What Changes from v2](#2-what-changes-from-v2)
   Diff table: tool model, graph nav, turn execution, cairn grounding.

3. [Design Principles](#3-design-principles)
   P1–P7 stand; P8 (cairn as interface boundary) and P9 (primitives as turn model) added.

4. [Semantic Graph Topology](#4-semantic-graph-topology)
   Node kinds, edge kinds, node identity. Same as v2.

5. [Graph Substrate Options](#5-graph-substrate-options)
   Rustworkx, NetworkX, SQLite property graph, Kuzu — pros/cons/implications/opportunities each.
   Recommendation and rationale.

6. [Cairn as Interface Boundary](#6-cairn-as-interface-boundary)
   How CairnExternals enforces the boundary. BootstrapExternals: the new graph + event ops.
   What .pym scripts can and cannot do.

7. [The Bootstrap Externals](#7-the-bootstrap-externals)
   Full BootstrapExternals API: file ops (inherited), graph ops (new), event ops (new).
   The .pym declaration pattern for each.

8. [Composable Turn Schemas](#8-composable-turn-schemas)
   TurnSchema absorbs TurnContract. Failure classification and retry routing.

9. [The Causal Event Bus](#9-the-causal-event-bus)
   BootstrapEvent envelope. Grounded in existing EventBus + EventStore.
   Causal graph queries.

10. [Swarm Protocols](#10-swarm-protocols)
    Typed state machines. DirectTask, ViolationResponse, CoverageGap.

11. [The Bootstrap Tool Set (.pym Edition)](#11-the-bootstrap-tool-set-pym-edition)
    All system tools as .pym scripts. Grail @external declarations. Privileged tools.

12. [Memory as a Graph Layer](#12-memory-as-a-graph-layer)
    memory.episode and memory.insight in the semantic graph. Recall via graph externals.

13. [Substrate Reflection](#13-substrate-reflection)
    Maintainer-only privileged .pym tools. Trial protocol activation. Safety constraints.

14. [Developer Inner Loop](#14-developer-inner-loop)
    CLI, synthetic harness (mock .pym externals), graph inspector, replay.

15. [Incremental Delivery Plan](#15-incremental-delivery-plan)
    M0–M8 milestones with deliverables and tests.

16. [How This Diverges from v2](#16-how-this-diverges-from-v2)
    Eight concrete changes and their rationale.

---

## 1. Core Premise

v2 states: the bootstrap builds a runtime that can inspect and evolve itself.
The swarm is the author of the next version of the swarm.

v3 accepts this goal and adds two grounding constraints that make it
implementable without ambiguity:

**Constraint 1 — Grail .pym scripts are the only agent tool interface.**
Agents do not call Python functions. They do not touch the file system
directly. Every external operation an agent performs goes through a named
`.pym` script. This is not a restriction imposed on agents — it is how the
Grail runtime works. `.pym` scripts declare `@external` dependencies, and the
Grail compiler enforces that only declared externals are available. The
bootstrap runtime controls the externals dict. Agents can only reach what the
runtime gives them.

**Constraint 2 — .pym scripts can only read and write cairn workspaces.**
The externals dict that the bootstrap runtime passes to every `.pym` script is
the `BootstrapExternals` dict: file operations (read/write/list on the agent's
cairn workspace), graph query operations (read-only graph traversal through the
semantic graph), and event operations (emit an event into the causal bus, read
recent event history). All of these are workspace-backed: the cairn layer
mediates every access. A .pym script cannot import `httpx`, open a socket, or
call `subprocess`. The Grail compiler rejects such scripts at load time.

The consequence: the entire agent capability set is **enumerable** (it is
exactly the set of registered `.pym` scripts in the system tool registry plus
the agent's own cairn workspace), **testable without a live LLM** (the
externals dict is injectable; swap real externals for mock ones), and
**auditable** (every external call is a named function with a declared
signature).

---

## 2. What Changes from v2

| Concern | v2 Approach | v3 Approach |
|---------|-------------|-------------|
| Tool interface | `BaseTool` Python classes with typed I/O | Grail `.pym` scripts exclusively |
| Tool side effects | `SideEffect` enum on Python class | Cairn workspace I/O only — enforced by Grail's `@external` system |
| Graph navigation | `InspectNode`, `QueryGraph` Python tools | `.pym` scripts calling new graph externals in `BootstrapExternals` |
| Turn execution | `TurnContract` + bespoke `TurnExecutor` | `TurnSchema` (from Primitives) + extended bootstrap runtime |
| Context assembly | Defined conceptually, not implemented | `ContextPipeline` + `ToolRef` (already in `primitives.py`) |
| User input | Not addressed | `InputGate` (already in `primitives.py`) |
| Memory access | Graph layer via direct Python API | `.pym` tools using graph externals to query memory nodes |
| Substrate reflection | `UpdateSubscription` + `RegisterProtocol` Python tools | Privileged `.pym` tools with elevated externals |
| Graph library | SQLite mentioned for persistence only | Rustworkx (in-memory traversal) + SQLite (storage + queries) |
| Grail integration | `.pym` mentioned as legacy, new Python tools preferred | `.pym` is the only tool model; Python classes replaced |
| Cairn externals | `CairnExternals` (file ops only) | `BootstrapExternals` extends with graph + event ops |
| Testing | Synthetic `SyntheticHarness` class | Mock externals dict replaces mock Python tool classes |

---

## 3. Design Principles

The v2 principles P1–P7 stand unchanged. Two additions ground them in
the actual implementation model:

### P1–P7 (from v2, unchanged)

- P1: Semantic graph over syntactic graph
- P2: Contracts before code
- P3: Failure is first-class
- P4: Causal provenance is mandatory
- P5: Testable without a live LLM
- P6: The swarm knows about itself
- P7: Protocols bound emergence

### P8: Cairn is the interface boundary

The cairn workspace is the only surface through which agents reach the
outside world. This is not an aspirational constraint — it is how the Grail
runtime is implemented. A `.pym` script can only call functions that appear in
its externals dict, and the runtime controls that dict completely.

In the bootstrap, the externals dict is `BootstrapExternals.as_externals()`.
This dict contains: file operations on the agent's cairn workspace, graph
query operations (read-only traversal of the semantic graph), and event
operations (emit into the causal bus, read recent history). Nothing else.

Consequence: adding a new agent capability means adding a new entry to
`BootstrapExternals` and writing a `.pym` script that uses it. There is no
other path.

### P9: Primitives are the canonical turn model

The six types in `primitives.py` — `str`, `ToolRef`, `Concat`, `InputGate`,
`Step`, `ContextPipeline`, `TurnSchema` — are the data model for every agent
turn. The runtime resolves a `TurnSchema` by:

1. Resolving `system` (calling any `ToolRef` pre-turn reads)
2. Running the `ContextPipeline` (each `Step` in order; outputs stored as
   `$step_name` for later steps)
3. Running the LLM loop with the declared `.pym` tool names

`bundle.yaml` + `_build_prompt()` is replaced by `TurnSchema`. No config
files, no hardcoded prompt assembly — just a data structure an agent can
build, return, and store in its cairn workspace.

---

## 4. Semantic Graph Topology

### 4.1 Node kinds

```
code.function         A callable unit of code (maps to CSTNode node_type="function")
code.class            A type definition (maps to CSTNode node_type="class")
code.file             A source file (maps to CSTNode node_type="file")
code.module           A Python module
spec.requirement      A stated capability requirement ("the system shall...")
spec.invariant        A property that must always hold
spec.contract         An explicit pre/post condition pair
test.assertion        A single test assertion tied to a spec or code node
test.case             A test function containing assertions
doc.section           A documentation section (maps to CSTNode node_type="section")
doc.example           A code example in documentation
agent.profile         A registered bootstrap agent
agent.protocol        A registered swarm protocol definition
memory.episode        A recorded interaction episode (short-horizon)
memory.insight        A distilled durable memory (long-horizon)
```

`code.*` nodes are seeded from v1's `CSTNode` objects via `discover()`. The
`node_id` for code nodes uses the same deterministic hash:
`compute_node_id(file_path, node_type, full_name)`. `AgentNode.caller_ids` and
`callee_ids` seed the initial `calls` edges. The semantic graph lives in its
own storage (SQLite `bootstrap_nodes` + `bootstrap_edges` tables) and does not
modify the existing `nodes` table used by v1.

### 4.2 Edge kinds

| Edge kind | From | To | Semantics | Activation |
|-----------|------|----|-----------|------------|
| `implements` | code.* | spec.requirement | this code satisfies this requirement | review when code changes |
| `tests` | test.* | code.* | this test exercises this code | run when code changes |
| `asserts` | test.assertion | spec.invariant | this assertion checks this invariant | index for violation detection |
| `documents` | doc.section | code.* | this doc describes this code | update when code changes |
| `violates` | code.* | spec.invariant | this code violates this invariant | immediately activates ViolationResponse |
| `proposes_change_to` | agent.profile | code.* | open proposal against this code | activates review protocol |
| `coordinates` | agent.profile | agent.profile | first agent delegates to second | routing hint |
| `caused_by` | any | event | this node exists because of this event | causal provenance |
| `remembers` | memory.episode | any | this episode involves this node | memory recall |
| `concerns` | memory.insight | any | this insight is about this node | insight recall |
| `specializes` | agent.profile | agent.profile | first is a specialization of second | capability inheritance |
| `calls` | code.function | code.function | direct call relationship (from caller_ids) | seeded from v1 |

### 4.3 Node identity

```python
node_id = stable_hash(kind, canonical_name, anchor)
```

For `code.*` nodes: `anchor` is the file path + qualified name (same as
`compute_node_id` in v1). For `spec.*`, `doc.*`, `agent.*`, `memory.*` nodes:
`anchor` is a human-assigned slug. This makes IDs stable across restarts.

### 4.4 Graph as activation fabric

When an agent creates a `violates` edge, the ViolationResponse protocol
activates — because violation-watcher agents subscribe to
`BootstrapEdgeCreatedEvent(edge_kind="violates")` via `SubscriptionPattern`.
Edge creation is an event. The graph and the event bus are peers: mutations to
the graph emit events; events can trigger graph mutations.

---

## 5. Graph Substrate Options

The semantic graph must be queryable through cairn `.pym` tools. The graph
library backs the `BootstrapExternals` graph query functions — agents never
touch it directly. Below are the realistic options.

### Requirements

- Store typed nodes (kind, node_id, attribute dict) and typed edges (kind,
  from_node, to_node, attribute dict)
- Efficient neighborhood queries: "all edges of kind K from node N"
- Multi-hop traversal: "causal ancestors of event E"
- Pattern queries: "all function nodes with no `tests` edges"
- Cycle detection (protocol deadlock)
- Persistence across restarts
- Fast enough for agent-frequency queries (dozens per turn, not millions)

---

### Option A: Rustworkx + SQLite (Recommended)

**What it is:** [rustworkx](https://github.com/Qiskit/rustworkx) is a
Rust-backed directed graph library from the Qiskit project. Used here as an
in-memory traversal engine, with SQLite as the durable backing store.

**Pros:**
- Rust-speed traversal: shortest path, cycle detection, topological sort,
  strongly connected components — all at native speed, no Python overhead
- `PyDiGraph` supports arbitrary Python objects as node/edge attributes
- Actively maintained, MIT license, `pip install rustworkx` — no native build
  tools required
- Cycle detection maps directly to protocol deadlock detection; shortest path
  maps directly to causal depth; topological sort maps to build dependency order
- Scales to millions of nodes without hitting Python's GC pressure

**Cons:**
- No native persistence: requires a SQLite serialize/deserialize layer
- No native property graph query language: neighborhood queries are Python
  loops over edge lists returned by `rustworkx` API calls
- Documentation is quantum-computing-flavored; the general graph API requires
  reading source or the API reference directly
- Must track the mapping `node_id (str) → rustworkx index (int)` since
  rustworkx uses integer node indices internally

**Implications:**
- Two systems: Rustworkx for traversal algorithms, SQLite for persistence and
  rich neighborhood queries
- On startup: load graph from SQLite into Rustworkx (fast — SQLite reads are
  cheap for <100k nodes)
- On shutdown / checkpoint: serialize Rustworkx back to SQLite
- Simple neighborhood queries (`inspect_node`, `query_graph`) go directly to
  SQLite (no need to touch Rustworkx for read-only lookups)
- Rustworkx invoked when algorithmic queries are needed: cycle detection,
  causal chain depth, transitive closure

**Opportunities:**
- All Rustworkx algorithms become available for free: topological sort for
  ordered dependency resolution, SCC analysis for detecting circular
  imports/invariants, minimum spanning tree for protocol simplification
- Because Rustworkx is indexed by integer, it can be used as a fast in-memory
  join layer: "give me all nodes reachable from node X within 3 hops" is a
  single Rustworkx call that returns a list of integers, then batch-resolved
  from the `str → int` index to get node IDs

---

### Option B: NetworkX + SQLite

**What it is:** [NetworkX](https://networkx.org/) is the de facto standard
Python graph library. Same hybrid model as Option A but pure Python.

**Pros:**
- Best documentation of any Python graph library; well-known by all Python
  developers; extensive Stack Overflow coverage
- Most Pythonic API: `G.nodes[n]` is a dict, `G.edges(n, data=True)` is a
  generator, graph operations compose naturally
- Richest algorithm coverage in Python: NetworkX has more algorithms than
  Rustworkx
- Excellent ecosystem: graph visualization (matplotlib, Graphviz), analysis
  tools, all speak NetworkX natively
- Easiest to debug: no integer index mapping, node IDs are strings directly

**Cons:**
- Pure Python: 10–50× slower than Rustworkx for large traversals
- Higher memory overhead per node/edge (Python dicts vs Rust structs)
- For Remora's expected graph sizes (<50k nodes in any realistic codebase),
  this performance gap is academic — the bottleneck is LLM API latency, not
  graph traversal

**Implications:**
- Identical hybrid model to Option A: NetworkX in memory, SQLite for
  persistence
- No integer index mapping needed (strings as node IDs directly)
- Could swap to Rustworkx later if profiling shows graph traversal is
  actually a bottleneck — both expose similar DiGraph semantics

**Opportunities:**
- Lower barrier to contribution: most Python developers can read NetworkX code
  without the Rustworkx learning curve
- Cleaner debugging experience during initial development

---

### Option C: SQLite Property Graph (Custom)

**What it is:** Skip the in-memory graph library entirely. The graph lives
exclusively in SQLite as a property graph schema:

```sql
CREATE TABLE bootstrap_nodes (
    node_id      TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    canonical_name TEXT,
    attrs        TEXT  -- JSON
);

CREATE TABLE bootstrap_edges (
    edge_id      TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    from_node    TEXT REFERENCES bootstrap_nodes(node_id),
    to_node      TEXT REFERENCES bootstrap_nodes(node_id),
    attrs        TEXT  -- JSON
);

CREATE INDEX idx_edges_from_kind ON bootstrap_edges(from_node, kind);
CREATE INDEX idx_edges_to_kind   ON bootstrap_edges(to_node, kind);
CREATE INDEX idx_nodes_kind      ON bootstrap_nodes(kind);
```

**Pros:**
- Zero new dependencies: SQLite already used for EventStore,
  SubscriptionRegistry, and v1's NodeStore
- Native persistence: no serialize/deserialize cycle; graph mutations are
  immediately durable
- SQL expressiveness: complex multi-condition queries are natural
  (e.g., "functions with `implements` edges but no `tests` edges" is a
  LEFT JOIN + WHERE NULL)
- Neighborhood queries are fast with proper indexes (covered by the indexes above)
- Can JOIN graph data with event log easily (same database file)

**Cons:**
- No native graph algorithms: cycle detection requires recursive CTEs or
  loading a subgraph into Python for traversal — both are complex
- Each traversal hop is a SQL round-trip; deep causal chains need either
  recursive CTEs or Python loop + multiple queries
- `WITH RECURSIVE` CTEs for transitive closure are correct but hard to read
  and maintain

**Implications:**
- This is essentially what v2 described (SQLite persistence)
- Works well for all neighborhood queries agents actually make (node
  inspection, edge traversal 1–2 hops)
- Algorithmic queries (deadlock detection, causal depth) require either
  recursive SQL or pulling a subgraph into Python

**Opportunities:**
- Simplest implementation path; highest confidence in correctness
- Can add Rustworkx as a targeted accelerator layer later without changing
  the storage model or the externals API

---

### Option D: Kuzu (Embedded Graph Database)

**What it is:** [Kuzu](https://kuzudb.com/) is an embedded ACID graph
database with columnar storage and openCypher query language. Analogous to
DuckDB but for property graphs.

**Pros:**
- Native property graph model with typed schemas for nodes and edges
- Cypher query language: expressive, readable, purpose-built for graph
  traversal. "Find all functions with no test coverage" is readable Cypher:
  ```cypher
  MATCH (f:code_function)
  WHERE NOT EXISTS { MATCH (f)<-[:tests]-() }
  RETURN f.node_id
  ```
- ACID transactions: concurrent graph mutations are safe
- Built-in persistence with columnar storage (fast for analytics)
- Actively maintained, Python API, MIT license, `pip install kuzu`

**Cons:**
- New dependency with a learning curve for contributors unfamiliar with Cypher
- Younger project: smaller community, less production track record than SQLite
- No native Python graph algorithm library integration (can't pass a Kuzu
  graph directly to NetworkX or Rustworkx)
- Adds schema migration complexity (Kuzu has typed node/edge tables that must
  be created upfront, not free-form dicts)

**Implications:**
- Graph queries from `.pym` externals would ultimately execute Cypher strings
- The most expressive option for complex pattern matching across many edge kinds
- Positions the graph as a genuine queryable database, not a runtime artifact

**Opportunities:**
- Could expose a `query_graph_cypher` external for privileged agents, enabling
  arbitrary semantic graph queries without new Python code
- Best fit if the semantic graph becomes a platform feature consumed by many
  external tools

---

### Recommendation

**Option A (Rustworkx + SQLite)** for v3. Rationale:

1. **SQLite for storage and neighborhood queries.** The `inspect_node` and
   `query_graph` externals resolve almost entirely against SQLite with the
   indexes above. SQLite is already in the project and requires zero new
   dependencies.

2. **Rustworkx for algorithmic queries.** Cycle detection (protocol deadlock),
   causal depth (max_depth guard), and transitive closure (causal scope for
   undo semantics) are the only cases that need a real graph algorithm. Load
   the relevant subgraph into Rustworkx on demand; discard after the query.

3. **Clear upgrade path to Kuzu.** If the semantic graph becomes a platform
   feature or the `query_graph_cypher` external becomes useful, the SQLite
   backing can be replaced with Kuzu without changing the externals API.

Option B is viable and has lower initial friction. Prefer it if the team
wants to start without a new dependency and profile first. The switch from
NetworkX to Rustworkx is low-effort since both use similar DiGraph semantics.

Option C works for M0–M3 without any in-memory library. Add Option A at M4
when deadlock detection is needed.

---

## 6. Cairn as Interface Boundary

### 6.1 How the boundary works in v1

In v1, `CairnExternals.as_externals()` returns the dict that the Grail runtime
passes to every `.pym` script. This dict is the complete set of external
functions the script can call:

```python
# v1 CairnExternals.as_externals() — the full dict today
{
    "read_file":      self.read_file,       # read from agent cairn workspace
    "write_file":     self.write_file,      # write to agent cairn workspace
    "list_dir":       self.list_dir,        # list workspace directory
    "file_exists":    self.file_exists,     # check file existence
    "search_files":   self.search_files,    # glob pattern search
    "search_content": self.search_content,  # content regex search
    "submit_result":  self.submit_result,   # declare turn complete + changed files
    "log":            self.log,             # structured logging
}
```

A `.pym` script that tries to use any function not in this dict gets a
compile-time error from the Grail runtime. There is no escape hatch.

### 6.2 BootstrapExternals: extending the boundary

The bootstrap runtime introduces `BootstrapExternals`, which extends
`CairnExternals` with two new categories:

**Graph operations** (read-only, backed by SQLite + Rustworkx):
```python
"inspect_node":       self.inspect_node,       # node details + neighbors
"query_graph":        self.query_graph,         # edge pattern query
"trace_causal_chain": self.trace_causal_chain,  # causal ancestors/descendants
"find_nodes":         self.find_nodes,           # nodes by kind + attrs
```

**Event operations** (write into event slot; runtime drains to EventBus):
```python
"emit_event":         self.emit_event,          # emit into causal bus
"read_recent_events": self.read_recent_events,  # read event history for a node
```

Everything else is inherited from `CairnExternals`. The externals dict passed
to privileged agents (maintainer role) additionally includes:

```python
"update_subscription": self.update_subscription,  # privileged: modify subscriptions
"register_protocol":   self.register_protocol,    # privileged: add new protocol
```

### 6.3 What .pym scripts can and cannot do

**Can do:**
- Read from the agent's cairn workspace (file layer)
- Write to the agent's cairn workspace (file layer)
- Query the semantic graph (graph ops — read-only, returns JSON strings)
- Emit events into the causal bus (event op — write, mediated by runtime)
- Read recent event history for nodes (event op — read-only)
- Log messages (structured, goes to runtime logger)
- Submit turn result (file layer — declares which files changed)

**Cannot do:**
- Import arbitrary Python modules (Grail compiler enforces this)
- Make network calls (no external in the dict for it)
- Access the file system outside the cairn workspace (paths are normalized
  through `PathResolver.to_workspace_path()`)
- Directly mutate the semantic graph (no `add_node`, `add_edge` external;
  graph mutations happen through event processing, not direct API calls)
- Access another agent's cairn workspace (each agent gets its own externals
  instance bound to its own workspace)

### 6.4 System tools vs. agent-local tools

**System tools** are `.pym` scripts maintained by the bootstrap runtime and
available to any agent that declares them in `TurnSchema.tools`. They live in
the bootstrap `tools/` directory and are discovered at startup via
`discover_grail_tools()`. They use `BootstrapExternals` (the full dict).

**Agent-local tools** are `.pym` scripts an agent writes to its own cairn
workspace via `write_file`. They are available only to the owning agent and
use only the externals available to that agent's role. An agent with `proposal`
role cannot write a local tool that uses `register_protocol` — that external
isn't in its dict.

The Tool Synthesis mechanism from the Primitives Walkthrough (Appendix III) is
how agent-local tools come into being: an agent writes a `.pym` file to its
workspace, emits a schema that references it, and the runtime discovers and
loads it from the workspace on the next turn.

---

## 7. The Bootstrap Externals

Full `BootstrapExternals` API. Each external is callable from `.pym` scripts
via the `@external` declaration pattern.

### File operations (inherited from CairnExternals)

```python
# In a .pym script:
@external
async def read_file(path: str) -> str: ...
# Returns file content as string. Returns "" if file does not exist.
# path is relative to the agent's cairn workspace root.

@external
async def write_file(path: str, content: str) -> bool: ...
# Writes content to agent cairn workspace. Returns True on success.

@external
async def list_dir(path: str = ".") -> list[str]: ...
# Lists workspace directory entries (names only, not full paths).

@external
async def file_exists(path: str) -> bool: ...

@external
async def search_files(pattern: str) -> list[str]: ...
# Glob pattern search within the cairn workspace.

@external
async def search_content(pattern: str, path: str = ".") -> list[Any]: ...
# Regex content search within the cairn workspace.

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool: ...
# Signal turn completion. changed_files are workspace-relative paths.

@external
async def log(message: str) -> bool: ...
```

### Graph operations (new in BootstrapExternals)

```python
@external
async def inspect_node(node_id: str, include_neighbors: bool = True) -> str: ...
# Returns JSON:
# {
#   "node_id": "...",
#   "kind": "code.function",
#   "canonical_name": "...",
#   "attrs": {...},
#   "neighbors": [
#     {"edge_kind": "tests", "direction": "in", "other_node_id": "..."},
#     ...
#   ]
# }
# Returns "{}" if node not found.

@external
async def query_graph(
    edge_kind: str,
    from_node: str | None = None,   # node_id filter on from side
    to_node: str | None = None,     # node_id filter on to side
    from_kind: str | None = None,   # node kind filter on from side
    to_kind: str | None = None,     # node kind filter on to side
    limit: int = 20,
) -> str: ...
# Returns JSON list of matching edges:
# [{"edge_id": "...", "kind": "...", "from_node": "...", "to_node": "...",
#   "attrs": {...}}, ...]

@external
async def find_nodes(
    kind: str | None = None,
    attr_filter: str = "{}",  # JSON dict of attr key/value pairs to match
    limit: int = 20,
) -> str: ...
# Returns JSON list of matching nodes.
# attr_filter is a JSON-encoded dict (string values match by equality).

@external
async def trace_causal_chain(
    event_id: str,
    direction: str = "descendants",  # "ancestors" | "descendants"
    max_depth: int = 10,
) -> str: ...
# Traverses causal_parent_id links. Uses Rustworkx for depth calculation.
# Returns JSON list of event summaries:
# [{"event_id": "...", "event_type": "...", "depth": 2, "agent_id": "..."}, ...]
```

### Event operations (new in BootstrapExternals)

```python
@external
async def emit_event(event_type: str, payload: str, target_node_id: str = "") -> str: ...
# payload is JSON-encoded string.
# Writes to the cairn event slot; runtime injects into EventBus with correct
# causal envelope (causal_parent_id, depth, correlation_id set by runtime).
# Returns JSON: {"event_id": "...", "depth": N}

@external
async def read_recent_events(
    node_id: str = "",
    event_types: str = "",     # comma-separated event type names, "" = all
    limit: int = 10,
) -> str: ...
# Queries EventStore for recent events involving node_id.
# Returns JSON list of event summaries.
```

### Privileged operations (maintainer role only)

```python
@external
async def update_subscription(
    agent_id: str,
    add_patterns: str,    # JSON list of SubscriptionPattern dicts
    remove_patterns: str, # JSON list of pattern IDs to remove
) -> str: ...
# Returns JSON: {"active_patterns": [...]}

@external
async def register_protocol(protocol_definition: str) -> str: ...
# protocol_definition is a JSON-encoded SwarmProtocol.
# Validates guards (max_depth >= 2, timeout > 0, etc.).
# Returns JSON: {"protocol_id": "...", "status": "trial"}
```

---

## 8. Composable Turn Schemas

### 8.1 TurnSchema absorbs TurnContract

v2 proposed a `TurnContract` with `requires`, `produces`, `allowed_tools`,
`budget`, and `on_failure` fields. In v3, the `TurnSchema` from `primitives.py`
is the execution unit:

```python
TurnSchema(
    system=...,          # PromptNode — resolved before the LLM sees anything
    context=ContextPipeline(steps=(
        Step("source", ToolRef("read_file", {"path": "$node.file_path"})),
        Step("history", ToolRef("read_recent_events", {"node_id": "$node.id"})),
    )),
    tools=("propose_patch", "emit_event", "write_file"),  # .pym names
    max_turns=5,
    termination="done",
)
```

`tools` contains `.pym` script names (without the `.pym` extension). The
executor resolves them by looking up the bootstrap system tool registry and the
agent's own cairn workspace (for agent-local tools).

The `ToolRef` calls in `ContextPipeline` are **pre-turn reads** — they call
`.pym` tools during context assembly, before the LLM sees the prompt. The LLM
never sees these as tool calls; it sees their resolved string output.

The `tools` in `TurnSchema.tools` are **interactive tools** — the LLM calls
them during its turn via the standard tool-use protocol.

All pre-turn reads and interactive tools go through the same `.pym` execution
engine with the same `BootstrapExternals` dict. There is no separate tool
execution path.

### 8.2 Failure classification

Every turn completes with one of these outcomes (from v2, unchanged):

| Outcome | Meaning | Routing |
|---------|---------|---------|
| `SUCCESS` | Turn produced expected output | Continue protocol |
| `PARSE_FAILURE` | LLM did not produce structured output | Retry with parse-focused reprompt |
| `SCHEMA_MISMATCH` | Tool call args didn't match tool schema | Emit diagnostic, retry once |
| `POLICY_DENIAL` | Agent called a tool not in `TurnSchema.tools` | Hard fail |
| `BUDGET_EXCEEDED` | `max_turns` exhausted | Terminate, emit partial result |
| `TIMEOUT` | Wall-clock limit exceeded | Terminate, emit diagnostic |
| `RUNTIME_ERROR` | Unhandled exception in `.pym` execution | Emit error event |

The active protocol's `on_failure` state determines routing. The executor does
not retry indefinitely: it applies `Retry(max=2)` for `PARSE_FAILURE`, then
routes to the protocol's failure state.

### 8.3 Schema storage and evolution

An agent stores its `TurnSchema` in its cairn workspace as `schema.json` (via
the `emit_schema` system tool). The runtime loads this on every activation. If
no `schema.json` exists, the runtime falls back to `DEFAULT_SCHEMA`.

An agent can update its schema at any time by calling `emit_schema` again.
Another agent can propose a schema change via `propose_patch` targeting the
agent's `schema.json`. The normal review protocol applies.

---

## 9. The Causal Event Bus

### 9.1 Grounding in v1 EventBus

v1's `EventBus` (`core/events/event_bus.py`) provides:
- Type-based subscription with MRO resolution
- Async/sync handler dispatch
- `stream()` async context manager
- `wait_for(event_type, predicate, timeout)` for synchronization

The bootstrap uses this EventBus directly. `BootstrapEvent` subclasses are
registered as new event types that the existing v1 `EventBus` dispatches.
The `EventStore` (`core/store/event_store.py`) persists them via its existing
SQLite WAL-mode write path.

### 9.2 BootstrapEvent envelope

Every bootstrap event extends `BootstrapEvent`:

```python
@dataclass(frozen=True)
class BootstrapEvent:
    event_id: str              # UUID
    event_type: str            # discriminator (class name)
    correlation_id: str        # top-level user request or workflow ID
    causal_parent_id: str | None  # event that triggered this one
    depth: int                 # causal depth from root (0 for root events)
    agent_id: str | None       # bootstrap agent that emitted this
    timestamp: float           # unix timestamp
    payload: dict              # event-specific data
```

When an agent calls the `emit_event` external, the runtime:
1. Reads the current turn's `correlation_id` and `causal_parent_id` from
   the turn context
2. Sets `depth = causal_parent_depth + 1`
3. Constructs the `BootstrapEvent` with these fields
4. Appends it to `EventStore` via the existing `append()` path
5. Emits it on the `EventBus`

The agent's `.pym` script never sets `causal_parent_id` or `depth` — the
runtime sets them. This enforces causal provenance without trusting agents.

### 9.3 Causal graph queries

The `trace_causal_chain` external queries the `causal_parent_id` chain in the
`EventStore`. For depth calculation and cycle detection, it loads the relevant
event subgraph into Rustworkx on demand:

```python
# Pseudocode for trace_causal_chain("event-id-abc", direction="descendants")
events = event_store.get_causal_descendants("event-id-abc")
g = rustworkx.PyDiGraph()
node_map = {}
for ev in events:
    if ev.event_id not in node_map:
        node_map[ev.event_id] = g.add_node(ev)
    if ev.causal_parent_id and ev.causal_parent_id in node_map:
        g.add_edge(node_map[ev.causal_parent_id], node_map[ev.event_id], None)
return rustworkx.dag_longest_path_length(g)  # max depth
```

This is the pattern: SQLite for storage and lookup, Rustworkx invoked on
demand for the algorithmic query, then discarded.

### 9.4 Depth and budget enforcement

Depth is tracked per-event, not per-agent. The `ProtocolEngine` checks
`event.depth` against the active protocol's `max_depth` guard before
dispatching the event to the next protocol state. Events that exceed
`max_depth` are routed to the protocol's failure state with a
`BUDGET_EXCEEDED` outcome — they are not silently dropped.

---

## 10. Swarm Protocols

### 10.1 Protocol anatomy

```python
@dataclass(frozen=True)
class SwarmProtocol:
    name: str
    trigger: EventPattern          # event pattern that starts this protocol
    states: tuple[ProtocolState, ...]
    guards: ProtocolGuards

@dataclass(frozen=True)
class ProtocolState:
    name: str
    agent_role: str                # role name, matched to agent.profile nodes
    turn_schema: TurnSchema        # the TurnSchema for this state
    on_success: str                # state name to advance to
    on_failure: str                # state name on failure ("terminal" for end)

@dataclass(frozen=True)
class ProtocolGuards:
    max_depth: int           # causal chain depth limit (min 2)
    max_loops: int           # times the same state can be revisited
    timeout_seconds: float   # wall-clock limit for the whole protocol
    require_progress: bool   # each loop must advance state
```

### 10.2 Initial protocol set

**DirectTask** — user intent → result
```
trigger:    BootstrapUserIntentEvent
states:
  intaking:     orchestrator / TaskIntake schema → planning | failed
  planning:     orchestrator / PlanDecompose schema → executing | human_review
  executing:    editor / ImplementPlan schema → reviewing | failed
  reviewing:    reviewer / ReviewOutput schema → done | executing (max_loops=2)
  done:         [terminal]
  human_review: [terminal, escalate]
  failed:       [terminal, emit diagnostic]
guards: max_depth=10, max_loops=2, timeout=300s
```

**ViolationResponse** — detected invariant violation → fix
```
trigger:    BootstrapEdgeCreatedEvent(edge_kind="violates")
states:
  triaging:   reviewer / ViolationTriage schema → patching | dismissed
  patching:   editor / ProposePatch schema → verifying | failed
  verifying:  reviewer / VerifyPatch schema → applying | patching (max_loops=2)
  applying:   maintainer / ApplyPatch schema → done | failed
  dismissed:  [terminal]
  done:       [terminal]
  failed:     [terminal, emit diagnostic]
guards: max_depth=8, max_loops=2, timeout=120s
```

**CoverageGap** — missing test coverage → new test proposed
```
trigger:    BootstrapEdgeRemovedEvent(edge_kind="tests") |
            BootstrapNodeDiscoveredEvent(uncovered=True)
states:
  assessing:  reviewer / AssessCoverage schema → generating | dismissed
  generating: editor / GenerateTest schema → reviewing | failed
  reviewing:  reviewer / ReviewTest schema → done | generating (max_loops=2)
  done:       [terminal]
guards: max_depth=6, max_loops=2, timeout=90s
```

### 10.3 Deadlock detection

The `ProtocolEngine` runs Rustworkx cycle detection on the active state graph
after each state transition. A cycle that involves `require_progress=True`
guards is flagged immediately: the cycle cannot make progress, so it is
terminated and a `ProtocolDeadlockEvent` is emitted. This replaces the
informal "agents waiting for each other" failure mode with a typed, detectable,
routable error.

---

## 11. The Bootstrap Tool Set (.pym Edition)

All system tools are `.pym` scripts discovered by `discover_grail_tools()` at
startup. They use `@external` to declare which `BootstrapExternals` functions
they need. The scripts live in `bootstrap/tools/`.

### Graph tools

**`inspect_node.pym`** — node details and neighborhood
```python
from grail import Input, external

node_id: str = Input("node_id", description="Node ID to inspect")
include_neighbors: bool = Input("include_neighbors", default=True)

@external
async def inspect_node(node_id: str, include_neighbors: bool = True) -> str: ...

result = await inspect_node(node_id, include_neighbors)
result  # JSON string: {node_id, kind, canonical_name, attrs, neighbors}
```

**`query_graph.pym`** — edge pattern query
```python
from grail import Input, external

edge_kind: str = Input("edge_kind")
from_node: str = Input("from_node", default="")
to_node:   str = Input("to_node",   default="")
from_kind: str = Input("from_kind", default="")
to_kind:   str = Input("to_kind",   default="")
limit:     int = Input("limit",     default=20)

@external
async def query_graph(edge_kind, from_node, to_node, from_kind, to_kind, limit) -> str: ...

result = await query_graph(edge_kind, from_node or None, to_node or None,
                            from_kind or None, to_kind or None, limit)
result  # JSON list of matching edges
```

**`find_nodes.pym`** — nodes by kind and attributes
```python
from grail import Input, external

kind:        str = Input("kind",        default="")
attr_filter: str = Input("attr_filter", default="{}")
limit:       int = Input("limit",       default=20)

@external
async def find_nodes(kind, attr_filter, limit) -> str: ...

result = await find_nodes(kind or None, attr_filter, limit)
result
```

**`trace_causal_chain.pym`** — causal ancestry traversal
```python
from grail import Input, external

event_id:  str = Input("event_id")
direction: str = Input("direction", default="descendants")
max_depth: int = Input("max_depth", default=10)

@external
async def trace_causal_chain(event_id, direction, max_depth) -> str: ...

result = await trace_causal_chain(event_id, direction, max_depth)
result  # JSON list of event summaries with depth field
```

### Event tools

**`emit_event.pym`** — emit into the causal bus
```python
from grail import Input, external
import json

event_type:     str = Input("event_type")
payload:        str = Input("payload",        default="{}")
target_node_id: str = Input("target_node_id", default="")

@external
async def emit_event(event_type, payload, target_node_id) -> str: ...

result = await emit_event(event_type, payload, target_node_id)
result  # JSON: {"event_id": "...", "depth": N}
```

**`read_recent_events.pym`** — event history for a node
```python
from grail import Input, external

node_id:     str = Input("node_id",     default="")
event_types: str = Input("event_types", default="")
limit:       int = Input("limit",       default=10)

@external
async def read_recent_events(node_id, event_types, limit) -> str: ...

result = await read_recent_events(node_id, event_types, limit)
result  # JSON list of event summaries
```

### Schema tools

**`emit_schema.pym`** — store a TurnSchema in cairn workspace
```python
from grail import Input, external

schema_json: str = Input("schema_json", description="JSON-encoded TurnSchema")

@external
async def write_file(path: str, content: str) -> bool: ...

# Validate and store the schema
await write_file("schema.json", schema_json)
{"stored": True}
```

### Proposal tools

**`propose_patch.pym`** — structured code change proposal
```python
from grail import Input, external
import json

target_node_id: str   = Input("target_node_id")
patch_content:  str   = Input("patch_content")
rationale:      str   = Input("rationale")
confidence:     float = Input("confidence", default=0.8)

@external
async def emit_event(event_type, payload, target_node_id) -> str: ...

payload = json.dumps({
    "target_node_id": target_node_id,
    "patch_content": patch_content,
    "rationale": rationale,
    "confidence": confidence,
})
result = await emit_event("ProposePatchEvent", payload, target_node_id)
result  # {"event_id": "...", "depth": N}
```

### Privileged tools (maintainer role only)

**`update_subscription.pym`** — modify agent subscriptions
```python
from grail import Input, external

agent_id:        str = Input("agent_id")
add_patterns:    str = Input("add_patterns",    default="[]")
remove_patterns: str = Input("remove_patterns", default="[]")

@external
async def update_subscription(agent_id, add_patterns, remove_patterns) -> str: ...

result = await update_subscription(agent_id, add_patterns, remove_patterns)
result  # JSON: {"active_patterns": [...]}
```

**`register_protocol.pym`** — register a new SwarmProtocol
```python
from grail import Input, external

protocol_definition: str = Input("protocol_definition")

@external
async def register_protocol(protocol_definition: str) -> str: ...

result = await register_protocol(protocol_definition)
result  # JSON: {"protocol_id": "...", "status": "trial"}
```

---

## 12. Memory as a Graph Layer

### 12.1 Memory is not a blob

Memory lives in the semantic graph as two node kinds:

**`memory.episode`** — a recorded interaction (short-horizon, ephemeral)
- `attrs`: `{correlation_id, summary, participating_agents, outcome, timestamp, ttl_seconds}`
- `remembers` edges to every node that was involved in the interaction
- Eviction: episodes older than `ttl_seconds` are archived (edges removed,
  content cleared, event log entry kept for causal provenance)

**`memory.insight`** — a distilled durable observation (long-horizon, persistent)
- `attrs`: `{content, confidence, source_episodes, created_at, last_reinforced_at}`
- `concerns` edges to relevant code/spec/agent nodes
- Created by the `bootstrap_maintainer` agent when patterns emerge across
  multiple episodes
- Eviction: only via explicit `ClearInsightEvent` or confidence decay below
  threshold

### 12.2 Memory recall via graph externals

An agent that needs context about a node uses `query_graph` and `find_nodes`:

```python
# In a .pym script's context pipeline (ToolRef in ContextPipeline):

# What recent episodes involved this function?
episodes_json = await query_graph(
    edge_kind="remembers",
    to_node=node_id,
    to_kind="code.function",
    from_kind="memory.episode",
    limit=5,
)

# What durable insights concern this module?
insights_json = await query_graph(
    edge_kind="concerns",
    to_node=module_id,
    from_kind="memory.insight",
    limit=10,
)
```

Results are JSON strings the agent includes in its `ContextPipeline` output.
No separate memory API — the graph externals serve memory recall.

### 12.3 Episode recording

At the end of each protocol run, the `ProtocolEngine` emits a
`ProtocolCompleteEvent`. The `bootstrap_maintainer` agent subscribes to this
event and creates a `memory.episode` node in the graph, adding `remembers`
edges to every node that appeared in the correlation chain (queried via
`trace_causal_chain`).

### 12.4 Cross-agent memory sharing

Because memory is in the shared semantic graph (not per-agent workspace),
any agent with read access can query it via `query_graph`. An orchestrator
checks whether a similar task was attempted before. A reviewer recalls whether
a specific node was found problematic in prior interactions. Memory is a shared
resource, not a per-agent silo.

---

## 13. Substrate Reflection

### 13.1 The meta-loop

The `bootstrap_maintainer` agent has `update_subscription` and
`register_protocol` in its externals dict (privileged role). The
`bootstrap_orchestrator` can propose new `agent.protocol` graph nodes via
`propose_patch`. The `bootstrap_reviewer` reviews proposed protocol changes
before they are applied.

The swarm can:
1. Notice a recurring task pattern not covered by any protocol
2. Propose a new protocol definition as a `agent.protocol` graph node
3. Have the reviewer validate it (depth bounds, required capabilities, state
   completeness)
4. Apply it via `register_protocol`, making it active for future triggering

### 13.2 Safety constraints

- Only the `maintainer` role can call `update_subscription` and
  `register_protocol` — these externals are not in other agents' dicts
- Protocol proposals go through ViolationResponse-style review before activation
- Newly registered protocols are tagged `"status": "trial"` for the first N
  activations; failures during trial disable the protocol and emit
  `TrialProtocolFailedEvent`
- `register_protocol` validates `ProtocolGuards` at registration time:
  `max_depth >= 2`, `timeout_seconds > 0`, all state `on_success`/`on_failure`
  targets must be defined states
- No agent can modify another agent's cairn workspace directly; they can only
  propose changes via `propose_patch` targeting the agent's `schema.json` or
  `role.md`

---

## 14. Developer Inner Loop

### 14.1 Running a single turn

```bash
# Synthetic mode — no LLM, mock externals
remora-bootstrap run --synthetic --protocol DirectTask \
    --input '{"objective": "explain the EventStore append path"}'

# Live LLM mode
remora-bootstrap run --protocol DirectTask \
    --input '{"objective": "explain the EventStore append path"}'
```

Output (structured):
```
[TURN] DirectTask / intaking
  schema: TaskIntake (tools: inspect_node, query_graph, read_recent_events)
  agent: bootstrap_orchestrator
  pre-turn reads: [inspect_node("fn:core.store.event_store.append")]
[EVENT] TurnCompleteEvent(outcome=SUCCESS)
[STATE] → planning

[TURN] DirectTask / planning
  ...
[EVENT] TurnCompleteEvent(outcome=PARSE_FAILURE, reason=structured_output_missing)
[RETRY] 1/2 with parse-focused reprompt
[EVENT] TurnCompleteEvent(outcome=SUCCESS)
[STATE] → executing
```

### 14.2 Synthetic test harness

The synthetic harness swaps the real `BootstrapExternals` for a mock dict:

```python
class MockExternals:
    """Injectable externals for deterministic testing."""

    def __init__(self):
        self._files: dict[str, str] = {}
        self._graph_nodes: dict[str, dict] = {}
        self._graph_edges: list[dict] = []
        self._emitted_events: list[dict] = []

    async def read_file(self, path: str) -> str:
        return self._files.get(path, "")

    async def write_file(self, path: str, content: str) -> bool:
        self._files[path] = content
        return True

    async def inspect_node(self, node_id: str, include_neighbors: bool = True) -> str:
        import json
        return json.dumps(self._graph_nodes.get(node_id, {}))

    async def query_graph(self, edge_kind, from_node=None, to_node=None,
                          from_kind=None, to_kind=None, limit=20) -> str:
        import json
        matches = [e for e in self._graph_edges
                   if e["kind"] == edge_kind
                   and (from_node is None or e["from_node"] == from_node)
                   and (to_node is None or e["to_node"] == to_node)]
        return json.dumps(matches[:limit])

    async def emit_event(self, event_type, payload, target_node_id="") -> str:
        import json, uuid
        event_id = str(uuid.uuid4())
        self._emitted_events.append({
            "event_id": event_id, "event_type": event_type, "payload": payload
        })
        return json.dumps({"event_id": event_id, "depth": 0})

    # ... read_recent_events, find_nodes, trace_causal_chain, etc.

    def as_externals(self) -> dict:
        return {
            "read_file": self.read_file,
            "write_file": self.write_file,
            "inspect_node": self.inspect_node,
            "query_graph": self.query_graph,
            "emit_event": self.emit_event,
            # ...
        }


def test_propose_patch_tool():
    externals = MockExternals()
    externals._graph_nodes["fn:my_module.my_fn"] = {
        "node_id": "fn:my_module.my_fn",
        "kind": "code.function",
        "canonical_name": "my_fn",
        "attrs": {},
        "neighbors": [],
    }

    # Run the propose_patch.pym script with mock externals
    result = run_pym_tool(
        "propose_patch",
        args={
            "target_node_id": "fn:my_module.my_fn",
            "patch_content": "def my_fn(): pass",
            "rationale": "simplify",
            "confidence": "0.9",
        },
        externals=externals.as_externals(),
    )

    assert len(externals._emitted_events) == 1
    assert externals._emitted_events[0]["event_type"] == "ProposePatchEvent"
```

No LLM. No network. Fully deterministic.

### 14.3 Graph inspector

```bash
# Show all nodes of a kind
remora-bootstrap graph --nodes code.function --limit 20

# Show neighbors of a specific node
remora-bootstrap graph --inspect "fn:core.store.event_store.append"

# Show causal descendants of an event
remora-bootstrap graph --causal-descendants "event-id-abc123"

# Show active protocols and their current state
remora-bootstrap protocols --active

# Show recent memory episodes
remora-bootstrap memory --episodes --limit 5
```

All commands are thin CLI wrappers over the same `BootstrapExternals` graph
query functions that agents use. No separate state.

### 14.4 Replay

```bash
# Replay a specific correlation chain from the EventStore
remora-bootstrap replay --correlation-id "abc-123"

# Replay up to a specific event (for debugging)
remora-bootstrap replay --correlation-id "abc-123" --until "event-id-xyz"
```

Replay executes the same `.pym` tool calls with the same inputs against the
real graph state at that point in the event log. Because `.pym` tools are pure
functions over the externals dict, replay is deterministic by construction.

---

